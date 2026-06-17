"""Authentication provider contracts."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class UserProfile:
    """Standardized user profile information retrieved from the provider."""

    user_id: str
    email: Optional[str] = None
    username: Optional[str] = None
    email_verified: Optional[bool] = None
    additional_claims: Mapping[str, Any] = field(default_factory=dict)

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

@dataclass
class AuthContext:
    user: AuthenticatedUser
    provider: 'AuthProvider'

class AuthError(Exception):
    """Raised when credentials are missing or invalid."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)
        self.message = message


class AuthConfigurationError(RuntimeError):
    """Raised when an auth provider is enabled but not configured."""


class AuthProvider(ABC):
    """Base class for pluggable backend authentication providers."""

    name: str = NotImplemented

    @property
    @abstractmethod
    def issuer(self) -> str:
        """The exact 'iss' claim URL/string this provider expects to validate."""
        raise NotImplementedError

    @abstractmethod
    async def authenticate_token(self, token: str) -> AuthenticatedUser:
        """Validate an access token and return the authenticated user."""
        raise NotImplementedError("Subclasses must implement this method")
    
    @abstractmethod
    async def fetch_user_info(self, access_token: Optional[str]=None) -> UserProfile:
        """Fetch full user profile from the OAuth2 UserInfo endpoint."""
        raise NotImplementedError("Subclasses must implement this method")

    