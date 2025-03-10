import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ades_fastapi.api import app

client = TestClient(app)

ADES_FASTAPI_ROOT_PATH = os.getenv("ADES_FASTAPI_ROOT_PATH", "/api/catalogue/wr")


def mock_jwt_decode(token, options, algorithms):
    if token == "valid_token":
        return {"preferred_username": "test_user", "roles": ["hub_user"]}
    elif token == "another_valid_token":
        return {"preferred_username": "another_test_user", "roles": ["hub_user"]}
    return {"preferred_username": "", "roles": []}


def mock_requests_post(url, json):
    if json["input"]["workspace"] == "test_user":
        return MagicMock(status_code=200, json=lambda: {"result": True})
    return MagicMock(status_code=403, json=lambda: {"result": False})


def mock_requests_get(url, headers):
    return MagicMock(status_code=200, text="Reponse content", headers={"Content-Type": "text/html"})


@pytest.fixture(autouse=True)
def mock_dependencies(monkeypatch):
    monkeypatch.setattr("jwt.decode", mock_jwt_decode)
    monkeypatch.setattr("requests.post", mock_requests_post)
    monkeypatch.setattr("requests.get", mock_requests_get)


@patch("ades_fastapi.ades_client.ADESClient.get_root")
def test_check_policy_valid_token(mock_get_root):
    mock_get_root.return_value = MagicMock(
        status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}
    )
    headers = {"authorization": "Bearer valid_token"}
    response = client.get(f"{ADES_FASTAPI_ROOT_PATH}", headers=headers)
    assert response.status_code == 200
    assert response.content.decode("utf-8") == "<h1>ADES HOMEPAGE</h1><p>Status: available</p>"


@patch("ades_fastapi.ades_client.ADESClient.get_root")
def test_check_policy_invalid_token(mock_get_root):
    mock_get_root.return_value = MagicMock(
        status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}
    )
    headers = {"authorization": "Bearer invalid_token"}
    response = client.get(f"{ADES_FASTAPI_ROOT_PATH}", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not Authenticated"}


@patch("ades_fastapi.ades_client.ADESClient.get_root")
def test_check_policy_no_token(mock_get_root):
    mock_get_root.return_value = MagicMock(
        status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}
    )
    response = client.get(f"{ADES_FASTAPI_ROOT_PATH}")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not Authenticated"}


@patch("ades_fastapi.ades_client.ADESClient.get_root")
def test_check_policy_not_authorized(mock_get_root):
    mock_get_root.return_value = MagicMock(
        status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}
    )
    headers = {"authorization": "Bearer another_valid_token"}
    response = client.get(f"{ADES_FASTAPI_ROOT_PATH}", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Not Authorized"}
