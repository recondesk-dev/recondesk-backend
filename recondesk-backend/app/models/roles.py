"""Canonical Role Definitions and Hierarchy for ReconDesk SaaS.

Defines granular CA practice roles, legacy aliases, and permission helper predicates.
Enforces fail-closed security defaults across all authentication and authorization layers.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class Role(str, Enum):
    # Canonical Granular Roles
    OWNER = "owner"          # Firm Owner / Principal CA (Root tenant)
    PARTNER = "partner"      # CA Partner (Full operational authority: filing, overrides, team)
    MANAGER = "manager"      # Practice Manager / Senior CA (Assignments, batch prep, review)
    PREPARER = "preparer"    # Staff Accountant / Article Clerk (Data entry, recon, draft returns)
    VIEWER = "viewer"        # Read-only User / Client Representative (View only)

    # Legacy Backward-Compatible Aliases
    ADMIN = "admin"          # Maps to OWNER / PARTNER authority
    STAFF = "staff"          # Maps to PREPARER authority


# All recognized roles in the system
ALL_ROLES = frozenset({
    Role.OWNER.value,
    Role.PARTNER.value,
    Role.MANAGER.value,
    Role.PREPARER.value,
    Role.VIEWER.value,
    Role.ADMIN.value,
    Role.STAFF.value,
})

# Roles that can be invited to a firm (owner is the workspace anchor)
INVITABLE_ROLES = frozenset({
    Role.PARTNER.value,
    Role.MANAGER.value,
    Role.PREPARER.value,
    Role.VIEWER.value,
    Role.ADMIN.value,
    Role.STAFF.value,
})

# Administrative / Partner roles (Statutory filing, override approval, policy config, team removal)
ADMIN_ROLES = frozenset({
    Role.OWNER.value,
    Role.PARTNER.value,
    Role.ADMIN.value,
})

# Manager roles and above (Client assignment, review, creating batches)
MANAGER_ROLES = frozenset({
    Role.OWNER.value,
    Role.PARTNER.value,
    Role.ADMIN.value,
    Role.MANAGER.value,
})

# Mutative write roles (Upload data, run recon, draft returns, save returns)
WRITER_ROLES = frozenset({
    Role.OWNER.value,
    Role.PARTNER.value,
    Role.ADMIN.value,
    Role.MANAGER.value,
    Role.PREPARER.value,
    Role.STAFF.value,
})

# Read-only roles
VIEWER_ROLES = frozenset({
    Role.VIEWER.value,
})

# Default fallback role on unauthenticated / unknown profile (FAIL CLOSED: strictly viewer)
DEFAULT_FAIL_CLOSED_ROLE = Role.VIEWER.value


def normalize_role(role: Any) -> str:
    """Normalize and validate role string; returns DEFAULT_FAIL_CLOSED_ROLE if invalid/empty/unknown.
    
    Security Guarantee: Never returns 'admin' or 'owner' for missing or unverified inputs.
    """
    if not role or not isinstance(role, str):
        return DEFAULT_FAIL_CLOSED_ROLE
    r = role.strip().lower()
    if r in ALL_ROLES:
        return r
    return DEFAULT_FAIL_CLOSED_ROLE


def is_admin_or_partner(role: Any) -> bool:
    """True if role holds Partner/Admin level authority (overrides, live filing, governance policy)."""
    return normalize_role(role) in ADMIN_ROLES


def is_manager_or_above(role: Any) -> bool:
    """True if role holds Manager or Partner/Admin level authority (assignment, batch prep, review)."""
    return normalize_role(role) in MANAGER_ROLES


def is_writer_or_above(role: Any) -> bool:
    """True if role can perform mutative reconciliation and draft operations."""
    return normalize_role(role) in WRITER_ROLES


def is_viewer_only(role: Any) -> bool:
    """True if role is strictly read-only."""
    return normalize_role(role) in VIEWER_ROLES
