#!/usr/bin/env python3
"""QT Strategy Lab — CLI 入口"""

import json
import re
import sys
from pathlib import Path

from qt_strategy_lab import (
    Hypothesis,
    HypothesisStatus,
)

# ── 路径约定 ─────────────────────────────────────────────
# 从 examples/default/examples/ 目录运行
# 到量化战略根目录: ../../.. (examples/default → quanttide-strategy)
PARENT = Path(__file__).resolve().parents[2].joinpath("..", "..", "..").resolve()
PROFILE_ENV = PARENT / "data" / "profile" / "environment" / "index.json"
JOURNAL_ENV = PARENT / "data" / "journal" / "environment"
JOURNAL_DEFAULT = PARENT / "data" / "journal" / "default"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _latest_journal(dir_path: Path) -> str:
    """取一个 journal 目录下最新的 .md 内容"""
    if not dir_path.exists():
        return ""
    files = sorted(dir_path.glob("*.md"), reverse=True)
    if not files:
        return ""
    return files[0].read_text()


def _keyword_overlap(text: str, candidates: list[str]) -> list[str]:
    """基于关键词重叠找到关联的环境信号"""
    text_lower = text.lower()
    matched = []
    for c in candidates:
        # 中文分词：用标点和空格拆，然后提 2-4 字的关键子串
        parts = re.split(r"[，。,.:、\s]+", c.lower())
        ngrams = set()
        for p in parts:
            chars = list(p)
            for i in range(len(chars)):
                for j in range(i + 2, min(i + 5, len(chars) + 1)):
                    ngrams.add("".join(chars[i:j]))
        if any(ng in text_lower for ng in ngrams):
            matched.append(c)
    return matched


# ── 命令 ──────────────────────────────────────────────────


def cmd_new(strategy_path: str):
    """从 profile/strategy/index.json 加载假设"""
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
    """从 profile/environment/index.json 自动关联环境信号到假设"""
    result_path = Path("results") / "hypotheses.json"
    if not result_path.exists():
        print("请先运行 new 生成 hypotheses.json")
        return

    data = json.loads(result_path.read_text())
    env = _load_json(PROFILE_ENV)
    if not env:
        print(f"环境文件不存在: {PROFILE_ENV}")
        return

    # 收集所有环境信号
    signals = []
    internal = env.get("internal", {})
    external = env.get("external", {})

    for bl in internal.get("businessLines", []):
        signals.append(bl.get("constraint", ""))

    for m in external.get("market", []):
        signals.append(m.get("characteristic", ""))

    signals = [s for s in signals if s]

    # 逐条假设匹配
    matched_count = 0
    for h in data["hypotheses"]:
        text = f"{h['statement']} {h['risk']}"
        deps = _keyword_overlap(text, signals)
        if deps:
            h["depends_on"] = deps
            matched_count += 1

    result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"已关联 {matched_count}/{len(data['hypotheses'])} 条假设到环境信号")
    for h in data["hypotheses"]:
        if h["depends_on"]:
            print(f"  [{h['source']}] 依赖: {', '.join(h['depends_on'])}")


def cmd_check():
    """从 journal/environment 和 journal/default 的最新日志找证据"""
    result_path = Path("results") / "hypotheses.json"
    if not result_path.exists():
        print("请先运行 new 生成 hypotheses.json")
        return

    data = json.loads(result_path.read_text())

    # 读最新的环境日志和默认日志
    env_text = _latest_journal(JOURNAL_ENV)
    default_text = _latest_journal(JOURNAL_DEFAULT)
    combined = f"{env_text}\n\n{default_text}"
    if not combined.strip():
        print("未找到 journal 数据")
        return

    # 关键词匹配：每条假设在日志中找相关段落
    evidence = []
    for i, h in enumerate(data["hypotheses"]):
        text = h["statement"]
        words = [w for w in re.findall(r"[\w\u4e00-\u9fff]+", text) if len(w) > 1]
        if not words:
            continue

        # 在日志中找包含这些词的段落
        relevant = []
        for line in combined.split("\n"):
            line_lower = line.lower()
            if any(w.lower() in line_lower for w in words[:5]):
                relevant.append(line.strip())

        if relevant:
            evidence.append(
                {
                    "hypothesis_index": i,
                    "hypothesis_statement": h["statement"],
                    "supporting": "\n".join(relevant[:3]),
                    "challenging": "",
                }
            )

    data["evidence"] = evidence

    # 更新假设状态
    for e in evidence:
        for h in data["hypotheses"]:
            if h["statement"] == e["hypothesis_statement"]:
                if e["supporting"]:
                    h["status"] = "evidence_with_difficulty"
                break

    result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"从 journal 找到 {len(evidence)}/{len(data['hypotheses'])} 条假设的相关证据")
    for e in evidence:
        idx = e["hypothesis_index"]
        print(f"\n  [{idx}] {e['hypothesis_statement'][:50]}...")
        print(f"      证据片段: {e['supporting'][:80]}...")


def cmd_status():
    """查看当前假设校验状态"""
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
        dep_str = f" 依赖: {', '.join(deps)}" if deps else ""
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
  enrich           自动关联环境信号到假设（从 profile/environment/）
  check            从 journal 最新日志发现证据
  status           查看当前假设状态
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
    else:
        cmd_help()


if __name__ == "__main__":
    main()
