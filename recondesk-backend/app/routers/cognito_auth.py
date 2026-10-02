from __future__ import annotations

import logging
import uuid
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
from app.cognito_verifier import get_current_cognito_claims, verify_cognito_token
from app.database import get_supabase, get_user_profile
from app.services.cognito_service import (
    CognitoCodeExpiredError,
    CognitoCodeMismatchError,
    CognitoInvalidCredentialsError,
    CognitoInvalidPasswordError,
    CognitoRateLimitError,
    CognitoService,
    CognitoServiceError,
    CognitoUserExistsError,
    CognitoUserNotConfirmedError,
    CognitoUserNotFoundError,
    get_cognito_service,
)
from app.utils.email_domain import validate_email_mx
from app.utils.rate_limit import limiter

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/cognito", tags=["Cognito Auth"])

from app.cognito_aurora_store import get_identity_store, set_identity_store


def get_ownership_verifier() -> Callable[[str, str, dict[str, Any]], bool]:
    """Dependency provider for server-side ownership verification.

    Enables test fixtures to inject mock verifiers via FastAPI dependency overrides (Item 1).
    """
    from app.cognito_aurora_store import verify_ownership_proof
    return verify_ownership_proof


def _lookup_profile_by_id(user_id: str) -> Optional[dict[str, Any]]:
    try:
        store = get_identity_store()
        if hasattr(store, "get_user_profile_by_id"):
            profile = store.get_user_profile_by_id(user_id)
            if profile is not None:
                return profile
    except Exception:
        pass
    return get_user_profile(user_id)


def _lookup_profile_by_email(email: str) -> Optional[dict[str, Any]]:
    try:
        store = get_identity_store()
        if hasattr(store, "get_user_profile_by_email"):
            profile = store.get_user_profile_by_email(email)
            if profile is not None:
                return profile
    except Exception:
        pass
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


class LookupMappingResponse(BaseModel):
    account_mapping_status: str  # "verified_mapping_found" or "pending_trusted_mapping_phase"
    user_id: Optional[str] = None


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


@router.post("/lookup-mapping", response_model=LookupMappingResponse)
async def cognito_lookup_mapping(
    claims: dict[str, Any] = Depends(get_current_cognito_claims),
    config: CognitoConfig = Depends(get_cognito_config),
    store: CognitoIdentityStore = Depends(get_identity_store),
) -> LookupMappingResponse:
    """Look up whether an exact, verified Cognito identity mapping exists in Aurora.

    Security Enforcement:
      1. Authenticated strictly via Cognito Bearer access-token verification.
      2. Derives cognito_sub strictly from the verified token's 'sub' claim.
      3. Derives user pool from the verified token's issuer and configured COGNITO_USER_POOL_ID.
      4. Does not accept or trust any identity parameters from the request body or query string.
      5. Missing/invalid/expired token or non-access token returns HTTP 401.
      6. Valid token with no valid mapping returns fail-closed pending status.
      7. Response returns ONLY account_mapping_status and user_id (when mapping is valid).
    """
    sub = claims.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verified token missing or invalid 'sub' claim",
        )

    configured_pool = config.COGNITO_USER_POOL_ID.strip()
    expected_issuer = config.issuer

    # Validate issuer matches configured User Pool
    iss = claims.get("iss", "")
    if iss != expected_issuer:
        _log.warning(
            "Token issuer mismatch in lookup-mapping: expected %r, got %r",
            expected_issuer,
            iss,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token was issued by an untrusted Cognito User Pool.",
        )

    # Validate token_use is strictly 'access'
    if claims.get("token_use") != "access":
        _log.warning(
            "Token use mismatch in lookup-mapping: expected 'access', got %r",
            claims.get("token_use"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token_use: expected 'access'",
        )

    # Query Aurora trusted store with verified sub and configured pool
    mapping_result = None
    if hasattr(store, "lookup_trusted_mapping"):
        def _resolve_profile(uid: str) -> Optional[dict[str, Any]]:
            if hasattr(store, "get_user_profile_by_id"):
                try:
                    prof = store.get_user_profile_by_id(uid)
                    if prof is not None:
                        return prof
                except Exception:
                    pass
            return _lookup_profile_by_id(uid)

        mapping_result = store.lookup_trusted_mapping(
            sub,
            pool_id=configured_pool,
            profile_lookup_fn=_resolve_profile,
        )
    else:
        mapping = store.get_mapping_by_sub(sub, pool_id=configured_pool)
        if (
            mapping
            and mapping.verified
            and mapping.cognito_user_pool_id == configured_pool
            and mapping.cognito_sub == sub
        ):
            profile = _lookup_profile_by_id(mapping.user_id)
            if profile and profile.get("is_active", True):
                mapping_result = {
                    "user_id": mapping.user_id,
                    "cognito_sub": mapping.cognito_sub,
                    "is_verified": True,
                }

    if mapping_result and mapping_result.get("user_id"):
        return LookupMappingResponse(
            account_mapping_status="verified_mapping_found",
            user_id=str(mapping_result["user_id"]),
        )

    return LookupMappingResponse(
        account_mapping_status="pending_trusted_mapping_phase",
        user_id=None,
    )


# ── Phase 7: Production Cognito Authentication Endpoints ──────────────────────


class CognitoSignupRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=6, description="User password")
    full_name: str = Field(..., min_length=1, description="Full name")
    firm_name: Optional[str] = Field(None, description="Accounting / CA firm name")
    phone: Optional[str] = Field(None, description="Contact phone number")


