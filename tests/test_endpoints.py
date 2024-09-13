import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ades_fastapi.__init__ import app

# OPA service endpoint
OPA_SERVICE_ENDPOINT = os.getenv(
    "OPA_SERVICE_ENDPOINT", "http://opal-client.opal:8181/v1/data/ades/allow"
)

# ADES service endpoint
ADES_SERVICE_ENDPOINT = os.getenv("ADES_SERVICE_ENDPOINT", "http://zoo-project-dru-service:80")

# Ingress path for ADES
ADES_INGRESS_PATH = os.getenv("ADES_INGRESS_PATH", "https://example-path/ades")


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
                json=lambda: {
                    "status": "processing",
                    "links": [
                        {
                            "href": "http://localhost:8080/test_workspace/ogc-api/processes/test_workflow"
                        }
                    ],
                },
                headers={"Content-Type": "application/json"},
            )
        return MagicMock(
            status_code=200,
            json=lambda: {
                "id": "test_workflow",
                "links": [
                    {"href": "http://localhost:8080/test_workspace/ogc-api/processes/test_workflow"}
                ],
            },
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
        if url == f"{ADES_SERVICE_ENDPOINT}/" or url.endswith("/oapip/"):
            return MagicMock(
                status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}
            )
        elif url.endswith("/test_workspace/ogc-api/"):
            return MagicMock(
                status_code=200,
                json=lambda: {"Data": "Response Data"},
                headers={"Content-Type": "application/json"},
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
                json=lambda: {
                    "status": "processing",
                    "links": [
                        {
                            "href": "http://localhost:8080/test_workspace/ogc-api/processes/test_workflow"
                        }
                    ],
                },
                headers={"Content-Type": "application/json"},
            )
        elif url.endswith("/jobs"):
            return MagicMock(
                status_code=200,
                json=lambda: {
                    "jobs": [
                        {
                            "id": "job_12345",
                            "links": [
                                {
                                    "href": "http://localhost:8080/test_workspace/ogc-api/jobs/job_12345"
                                }
                            ],
                        },
                        {
                            "id": "job_67890",
                            "links": [
                                {
                                    "href": "http://localhost:8080/test_workspace/ogc-api/jobs/job_67890"
                                }
                            ],
                        },
                    ]
                },
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
        elif url.endswith("/processes"):
            return MagicMock(
                status_code=200,
                json=lambda: {
                    "processes": [
                        {
                            "id": "test_workflow_1",
                            "links": [
                                {
                                    "href": "http://localhost:8080/test_workspace/ogc-api/processes/test_workflow"
                                }
                            ],
                        }
                    ]
                },
                headers={"Content-Type": "application/json"},
            )
        elif url.endswith("/processes/test_workflow"):
            return MagicMock(
                status_code=200,
                json=lambda: {
                    "id": "test_workflow",
                    "links": [
                        {
                            "href": "http://localhost:8080/test_workspace/ogc-api/processes/test_workflow"
                        }
                    ],
                },
                headers={"Content-Type": "application/json"},
            )
        elif url.endswith("/temp/test_workflow-12312312-aaaa-bbbb-cccc-dddddddddddd/file.log"):
            return MagicMock(
                status_code=200,
                content="Some log content",
                headers={"Content-Type": "text/plain"},
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


def test_root():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.content.decode("utf-8") == "<h1>ADES HOMEPAGE</h1><p>Status: available</p>"


def test_workspace_root():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades/test_workspace/ogc-api", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Data": "Response Data"}


def test_docs_root():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades/ogc-api/api", headers=headers)
    assert response.status_code == 200
    assert (
        response.headers["Content-Type"]
        == "application/vnd.oai.openapi+json;version=3.0;charset=UTF-8"
    )
    assert response.json() == {"Data": "Response Data"}


def test_swagger_docs():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades/api", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.content.decode("utf-8") == "Reponse content"


def test_delete_process():
    headers = {"authorization": "Bearer valid_token"}
    response = client.delete(
        "/ades/test_workspace/ogc-api/processes/test_workflow", headers=headers
    )
    assert response.status_code == 204
    assert response.json() == {"Response": "Response text"}


def test_list_processes():
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades/test_workspace/ogc-api/processes", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "processes": [
            {
                "id": "test_workflow_1",
                "links": [
                    {"href": f"{ADES_INGRESS_PATH}/test_workspace/ogc-api/processes/test_workflow"}
                ],
            }
        ]
    }


