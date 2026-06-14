"""FastAPI authentication helpers."""

from typing import Optional

from fastapi import Header, HTTPException, WebSocket, status

from ..config import get_config
from ..core.logger import get_logger
from .cognito_provider import CognitoAuthProvider
from .provider import AuthConfigurationError, AuthError, AuthProvider, AuthenticatedUser

logger = get_logger("auth")

_auth_provider: Optional[AuthProvider] = None


def get_auth_provider() -> AuthProvider:
    """Build the configured auth provider."""
    global _auth_provider

    if _auth_provider is not None:
        return _auth_provider

    config = get_config()
    provider_name = config.auth_provider.lower()
    if provider_name == "cognito":
        _auth_provider = CognitoAuthProvider(
            region=config.cognito_region or "",
            user_pool_id=config.cognito_user_pool_id or "",
            app_client_id=config.cognito_app_client_id,
            expected_token_use=config.cognito_token_use,
            leeway_seconds=config.cognito_jwt_leeway_seconds,
        )
        return _auth_provider

    raise AuthConfigurationError(f"Unsupported auth provider: {config.auth_provider}")


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Extract a bearer token from an Authorization header."""
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


async def authenticate_http_request(
    authorization: Optional[str] = Header(default=None),
) -> Optional[AuthenticatedUser]:
    """FastAPI dependency for HTTP routes that should respect configured auth."""
    config = get_config()
    if not config.auth_enabled:
        return None

    token = extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return await get_auth_provider().authenticate_token(token)
    except AuthConfigurationError:
        logger.exception("Authentication provider is misconfigured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication provider is misconfigured",
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def authenticate_websocket(websocket: WebSocket) -> Optional[AuthenticatedUser]:
    """Authenticate a WebSocket handshake when auth is enabled."""
    config = get_config()
    #if not config.auth_enabled:
    #    return None

    token = extract_bearer_token(websocket.headers.get("authorization"))
    if not token:
        token = websocket.query_params.get("access_token")

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise AuthError("Missing bearer token")

    try:
        return await get_auth_provider().authenticate_token(token)
    except AuthConfigurationError:
        logger.exception("Authentication provider is misconfigured")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        raise
    except AuthError as e:
        logger.error(f"Authentication error: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise
