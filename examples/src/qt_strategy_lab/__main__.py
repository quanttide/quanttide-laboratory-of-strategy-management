#!/usr/bin/env python3
"""QT Strategy Lab — CLI 入口"""

import json
import sys
from pathlib import Path

from qt_strategy_lab import (
    AssumptionGraph,
    Evidence,
    Hypothesis,
    HypothesisStatus,
)


def cmd_new(graph_path: str):
    """发起一次推演：从 profile/strategy/index.json 加载假设"""
    path = Path(graph_path)
    if not path.exists():
        print(f"文件不存在: {graph_path}")
        return

    raw = json.loads(path.read_text())
    graph = AssumptionGraph()

    # 公司战略假设
    if "corporate_strategy" in raw:
        cs = raw["corporate_strategy"]
        graph.add(
            Hypothesis(
                statement=f"公司方向: {cs.get('direction', '')}",
                source="公司战略",
                risk=cs.get("tension", ""),
            )
        )

    # 各业务线假设
    for b in raw.get("business_strategy", []):
        graph.add(
            Hypothesis(
                statement=f"{b['name']}: {b.get('challenge', '')}",
                source=b["name"],
                risk=b.get("signal", ""),
            )
        )

    print(f"已加载 {len(graph.hypotheses)} 条战略假设\n")
    for i, h in enumerate(graph.hypotheses):
        print(f"  [{i}] {h.statement[:60]}...")
    print()

    # 保存初始图
    result = {
        "strategy_source": graph_path,
        "hypotheses": [h.to_dict() for h in graph.hypotheses],
        "evidence": [],
    }
    ts = Path(graph_path).stem
    out = Path("results") / f"{ts}_hypotheses.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"已保存: {out}")


def cmd_validate(evidence_path: str):
    """从证据文件加载校验结果并展示"""
    path = Path(evidence_path)
    if not path.exists():
        print(f"文件不存在: {evidence_path}")
        return

    data = json.loads(path.read_text())
    print(f"\n假设校验状态 ({path.stem}):\n")
    for h in data.get("hypotheses", []):
        icon = {
            "confirmed": "✓",
            "rejected": "✗",
            "evidence_with_difficulty": "△",
            "no_evidence": "?",
            "proposed": " ",
        }.get(h.get("status", ""), "?")
        print(f"  {icon} [{h.get('status', '?')}] {h.get('statement', '')[:70]}")
        if h.get("risk"):
            print(f"      风险: {h['risk'][:70]}")


def cmd_help():
    print("""QT Strategy Lab

用法: python -m qt_strategy_lab <命令> [参数]

命令:
  new <json路径>       从 profile/strategy/index.json 加载假设
  validate <json路径>   查看假设校验状态
  help                 显示帮助
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
    elif cmd == "validate":
        if len(sys.argv) < 3:
            print("需要指定结果 JSON 文件路径")
            return
        cmd_validate(sys.argv[2])
    else:
        cmd_help()


if __name__ == "__main__":
    main()
