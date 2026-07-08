"""战略假设推演实验室。

假设是第一等公民（first-class citizen）：
可序列化、可关联环境变量、可追踪校验状态。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class HypothesisStatus(Enum):
    PROPOSED = "proposed"  # 刚提出
    CONFIRMED = "confirmed"  # 被证据支持
    REJECTED = "rejected"  # 被证据挑战
    EVIDENCE_WITH_DIFFICULTY = "evidence_with_difficulty"  # 既有支持也有挑战
    NO_EVIDENCE = "no_evidence"  # 暂无相关证据
    SUPERSEDED = "superseded"  # 被新假设替代


@dataclass
class Hypothesis:
    """一条战略假设。"""

    statement: str  # 假设原文
    source: str  # 来源战略（如"量潮数据"）
    htype: str = "external"  # internal / external
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    risk: str = ""  # 如果假设不成立的风险
    counterfactual: str = ""  # 反事实描述
    signals_to_watch: list[str] = field(default_factory=list)  # 应关注的信号
    depends_on: list[str] = field(default_factory=list)  # 依赖的环境变量
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "statement": self.statement,
            "source": self.source,
            "type": self.htype,
            "status": self.status.value,
            "risk": self.risk,
            "counterfactual": self.counterfactual,
            "signals_to_watch": self.signals_to_watch,
            "depends_on": self.depends_on,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class Evidence:
    """一条支持或挑战假设的证据。"""

    hypothesis_index: int  # 对应哪条假设
    hypothesis_statement: str  # 假设原文（冗余，方便独立阅读）
    supporting: str = ""  # 支持证据
    challenging: str = ""  # 挑战证据


@dataclass
class AssumptionGraph:
    """假设依赖图 — 类比 DoWhy 的 CausalModel。

    记录：环境变量 → 战略假设 的依赖关系。
    """

    hypotheses: list[Hypothesis] = field(default_factory=list)
    evidence_records: list[Evidence] = field(default_factory=list)

    def add(self, h: Hypothesis):
        self.hypotheses.append(h)

    def add_evidence(self, e: Evidence):
        self.evidence_records.append(e)
        # 更新对应假设的状态
        for h in self.hypotheses:
            if h.statement == e.hypothesis_statement:
                if e.supporting and not e.challenging:
                    h.status = HypothesisStatus.CONFIRMED
                elif e.challenging and not e.supporting:
                    h.status = HypothesisStatus.REJECTED
                elif e.supporting and e.challenging:
                    h.status = HypothesisStatus.EVIDENCE_WITH_DIFFICULTY
                else:
                    h.status = HypothesisStatus.NO_EVIDENCE
                h.updated_at = datetime.now().isoformat()
                break

    def to_dict(self) -> dict:
        return {
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "evidence": [
                {
                    "hypothesis_index": e.hypothesis_index,
                    "hypothesis_statement": e.hypothesis_statement,
                    "supporting": e.supporting,
                    "challenging": e.challenging,
                }
                for e in self.evidence_records
            ],
        }
