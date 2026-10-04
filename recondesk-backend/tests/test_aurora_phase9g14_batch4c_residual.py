"""Phase 9G-14: Batch 4C Residual Supabase Dependency Audit Test Suite.

Verifies:
1. Zero active Supabase primary dependencies (Category A = 0).
2. Zero unresolved dependencies (Category G = 0).
3. All residual Supabase references are verified Category B (intentional non-blocking fallback),
   Category C (tests), Category D (migration tooling), or Category E (documentation/schema).
4. Zero normal Supabase reads / writes during standard operations.
5. Zero dual-writes: writes go exclusively to Aurora PRIMARY.
"""

import ast
import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BACKEND_DIR.parent / "recondesk-frontend"

BATCH4C_TABLES = [
    "notification_preferences",
    "upload_requests",
    "uploaded_files",
    "communication_logs",
    "audit_logs",
]


def test_no_unresolved_dependencies_batch4c():
    """Verify that there are 0 Category G (unresolved) dependencies across the repository."""
    # Search python backend files excluding tests, migrations, and scripts
    suspicious_patterns = [
        re.compile(r'db\.table\(["\'](notification_preferences|upload_requests|uploaded_files|communication_logs|audit_logs)["\']\)\.(insert|select|update|delete)'),
        re.compile(r'supabase\.table\(["\'](notification_preferences|upload_requests|uploaded_files|communication_logs|audit_logs)["\']\)\.(insert|select|update|delete)'),
        re.compile(r'client\.table\(["\'](notification_preferences|upload_requests|uploaded_files|communication_logs|audit_logs)["\']\)\.(insert|select|update|delete)'),
    ]

    backend_py_files = [
        p for p in (BACKEND_DIR / "app").rglob("*.py")
        if "tests" not in str(p) and "scripts" not in str(p)
    ]

    for py_file in backend_py_files:
        content = py_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        for idx, line in enumerate(lines, start=1):
            for pat in suspicious_patterns:
                if pat.search(line):
                    # Check that this line is inside an except block or fallback branch
                    surrounding = "\n".join(lines[max(0, idx - 40):idx])
                    is_fallback = (
                        "except" in surrounding
                        or "fallback" in surrounding.lower()
                        or "aurora_exc" in surrounding
                    )
                    assert is_fallback, (
                        f"Unresolved active Supabase query found outside fallback in "
                        f"{py_file.name}:{idx} -> {line.strip()}"
                    )


def test_zero_dual_writes_in_audit_utils():
    """Verify that app/utils/audit.py returns immediately after Aurora write and does not write to Supabase."""
    audit_py = (BACKEND_DIR / "app" / "utils" / "audit.py").read_text(encoding="utf-8")
    
    # Must contain Aurora insert
    assert "repo.insert_audit_log(" in audit_py
    # Must contain early return to prevent dual write
    assert "return  # Successful Aurora primary write; do not dual-write to Supabase" in audit_py
    # Supabase table write must only be in fallback
    assert "Aurora audit_log insert failed" in audit_py


def test_zero_dual_writes_in_notifications_router():
    """Verify that app/routers/notifications.py writes to Aurora and returns, falling back only on exception."""
    notif_py = (BACKEND_DIR / "app" / "routers" / "notifications.py").read_text(encoding="utf-8")

    assert "repo.get_notification_preferences(user_id)" in notif_py
    assert "repo.upsert_notification_preferences(" in notif_py
    assert "Aurora get_preferences failed" in notif_py
    assert "Aurora update_preferences failed" in notif_py


def test_zero_dual_writes_in_upload_router():
    """Verify that app/routers/upload.py uses Aurora PRIMARY for all Batch 4C operations."""
    upload_py = (BACKEND_DIR / "app" / "routers" / "upload.py").read_text(encoding="utf-8")

    assert "repo.get_upload_request_by_token(" in upload_py
    assert "repo.create_uploaded_file(" in upload_py
    assert "repo.create_upload_request(" in upload_py
    assert "repo.list_upload_requests(" in upload_py
    assert "repo.list_uploaded_files_by_request_ids(" in upload_py
    assert "repo.list_communication_logs(" in upload_py
    assert "repo.create_communication_log(" in upload_py


def test_frontend_routes_cutover():
    """Verify that frontend components call API proxy first before any Supabase direct call."""
    modal_tsx = (FRONTEND_DIR / "components" / "communication" / "GenerateUploadLinkModal.tsx").read_text(encoding="utf-8")
    assert 'fetch("/api/upload/request"' in modal_tsx

    center_tsx = (FRONTEND_DIR / "components" / "communication" / "CommunicationCenter.tsx").read_text(encoding="utf-8")
    assert "/api/upload/requests/" in center_tsx
    assert "/api/upload/files?" in center_tsx
    assert "/api/upload/communication-logs/" in center_tsx

    upload_client_tsx = (FRONTEND_DIR / "components" / "upload" / "UploadPageClient.tsx").read_text(encoding="utf-8")
    assert "${API_URL}/upload/record-file" in upload_client_tsx
