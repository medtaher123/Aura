"""FastAPI authentication helpers."""

from typing import Optional

from fastapi import Header, HTTPException, WebSocket, status

from src.auth.router import AuthRouter

from ..config import get_config
from ..core.logger import get_logger
from .provider import AuthConfigurationError, AuthContext, AuthError, AuthProvider, AuthenticatedUser

logger = get_logger("auth")

_auth_provider: Optional[AuthProvider] = None


def get_auth_provider() -> AuthProvider:
    """ throw not implemented error """
    raise NotImplementedError("get_auth_provider is not implemented")

async def get_current_user_from_token(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> AuthContext:
    """FastAPI dependency that extracts, routes, and validates a bearer token 
    against the appropriate enabled authentication provider.
    """
    token = AuthRouter.extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # 1. Dynamically route the token to the correct auth provider based on its issuer
        provider = AuthRouter.get_provider_by_token(token)
        
        user = await provider.authenticate_token(token)
        return AuthContext(user=user, provider=provider)
        
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc