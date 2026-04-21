import pytest

from tests.conftest import MOCK_USER_ID


@pytest.mark.asyncio
async def test_protected_endpoint_without_token_returns_401(
    unauthed_client, without_demo_mode
):
    response = await unauthed_client.get("/api/v1/test-auth")
    assert response.status_code == 401
    data = response.json()
    assert data["detail"]["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_protected_endpoint_with_mock_token_returns_200(client):
    response = await client.get("/api/v1/test-auth")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_auth_returns_user_id(client):
    data = (await client.get("/api/v1/test-auth")).json()
    assert data["user_id"] == MOCK_USER_ID