@patch("ades_fastapi.__init__.get_workflow_id_from_url")
def test_deploy_process_from_url(mock_get_workflow_id_from_url):
    # Configure mocks
    mock_get_workflow_id_from_url.return_value = "example-workflow"

    headers = {
        "authorization": "Bearer valid_token",
        "content-type": "application/json",
        "accept": "application/json",
    }
    response = client.post(
        "/ades/test_workspace/ogc-api/processes",
        headers=headers,
        json={"executionUnit": {"href": "https://test_workflow-url"}},
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Location"] == "https://test-location"
    assert response.json() == {
        "id": "test_workflow",
        "links": [{"href": f"{ADES_INGRESS_PATH}/test_workspace/ogc-api/processes/test_workflow"}],
    }


@patch("ades_fastapi.__init__.get_workflow_id_from_file")
def test_deploy_process_from_file(mock_get_workflow_id_from_url):
    # Configure mocks
    mock_get_workflow_id_from_url.return_value = "test_workflow"

    headers = {"authorization": "Bearer valid_token", "Content-Type": "application/cwl+yaml"}
    response = client.post(
        "/ades/test_workspace_2/ogc-api/processes",
        headers=headers,
        content="""
        cwlVersion: v1.0
        $graph:
        - class: Workflow
          id: test_workflow""",
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Location"] == "https://test-location"
    assert response.json() == {
        "id": "test_workflow",
        "links": [{"href": f"{ADES_INGRESS_PATH}/test_workspace/ogc-api/processes/test_workflow"}],
    }


@patch("ades_fastapi.__init__.get_workflow_id_from_url")
def test_deploy_process_from_file_rate_limit(mock_get_workflow_id_from_url):
    # Configure mocks
    mock_get_workflow_id_from_url.return_value = "test_workflow"

    headers = {"authorization": "Bearer valid_token", "Content-Type": "application/cwl+yaml"}
    response = client.post(
        "/ades/test_workspace_3/ogc-api/processes",
        headers=headers,
        content="""
        cwlVersion: v1.0
        $graph:
        - class: Workflow
          id: test_workflow""",
    )
    response = client.post(
        "/ades/test_workspace_3/ogc-api/processes",
        headers=headers,
        content="""
        cwlVersion: v1.0
        $graph:
        - class: Workflow
          id: test_workflow-2""",
    )
    assert response.status_code == 429
    assert response.json() == {
        "detail": "Too Many Requests: Please wait 5 seconds before retrying."
    }


def test_update_process_from_url():
    headers = {
        "authorization": "Bearer valid_token",
        "Content-Type": "application/json",
        "accept": "application/json",
    }
    response = client.put(
        "/ades/test_workspace/ogc-api/processes/test_workflow",
        headers=headers,
        json={"executionUnit": {"href": "https://test_workflow-url"}},
    )
    assert response.status_code == 204
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Location"] == "https://test-location"
    assert response.json() == {"results": True}


def test_update_process_from_file():
    headers = {
        "authorization": "Bearer valid_token",
        "Content-Type": "application/cwl+yaml",
        "accept": "application/json",
    }
    response = client.put(
        "/ades/test_workspace/ogc-api/processes/test_workflow",
        headers=headers,
        content="test_workflow-file-contents",
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
    assert response.json() == {
        "id": "test_workflow",
        "links": [{"href": f"{ADES_INGRESS_PATH}/test_workspace/ogc-api/processes/test_workflow"}],
    }


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
    assert response.json() == {
        "status": "processing",
        "links": [{"href": f"{ADES_INGRESS_PATH}/test_workspace/ogc-api/processes/test_workflow"}],
    }


def test_get_execute_status():
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.get("/ades/test_workspace/ogc-api/jobs/job_12345", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {
        "status": "processing",
        "links": [{"href": f"{ADES_INGRESS_PATH}/test_workspace/ogc-api/processes/test_workflow"}],
    }


def test_get_processing_results():
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.get("/ades/test_workspace/ogc-api/jobs/job_12345/results", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"result_location": "https://results-url"}


def test_list_jobs():
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.get("/ades/test_workspace/ogc-api/jobs", headers=headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {
        "jobs": [
            {
                "id": "job_12345",
                "links": [{"href": f"{ADES_INGRESS_PATH}/test_workspace/ogc-api/jobs/job_12345"}],
            },
            {
                "id": "job_67890",
                "links": [{"href": f"{ADES_INGRESS_PATH}/test_workspace/ogc-api/jobs/job_67890"}],
            },
        ]
    }


@patch("ades_fastapi.__init__.list_jobs_dict")
def test_get_logs(mock_list_jobs_dict):
    # Mock get_user_details
    mock_list_jobs_dict.return_value = {
        "jobs": [{"jobID": "12312312-aaaa-bbbb-cccc-dddddddddddd", "processID": "test_workflow"}]
    }
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.get(
        "/ades/temp/test_workflow-12312312-aaaa-bbbb-cccc-dddddddddddd/file.log",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain"
    assert response.content.decode("utf-8") == "Some log content"


def test_delete_job():
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.delete("/ades/test_workspace/ogc-api/jobs/job_12345", headers=headers)
    assert response.status_code == 501
    assert response.content.decode("utf-8") == "Endpoint not implemented yet"


@patch("ades_fastapi.__init__.get_quote_from_airbus")
@patch("ades_fastapi.__init__.generate_access_token")
def test_quote(mock_generate_access_token, mock_get_quote_from_airbus):
    result = {"acquisitionId": "12345", "price": 100}
    mock_get_quote_from_airbus.return_value = [{"acquisitionId": "otherId", "price": 200}, result]
    mock_generate_access_token.return_value = "valid_token"
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.post("/ades/quotes", headers=headers, json={"acquisitionId": "12345"})
    assert response.status_code == 200
    assert response.json() == result
