"""Authentication provider contracts."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class AuthenticatedUser:
    """User identity returned by an authentication provider."""

    user_id: str
    username: Optional[str]
    email: Optional[str]
    groups: tuple[str, ...]
    token_use: Optional[str]
    claims: Mapping[str, Any]
    access_token: Optional[str]


class AuthError(Exception):
    """Raised when credentials are missing or invalid."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)
        self.message = message


class AuthConfigurationError(RuntimeError):
    """Raised when an auth provider is enabled but not configured."""


class AuthProvider(ABC):
    """Base class for pluggable backend authentication providers."""

    @abstractmethod
    async def authenticate_token(self, token: str) -> AuthenticatedUser:
        """Validate an access token and return the authenticated user."""
    
    @abstractmethod
    async def fetch_user_info(self, access_token: Optional[str]=None) -> dict[str, Any]:
        """Fetch full user profile from the OAuth2 UserInfo endpoint."""