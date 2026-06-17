"""AWS Cognito authentication provider."""

import asyncio
import json
import urllib.request
import urllib.error
from typing import Any, Optional

from .provider import AuthConfigurationError, AuthError, AuthProvider, AuthenticatedUser


class CognitoAuthProvider(AuthProvider):
    """Validate AWS Cognito JWTs using the user pool JWKS."""

    def __init__(
        self,
        *,
        region: str,
        user_pool_id: str,
        cognito_domain: str,
        app_client_id: Optional[str] = None,
        expected_token_use: Optional[str] = None,
        leeway_seconds: int = 0,
    ):
        if not region:
            raise AuthConfigurationError("COGNITO_REGION is required")
        if not user_pool_id:
            raise AuthConfigurationError("COGNITO_USER_POOL_ID is required")
        if not cognito_domain:
            raise AuthConfigurationError("COGNITO_DOMAIN is required")

        try:
            import jwt
        except ImportError as exc:
            raise AuthConfigurationError(
                "PyJWT is required for Cognito auth. Install 'PyJWT[crypto]'."
            ) from exc

        self._jwt = jwt
        self.region = region
        self.user_pool_id = user_pool_id
        self.app_client_id = app_client_id
        self.expected_token_use = expected_token_use
        self.leeway_seconds = leeway_seconds
        
        self.cognito_domain = cognito_domain.rstrip("/")
        self.userinfo_url = f"{self.cognito_domain}/oauth2/userInfo"
        
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self._jwks_client = jwt.PyJWKClient(self.jwks_url)

    async def authenticate_token(self, token: str) -> AuthenticatedUser:
        """Validate a JWT and return Cognito user claims."""
        if not token:
            raise AuthError("Missing authentication token")

        return await asyncio.to_thread(self._decode_token, token)

    async def fetch_user_info(self, access_token: Optional[str]=None) -> dict[str, Any]:
        """Fetch the user's profile claims from Cognito UserInfo endpoint."""
        if not access_token:
            raise AuthError("Missing access token")

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

        return await asyncio.to_thread(_fetch)

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
            username=self._string_claim(claims, "cognito:username")
            or self._string_claim(claims, "username"),
            email=self._string_claim(claims, "email"),
            groups=tuple(str(group) for group in groups),
            token_use=str(token_use) if token_use else None,
            claims=claims,
            access_token=token,  # Retain token for UserInfo fetching
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
        