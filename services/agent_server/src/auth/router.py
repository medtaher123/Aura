import importlib
import os
from pathlib import Path
import pkgutil
import jwt
from typing import Optional, Any
from fastapi import Header, HTTPException, status

from src.config import get_config

# Import your base components and specific providers
from .provider import AuthProvider, AuthenticatedUser, AuthError

class AuthRouter:
    """Static authentication router that manages multiple providers.
    
    Automatically initializes based on enabled providers configured via environment variables.
    """
    # Static registry mapping: { "issuer_url_or_string": provider_instance }
    _registry: dict[str, AuthProvider] = {}
    
    @classmethod
    def initialize(cls) -> None:
        """Initializes enabled auth providers based on configuration settings.
        
        This maps each provider's unique issuer to its instantiated provider object.
        """

        config = get_config()
        enabled_providers = [p.strip().lower() for p in config.auth_providers.split(",") if p.strip()]

        print("config.dev_mode: ", config.dev_mode)
        if config.dev_mode:
            enabled_providers.append("test")


        providers_dir = Path(__file__).resolve().parent / "auth_providers"
        if providers_dir.exists() and providers_dir.is_dir():
            for _, module_name, is_pkg in pkgutil.iter_modules([str(providers_dir)]):
                importlib.import_module(f"{__package__}.auth_providers.{module_name}")

        for provider_class in AuthProvider.__subclasses__():    
            if provider_class.name.lower() in enabled_providers:
                provider_class_instance = provider_class()
                cls._registry[provider_class_instance.issuer] = provider_class_instance

    @staticmethod
    def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
        """Extract a bearer token from an Authorization header."""
        if not authorization:
            return None

        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        return token.strip()

    @classmethod
    def get_provider_by_token(cls, token: str) -> AuthProvider:
        """Unsafely parses a JWT token payload to extract its issuer, 
        then routes it to the matching registered provider.
        """
        try:
            # Decode payload without verifying signature just to read the 'iss' claim
            unverified_claims = jwt.decode(token, options={"verify_signature": False})
            issuer = unverified_claims.get("iss")
        except Exception as exc:
            raise AuthError("Invalid token format or corrupt payload structure") from exc

        if not issuer:
            raise AuthError("Authentication token is missing the required issuer ('iss') claim")

        provider = cls._registry.get(issuer)
        if not provider:
            raise AuthError(f"Untrusted or unsupported token issuer: '{issuer}'")

        return provider

    @classmethod
    def get_provider_by_issuer(cls, issuer: str) -> AuthProvider:
        """Get a provider by name."""
        provider = cls._registry.get(issuer.lower())
        if not provider:
            raise AuthError(f"Provider not found: '{issuer}'")

        return provider


    


    


