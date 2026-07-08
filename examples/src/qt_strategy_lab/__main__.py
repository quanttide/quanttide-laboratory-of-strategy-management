#!/usr/bin/env python3
"""QT Strategy Lab — CLI 入口"""

import json
import sys
from pathlib import Path

from quanttide_agent import LLM
from quanttide_agent.config import settings

from qt_strategy_lab import Hypothesis

LLM_CLIENT = LLM(
    model=settings.llm_model or "deepseek-chat",
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
)

# ── 根目录 ────────────────────────────────────────────────
QT_ROOT = Path(__file__).resolve().parents[2].joinpath("..", "..", "..").resolve()
QT_TECH = QT_ROOT.parent.parent / "default" / "quanttide-tech"  # 外部事实源

# 本仓库 profile（待核验的断言）
PROFILE_STRATEGY = QT_ROOT / "data" / "profile" / "strategy" / "index.json"
PROFILE_ENV = QT_ROOT / "data" / "profile" / "environment" / "index.json"

# 日志事实源（本仓库 + 外部仓库）
FACT_SOURCES = [
    ("本仓库-journal", QT_ROOT / "data" / "journal"),
    ("外部-quanttide-tech", QT_TECH / "data" / "journal"),
]


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _llm(prompt: str, max_tokens: int = 4000) -> str:
    resp = LLM_CLIENT.complete(prompt, temperature=0.2, max_tokens=max_tokens)
    return resp.content.strip()


def _parse_json(text: str) -> dict | list:
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


def _all_journal_text() -> str:
    """从所有事实源收集 journal 文本"""
    texts = []
    for label, path in FACT_SOURCES:
        if not path.exists():
            continue
        for sub in sorted(path.iterdir()):
            if not sub.is_dir() or sub.name.startswith("."):
                continue
            files = sorted(sub.glob("*.md"), reverse=True)[:3]  # 每个目录最近 3 篇
            for f in files:
                texts.append(f"\n=== {label}/{sub.name}/{f.stem} ===\n{f.read_text()}")
    return "\n".join(texts)


# ── 命令 ──────────────────────────────────────────────────


