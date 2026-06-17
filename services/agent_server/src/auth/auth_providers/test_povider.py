from typing import Optional
from src.auth.provider import AuthProvider, AuthenticatedUser, UserProfile

class TestProvider(AuthProvider):
    name = "test"

    def __init__(self):
        pass

    @property
    def issuer(self) -> str:
        return "metaplanet-local-test-environment"

    async def authenticate_token(self, token: str) -> AuthenticatedUser:
        return AuthenticatedUser(user_id="test_user", username="test_user", email="test_user@test.com", groups=("test_group",), token_use="test_token_use", claims={"test_claim": "test_value"}, access_token=token)

    async def fetch_user_info(self, access_token: Optional[str] = None) -> UserProfile:
        return UserProfile(user_id="test_user", username="test_user", email="test_user@test.com", email_verified=True, additional_claims={"test_claim": "test_value"})