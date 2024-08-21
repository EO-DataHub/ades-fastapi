import os
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from ades_fastapi.__init__ import app

OPA_SERVICE_ENDPOINT = os.getenv(
    "OPA_SERVICE_ENDPOINT", "http://opal-client.opal:8181/v1/data/ades/allow"
)

# ADES service endpoint
ADES_SERVICE_ENDPOINT = os.getenv("ADES_SERVICE_ENDPOINT", "http://zoo-project-dru-service:80")


client = TestClient(app)


def mock_jwt_decode(token, options, algorithms):
    if token == "valid_token":
        return {"preferred_username": "test_user", "roles": ["hub_user"]}
    return {"preferred_username": "", "roles": []}


def mock_opa_request(input_data: dict):
    if input_data["input"]["username"] == "test_user":
        return MagicMock(status_code=200, json=lambda: {"result": True})
    return MagicMock(status_code=403, json=lambda: {"result": False})


class ADESMock:
    def mock_requests_post(
        self, url: str, json: dict = None, data: str = None, headers: dict = None
    ):
        if url.endswith("/execution"):
            return MagicMock(
                status_code=200,
                json=lambda: {"status": "processing"},
                headers={"Content-Type": "application/json"},
            )
        return MagicMock(
            status_code=200,
            json=lambda: {"workflow_id": "AAA-123456-BBB-456789"},
            headers={"Content-Type": "application/json", "Location": "https://test-location"},
        )

    def mock_requests_put(
        self, url: str, json: dict = None, data: str = None, headers: dict = None
    ):
        return MagicMock(
            status_code=204,
            json=lambda: {"results": True},
            headers={"Location": "https://test-location", "Content-Type": "application/json"},
        )

    def mock_requests_get(self, url: str, headers: dict = None):
        if (
            url.endswith("/ogc-api/")
            or url == f"{ADES_SERVICE_ENDPOINT}/"
            or url.endswith("/oapip/")
        ):
            return MagicMock(
                status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}
            )
        elif url.endswith("/results"):
            return MagicMock(
                status_code=200,
                json=lambda: {"result_location": "https://results-url"},
                headers={"Content-Type": "application/json"},
            )
        elif url.endswith("/jobs/job_12345"):
            return MagicMock(
                status_code=200,
                json=lambda: {"status": "processing"},
                headers={"Content-Type": "application/json"},
            )
        elif url.endswith("/jobs"):
            return MagicMock(
                status_code=200,
                json=lambda: {"job": [{"id": "job_12345"}, {"id": "job_67890"}]},
                headers={"Content-Type": "application/json"},
            )
        elif url.endswith("/ogc-api/api"):
            return MagicMock(
                status_code=200,
                json=lambda: {"Data": "Response Data"},
                headers={
                    "Content-Type": "application/vnd.oai.openapi+json;version=3.0;charset=UTF-8"
                },
            )
        return MagicMock(
            status_code=200,
            json=lambda: {"results": True},
            headers={"Content-Type": "application/json"},
        )

    def mock_requests_delete(self, url: str, headers: dict = None):
        return MagicMock(
            status_code=204,
            json=lambda: {"Response": "Response text"},
            headers={"Content-Type": "application/json"},
        )


@pytest.fixture(autouse=True)
def mock_dependencies(monkeypatch):
    mock_ades = ADESMock()
    monkeypatch.setattr("jwt.decode", mock_jwt_decode)
    # Mock requests.post for middleware and ADES
    monkeypatch.setattr("ades_fastapi.__init__.opa_request", mock_opa_request)
    # Mock requests for ADES
    monkeypatch.setattr("requests.post", mock_ades.mock_requests_post)
    monkeypatch.setattr("requests.put", mock_ades.mock_requests_put)
    monkeypatch.setattr("requests.get", mock_ades.mock_requests_get)
    monkeypatch.setattr("requests.delete", mock_ades.mock_requests_delete)