class CognitoSignupResponse(BaseModel):
    message: str
    user_id: str
    cognito_sub: str
    user_confirmed: bool
    delivery_medium: Optional[str] = None
    destination: Optional[str] = None


class CognitoConfirmSignupRequest(BaseModel):
    email: str
    confirmation_code: str


class CognitoResendCodeRequest(BaseModel):
    email: str


class CognitoLoginRequest(BaseModel):
    email: str
    password: str


class CognitoLoginResponse(BaseModel):
    access_token: str
    id_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: int = 3600
    token_type: str = "Bearer"
    user: dict[str, Any]
    provider: str = "cognito"


class CognitoForgotPasswordRequest(BaseModel):
    email: str


class CognitoConfirmForgotPasswordRequest(BaseModel):
    email: str
    confirmation_code: str
    new_password: str = Field(..., min_length=6)


class CognitoRefreshRequest(BaseModel):
    refresh_token: str


class CognitoLogoutRequest(BaseModel):
    access_token: Optional[str] = None


@router.post("/signup", response_model=CognitoSignupResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def cognito_signup(
    request: Request,
    payload: CognitoSignupRequest,
    config: CognitoConfig = Depends(get_cognito_config),
    cognito_service: CognitoService = Depends(get_cognito_service),
    store: CognitoIdentityStore = Depends(get_identity_store),
) -> CognitoSignupResponse:
    """Register a new user in Amazon Cognito User Pool and provision their profile in Aurora."""
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is disabled on this server.",
        )

    clean_email = payload.email.strip().lower()
    validate_email_mx(clean_email)

    try:
        res = cognito_service.signup(
            email=clean_email,
            password=payload.password,
            full_name=payload.full_name,
            phone=payload.phone,
        )
    except CognitoUserExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists. Please sign in or reset your password.",
        ) from exc
    except CognitoInvalidPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        ) from exc
    except CognitoServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        ) from exc

    user_sub = str(res["user_sub"])
    user_confirmed = bool(res["user_confirmed"])
    delivery = res.get("code_delivery_details") or {}

    # Check if profile already exists in Aurora
    existing_profile = None
    if hasattr(store, "get_user_profile_by_email"):
        existing_profile = store.get_user_profile_by_email(clean_email)

    if existing_profile:
        user_id = str(existing_profile["id"])
    else:
        user_id = str(uuid.uuid4())
        if hasattr(store, "create_user_profile"):
            store.create_user_profile(
                user_id=user_id,
                email=clean_email,
                full_name=payload.full_name,
                firm_name=payload.firm_name,
                phone=payload.phone,
                role="admin",
                is_active=True,
                runs_limit=2,
            )

    # Pre-provision mapping in Aurora
    if hasattr(store, "pre_provision_mapping"):
        try:
            store.pre_provision_mapping(
                user_id=user_id,
                cognito_sub=user_sub,
                email=clean_email,
                pool_id=config.COGNITO_USER_POOL_ID,
                provisioned_by="self_signup",
            )
        except Exception as exc:
            _log.warning("Could not pre-provision mapping during signup: %s", exc)

    # Mirror to Supabase if Supabase is active
    try:
        sb = get_supabase()
        sb.table("user_profiles").upsert({
            "id": user_id,
            "email": clean_email,
            "full_name": payload.full_name,
            "firm_name": payload.firm_name,
            "phone": payload.phone,
            "role": "admin",
            "is_active": True,
            "runs_limit": 2,
        }, on_conflict="id").execute()
    except Exception as exc:
        _log.debug("Supabase mirror during signup skipped: %s", exc)

    return CognitoSignupResponse(
        message="Sign up successful. Please verify your email with the confirmation code.",
        user_id=user_id,
        cognito_sub=user_sub,
        user_confirmed=user_confirmed,
        delivery_medium=delivery.get("DeliveryMedium"),
        destination=delivery.get("Destination"),
    )


