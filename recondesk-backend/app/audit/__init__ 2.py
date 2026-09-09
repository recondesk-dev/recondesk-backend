"""Audit observation aggregation — read-only layer over reconciliation outputs."""

from app.audit.observation_builder import build_observations
from app.audit.observation_rules import OBSERVATION_RULES

__all__ = ["OBSERVATION_RULES", "build_observations"]
