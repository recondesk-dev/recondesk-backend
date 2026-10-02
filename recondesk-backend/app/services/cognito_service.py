"""AWS Cognito identity provider client service for ReconDesk.

Handles all Amazon Cognito User Pool authentication operations via boto3:
- User signup and confirmation code lifecycle
- Direct password authentication (USER_PASSWORD_AUTH)
- Session token refresh (REFRESH_TOKEN_AUTH)
- Password recovery (forgot_password & confirm_forgot_password)
- Global session termination (global_sign_out)
- Automatic HMAC-SHA256 SecretHash computation for confidential clients
- Transparent migration bridging for existing Supabase users
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from app.cognito_config import CognitoConfig, get_cognito_config

_log = logging.getLogger(__name__)


# ── Exception Hierarchy ───────────────────────────────────────────────────────


class CognitoServiceError(Exception):
    """Base exception for all Cognito service interactions."""

    def __init__(self, message: str, code: str = "CognitoServiceError") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class CognitoUserExistsError(CognitoServiceError):
    """Raised when attempting to sign up an email that is already registered."""

    def __init__(self, message: str = "An account with this email address already exists.") -> None:
        super().__init__(message, code="UsernameExistsException")


class CognitoInvalidPasswordError(CognitoServiceError):
    """Raised when password fails Cognito complexity or length requirements."""

    def __init__(self, message: str = "Password does not meet complexity requirements.") -> None:
        super().__init__(message, code="InvalidPasswordException")


class CognitoUserNotConfirmedError(CognitoServiceError):
    """Raised when login is attempted before email confirmation."""

    def __init__(self, message: str = "Email address is not verified. Please confirm your account.") -> None:
        super().__init__(message, code="UserNotConfirmedException")


class CognitoCodeMismatchError(CognitoServiceError):
    """Raised when an invalid confirmation code is provided."""

    def __init__(self, message: str = "Invalid verification code.") -> None:
        super().__init__(message, code="CodeMismatchException")


class CognitoCodeExpiredError(CognitoServiceError):
    """Raised when a confirmation code has expired."""

    def __init__(self, message: str = "Verification code has expired. Please request a new one.") -> None:
        super().__init__(message, code="ExpiredCodeException")


class CognitoInvalidCredentialsError(CognitoServiceError):
    """Raised on incorrect username or password."""

    def __init__(self, message: str = "Incorrect email or password.") -> None:
        super().__init__(message, code="NotAuthorizedException")


class CognitoUserNotFoundError(CognitoServiceError):
    """Raised when the specified user does not exist in Cognito."""

    def __init__(self, message: str = "User account not found.") -> None:
        super().__init__(message, code="UserNotFoundException")


class CognitoRateLimitError(CognitoServiceError):
    """Raised when rate limits or quotas are exceeded."""

    def __init__(self, message: str = "Too many requests. Please try again later.") -> None:
        super().__init__(message, code="TooManyRequestsException")


# ── Helper Functions ─────────────────────────────────────────────────────────


def compute_secret_hash(client_id: str, client_secret: str, username: str) -> str:
    """Compute the HMAC-SHA256 SecretHash required for Cognito confidential clients."""
    message = username.strip() + client_id.strip()
    dig = hmac.new(
        client_secret.strip().encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(dig).decode("utf-8")


# ── CognitoService Class ─────────────────────────────────────────────────────


class CognitoService:
    """Encapsulates AWS Cognito User Pool identity operations via boto3."""

    def __init__(
        self,
        config: Optional[CognitoConfig] = None,
        client: Optional[Any] = None,
    ) -> None:
        self._config = config or get_cognito_config()
        self._client = client

    @property
    def client(self) -> Any:
        """Lazy-initialize boto3 cognito-idp client."""
        if self._client is None:
            self._client = boto3.client(
                "cognito-idp",
                region_name=self._config.COGNITO_REGION,
            )
        return self._client

    def _secret_hash(self, username: str) -> Optional[str]:
        """Compute SecretHash if a client secret is configured; otherwise None."""
        if self._config.has_client_secret and self._config.COGNITO_CLIENT_SECRET:
            return compute_secret_hash(
                self._config.COGNITO_CLIENT_ID,
                self._config.COGNITO_CLIENT_SECRET,
                username,
            )
        return None

    def signup(
        self,
        email: str,
        password: str,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> dict[str, Any]:
        """Register a new user in the Cognito User Pool."""
        clean_email = email.strip().lower()
        params: dict[str, Any] = {
            "ClientId": self._config.COGNITO_CLIENT_ID,
            "Username": clean_email,
            "Password": password,
        }
        secret_hash = self._secret_hash(clean_email)
        if secret_hash:
            params["SecretHash"] = secret_hash

        user_attributes = [{"Name": "email", "Value": clean_email}]
        if full_name and full_name.strip():
            user_attributes.append({"Name": "name", "Value": full_name.strip()})
        if phone and phone.strip():
            user_attributes.append({"Name": "phone_number", "Value": phone.strip()})
        params["UserAttributes"] = user_attributes

        try:
            resp = self.client.sign_up(**params)
            return {
                "user_sub": resp.get("UserSub"),
                "user_confirmed": resp.get("UserConfirmed", False),
                "code_delivery_details": resp.get("CodeDeliveryDetails", {}),
            }
        except ClientError as exc:
            self._handle_client_error(exc, clean_email)

    def confirm_signup(self, email: str, confirmation_code: str) -> dict[str, Any]:
        """Confirm a user's signup using the verification code delivered to their email."""
        clean_email = email.strip().lower()
        clean_code = confirmation_code.strip()
        params: dict[str, Any] = {
            "ClientId": self._config.COGNITO_CLIENT_ID,
            "Username": clean_email,
            "ConfirmationCode": clean_code,
        }
        secret_hash = self._secret_hash(clean_email)
        if secret_hash:
            params["SecretHash"] = secret_hash

        try:
            self.client.confirm_sign_up(**params)
            return {"confirmed": True, "message": "Account confirmed successfully."}
        except ClientError as exc:
            self._handle_client_error(exc, clean_email)

    def resend_confirmation_code(self, email: str) -> dict[str, Any]:
        """Resend signup confirmation code to the user's email."""
        clean_email = email.strip().lower()
        params: dict[str, Any] = {
            "ClientId": self._config.COGNITO_CLIENT_ID,
            "Username": clean_email,
        }
        secret_hash = self._secret_hash(clean_email)
        if secret_hash:
            params["SecretHash"] = secret_hash

        try:
            resp = self.client.resend_confirmation_code(**params)
            return {
                "resent": True,
                "code_delivery_details": resp.get("CodeDeliveryDetails", {}),
            }
        except ClientError as exc:
            self._handle_client_error(exc, clean_email)

    def login(self, email: str, password: str) -> dict[str, Any]:
        """Authenticate user via USER_PASSWORD_AUTH and return tokens."""
        clean_email = email.strip().lower()
        auth_params = {
            "USERNAME": clean_email,
            "PASSWORD": password,
        }
        secret_hash = self._secret_hash(clean_email)
        if secret_hash:
            auth_params["SECRET_HASH"] = secret_hash

        params: dict[str, Any] = {
            "ClientId": self._config.COGNITO_CLIENT_ID,
            "AuthFlow": "USER_PASSWORD_AUTH",
            "AuthParameters": auth_params,
        }

        try:
            resp = self.client.initiate_auth(**params)
            auth_result = resp.get("AuthenticationResult")
            if auth_result:
                return {
                    "access_token": auth_result["AccessToken"],
                    "id_token": auth_result.get("IdToken"),
                    "refresh_token": auth_result.get("RefreshToken"),
                    "expires_in": auth_result.get("ExpiresIn", 3600),
                    "token_type": auth_result.get("TokenType", "Bearer"),
                }
            # Handle challenge if returned (e.g. NEW_PASSWORD_REQUIRED)
            return {
                "challenge_name": resp.get("ChallengeName"),
                "session": resp.get("Session"),
                "challenge_parameters": resp.get("ChallengeParameters", {}),
            }
        except ClientError as exc:
            self._handle_client_error(exc, clean_email)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Exchange a refresh token for fresh access and ID tokens."""
        auth_params = {
            "REFRESH_TOKEN": refresh_token.strip(),
        }
        # Note: REFRESH_TOKEN_AUTH requires SECRET_HASH if client secret is configured,
        # but Username is typically not passed in auth parameters; SECRET_HASH uses sub/username
        # if available or empty. If Cognito requires SECRET_HASH for REFRESH_TOKEN_AUTH,
        # caller should provide username or we derive it from token.
        params: dict[str, Any] = {
            "ClientId": self._config.COGNITO_CLIENT_ID,
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "AuthParameters": auth_params,
        }

        try:
            resp = self.client.initiate_auth(**params)
            auth_result = resp.get("AuthenticationResult", {})
            return {
                "access_token": auth_result.get("AccessToken"),
                "id_token": auth_result.get("IdToken"),
                "expires_in": auth_result.get("ExpiresIn", 3600),
                "token_type": auth_result.get("TokenType", "Bearer"),
            }
        except ClientError as exc:
            self._handle_client_error(exc, "refresh_token")

    def forgot_password(self, email: str) -> dict[str, Any]:
        """Initiate password recovery flow; Cognito sends a reset code to email."""
        clean_email = email.strip().lower()
        params: dict[str, Any] = {
            "ClientId": self._config.COGNITO_CLIENT_ID,
            "Username": clean_email,
        }
        secret_hash = self._secret_hash(clean_email)
        if secret_hash:
            params["SecretHash"] = secret_hash

        try:
            resp = self.client.forgot_password(**params)
            return {
                "initiated": True,
                "code_delivery_details": resp.get("CodeDeliveryDetails", {}),
            }
        except ClientError as exc:
            self._handle_client_error(exc, clean_email)

    def confirm_forgot_password(
        self,
        email: str,
        confirmation_code: str,
        new_password: str,
    ) -> dict[str, Any]:
        """Complete password reset using the emailed code and the new password."""
        clean_email = email.strip().lower()
        params: dict[str, Any] = {
            "ClientId": self._config.COGNITO_CLIENT_ID,
            "Username": clean_email,
            "ConfirmationCode": confirmation_code.strip(),
            "Password": new_password,
        }
        secret_hash = self._secret_hash(clean_email)
        if secret_hash:
            params["SecretHash"] = secret_hash

        try:
            self.client.confirm_forgot_password(**params)
            return {"reset": True, "message": "Password has been reset successfully."}
        except ClientError as exc:
            self._handle_client_error(exc, clean_email)

    def global_sign_out(self, access_token: str) -> bool:
        """Revoke all tokens and sign the user out of all sessions."""
        try:
            self.client.global_sign_out(AccessToken=access_token.strip())
            return True
        except ClientError as exc:
            _log.warning("Cognito global_sign_out warning: %s", exc.response.get("Error", {}).get("Code"))
            return False

    def admin_create_and_confirm_user(
        self,
        email: str,
        password: str,
        full_name: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Administratively create and set permanent password for transparent migration of existing users.

        Used when an existing ReconDesk user authenticates with Supabase credentials:
        this provisions their Cognito record silently and sets their password so future
        logins can use Cognito directly.
        """
        clean_email = email.strip().lower()
        pool_id = self._config.COGNITO_USER_POOL_ID
        try:
            # 1. Admin create user (suppressing email delivery)
            attrs = [
                {"Name": "email", "Value": clean_email},
                {"Name": "email_verified", "Value": "true"},
            ]
            if full_name:
                attrs.append({"Name": "name", "Value": full_name.strip()})

            create_resp = self.client.admin_create_user(
                UserPoolId=pool_id,
                Username=clean_email,
                UserAttributes=attrs,
                MessageAction="SUPPRESS",
            )
            user_obj = create_resp.get("User", {})
            user_sub = None
            for attr in user_obj.get("Attributes", []):
                if attr.get("Name") == "sub":
                    user_sub = attr.get("Value")

            # 2. Set permanent password
            self.client.admin_set_user_password(
                UserPoolId=pool_id,
                Username=clean_email,
                Password=password,
                Permanent=True,
            )
            return {"user_sub": user_sub, "email": clean_email}
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "UsernameExistsException":
                # Already exists in Cognito; update password
                try:
                    self.client.admin_set_user_password(
                        UserPoolId=pool_id,
                        Username=clean_email,
                        Password=password,
                        Permanent=True,
                    )
                    get_resp = self.client.admin_get_user(
                        UserPoolId=pool_id,
                        Username=clean_email,
                    )
                    user_sub = None
                    for attr in get_resp.get("UserAttributes", []):
                        if attr.get("Name") == "sub":
                            user_sub = attr.get("Value")
                    return {"user_sub": user_sub, "email": clean_email}
                except Exception as inner_exc:
                    _log.warning("admin_set_user_password failed: %s", inner_exc)
                    return None
            _log.warning("admin_create_and_confirm_user failed: %s", exc)
            return None

    def _handle_client_error(self, exc: ClientError, username: str) -> None:
        """Map botocore ClientError codes to domain exceptions."""
        error = exc.response.get("Error", {})
        code = error.get("Code", "UnknownError")
        raw_msg = error.get("Message", "")
        _log.info("Cognito IDP ClientError code=%s for user=%s", code, username)

        if code == "UsernameExistsException":
            raise CognitoUserExistsError() from exc
        elif code == "InvalidPasswordException":
            raise CognitoInvalidPasswordError(raw_msg or "Password does not meet requirements.") from exc
        elif code == "UserNotConfirmedException":
            raise CognitoUserNotConfirmedError() from exc
        elif code == "CodeMismatchException":
            raise CognitoCodeMismatchError() from exc
        elif code == "ExpiredCodeException":
            raise CognitoCodeExpiredError() from exc
        elif code in ("NotAuthorizedException", "UserNotFoundException"):
            # Obfuscate between user not found and bad password
            raise CognitoInvalidCredentialsError() from exc
        elif code in ("TooManyRequestsException", "LimitExceededException"):
            raise CognitoRateLimitError() from exc
        else:
            raise CognitoServiceError(
                message="An authentication error occurred. Please check your details and try again.",
                code=code,
            ) from exc


# ── Dependency Provider ───────────────────────────────────────────────────────

_cognito_service_instance: Optional[CognitoService] = None


def get_cognito_service() -> CognitoService:
    """FastAPI dependency for accessing the Cognito service singleton."""
    global _cognito_service_instance
    if _cognito_service_instance is None:
        _cognito_service_instance = CognitoService()
    return _cognito_service_instance


def set_cognito_service(service: Optional[CognitoService]) -> None:
    """Override or reset CognitoService instance (useful for unit tests with mocks)."""
    global _cognito_service_instance
    _cognito_service_instance = service
