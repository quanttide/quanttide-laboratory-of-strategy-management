#!/usr/bin/env python3
"""QT Strategy Lab — CLI 入口"""

import json
import sys
import textwrap
from pathlib import Path

from quanttide_agent import LLM
from quanttide_agent.config import settings

from qt_strategy_lab import Hypothesis, HypothesisStatus

LLM_CLIENT = LLM(
    model=settings.llm_model or "deepseek-chat",
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
)

# ── 路径约定 ─────────────────────────────────────────────
PARENT = Path(__file__).resolve().parents[2].joinpath("..", "..", "..").resolve()
PROFILE_ENV = PARENT / "data" / "profile" / "environment" / "index.json"
JOURNAL_ENV = PARENT / "data" / "journal" / "environment"
JOURNAL_DEFAULT = PARENT / "data" / "journal" / "default"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _latest_journal(dir_path: Path) -> str:
    if not dir_path.exists():
        return ""
    files = sorted(dir_path.glob("*.md"), reverse=True)
    if not files:
        return ""
    return files[0].read_text()


def _llm(prompt: str, max_tokens: int = 2000) -> str:
    resp = LLM_CLIENT.complete(prompt, temperature=0.2, max_tokens=max_tokens)
    return resp.content.strip()


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n", 1)
        text = lines[1] if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


# ── 命令 ──────────────────────────────────────────────────


def cmd_new(strategy_path: str):
    path = Path(strategy_path)
    if not path.exists():
        print(f"文件不存在: {strategy_path}")
        return

    raw = json.loads(path.read_text())
    hypotheses = []

    if "corporate_strategy" in raw:
        cs = raw["corporate_strategy"]
        hypotheses.append(
            Hypothesis(
                statement=f"公司方向: {cs.get('direction', '')}",
                source="公司战略",
                risk=cs.get("tension", ""),
            )
        )

    for b in raw.get("business_strategy", []):
        hypotheses.append(
            Hypothesis(
                statement=f"{b['name']}: {b.get('challenge', '')}",
                source=b["name"],
                risk=b.get("signal", ""),
            )
        )

    for f in raw.get("functional_strategies", []):
        hypotheses.append(
            Hypothesis(
                statement=f"{f['name']}: {f.get('goal', '')}",
                source=f["name"],
                risk="; ".join(f.get("tactics", [])),
            )
        )

    result = {
        "strategy_source": strategy_path,
        "hypotheses": [h.to_dict() for h in hypotheses],
        "evidence": [],
    }

    out = Path("results") / "hypotheses.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"已加载 {len(hypotheses)} 条假设, 保存到 {out}")
    for i, h in enumerate(hypotheses):
        print(f"  [{i}] {h.statement[:60]}...")


def cmd_enrich():
    """LLM 自动关联环境信号到假设"""
    result_path = Path("results") / "hypotheses.json"
    if not result_path.exists():
        print("请先运行 new")
        return

    data = json.loads(result_path.read_text())
    env = _load_json(PROFILE_ENV)
    if not env:
        print(f"环境文件不存在: {PROFILE_ENV}")
        return

    # 收集环境信号
    signals = []
    for bl in env.get("internal", {}).get("businessLines", []):
        if bl.get("constraint"):
            signals.append(f"内部-{bl['name']}: {bl['constraint']}")
    for m in env.get("external", {}).get("market", []):
        if m.get("characteristic"):
            signals.append(f"外部-{m['dimension']}: {m['characteristic']}")
    for s in env.get("signals", []):
        signals.append(f"信号-{s.get('observation', '')}: {s.get('implication', '')}")

    signal_text = "\n".join(f"  [{i}] {s}" for i, s in enumerate(signals))

    for h in data["hypotheses"]:
        hyps_text = f"假设: {h['statement']}\n来源: {h['source']}\n风险: {h['risk']}"
        prompt = f"""判断以下假设依赖哪些环境信号（可多选或不选）。

输出格式: JSON 数组，如 [0, 2]，表示依赖信号列表中索引 0 和 2 的信号。一个都不依赖则输出 []。

假设:
{hyps_text}

可选的环境信号:
{signal_text}"""
        try:
            resp = _llm(prompt, max_tokens=500)
            indices = _parse_json(resp)
            if isinstance(indices, list):
                deps = [signals[i] for i in indices if i < len(signals)]
                h["depends_on"] = deps
                if deps:
                    print(f"  [{h['source']}] 依赖 {len(deps)} 个信号")
                    for d in deps:
                        print(f"      {d[:60]}")
        except Exception as e:
            print(f"  [{h['source']}] 跳过 ({e})")

    result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n已更新 {len(data['hypotheses'])} 条假设的环境依赖")


