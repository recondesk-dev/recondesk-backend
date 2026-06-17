"""Rule registry — import all rule modules to trigger registration."""

from app.rules import decision, itc, matching, normalization, period
from app.rules.base import REGISTRY, RuleCategory, RuleDefinition, RuleSeverity

__all__ = [
    "REGISTRY",
    "RuleCategory",
    "RuleDefinition",
    "RuleSeverity",
]
