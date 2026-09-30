from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.cognito_config import CognitoConfig, get_cognito_config
from app.cognito_identity import (
    CognitoAccountConflictError,
    CognitoAccountLinkingRequiredError,
    CognitoIdentityError,
    CognitoIdentityStore,
    InMemoryCognitoIdentityStore,
    complete_account_linking,
    resolve_cognito_user_id,
)
from app.cognito_verifier import get_current_cognito_claims
from app.database import get_user_profile
from app.utils.rate_limit import limiter

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/cognito", tags=["Cognito Auth (Dev)"])

# Development-only in-memory identity mapping store
_identity_store: CognitoIdentityStore = InMemoryCognitoIdentityStore()


def get_identity_store() -> CognitoIdentityStore:
    return _identity_store


def set_identity_store(store: CognitoIdentityStore) -> None:
    global _identity_store
    _identity_store = store


def get_ownership_verifier() -> Callable[[str, str, dict[str, Any]], bool]:
    """Dependency provider for server-side ownership verification.

    Enables test fixtures to inject mock verifiers via FastAPI dependency overrides (Item 1).
    """
    from app.cognito_aurora_store import verify_ownership_proof
    return verify_ownership_proof


def _lookup_profile_by_id(user_id: str) -> Optional[dict[str, Any]]:
    return get_user_profile(user_id)


def _lookup_profile_by_email(email: str) -> Optional[dict[str, Any]]:
    try:
        from app.database import get_supabase
        sb = get_supabase()
        res = (
            sb.table("user_profiles")
            .select("*")
            .ilike("email", email)
            .limit(1)
            .execute()
        )
        data = res.data or []
        return data[0] if data else None
    except Exception:
        return None


class CognitoStatusResponse(BaseModel):
    enabled: bool
    region: str
    user_pool_id: str
    client_id: str
    redirect_uri: str
    logout_uri: str
    issuer: str
    has_client_secret: bool
    domain: Optional[str] = None
    domain_url: Optional[str] = None
    authorize_url: Optional[str] = None
    token_url: Optional[str] = None


class AccountLinkingRequest(BaseModel):
    linking_token: str = Field(..., description="One-time cryptographically secure linking token")


class RequestLinkingTokenPayload(BaseModel):
    """Payload for initiating account linking.

    Security Policies (Items 1 & 2):
      - Only trusted user-supplied proof (active Supabase session token or password) is accepted.
      - Disallows mock proof types or client-supplied administrative dictionaries.
    """
    supabase_token: Optional[str] = Field(None, description="Active Supabase session JWT proving ownership")
    password: Optional[str] = Field(None, description="Account password credential proving ownership")


class AccountLinkingInitiateResponse(BaseModel):
    message: str
    linking_token: str


@router.get("/status", response_model=CognitoStatusResponse)
async def cognito_status(
    config: CognitoConfig = Depends(get_cognito_config),
) -> CognitoStatusResponse:
    """Return public Cognito environment configuration for verification.

    Never exposes secrets or credentials.
    """
    safe = config.get_safe_dict()
    return CognitoStatusResponse(
        enabled=safe["auth_enabled"],
        region=safe["region"],
        user_pool_id=safe["user_pool_id"],
        client_id=safe["client_id"],
        redirect_uri=safe["redirect_uri"],
        logout_uri=safe["logout_uri"],
        issuer=safe["issuer"],
        has_client_secret=safe["has_client_secret"],
        domain=safe.get("domain"),
        domain_url=safe.get("domain_url"),
        authorize_url=safe.get("authorize_url"),
        token_url=safe.get("token_url"),
    )