def cmd_check():
    """LLM 从日志发现证据"""
    result_path = Path("results") / "hypotheses.json"
    if not result_path.exists():
        print("请先运行 new")
        return

    data = json.loads(result_path.read_text())

    env_text = _latest_journal(JOURNAL_ENV)
    default_text = _latest_journal(JOURNAL_DEFAULT)
    combined = f"{env_text}\n\n{default_text}"
    if not combined.strip():
        print("未找到 journal 数据")
        return

    journal_snippet = combined[:6000]

    for i, h in enumerate(data["hypotheses"]):
        prompt = f"""你是事实校验分析师。下面是一条战略假设和公司日志。请判断日志中是否有证据支持或挑战这个假设。

输出 JSON:
{{"supporting": "支持证据的原文片段（如果没有就留空）", "challenging": "挑战证据的原文片段（如果没有就留空）", "verdict": "confirmed|rejected|no_evidence|evidence_with_difficulty", "reason": "一句话说明判断理由"}}

假设: {h["statement"]}
来源: {h["source"]}

公司日志:
{journal_snippet}"""
        try:
            resp = _llm(prompt, max_tokens=1000)
            result = _parse_json(resp)
            if result:
                h["status"] = result.get("verdict", h.get("status", "proposed"))
                data["evidence"].append(
                    {
                        "hypothesis_index": i,
                        "hypothesis_statement": h["statement"],
                        "supporting": result.get("supporting", ""),
                        "challenging": result.get("challenging", ""),
                        "reason": result.get("reason", ""),
                    }
                )
                icon = {
                    "confirmed": "✓",
                    "rejected": "✗",
                    "evidence_with_difficulty": "△",
                    "no_evidence": "?",
                }.get(result.get("verdict", ""), "?")
                print(
                    f"  {icon} [{result.get('verdict', '?')}] {h['source']}: {result.get('reason', '')[:50]}"
                )
        except Exception as e:
            print(f"  ✗ [{h['source']}] 跳过 ({e})")

    result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    n = len(data["evidence"])
    print(f"\n已更新 {n} 条证据记录")


def cmd_status():
    result_path = Path("results") / "hypotheses.json"
    if not result_path.exists():
        print("请先运行 new")
        return

    data = json.loads(result_path.read_text())
    print(f"\n假设校验状态:\n")
    for h in data["hypotheses"]:
        icon = {
            "confirmed": "✓",
            "rejected": "✗",
            "evidence_with_difficulty": "△",
            "no_evidence": "?",
            "proposed": " ",
        }.get(h.get("status", ""), "?")
        deps = h.get("depends_on", [])
        dep_str = f"  依赖: {len(deps)} 个环境信号" if deps else ""
        print(
            f"  {icon} [{h.get('status', '?')}] {h['source']}: {h['statement'][:50]}...{dep_str}"
        )

    ev_count = len(data.get("evidence", []))
    print(f"\n共 {len(data['hypotheses'])} 条假设, {ev_count} 条证据记录")


def cmd_help():
    print("""QT Strategy Lab

用法: python -m qt_strategy_lab <命令>

命令:
  new <json路径>    从 profile/strategy/index.json 加载假设
  enrich           LLM 自动关联环境信号到假设
  check            LLM 从 journal 最新日志发现证据
  status           查看当前假设状态
  reset            清空 results/
  help             显示帮助
""")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "--help", "-h"):
        cmd_help()
        return

    cmd = sys.argv[1]
    if cmd == "new":
        if len(sys.argv) < 3:
            print("需要指定 JSON 文件路径")
            return
        cmd_new(sys.argv[2])
    elif cmd == "enrich":
        cmd_enrich()
    elif cmd == "check":
        cmd_check()
    elif cmd == "status":
        cmd_status()
    elif cmd == "reset":
        import shutil

        p = Path("results")
        if p.exists():
            shutil.rmtree(p)
            print("已重置")
    else:
        cmd_help()


if __name__ == "__main__":
    main()
