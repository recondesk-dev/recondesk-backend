"""Rules registry API — `/api/rules`."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_active_user
from app.rules import REGISTRY, RuleCategory, RuleSeverity

router = APIRouter()


@router.get("/summary")
async def rules_summary():
    """Public summary of registered rules (for landing page)."""
    return REGISTRY.summary()


@router.get("/list")
async def rules_list(
    category: Optional[RuleCategory] = Query(None),
    severity: Optional[RuleSeverity] = Query(None),
    tag: Optional[str] = Query(None),
    _current_user: dict = Depends(get_current_active_user),
):
    """Return all rules, optionally filtered by category, severity, or tag."""
    rules = REGISTRY.all()
    if category is not None:
        rules = [r for r in rules if r.category == category]
    if severity is not None:
        rules = [r for r in rules if r.severity == severity]
    if tag is not None:
        tag_lower = tag.lower()
        rules = [r for r in rules if tag_lower in (t.lower() for t in r.tags)]
    return [r.to_dict() for r in rules]


@router.get("/{rule_id}")
async def get_rule(
    rule_id: str,
    _current_user: dict = Depends(get_current_active_user),
):
    """Return a single rule by ID."""
    rule = REGISTRY.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule.to_dict()