@router.post("/confirm-signup")
@limiter.limit("10/minute")
async def cognito_confirm_signup(
    request: Request,
    payload: CognitoConfirmSignupRequest,
    config: CognitoConfig = Depends(get_cognito_config),
    cognito_service: CognitoService = Depends(get_cognito_service),
) -> dict[str, Any]:
    """Verify signup confirmation code with Cognito."""
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is disabled on this server.",
        )
    try:
        cognito_service.confirm_signup(payload.email, payload.confirmation_code)
        return {"message": "Account confirmed successfully. You can now log in."}
    except (CognitoCodeMismatchError, CognitoCodeExpiredError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except CognitoServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.post("/resend-code")
@limiter.limit("5/minute")
async def cognito_resend_code(
    request: Request,
    payload: CognitoResendCodeRequest,
    config: CognitoConfig = Depends(get_cognito_config),
    cognito_service: CognitoService = Depends(get_cognito_service),
) -> dict[str, Any]:
    """Resend email confirmation code."""
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is disabled on this server.",
        )
    try:
        res = cognito_service.resend_confirmation_code(payload.email)
        return {
            "message": "Verification code resent successfully.",
            "details": res.get("code_delivery_details"),
        }
    except CognitoServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.post("/login", response_model=CognitoLoginResponse)