def cmd_verify():
    """读 profile/ 战略断言 → 生成核验清单 → 到外部事实源找证据"""
    strategy = _load_json(PROFILE_STRATEGY)
    env = _load_json(PROFILE_ENV)

    # 1. 收集所有需要核验的战略断言
    assertions = []

    if "corporate_strategy" in strategy:
        cs = strategy["corporate_strategy"]
        assertions.append(
            {
                "source": "公司战略",
                "assertion": cs.get("direction", ""),
                "context": cs.get("tension", ""),
            }
        )

    for b in strategy.get("business_strategy", []):
        assertions.append(
            {
                "source": b["name"],
                "assertion": b.get("challenge", ""),
                "context": b.get("signal", ""),
            }
        )

    for f in strategy.get("functional_strategies", []):
        assertions.append(
            {
                "source": f["name"],
                "assertion": f.get("goal", ""),
                "context": "; ".join(f.get("tactics", [])),
            }
        )

    # 2. 生成核验清单——每条断言需要找什么证据
    print(f"共 {len(assertions)} 条战略断言需要核验")
    print("生成核验清单...")

    verify_plan_prompt = f"""下面是公司的战略断言清单。对每条断言，生成一个"核验条目"——到外部事实源（各业务线日志）中要找什么证据来验证它。

输出 JSON 数组:
[{{"source": "来源", "assertion": "断言原文", "what_to_look_for": "到日志中找什么具体的证据（行为/数据/事件）才能确认或挑战这条断言", "key_signals": ["关注的关键信号词"]}}]

战略断言:
{json.dumps(assertions, ensure_ascii=False, indent=2)}"""

    try:
        plan = _parse_json(_llm(verify_plan_prompt, max_tokens=3000))
        if isinstance(plan, dict):
            plan = [plan]
    except Exception:
        plan = []

    if not plan:
        print("生成核验清单失败")
        return

    print(f"已生成 {len(plan)} 条核验条目\n")

    # 3. 收集事实源文本
    print("收集外部事实源...")
    fact_text = _all_journal_text()
    print(f"共 {len(fact_text)} 字符\n")

    if not fact_text.strip():
        print("无可用事实源")
        return

    # 4. 逐条核验
    results = []
    for item in plan:
        source = item.get("source", "")
        assertion = item.get("assertion", "")
        what = item.get("what_to_look_for", "")

        prompt = f"""你是事实校验分析师。下面是一条战略断言和核验指引。请从事实源里找相关证据。

输出 JSON:
{{"source": "来源", "assertion": "断言原文", "supporting": "支持证据的原文片段（引用具体内容，无则空）", "challenging": "挑战证据的原文片段（引用具体内容，无则空）", "verdict": "confirmed|rejected|evidence_with_difficulty|no_evidence", "reason": "一句话判断理由", "found_in": ["找到证据的文件路径"]}}

战略断言: {assertion}
来源: {source}
核验指引: {what}

事实源:
{fact_text[:8000]}"""
        try:
            resp = _llm(prompt, max_tokens=1500)
            r = _parse_json(resp)
            if isinstance(r, dict) and r.get("verdict"):
                results.append(r)
                icon = {
                    "confirmed": "✓",
                    "rejected": "✗",
                    "evidence_with_difficulty": "△",
                    "no_evidence": "?",
                }.get(r.get("verdict", ""), "?")
                print(f"  {icon} [{r['verdict']}] {source}: {r.get('reason', '')[:60]}")
        except Exception as e:
            print(f"  ✗ [{source}] 跳过 ({e})")

    # 5. 保存结果
    out = {
        "verified_at": __import__("datetime").datetime.now().isoformat(),
        "assumptions": assertions,
        "plan": plan,
        "results": results,
        "summary": {
            "total": len(assertions),
            "verified": len(results),
            "confirmed": sum(1 for r in results if r.get("verdict") == "confirmed"),
            "rejected": sum(1 for r in results if r.get("verdict") == "rejected"),
            "evidence_with_difficulty": sum(
                1 for r in results if r.get("verdict") == "evidence_with_difficulty"
            ),
            "no_evidence": sum(1 for r in results if r.get("verdict") == "no_evidence"),
        },
    }

    out_path = Path("results") / "verification.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n保存到 {out_path}")
    print(
        f"✓ {out['summary']['confirmed']} │ ✗ {out['summary']['rejected']} │ △ {out['summary']['evidence_with_difficulty']} │ ? {out['summary']['no_evidence']}"
    )


def cmd_status():
    """查看上次核验结果"""
    path = Path("results") / "verification.json"
    if not path.exists():
        print("请先运行 verify")
        return

    data = json.loads(path.read_text())
    print(f"\n战略核验结果 ({data['verified_at'][:19]}):\n")
    for r in data.get("results", []):
        icon = {
            "confirmed": "✓",
            "rejected": "✗",
            "evidence_with_difficulty": "△",
            "no_evidence": "?",
        }.get(r.get("verdict", ""), "?")
        print(f"  {icon} [{r['verdict']}] {r['source']}")
        print(f"     断言: {r['assertion'][:60]}...")
        print(f"     判断: {r.get('reason', '')[:60]}")
        if r.get("found_in"):
            print(f"     来源: {', '.join(r['found_in'][:2])}")
        print()

    s = data.get("summary", {})
    print(
        f"共 {s.get('total', 0)} 条 | ✓ {s.get('confirmed', 0)} ✗ {s.get('rejected', 0)} △ {s.get('evidence_with_difficulty', 0)} ? {s.get('no_evidence', 0)}"
    )


def cmd_help():
    print("""QT Strategy Lab

读 profile/ 里的战略断言 → 生成核验清单 → 到外部事实源（journal）找证据。

用法: python -m qt_strategy_lab <命令>

命令:
  verify    读 profile/ 所有断言，生成核验清单，到外部找证据
  status    查看上次核验结果
  help      显示帮助
""")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "--help", "-h"):
        cmd_help()
        return

    cmd = sys.argv[1]
    if cmd == "verify":
        cmd_verify()
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
