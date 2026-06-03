"""Rule registry — metadata-only definitions for reconciliation engine rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RuleCategory(str, Enum):
    MATCHING = "matching"
    ITC = "itc"
    NORMALIZATION = "normalization"
    PERIOD = "period"
    SUPPLIER = "supplier"
    REPORTING = "reporting"
    TDS_TCS = "tds_tcs"
    DECISION = "decision"


class RuleSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class RuleDefinition:
    id: str
    name: str
    category: RuleCategory
    severity: RuleSeverity
    description: str
    applies_to: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    gst_ref: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category.value,
            "severity": self.severity.value,
            "description": self.description,
            "gst_ref": self.gst_ref,
            "applies_to": list(self.applies_to),
            "tags": list(self.tags),
        }


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, RuleDefinition] = {}

    def register(self, rule: RuleDefinition) -> None:
        if rule.id in self._rules:
            raise ValueError(f"Duplicate rule id: {rule.id}")
        self._rules[rule.id] = rule

    def all(self) -> list[RuleDefinition]:
        return list(self._rules.values())

    def by_category(self, category: RuleCategory) -> list[RuleDefinition]:
        return [r for r in self._rules.values() if r.category == category]

    def by_severity(self, severity: RuleSeverity) -> list[RuleDefinition]:
        return [r for r in self._rules.values() if r.severity == severity]

    def get(self, rule_id: str) -> RuleDefinition | None:
        return self._rules.get(rule_id)

    @property
    def count(self) -> int:
        return len(self._rules)

    def summary(self) -> dict:
        by_category: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for rule in self._rules.values():
            cat = rule.category.value
            sev = rule.severity.value
            by_category[cat] = by_category.get(cat, 0) + 1
            by_severity[sev] = by_severity.get(sev, 0) + 1
        return {
            "total": self.count,
            "by_category": dict(sorted(by_category.items())),
            "by_severity": dict(sorted(by_severity.items())),
        }


REGISTRY = RuleRegistry()
