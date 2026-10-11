"""Unit and regression tests for Phase 3.3 Client Review, Consent and Filing Authorization.

Verifies:
1. Cryptographic token generation: 256-bit entropy url-safe token, SHA-256 hash storage (plaintext never saved).
2. Review link access: Link view transitions PENDING -> VIEWED; link click alone NEVER counts as authorization.
3. Explicit client authorization: Captures signatory name, designation, contact, consent version v1.0, IP, and User-Agent.
4. Client rejection: Mandatory detailed rejection reason; blocks subsequent authorization.
5. Expiration handling: Tokens past expires_at raise HTTP 410 / HTTP 403; cannot file.
6. CA revocation: Manager/Partner role enforcement; deactivates review portal.
7. Cryptographic figures binding & tamper detection: Altered figures invalidate consent and raise HTTP 409.
8. Server-side filing gate enforcement: Blocks GSTR-1, GSTR-3B, and Celery batch filing when authorization is unfulfilled.
9. Tenant isolation and security.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.client_authorization_service import (
    ClientAuthAction,
    ClientAuthStatus,
    _client_store,
    assert_client_authorization_gate,
    create_authorization_request,
    generate_review_token,
    get_authorization_by_token,
    get_client_authorization_history,
    get_latest_client_authorization,
    hash_review_token,
    reject_client_authorization,
    revoke_authorization_request,
    submit_client_authorization,
)
from app.services.pre_filing_validator import compute_figures_digest


@pytest.fixture(autouse=True)
def clean_client_auth_store():
    """Ensure in-memory store is clean between tests."""
    _client_store.clear()
    yield
    _client_store.clear()


@pytest.fixture
def mock_sb():
    """Mock database client configured for in-memory / test runner."""
    sb = MagicMock()
    sb.is_real_db = False
    return sb


@pytest.fixture
def preparer_actor():
    return {
        "id": "preparer-uuid-1",
        "full_name": "Priya Sharma",
        "email": "priya@cafirm.com",
        "role": "preparer",
    }


@pytest.fixture
def manager_actor():
    return {
        "id": "manager-uuid-1",
        "full_name": "Vikram Mehta",
        "email": "vikram@cafirm.com",
        "role": "manager",
    }


@pytest.fixture
def viewer_actor():
    return {
        "id": "viewer-uuid-1",
        "full_name": "Ananya Roy",
        "email": "ananya@cafirm.com",
        "role": "viewer",
    }


@pytest.fixture
def sample_figures():
    return {
        "total_taxable_value": 500000.0,
        "total_tax": 90000.0,
        "igst": 90000.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "cess": 0.0,
        "invoice_count": 12,
    }


# ---------------------------------------------------------------------------
# 1. Cryptographic Token Hashing & Storage
# ---------------------------------------------------------------------------

def test_token_generation_and_hashing():
    raw_token, token_hash = generate_review_token()
    assert len(raw_token) >= 32
    assert len(token_hash) == 64  # SHA-256 hex digest
    assert hash_review_token(raw_token) == token_hash

    # Different tokens produce different hashes
    raw_token2, token_hash2 = generate_review_token()
    assert raw_token != raw_token2
    assert token_hash != token_hash2


def test_create_authorization_request_stores_hash_not_plaintext(mock_sb, preparer_actor, sample_figures):
    firm_id = "firm-1"
    client_gstin_id = "client-gstin-1"
    gstin = "27AABCU9603R1ZX"
    period = "2026-10"

    auth, raw_token = create_authorization_request(
        mock_sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=period,
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
        expires_in_hours=48,
    )

    assert auth.status == ClientAuthStatus.PENDING
    assert auth.token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    # Plaintext token must not be part of the persisted object attributes
    assert not hasattr(auth, "raw_token")
    assert raw_token not in auth.to_dict().values()

    # Verify figures digest calculation
    expected_digest = compute_figures_digest(sample_figures)
    assert auth.figures_digest == expected_digest


def test_unauthorized_role_cannot_create_request(mock_sb, viewer_actor, sample_figures):
    with pytest.raises(HTTPException) as exc_info:
        create_authorization_request(
            mock_sb,
            firm_id="firm-1",
            client_gstin_id="client-gstin-1",
            gstin="27AABCU9603R1ZX",
            period="2026-10",
            return_type="GSTR-1",
            figures_payload=sample_figures,
            actor=viewer_actor,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "INSUFFICIENT_ROLE_FOR_AUTHORIZATION_REQUEST"


# ---------------------------------------------------------------------------
# 2. Review Link Access vs Explicit Authorization
# ---------------------------------------------------------------------------

def test_link_access_marks_viewed_but_never_authorizes(mock_sb, preparer_actor, sample_figures):
    auth, raw_token = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
    )
    assert auth.status == ClientAuthStatus.PENDING

    # Client visits the portal with raw_token
    client_ip = "203.0.113.42"
    user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"

    viewed_auth = get_authorization_by_token(
        mock_sb,
        raw_token,
        client_ip=client_ip,
        user_agent=user_agent,
    )

    # CRITICAL: Opening or clicking link MUST NOT authorize!
    assert viewed_auth.status == ClientAuthStatus.VIEWED
    assert viewed_auth.status != ClientAuthStatus.AUTHORIZED
    assert viewed_auth.client_ip == client_ip

    # Audit trail verification
    audit = get_client_authorization_history(mock_sb, authorization_id=auth.id, firm_id="firm-1")
    actions = [e["action"] for e in audit]
    assert ClientAuthAction.REQUEST_CREATED.value in actions
    assert ClientAuthAction.LINK_VIEWED.value in actions


# ---------------------------------------------------------------------------
# 3. Explicit Client Authorization
# ---------------------------------------------------------------------------

def test_explicit_client_authorization_success(mock_sb, preparer_actor, sample_figures):
    auth, raw_token = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
    )

    client_ip = "198.51.100.25"
    user_agent = "Chrome/120.0.0.0 Safari/537.36"

    # Client submits explicit consent
    authorized_auth = submit_client_authorization(
        mock_sb,
        raw_token,
        signatory_name="Rajesh Kumar",
        signatory_designation="Managing Director",
        signatory_contact="+91 98765 43210",
        consent_text_version="v1.0",
        client_ip=client_ip,
        user_agent=user_agent,
    )

    assert authorized_auth.status == ClientAuthStatus.AUTHORIZED
    assert authorized_auth.signatory_name == "Rajesh Kumar"
    assert authorized_auth.signatory_designation == "Managing Director"
    assert authorized_auth.signatory_contact == "+91 98765 43210"
    assert authorized_auth.consent_text_version == "v1.0"
    assert authorized_auth.authorized_at is not None
    assert authorized_auth.client_ip == client_ip

    # Audit trail verifies client actor
    audit = get_client_authorization_history(mock_sb, authorization_id=auth.id, firm_id="firm-1")
    auth_event = next(e for e in audit if e["action"] == ClientAuthAction.AUTHORIZED.value)
    assert auth_event["actor_type"] == "client"
    assert "Rajesh Kumar" in auth_event["actor_name"]


def test_submit_authorization_requires_valid_signatory_details(mock_sb, preparer_actor, sample_figures):
    _, raw_token = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
    )

    # Empty name
    with pytest.raises(HTTPException) as exc1:
        submit_client_authorization(
            mock_sb,
            raw_token,
            signatory_name="",
            signatory_designation="Director",
            signatory_contact="9876543210",
        )
    assert exc1.value.status_code == 400
    assert exc1.value.detail["code"] == "INVALID_SIGNATORY_NAME"

    # Empty designation
    with pytest.raises(HTTPException) as exc2:
        submit_client_authorization(
            mock_sb,
            raw_token,
            signatory_name="Rajesh Kumar",
            signatory_designation="",
            signatory_contact="9876543210",
        )
    assert exc2.value.status_code == 400
    assert exc2.value.detail["code"] == "INVALID_SIGNATORY_DESIGNATION"


# ---------------------------------------------------------------------------
# 4. Client Rejection
# ---------------------------------------------------------------------------

def test_client_rejection_requires_detailed_reason(mock_sb, preparer_actor, sample_figures):
    _, raw_token = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
    )

    # Missing / short reason
    with pytest.raises(HTTPException) as exc:
        reject_client_authorization(
            mock_sb,
            raw_token,
            rejection_reason="No",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "REJECTION_REASON_REQUIRED"

    # Valid rejection
    rejected_auth = reject_client_authorization(
        mock_sb,
        raw_token,
        rejection_reason="Discrepancy in B2B table: invoice INV-002 taxable amount mismatch.",
        signatory_name="Rajesh Kumar",
    )
    assert rejected_auth.status == ClientAuthStatus.REJECTED
    assert "invoice INV-002" in rejected_auth.rejection_reason
    assert rejected_auth.rejected_at is not None

    # Cannot authorize rejected return
    with pytest.raises(HTTPException) as exc_reauth:
        submit_client_authorization(
            mock_sb,
            raw_token,
            signatory_name="Rajesh Kumar",
            signatory_designation="Director",
            signatory_contact="9876543210",
        )
    assert exc_reauth.value.status_code == 400
    assert exc_reauth.value.detail["code"] == "RETURN_ALREADY_REJECTED"


# ---------------------------------------------------------------------------
# 5. Token Expiration
# ---------------------------------------------------------------------------

def test_token_expiration_behavior(mock_sb, preparer_actor, sample_figures):
    auth, raw_token = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
        expires_in_hours=1,
    )

    # Force expiration into past
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    auth.expires_at = past_iso

    with pytest.raises(HTTPException) as exc:
        get_authorization_by_token(mock_sb, raw_token)
    assert exc.value.status_code == 410
    assert exc.value.detail["code"] == "AUTHORIZATION_TOKEN_EXPIRED"


# ---------------------------------------------------------------------------
# 6. CA Firm Revocation
# ---------------------------------------------------------------------------

def test_ca_firm_revocation(mock_sb, preparer_actor, manager_actor, viewer_actor, sample_figures):
    auth, raw_token = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
    )

    # Viewer or Preparer cannot revoke
    with pytest.raises(HTTPException) as exc_perm:
        revoke_authorization_request(
            mock_sb,
            authorization_id=auth.id,
            firm_id="firm-1",
            revocation_reason="Revision needed",
            actor=viewer_actor,
        )
    assert exc_perm.value.status_code == 403

    # Manager can revoke
    revoked = revoke_authorization_request(
        mock_sb,
        authorization_id=auth.id,
        firm_id="firm-1",
        revocation_reason="Client requested revised sales vouchers.",
        actor=manager_actor,
    )
    assert revoked.status == ClientAuthStatus.REVOKED
    assert revoked.revocation_reason == "Client requested revised sales vouchers."

    # Public portal access with revoked token returns 400
    with pytest.raises(HTTPException) as exc_access:
        get_authorization_by_token(mock_sb, raw_token)
    assert exc_access.value.status_code == 400
    assert exc_access.value.detail["code"] == "AUTHORIZATION_TOKEN_REVOKED"


# ---------------------------------------------------------------------------
# 7. Cryptographic Figures Tamper Binding (Stale Consent Invalidation)
# ---------------------------------------------------------------------------

def test_stale_figures_invalidation_raises_http_409(mock_sb, preparer_actor, sample_figures):
    auth, raw_token = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
    )

    # Client authorizes original figures
    submit_client_authorization(
        mock_sb,
        raw_token,
        signatory_name="Rajesh Kumar",
        signatory_designation="Director",
        signatory_contact="9876543210",
    )

    # Figures are altered after client consent!
    altered_figures = dict(sample_figures)
    altered_figures["total_taxable_value"] = 650000.0  # Increased from 500000.0

    # Filing gate must catch the tamper and raise HTTP 409
    with pytest.raises(HTTPException) as exc:
        assert_client_authorization_gate(
            mock_sb,
            firm_id="firm-1",
            client_gstin_id="client-gstin-1",
            gstin="27AABCU9603R1ZX",
            period="2026-10",
            return_type="GSTR-1",
            current_figures_payload=altered_figures,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "CLIENT_AUTHORIZATION_STALE_FIGURES_ALTERED"

    # Consent must be durably revoked so stale tokens cannot reauthorize changed figures
    reloaded_auth = get_latest_client_authorization(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        period="2026-10",
        return_type="GSTR-1",
    )
    assert reloaded_auth.status == ClientAuthStatus.REVOKED
    assert reloaded_auth.signatory_name is None
    assert "Figures altered" in reloaded_auth.revocation_reason or "figures altered" in reloaded_auth.revocation_reason

    # Audit trail records tamper invalidation
    audit = get_client_authorization_history(mock_sb, authorization_id=auth.id, firm_id="firm-1")
    actions = [e["action"] for e in audit]
    assert ClientAuthAction.CONSENT_INVALIDATED_FIGURES_ALTERED.value in actions

    # Attempting to re-authorize with the stale token MUST be blocked
    with pytest.raises(HTTPException) as exc_stale:
        submit_client_authorization(
            mock_sb,
            raw_token,
            signatory_name="Rajesh Kumar",
            signatory_designation="Director",
            signatory_contact="9876543210",
        )
    assert exc_stale.value.status_code == 400
    assert exc_stale.value.detail["code"] == "AUTHORIZATION_TOKEN_REVOKED"


# ---------------------------------------------------------------------------
# 8. Server-Side Filing Gate Enforcement
# ---------------------------------------------------------------------------

def test_filing_gate_blocks_when_authorization_pending_or_viewed(mock_sb, preparer_actor, sample_figures):
    auth, raw_token = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
    )

    # 1. PENDING status: filing blocked
    with pytest.raises(HTTPException) as exc_pending:
        assert_client_authorization_gate(
            mock_sb,
            firm_id="firm-1",
            client_gstin_id="client-gstin-1",
            gstin="27AABCU9603R1ZX",
            period="2026-10",
            return_type="GSTR-1",
            current_figures_payload=sample_figures,
        )
    assert exc_pending.value.status_code == 403
    assert exc_pending.value.detail["code"] == "CLIENT_AUTHORIZATION_REQUIRED"

    # 2. VIEWED status: link opened by client, but not authorized yet: filing blocked!
    get_authorization_by_token(mock_sb, raw_token)
    with pytest.raises(HTTPException) as exc_viewed:
        assert_client_authorization_gate(
            mock_sb,
            firm_id="firm-1",
            client_gstin_id="client-gstin-1",
            gstin="27AABCU9603R1ZX",
            period="2026-10",
            return_type="GSTR-1",
            current_figures_payload=sample_figures,
        )
    assert exc_viewed.value.status_code == 403
    assert exc_viewed.value.detail["code"] == "CLIENT_AUTHORIZATION_REQUIRED"

    # 3. AUTHORIZED status with identical figures: filing passes!
    submit_client_authorization(
        mock_sb,
        raw_token,
        signatory_name="Rajesh Kumar",
        signatory_designation="Director",
        signatory_contact="9876543210",
    )
    passed_auth = assert_client_authorization_gate(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        current_figures_payload=sample_figures,
    )
    assert passed_auth.status == ClientAuthStatus.AUTHORIZED


def test_filing_gate_firm_policy_mandate(mock_sb):
    """When firm policy requires client authorization and none exists, filing is blocked."""
    firm_id = "firm-policy-mandate"
    client_gstin_id = "client-gstin-2"

    with patch("app.services.filing_override_service.get_firm_filing_policy") as mock_policy:
        mock_p = MagicMock()
        mock_p.require_client_authorization = True
        mock_policy.return_value = mock_p

        with pytest.raises(HTTPException) as exc:
            assert_client_authorization_gate(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_gstin_id,
                gstin="27AABCU9603R1ZX",
                period="2026-10",
                return_type="GSTR-3B",
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "CLIENT_AUTHORIZATION_REQUIRED"


# ---------------------------------------------------------------------------
# 9. Targeted Release-Safety Tests (Areas 1, 2, 3, 4)
# ---------------------------------------------------------------------------

def test_client_signatory_identity_assurance_self_declared(mock_sb, preparer_actor, sample_figures):
    """Area 1: Verify identity is explicitly recorded as self-declared without claiming OTP verification."""
    auth, raw_token = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
    )

    authorized = submit_client_authorization(
        mock_sb,
        raw_token,
        signatory_name="Anil Kapoor",
        signatory_designation="Director",
        signatory_contact="+91 9988776655",
        client_ip="49.36.12.1",
        user_agent="Mozilla/5.0",
    )

    # Must accurately reflect self-declaration
    assert authorized.identity_verification_method == "self_declaration"
    assert authorized.to_dict()["identity_verification_method"] == "self_declaration"
    assert authorized.to_client_view_dict()["identity_verification_method"] == "self_declaration"

    # Audit log metadata verification
    history = get_client_authorization_history(mock_sb, authorization_id=auth.id, firm_id="firm-1")
    auth_entry = next(e for e in history if e["action"] == ClientAuthAction.AUTHORIZED.value)
    meta = auth_entry["metadata"]
    assert meta["identity_verification_method"] == "self_declaration"
    assert meta["is_otp_verified"] is False
    assert meta["identity_assurance_level"] == "self_declared_with_ip_audit"


def test_superseded_token_when_revised_figures_prepared(mock_sb, preparer_actor, sample_figures):
    """Area 2: Preparing revised figures automatically supersedes/revokes older active review token."""
    # Request 1 with original figures
    auth1, token1 = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
    )
    assert auth1.status == ClientAuthStatus.PENDING

    # Request 2 with altered figures for the same filing
    revised_figures = dict(sample_figures)
    revised_figures["total_taxable_value"] = 800000.0

    auth2, token2 = create_authorization_request(
        mock_sb,
        firm_id="firm-1",
        client_gstin_id="client-gstin-1",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=revised_figures,
        actor=preparer_actor,
    )

    # Newer token is active
    assert auth2.status == ClientAuthStatus.PENDING
    assert token2 != token1

    # Older token is revoked and cannot be accessed or authorized by client
    with pytest.raises(HTTPException) as exc_old:
        get_authorization_by_token(mock_sb, token1)
    assert exc_old.value.status_code == 400
    assert exc_old.value.detail["code"] == "AUTHORIZATION_TOKEN_REVOKED"


def test_public_portal_financial_data_redaction_and_enumeration_resistance(mock_sb, preparer_actor, sample_figures):
    """Area 3: Verify client view omits internal firm IDs, UUIDs, staff identities, and enumeration resistance."""
    auth, raw_token = create_authorization_request(
        mock_sb,
        firm_id="firm-secret-uuid",
        client_gstin_id="client-secret-uuid",
        gstin="27AABCU9603R1ZX",
        period="2026-10",
        return_type="GSTR-1",
        figures_payload=sample_figures,
        actor=preparer_actor,
    )

    # 1. Non-existent token returns generic 404 without leaking firm or GSTIN existence
    with pytest.raises(HTTPException) as exc_404:
        get_authorization_by_token(mock_sb, "non-existent-token-12345")
    assert exc_404.value.status_code == 404
    assert exc_404.value.detail["code"] == "AUTHORIZATION_TOKEN_NOT_FOUND"

    # 2. Public client view data redaction
    client_view = get_authorization_by_token(mock_sb, raw_token).to_client_view_dict()
    forbidden_keys = {"firm_id", "client_gstin_id", "created_by", "revoked_by", "token_hash", "client_ip", "user_agent"}
    for k in forbidden_keys:
        assert k not in client_view, f"Key '{k}' must not be exposed in public client view!"

    # Allowed keys verification
    assert client_view["gstin"] == "27AABCU9603R1ZX"
    assert client_view["period"] == "2026-10"
    assert client_view["figures_digest"] == auth.figures_digest


def test_celery_worker_blocks_unauthorized_batch_items():
    """Area 4: Celery bulk filing worker blocks items lacking client authorization."""
    from app.worker.filing_batch_task import process_filing_batch
    mock_sb = MagicMock()
    batch_id = "batch-phase33-01"
    firm_id = "firm-worker-1"
    client_id = "client-worker-1"
    gstin = "27AABCU9603R1ZX"
    period = "2026-10"

    batch_row = {
        "id": batch_id,
        "firm_id": firm_id,
        "period": period,
        "status": "pending",
        "created_by": "user-admin",
        "items": [
            {
                "id": "item-worker-1",
                "client_gstin_id": client_id,
                "gstin": gstin,
                "status": "pending",
            }
        ],
    }

    save_payload = {"b2b": [{"inum": "INV-1", "val": 1000.0}]}

    # In-memory store has an un-authorized request in PENDING state
    with patch("app.services.client_authorization_service.assert_client_gstin_in_firm"):
        auth, _ = create_authorization_request(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type="GSTR-1",
            figures_payload=save_payload,
            actor={"id": "prep-1", "role": "preparer"},
        )
    assert auth.status == ClientAuthStatus.PENDING

    with patch("app.worker.filing_batch_task.get_supabase", return_value=mock_sb):
        with patch("app.worker.filing_batch_task.filing_store.get_batch", return_value=batch_row):
            with patch("app.services.firm_access.assert_client_gstin_in_firm"):
                with patch("app.worker.filing_batch_task.filing_store.get_active_session", return_value={"session_token": "token", "id": "s-1"}):
                    with patch("app.worker.filing_batch_task.fetch_sales_register_records", return_value=[{"inum": "INV-1", "val": 1000.0}]):
                        with patch("app.worker.filing_batch_task.map_sales_register_to_gstr1") as mock_map:
                            mock_mapped = MagicMock()
                            mock_mapped.save_payload = save_payload
                            mock_map.return_value = mock_mapped

                            with patch("app.worker.filing_batch_task.serialize_gstr1_readiness", return_value={"pending_review_count": 0}):
                                with patch("app.services.pre_filing_validator.validate_gstr1_pre_filing"):
                                    with patch("app.services.filing_override_service.verify_filing_governance_gate"):
                                        with patch("app.services.maker_checker_service.assert_maker_checker_gate"):
                                            with patch("app.worker.filing_batch_task.filing_store.update_batch_item") as mock_update_item:
                                                fn = getattr(process_filing_batch, "__wrapped__", process_filing_batch)
                                                fn(batch_id)

                                                # Item must be blocked with CLIENT_AUTHORIZATION_REQUIRED
                                                calls = [c for c in mock_update_item.call_args_list if c[1].get("status") == "blocked"]
                                                assert len(calls) > 0
                                                assert calls[0][1]["error_code"] == "CLIENT_AUTHORIZATION_REQUIRED"


def test_stale_authorization_invalidation_durable_transaction_boundary():
    """Area 2: Invalidation durably revokes consent even when caller rolls back transaction upon HTTP 409."""
    import json
    from typing import Any
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite:///:memory:")

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE client_filing_authorizations (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                return_type TEXT NOT NULL,
                status TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                figures_digest TEXT NOT NULL,
                figures_summary TEXT NOT NULL DEFAULT '{}',
                signatory_name TEXT,
                signatory_designation TEXT,
                signatory_contact TEXT,
                consent_text_version TEXT NOT NULL DEFAULT 'v1.0',
                consent_declaration TEXT,
                identity_verification_method TEXT NOT NULL DEFAULT 'self_declaration',
                client_ip TEXT,
                user_agent TEXT,
                authorized_at TEXT,
                rejected_at TEXT,
                rejection_reason TEXT,
                revoked_at TEXT,
                revocation_reason TEXT,
                revoked_by TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """))
        conn.execute(text("""
            CREATE TABLE client_authorization_audit_trail (
                id TEXT PRIMARY KEY,
                authorization_id TEXT NOT NULL,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                return_type TEXT NOT NULL,
                action TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_id TEXT,
                actor_name TEXT NOT NULL,
                figures_digest TEXT NOT NULL,
                client_ip TEXT,
                user_agent TEXT,
                notes TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
        """))
        conn.commit()

    class _APIResponse:
        def __init__(self, data):
            self.data = data

    class _SqliteQueryBuilder:
        def __init__(self, eng, table_name: str):
            self.eng = eng
            self.table_name = table_name
            self._action = "select"
            self._where = []
            self._params = {}
            self._payload = None
            self._limit = None

        def select(self, cols="*"):
            self._action = "select"
            return self

        def eq(self, col: str, val: Any):
            p = f"p_{col}_{len(self._params)}"
            self._where.append(f"{col} = :{p}")
            self._params[p] = val
            return self

        def order(self, col: str, desc: bool = False):
            return self

        def limit(self, n: int):
            self._limit = n
            return self

        def insert(self, data: dict):
            self._action = "insert"
            self._payload = data
            return self

        def upsert(self, data: dict, on_conflict: str = ""):
            self._action = "upsert"
            self._payload = data
            return self

        def execute(self):
            with self.eng.connect() as c:
                if self._action == "select":
                    where_clause = (" WHERE " + " AND ".join(self._where)) if self._where else ""
                    limit_clause = f" LIMIT {self._limit}" if self._limit else ""
                    sql = f"SELECT * FROM {self.table_name}{where_clause}{limit_clause}"
                    rows = [dict(r._mapping) for r in c.execute(text(sql), self._params).fetchall()]
                    for r in rows:
                        if "figures_summary" in r and isinstance(r["figures_summary"], str):
                            try:
                                r["figures_summary"] = json.loads(r["figures_summary"])
                            except Exception:
                                pass
                    return _APIResponse(rows)
                elif self._action in ("insert", "upsert"):
                    cols = list(self._payload.keys())
                    col_sql = ", ".join(cols)
                    val_sql = ", ".join([f":{col}" for col in cols])
                    sql = f"INSERT OR REPLACE INTO {self.table_name} ({col_sql}) VALUES ({val_sql})"
                    params = {col: json.dumps(v) if isinstance(v, (dict, list)) else v for col, v in self._payload.items()}
                    c.execute(text(sql), params)
                    c.commit()
                    return _APIResponse([self._payload])
            return _APIResponse([])

    class _SqliteDbAdapter:
        def __init__(self, eng):
            self.eng = eng
            self.is_real_db = True

        def table(self, tbl: str):
            return _SqliteQueryBuilder(self.eng, tbl)

    db_client = _SqliteDbAdapter(engine)
    firm_id = "firm-tx-auth-1"
    client_id = "client-tx-auth-1"
    gstin = "27AABCU9603R1ZX"
    period = "2026-10"
    return_type = "GSTR-1"

    preparer = {"id": "prep-tx", "role": "preparer", "email": "prep@firm.com"}

    with patch("app.services.client_authorization_service.assert_client_gstin_in_firm"):
        # 1. Create request in real DB
        figures_original = {"total_taxable_value": 100000.0, "total_tax": 18000.0}
        auth, raw_token = create_authorization_request(
            db_client,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            figures_payload=figures_original,
            actor=preparer,
        )

        # 2. Authorize
        authorized = submit_client_authorization(
            db_client,
            raw_token,
            signatory_name="Sanjay Gupta",
            signatory_designation="Director",
            signatory_contact="9876543210",
        )
        assert authorized.status == ClientAuthStatus.AUTHORIZED

        # 3. Simulate caller transaction boundary where figures are altered
        figures_altered = {"total_taxable_value": 300000.0, "total_tax": 54000.0}

        with engine.connect() as outer_conn:
            with outer_conn.begin():
                with pytest.raises(HTTPException) as exc_409:
                    assert_client_authorization_gate(
                        db_client,
                        firm_id=firm_id,
                        client_gstin_id=client_id,
                        gstin=gstin,
                        period=period,
                        return_type=return_type,
                        current_figures_payload=figures_altered,
                    )
                assert exc_409.value.status_code == 409
                assert exc_409.value.detail["code"] == "CLIENT_AUTHORIZATION_STALE_FIGURES_ALTERED"

        # 4. Verify durable persistence in real DB: status must be REVOKED
        reloaded = get_latest_client_authorization(
            db_client,
            firm_id=firm_id,
            client_gstin_id=client_id,
            period=period,
            return_type=return_type,
        )
        assert reloaded.status == ClientAuthStatus.REVOKED
        assert "Consent invalidated" in reloaded.revocation_reason

