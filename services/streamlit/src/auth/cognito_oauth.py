"""Cognito Hosted UI OAuth2 (authorization code) login flow for Streamlit.

This module drives a redirect-based sign-in against the AWS Cognito Hosted UI:

1. An unauthenticated visitor is redirected to the Cognito login page.
2. Cognito redirects back to the app with an authorization ``code``.
3. The code is exchanged for tokens at the Cognito token endpoint.
4. The Cognito **access token** is kept in session state so it can be
   forwarded to the Agent Server WebSocket as a bearer token.

Configuration is environment driven so no secrets are hardcoded. Required:

- ``COGNITO_DOMAIN`` (e.g. ``https://my-app.auth.eu-west-3.amazoncognito.com``)
- ``COGNITO_CLIENT_ID`` (the Cognito app client id)

Optional:

- ``COGNITO_CLIENT_SECRET`` (only for confidential app clients)
- ``COGNITO_REDIRECT_URI`` (default ``http://localhost:8501``)
- ``COGNITO_SCOPES`` (default ``openid email profile``)
- ``COGNITO_LOGOUT_REDIRECT_URI`` (default: the redirect URI)
- ``COGNITO_AUTH_ENABLED`` (force-enable/disable the login gate)
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import requests
import streamlit as st
import streamlit.components.v1 as components

from src.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_SCOPES = "openid email profile"
DEFAULT_REDIRECT_URI = "http://localhost:8501"
TOKEN_REQUEST_TIMEOUT = 10
# Refresh slightly before real expiry to avoid races with the backend.
EXPIRY_SAFETY_SECONDS = 30

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CognitoOAuthConfig:
    """Resolved Cognito Hosted UI configuration."""

    domain: str
    client_id: str
    redirect_uri: str
    scopes: str
    client_secret: Optional[str] = None
    logout_redirect_uri: Optional[str] = None

    @property
    def authorize_endpoint(self) -> str:
        return f"{self.domain}/oauth2/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self.domain}/oauth2/token"

    @property
    def logout_endpoint(self) -> str:
        return f"{self.domain}/logout"


def _clean_domain(domain: str) -> str:
    domain = (domain or "").strip().rstrip("/")
    if domain and not domain.startswith("http://") and not domain.startswith("https://"):
        domain = f"https://{domain}"
    return domain


def get_oauth_config() -> Optional[CognitoOAuthConfig]:
    """Build the Cognito config from environment, or ``None`` if incomplete."""
    domain = _clean_domain(os.getenv("COGNITO_DOMAIN", ""))
    client_id = (
        os.getenv("COGNITO_CLIENT_ID") or os.getenv("COGNITO_APP_CLIENT_ID") or ""
    ).strip()

    if not domain or not client_id:
        return None

    redirect_uri = (os.getenv("COGNITO_REDIRECT_URI") or DEFAULT_REDIRECT_URI).strip()
    scopes = (os.getenv("COGNITO_SCOPES") or DEFAULT_SCOPES).strip()
    client_secret = (os.getenv("COGNITO_CLIENT_SECRET") or "").strip() or None
    logout_redirect_uri = (
        os.getenv("COGNITO_LOGOUT_REDIRECT_URI") or redirect_uri
    ).strip()

    return CognitoOAuthConfig(
        domain=domain,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        client_secret=client_secret,
        logout_redirect_uri=logout_redirect_uri,
    )


def auth_enabled() -> bool:
    """Whether the Cognito login gate should be enforced."""
    flag = os.getenv("COGNITO_AUTH_ENABLED")
    if flag is not None:
        return flag.strip().lower() in _TRUTHY
    return get_oauth_config() is not None


def build_login_url(config: CognitoOAuthConfig, state: str) -> str:
    """Build the Cognito Hosted UI authorization URL."""
    params = {
        "client_id": config.client_id,
        "response_type": "code",
        "scope": config.scopes,
        "redirect_uri": config.redirect_uri,
        "state": state,
    }
    return f"{config.authorize_endpoint}?{urlencode(params)}"


def build_logout_url(config: CognitoOAuthConfig) -> str:
    """Build the Cognito Hosted UI logout URL."""
    params = {
        "client_id": config.client_id,
        "logout_uri": config.logout_redirect_uri or config.redirect_uri,
    }
    return f"{config.logout_endpoint}?{urlencode(params)}"


def exchange_code_for_tokens(config: CognitoOAuthConfig, code: str) -> dict[str, Any]:
    """Exchange an authorization code for Cognito tokens."""
    data = {
        "grant_type": "authorization_code",
        "client_id": config.client_id,
        "code": code,
        "redirect_uri": config.redirect_uri,
    }
    auth = (config.client_id, config.client_secret) if config.client_secret else None
    response = requests.post(
        config.token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=auth,
        timeout=TOKEN_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def refresh_tokens(config: CognitoOAuthConfig, refresh_token: str) -> dict[str, Any]:
    """Use a refresh token to obtain a fresh access/id token."""
    data = {
        "grant_type": "refresh_token",
        "client_id": config.client_id,
        "refresh_token": refresh_token,
    }
    auth = (config.client_id, config.client_secret) if config.client_secret else None
    response = requests.post(
        config.token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=auth,
        timeout=TOKEN_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def decode_jwt_claims(token: Optional[str]) -> dict[str, Any]:
    """Decode JWT claims without signature verification (display only).

    The backend is responsible for cryptographic validation; here we only
    read non-sensitive display fields like email and expiry.
    """
    if not token:
        return {}
    try:
        payload_segment = token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        decoded = base64.urlsafe_b64decode(payload_segment + padding)
        claims = json.loads(decoded)
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


def _store_tokens(
    token_response: dict[str, Any],
    *,
    previous_refresh_token: Optional[str] = None,
) -> dict[str, Any]:
    """Persist tokens in session state and return the stored record."""
    access_token = token_response.get("access_token")
    id_token = token_response.get("id_token")
    refresh_token = token_response.get("refresh_token") or previous_refresh_token
    expires_in = int(token_response.get("expires_in", 3600) or 3600)
    claims = decode_jwt_claims(id_token) or decode_jwt_claims(access_token)

    tokens = {
        "access_token": access_token,
        "id_token": id_token,
        "refresh_token": refresh_token,
        "expires_at": time.time() + expires_in - EXPIRY_SAFETY_SECONDS,
        "claims": claims,
    }
    st.session_state.cognito_tokens = tokens
    return tokens


def _tokens_expired(tokens: dict[str, Any]) -> bool:
    return time.time() >= float(tokens.get("expires_at", 0) or 0)


def _redirect(url: str) -> None:
    """Best-effort top-level browser redirect from within Streamlit."""
    safe_url = json.dumps(url)
    components.html(
        f"""
        <script>
            (function () {{
                var target = {safe_url};
                try {{
                    window.top.location.href = target;
                }} catch (err) {{
                    try {{
                        window.parent.location.href = target;
                    }} catch (err2) {{
                        window.location.href = target;
                    }}
                }}
            }})();
        </script>
        """,
        height=0,
    )


def _ensure_oauth_state() -> str:
    state = st.session_state.get("cognito_oauth_state")
    if not state:
        state = secrets.token_urlsafe(24)
        st.session_state.cognito_oauth_state = state
    return state


def _render_login_screen(
    config: CognitoOAuthConfig,
    *,
    error: Optional[str] = None,
) -> None:
    """Render the sign-in screen and trigger the Cognito redirect."""
    state = _ensure_oauth_state()
    login_url = build_login_url(config, state)

    st.title("🔐 Sign in required")

    if error:
        # On errors we avoid auto-redirect to prevent redirect loops.
        st.error(error)
        st.link_button("Try signing in again", login_url, type="primary")
        return

    st.write("Redirecting you to the secure Cognito login page…")
    st.link_button("Continue to sign in", login_url, type="primary")
    st.caption("If you are not redirected automatically, use the button above.")
    _redirect(login_url)


def render_login_gate() -> Optional[dict[str, Any]]:
    """Enforce Cognito login. Returns the token record, or ``None`` if auth disabled.

    When the visitor is not authenticated this renders the login screen and
    halts the script via ``st.stop()``.
    """
    config = get_oauth_config()
    if not auth_enabled() or config is None:
        return None

    tokens = st.session_state.get("cognito_tokens")

    # Already authenticated with a valid token.
    if tokens and tokens.get("access_token") and not _tokens_expired(tokens):
        return tokens

    # Token expired: try a silent refresh before bouncing to the login page.
    if tokens and tokens.get("refresh_token") and _tokens_expired(tokens):
        try:
            refreshed = refresh_tokens(config, tokens["refresh_token"])
            return _store_tokens(
                refreshed, previous_refresh_token=tokens.get("refresh_token")
            )
        except Exception as exc:
            logger.warning(f"Cognito token refresh failed: {type(exc).__name__}: {exc}")
            st.session_state.pop("cognito_tokens", None)

    # Handle the redirect back from Cognito (``?code=...``).
    code = st.query_params.get("code")
    if code:
        returned_state = st.query_params.get("state")
        expected_state = st.session_state.get("cognito_oauth_state")
        # Session state is often lost across the external redirect, so only
        # enforce the state check when we still have the expected value.
        if expected_state and returned_state and returned_state != expected_state:
            _render_login_screen(
                config, error="Login session expired or invalid. Please sign in again."
            )
            st.stop()

        try:
            token_response = exchange_code_for_tokens(config, code)
        except Exception as exc:
            logger.error(
                f"Cognito token exchange failed: {type(exc).__name__}: {exc}"
            )
            st.query_params.clear()
            _render_login_screen(
                config, error="Could not complete sign-in. Please try again."
            )
            st.stop()
            return None

        _store_tokens(token_response)
        st.session_state.pop("cognito_oauth_state", None)
        st.query_params.clear()
        st.rerun()

    # Not authenticated and no code present: send the user to Cognito.
    _render_login_screen(config)
    st.stop()
    return None


def render_logout_control(config: Optional[CognitoOAuthConfig] = None) -> None:
    """Render a logout button that clears local tokens and logs out of Cognito."""
    config = config or get_oauth_config()
    if config is None:
        return

    if st.button("Log out", use_container_width=True):
        st.session_state.pop("cognito_tokens", None)
        st.session_state.pop("cognito_oauth_state", None)
        _redirect(build_logout_url(config))
        st.stop()
