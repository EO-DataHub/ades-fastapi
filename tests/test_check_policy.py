from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from ades_fastapi.__init__ import app

client = TestClient(app)


def mock_jwt_decode(token, options, algorithms):
    if token == "valid_token":
        return {"preferred_username": "test_user", "roles": ["hub_user"]}
    return {"preferred_username": "", "roles": []}


def mock_requests_post(url, json):
    if json["input"]["workspace"] == "test_user":
        return MagicMock(status_code=200, json=lambda: {"result": True})
    return MagicMock(status_code=403, json=lambda: {"result": False})


def mock_requests_get(url):
    return MagicMock(status_code=200, text="Reponse content", headers={"Content-Type": "text/html"})


@pytest.fixture(autouse=True)
def mock_dependencies(monkeypatch):
    monkeypatch.setattr("jwt.decode", mock_jwt_decode)
    monkeypatch.setattr("requests.post", mock_requests_post)
    monkeypatch.setattr("requests.get", mock_requests_get)


def test_check_policy_valid_token():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades", headers=headers)
    assert response.status_code == 200
    assert response.content.decode("utf-8") == "<h1>ADES HOMEPAGE</h1><p>Status: available</p>"


def test_check_policy_invalid_token():
    headers = {"authorization": "Bearer invalid_token"}
    response = client.get("/ades", headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied"}


def test_check_policy_no_token():
    response = client.get("/ades")
    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied"}