def test_check_root():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.content.decode("utf-8") == "Reponse content"


def test_check_workspace_root():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades/test_workspace/ogc-api", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.content.decode("utf-8") == "Reponse content"


def test_check_docs_root():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades/ogc-api/api", headers=headers)
    assert response.status_code == 200
    assert (
        response.headers["Content-Type"]
        == "application/vnd.oai.openapi+json;version=3.0;charset=UTF-8"
    )
    assert response.json() == {"Data": "Response Data"}


def test_check_swagger_docs():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades/api", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.content.decode("utf-8") == "Reponse content"


def test_check_delete_process():
    headers = {"authorization": "Bearer valid_token"}
    response = client.delete(
        "/ades/test_workspace/ogc-api/processes/test_workflow", headers=headers
    )
    assert response.status_code == 204
    assert response.json() == {"Response": "Response text"}


def test_check_list_processes():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades/test_workspace/ogc-api/processes", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"results": True}


def test_check_deploy_process_from_url(monkeypatch):
    headers = {
        "authorization": "Bearer valid_token",
        "content-type": "application/json",
        "accept": "application/json",
    }
    response = client.post(
        "/ades/test_workspace/ogc-api/processes",
        headers=headers,
        json={"url": "https://test-workflow-url"},
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Location"] == "https://test-location"
    assert response.json() == {"workflow_id": "AAA-123456-BBB-456789"}


def test_check_deploy_process_from_file():
    headers = {"authorization": "Bearer valid_token", "Content-Type": "application/cwl+yaml"}
    response = client.post(
        "/ades/test_workspace/ogc-api/processes",
        headers=headers,
        content="test-workflow-file-contents",
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Location"] == "https://test-location"
    assert response.json() == {"workflow_id": "AAA-123456-BBB-456789"}


def test_check_update_process_from_url():
    headers = {
        "authorization": "Bearer valid_token",
        "Content-Type": "application/json",
        "accept": "application/json",
    }
    response = client.put(
        "/ades/test_workspace/ogc-api/processes/test_workflow",
        headers=headers,
        json={"url": "https://test-workflow-url"},
    )
    assert response.status_code == 204
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Location"] == "https://test-location"
    assert response.json() == {"results": True}


def test_check_update_process_from_file():
    headers = {
        "authorization": "Bearer valid_token",
        "Content-Type": "application/cwl+yaml",
        "accept": "application/json",
    }
    response = client.put(
        "/ades/test_workspace/ogc-api/processes/test_workflow",
        headers=headers,
        content="test-workflow-file-contents",
    )
    assert response.status_code == 204
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Location"] == "https://test-location"
    assert response.json() == {"results": True}


def test_get_process_details():
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.get("/ades/test_workspace/ogc-api/processes/test_workflow", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"results": True}


def test_execute_process():
    headers = {
        "authorization": "Bearer valid_token",
        "accept": "application/json",
        "content-type": "application/json",
        "Prefer": "respond-async",
    }
    response = client.post(
        "/ades/test_workspace/ogc-api/processes/test_workflow/execution",
        headers=headers,
        json={"inputs": {"input1": "value1"}},
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"status": "processing"}


def test_get_execute_status():
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.get("/ades/test_workspace/ogc-api/jobs/job_12345", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.content.decode("utf-8") == '{"status": "processing"}'


def test_get_processing_results():
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.get("/ades/test_workspace/ogc-api/jobs/job_12345/results", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.content.decode("utf-8") == '{"result_location": "https://results-url"}'


def test_list_jobs():
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.get("/ades/test_workspace/ogc-api/jobs", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.content.decode("utf-8") == '{"job": [{"id": "job_12345"}, {"id": "job_67890"}]}'


def test_delete_job():
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.delete("/ades/test_workspace/ogc-api/jobs/job_12345", headers=headers)
    assert response.status_code == 501
    assert response.content.decode("utf-8") == "Endpoint not implemented yet"