@router.get("/me")
async def cognito_me(
    claims: dict[str, Any] = Depends(get_current_cognito_claims),
    config: CognitoConfig = Depends(get_cognito_config),
    store: CognitoIdentityStore = Depends(get_identity_store),
) -> dict[str, Any]:
    """Resolve authenticated Cognito claims to a ReconDesk user profile.

    Strictly preserves existing user_profiles.id, firm ownership, and staff roles.
    Fails closed if the email matches an existing account without established mapping.
    Pool ID is derived strictly from trusted server configuration (Item 5).
    """
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is disabled on this server.",
        )

    try:
        resolved_user_id = resolve_cognito_user_id(
            claims,
            identity_store=store,
            profile_lookup_fn=_lookup_profile_by_id,
            profile_by_email_fn=_lookup_profile_by_email,
            auto_provision_new_users=False,
            expected_user_pool_id=config.COGNITO_USER_POOL_ID,
        )
    except CognitoAccountLinkingRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ACCOUNT_LINKING_REQUIRED",
                "message": str(exc),
                "email": exc.email,
            },
        ) from exc
    except (CognitoAccountConflictError, CognitoIdentityError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Identity resolution failed: unauthorized or conflicting identity.",
        ) from exc

    profile = _lookup_profile_by_id(resolved_user_id) or {
        "id": resolved_user_id,
        "email": claims.get("email"),
        "role": "admin",
        "is_active": True,
    }

    return {
        "user_id": resolved_user_id,
        "cognito_sub": claims.get("sub"),
        "profile": profile,
        "token_use": claims.get("token_use"),
    }


@router.post("/request-link", response_model=AccountLinkingInitiateResponse)
@limiter.limit("5/minute")
async def cognito_request_linking_token(
    request: Request,
    payload: RequestLinkingTokenPayload,
    claims: dict[str, Any] = Depends(get_current_cognito_claims),
    config: CognitoConfig = Depends(get_cognito_config),
    store: CognitoIdentityStore = Depends(get_identity_store),
    ownership_verifier: Callable[[str, str, dict[str, Any]], bool] = Depends(get_ownership_verifier),
) -> AccountLinkingInitiateResponse:
    """Issue a one-time account-linking token ONLY after trusted server-side proof
    of existing ReconDesk account ownership (Requirements 2, 3, 5, 8).

    Rate-limited to 5 requests per minute.
    """
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is disabled on this server.",
        )

    sub = claims.get("sub")
    email = (claims.get("email") or "").strip().lower()
    if not sub or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated Cognito claims must contain valid sub and email.",
        )

    # Locate existing ReconDesk profile
    profile = _lookup_profile_by_email(email)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existing ReconDesk account matches this email address.",
        )

    user_id = str(profile.get("id"))

    # Construct ownership proof dictionary strictly from verified credentials (Item 2)
    if payload.supabase_token:
        ownership_proof = {"type": "supabase_jwt", "token": payload.supabase_token}
    elif payload.password:
        ownership_proof = {"type": "supabase_password", "password": payload.password}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ownership proof (supabase_token or password) is required to issue linking token.",
        )

    client_ip = request.client.host if request.client else None

    try:
        token = store.issue_account_linking_token(
            user_id=user_id,
            cognito_sub=sub,
            email=email,
            ownership_proof=ownership_proof,
            pool_id=config.COGNITO_USER_POOL_ID,
            created_ip=client_ip,
            verify_proof_fn=ownership_verifier,
        )
    except (CognitoIdentityError, CognitoAccountConflictError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Failed to issue account linking token: proof of ownership rejected.",
        ) from exc

    return AccountLinkingInitiateResponse(
        message="Account linking token issued successfully.",
        linking_token=token,
    )


@router.post("/link")
@limiter.limit("5/minute")
async def cognito_link_account(
    request: Request,
    payload: AccountLinkingRequest,
    claims: dict[str, Any] = Depends(get_current_cognito_claims),
    config: CognitoConfig = Depends(get_cognito_config),
    store: CognitoIdentityStore = Depends(get_identity_store),
) -> dict[str, Any]:
    """Complete cryptographic account linking between an existing ReconDesk profile and Cognito sub.

    Rate-limited to 5 requests per minute.
    """
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is disabled on this server.",
        )

    client_ip = request.client.host if request.client else None

    try:
        user_id = complete_account_linking(
            payload.linking_token,
            claims,
            identity_store=store,
            profile_lookup_fn=_lookup_profile_by_id,
            expected_user_pool_id=config.COGNITO_USER_POOL_ID,
            linking_ip=client_ip,
        )
    except (CognitoAccountConflictError, CognitoIdentityError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account linking failed: invalid, expired, or conflicting token.",
        ) from exc

    return {
        "status": "linked",
        "user_id": user_id,
        "cognito_sub": claims.get("sub"),
    }
