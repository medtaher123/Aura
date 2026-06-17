"""AWS Cognito authentication provider."""

import asyncio
import json
import urllib.request
import urllib.error
from typing import Any, Optional

from src.config import get_config

from src.auth.provider import (
    AuthConfigurationError, 
    AuthError, 
    AuthProvider, 
    AuthenticatedUser, 
    UserProfile
)

class CognitoAuthProvider(AuthProvider):
    """Validate AWS Cognito JWTs using the user pool JWKS."""
    name = "cognito"

    def __init__(self):

        config = get_config()

        try:
            import jwt
        except ImportError as exc:
            raise AuthConfigurationError(
                "PyJWT is required for Cognito auth. Install 'PyJWT[crypto]'."
            ) from exc

        self._jwt = jwt
        self.region = config.cognito_region or ""
        self.user_pool_id = config.cognito_user_pool_id or ""
        self.app_client_id = config.cognito_app_client_id
        self.expected_token_use = config.cognito_token_use
        self.leeway_seconds = config.cognito_jwt_leeway_seconds
        
        self.cognito_domain = config.cognito_domain or ""
        self.cognito_domain = self.cognito_domain.rstrip("/")
        self.userinfo_url = f"{self.cognito_domain}/oauth2/userInfo"
        
        #self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self._jwks_client = jwt.PyJWKClient(self.jwks_url)

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    async def authenticate_token(self, token: str) -> AuthenticatedUser:
        """Validate a JWT and return Cognito user claims."""
        if not token:
            raise AuthError("Missing authentication token")

        return await asyncio.to_thread(self._decode_token, token)

    async def fetch_user_info(self, access_token: Optional[str] = None) -> UserProfile:
        """Fetch the user's profile claims from Cognito UserInfo endpoint."""
        if not access_token:
            raise AuthError("Cannot fetch user profile without an access token")

        def _fetch() -> dict[str, Any]:
            req = urllib.request.Request(
                self.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            try:
                with urllib.request.urlopen(req) as response:
                    return json.loads(response.read())
            except urllib.error.URLError as exc:
                raise AuthError(f"Failed to fetch user info from Cognito: {exc}")

        raw_claims = await asyncio.to_thread(_fetch)
        
        # Extract and map standard Cognito/OIDC claims to the strict UserProfile schema
        user_id = raw_claims.get("sub")
        if not user_id:
            raise AuthError("UserInfo response is missing required 'sub' attribute")

        # Handle string-to-boolean conversion safely for email_verified if returned as a string
        email_verified_raw = raw_claims.get("email_verified")
        email_verified = (
            email_verified_raw 
            if isinstance(email_verified_raw, bool) 
            else str(email_verified_raw).lower() == "true" if email_verified_raw is not None else None
        )

        return UserProfile(
            user_id=user_id,
            email=self._string_claim(raw_claims, "email"),
            username=self._string_claim(raw_claims, "cognito:username") or self._string_claim(raw_claims, "username"),
            email_verified=email_verified,
            additional_claims=raw_claims,
        )

    def _decode_token(self, token: str) -> AuthenticatedUser:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = self._jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False},
                leeway=self.leeway_seconds,
            )
        except self._jwt.ExpiredSignatureError as exc:
            raise AuthError("Authentication token has expired") from exc
        except self._jwt.InvalidTokenError as exc:
            raise AuthError("Authentication token is invalid") from exc
        except Exception as exc:
            raise AuthError("Unable to validate authentication token") from exc

        token_use = claims.get("token_use")
        if self.expected_token_use and token_use != self.expected_token_use:
            raise AuthError("Authentication token has an unexpected token_use")

        if self.app_client_id and not self._matches_app_client(claims):
            raise AuthError("Authentication token was not issued for this app client")

        user_id = claims.get("sub")
        if not isinstance(user_id, str) or not user_id:
            raise AuthError("Authentication token is missing subject")

        groups = claims.get("cognito:groups", ())
        if not isinstance(groups, list):
            groups = ()

        return AuthenticatedUser(
            user_id=user_id,
            username=self._string_claim(claims, "cognito:username") or self._string_claim(claims, "username"),
            email=self._string_claim(claims, "email"),
            groups=tuple(str(group) for group in groups),
            token_use=str(token_use) if token_use else None,
            claims=claims,
            access_token=token,
        )

    def _matches_app_client(self, claims: dict[str, Any]) -> bool:
        audience = claims.get("aud")
        if isinstance(audience, str) and audience == self.app_client_id:
            return True
        if isinstance(audience, list) and self.app_client_id in audience:
            return True
        return claims.get("client_id") == self.app_client_id

    @staticmethod
    def _string_claim(claims: dict[str, Any], key: str) -> Optional[str]:
        value = claims.get(key)
        return value if isinstance(value, str) else None