@limiter.limit("10/minute")
async def cognito_login(
    request: Request,
    payload: CognitoLoginRequest,
    config: CognitoConfig = Depends(get_cognito_config),
    cognito_service: CognitoService = Depends(get_cognito_service),
    store: CognitoIdentityStore = Depends(get_identity_store),
) -> CognitoLoginResponse:
    """Direct username & password authentication with Amazon Cognito and Supabase fallback."""
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is disabled on this server.",
        )

    clean_email = payload.email.strip().lower()
    cognito_tokens = None

    # 1. Authenticate directly via Amazon Cognito (100% Cognito Cutover)
    try:
        cognito_tokens = cognito_service.login(clean_email, payload.password)
    except (CognitoInvalidCredentialsError, CognitoUserNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except CognitoUserNotConfirmedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address is not confirmed. Please check your inbox for the verification code.",
        ) from exc
    except CognitoServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        ) from exc

    # 2. Cognito tokens obtained: extract claims and ensure Aurora mapping exists
    access_token = cognito_tokens["access_token"]
    try:
        claims = verify_cognito_token(access_token, expected_token_use="access", config=config)
    except Exception as exc:
        _log.error("Failed to verify newly issued Cognito token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify authentication session.",
        ) from exc

    sub = str(claims.get("sub") or "").strip()
    configured_pool = config.COGNITO_USER_POOL_ID.strip()

    # Resolve mapped profile
    user_id = None
    profile = None
    if hasattr(store, "get_mapping_by_sub"):
        mapping = store.get_mapping_by_sub(sub, pool_id=configured_pool)
        if mapping and mapping.verified:
            user_id = mapping.user_id

    if not user_id:
        # Check if profile exists by email in Aurora or Supabase
        prof = _lookup_profile_by_email(clean_email)
        if prof:
            user_id = str(prof["id"])
            profile = prof
        else:
            user_id = str(uuid.uuid4())
            if hasattr(store, "create_user_profile"):
                profile = store.create_user_profile(
                    user_id=user_id,
                    email=clean_email,
                    role="admin",
                    is_active=True,
                )

        if hasattr(store, "pre_provision_mapping"):
            try:
                store.pre_provision_mapping(
                    user_id=user_id,
                    cognito_sub=sub,
                    email=clean_email,
                    pool_id=configured_pool,
                    provisioned_by="direct_login",
                )
            except Exception as exc:
                _log.warning("Could not pre-provision mapping on login: %s", exc)

    if not profile and hasattr(store, "get_user_profile_by_id"):
        profile = store.get_user_profile_by_id(user_id)
    if not profile:
        profile = _lookup_profile_by_id(user_id)

    return CognitoLoginResponse(
        access_token=access_token,
        id_token=cognito_tokens.get("id_token"),
        refresh_token=cognito_tokens.get("refresh_token"),
        expires_in=cognito_tokens.get("expires_in", 3600),
        token_type="Bearer",
        user=profile or {"id": user_id, "email": clean_email},
        provider="cognito",
    )


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def cognito_forgot_password(
    request: Request,
    payload: CognitoForgotPasswordRequest,
    config: CognitoConfig = Depends(get_cognito_config),
    cognito_service: CognitoService = Depends(get_cognito_service),
) -> dict[str, Any]:
    """Initiate password reset via Amazon Cognito."""
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is disabled on this server.",
        )
    try:
        res = cognito_service.forgot_password(payload.email)
        return {
            "message": "Password reset code sent to your email.",
            "delivery": res.get("code_delivery_details"),
        }
    except CognitoUserNotFoundError:
        return {"message": "If an account with that email exists, a password reset code has been sent."}
    except CognitoServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.post("/confirm-forgot-password")
@limiter.limit("5/minute")
async def cognito_confirm_forgot_password(
    request: Request,
    payload: CognitoConfirmForgotPasswordRequest,
    config: CognitoConfig = Depends(get_cognito_config),
    cognito_service: CognitoService = Depends(get_cognito_service),
) -> dict[str, Any]:
    """Complete password reset using confirmation code and new password."""
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is disabled on this server.",
        )
    try:
        cognito_service.confirm_forgot_password(
            email=payload.email,
            confirmation_code=payload.confirmation_code,
            new_password=payload.new_password,
        )
        return {"message": "Password reset successfully. You may now log in with your new password."}
    except (CognitoCodeMismatchError, CognitoCodeExpiredError, CognitoInvalidPasswordError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except CognitoServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.post("/refresh")
@limiter.limit("20/minute")
async def cognito_refresh(
    request: Request,
    payload: CognitoRefreshRequest,
    config: CognitoConfig = Depends(get_cognito_config),
    cognito_service: CognitoService = Depends(get_cognito_service),
) -> dict[str, Any]:
    """Exchange refresh token for fresh Cognito access and ID tokens."""
    if not config.COGNITO_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito authentication is disabled on this server.",
        )
    try:
        tokens = cognito_service.refresh(payload.refresh_token)
        return tokens
    except CognitoServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        ) from exc


@router.post("/logout")
async def cognito_logout(
    request: Request,
    payload: Optional[CognitoLogoutRequest] = None,
    cognito_service: CognitoService = Depends(get_cognito_service),
) -> dict[str, Any]:
    """Revoke tokens and sign out of Cognito."""
    token = None
    if payload and payload.access_token:
        token = payload.access_token
    else:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

    if token:
        cognito_service.global_sign_out(token)

    return {"message": "Logged out successfully."}
