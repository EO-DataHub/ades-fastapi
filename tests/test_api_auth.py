import os
import re
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ades_fastapi.api import app, job_saver

client = TestClient(app)

# Root Catalogs for processes
PUBLIC_CATALOG_ROOT = os.getenv("PUBLIC_CATALOG_ROOT", "public")
USER_CATALOG_ROOT = os.getenv("USER_CATALOG_ROOT", "user")

# Root path for FastAPI
ADES_FASTAPI_ROOT_PATH = os.getenv("ADES_FASTAPI_ROOT_PATH", "/api/catalogue/stac")


def mock_jwt_decode(token: str, key: Any, audience: list[str], algorithms: list[str]) -> dict[str, Any]:
    if token == "valid_token":
        return {
            "preferred_username": "username",
            "workspace": "test_user",
            "workspaces": ["test_user"],
            "roles": ["hub_user"],
        }
    elif token == "another_valid_token":
        return {
            "preferred_username": "username",
            "workspace": "another_test_user",
            "roles": ["hub_user"],
        }
    return {"preferred_username": "", "workspace": "", "roles": []}


def mock_requests_post(url: str, json: dict[str, Any]) -> MagicMock:
    if json["input"]["workspace"] == "test_user":
        return MagicMock(status_code=200, json=lambda: {"result": True})
    return MagicMock(status_code=403, json=lambda: {"result": False})


def mock_requests_get(url: str, headers: dict[str, str], timeout: int = 10) -> MagicMock:
    return MagicMock(status_code=200, text="Reponse content", headers={"Content-Type": "text/html"})


@pytest.fixture(autouse=True)
def mock_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jwt.decode", mock_jwt_decode)
    monkeypatch.setattr("ades_fastapi.utils._jwks_client", lambda: MagicMock())
    monkeypatch.setattr("requests.post", mock_requests_post)
    monkeypatch.setattr("requests.get", mock_requests_get)


@patch("ades_fastapi.ades_client.ADESClient.list_processes")
def test_check_policy_valid_token(mock_list_processes: MagicMock) -> None:
    mock_list_processes.return_value = (
        MagicMock(status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}),
        "Reponse content",
    )
    headers = {"authorization": "Bearer valid_token"}
    response = client.get(
        f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/workspace/processes",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.content.decode("utf-8") == "Reponse content"


@patch("ades_fastapi.ades_client.ADESClient.list_processes")
def test_check_policy_invalid_token(mock_list_processes: MagicMock) -> None:
    mock_list_processes.return_value = (
        MagicMock(status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}),
        "Reponse content",
    )
    headers = {"authorization": "Bearer invalid_token"}
    response = client.get(
        f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/workspace/processes",
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Not Authenticated"}


@patch("ades_fastapi.ades_client.ADESClient.list_processes")
def test_check_policy_no_token(mock_list_processes: MagicMock) -> None:
    mock_list_processes.return_value = (
        MagicMock(status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}),
        "Reponse content",
    )
    response = client.get(f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/workspace/processes")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not Authenticated"}


@patch("ades_fastapi.ades_client.ADESClient.list_processes")
def test_check_policy_not_authorized(mock_list_processes: MagicMock) -> None:
    mock_list_processes.return_value = (
        MagicMock(status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}),
        "Reponse content",
    )
    headers = {"authorization": "Bearer another_valid_token"}
    response = client.get(
        f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/workspace/processes",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Not Authorized"}


CALLER_JOBS_URL = f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/test_user/jobs"
AUTH = {"authorization": "Bearer valid_token"}


@pytest.fixture
def called_scope_backends() -> Iterator[dict[str, MagicMock]]:
    """S3 index listing, ZOO job fetches and the deployed list, all mocked."""

    def zoo_job(verb: str, url_path: str = "", *args: Any, **kwargs: Any) -> MagicMock:
        job_id = url_path.rsplit("/", 1)[1]
        body = {"jobID": job_id, "links": []}
        return MagicMock(status_code=200, json=lambda: body, headers={"Content-Type": "application/json"})

    with (
        patch.object(job_saver, "s3_client") as s3,
        patch("ades_fastapi.ades_client.ADESClient._send_request", side_effect=zoo_job) as send_request,
        patch("ades_fastapi.ades_client.ADESClient.get_deployed_workspaced_jobs") as deployed,
    ):
        s3.list_objects_v2.return_value = {
            "KeyCount": 1,
            "IsTruncated": False,
            "Contents": [{"Key": "_by-caller/test_user/8235000000001/publisher/job-1"}],
        }
        deployed.return_value = (
            MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
            '{"jobs": []}',
        )
        yield {"s3": s3, "send_request": send_request, "deployed": deployed}


def test_jobs_list_called_scope_lists_caller_index(
    called_scope_backends: dict[str, MagicMock],
) -> None:
    after = "8235000000009/publisher/job-0"

    response = client.get(CALLER_JOBS_URL, params={"scope": "called", "after": after}, headers=AUTH)

    assert response.status_code == 200
    assert [job["jobID"] for job in response.json()["jobs"]] == ["job-1"]
    list_kwargs = called_scope_backends["s3"].list_objects_v2.call_args.kwargs
    assert list_kwargs["Prefix"] == "_by-caller/test_user/"
    assert list_kwargs["MaxKeys"] == 20
    assert list_kwargs["StartAfter"] == f"_by-caller/test_user/{after}"
    called_scope_backends["deployed"].assert_not_called()


def test_jobs_list_called_scope_forbidden_for_other_workspace(
    called_scope_backends: dict[str, MagicMock],
) -> None:
    response = client.get(
        f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/someone_else/jobs",
        params={"scope": "called"},
        headers=AUTH,
    )

    assert response.status_code == 403
    called_scope_backends["s3"].list_objects_v2.assert_not_called()


UNSUPPORTED_FILTER = [re.compile("not supported", re.IGNORECASE), re.compile(re.escape("scope=called"))]


@pytest.mark.parametrize(
    ("query", "status", "detail_patterns"),
    [
        ({"status": "running"}, 400, UNSUPPORTED_FILTER),
        ({"datetime": "2026-01-01T00:00:00Z/.."}, 400, UNSUPPORTED_FILTER),
        ({"skip": 5}, 400, UNSUPPORTED_FILTER),
        ({"after": "job-1"}, 400, []),
        ({"after": "8235000000001/job-1"}, 400, []),
        ({"after": "not-a-time/publisher/job-1"}, 400, []),
        ({"after": "8235000000001/publisher/job-1/extra"}, 400, []),
        ({"limit": 101}, 422, []),
    ],
    ids=[
        "status-filter",
        "datetime-filter",
        "skip",
        "after-job-id-only",
        "after-missing-workspace",
        "after-bad-time",
        "after-extra-part",
        "limit-above-100",
    ],
)
def test_jobs_list_called_scope_rejects_bad_query(
    called_scope_backends: dict[str, MagicMock],
    query: dict[str, Any],
    status: int,
    detail_patterns: list[re.Pattern[str]],
) -> None:
    response = client.get(CALLER_JOBS_URL, params={"scope": "called", **query}, headers=AUTH)

    assert response.status_code == status
    for pattern in detail_patterns:
        assert pattern.search(str(response.json()["detail"]))
    called_scope_backends["s3"].list_objects_v2.assert_not_called()
