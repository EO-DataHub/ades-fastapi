import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import botocore
import pytest
from fastapi import HTTPException, Request

from ades_fastapi.ades_client import ADESClient
from ades_fastapi.utils import WorkflowType

ADES_FASTAPI_ROOT_PATH = os.getenv("ADES_FASTAPI_ROOT_PATH", "/api/catalogue/stac")
API_DOCS_ROOT = os.getenv("API_DOCS_ROOT", "/api/docs")
USER_CATALOG_ROOT = os.getenv("USER_CATALOG_ROOT", "user")
ADES_INGRESS_PATH = os.getenv("ADES_INGRESS_PATH", "https://example-path")


@pytest.fixture
def ades_client():
    return ADESClient(
        service_endpoint="http://test-service-endpoint",
        base_url="http://test-base-url",
        policy_bucket="test-policy-bucket",
        policy_prefix="test-policy-prefix",
        catalog_root="user",
    )


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.get_workflow_id_from_file", return_value=(False, "Invalid CWL"))
async def test_deploy_workflow_invalid_cwl(mock_get_workflow_id_from_file, ades_client):
    request = MagicMock()
    request.headers = {"Content-Type": "application/cwl+yaml"}
    request.body = AsyncMock(return_value=b"test-cwl-content")

    with pytest.raises(HTTPException) as excinfo:
        await ades_client.deploy_workflow(request, "test_workspace")
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid CWL"


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch("ades_fastapi.ades_client.get_workflow_id_from_url", return_value=(True, "workflow-id"))
async def test_deploy_workflow_json(mock_get_workflow_id_from_url, mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(
        status_code=200,
        json=lambda: {"Details": "Content"},
        headers={
            "Content-Type": "application/json",
            "Location": "http://localhost:8080/test_workspace/ogc-api/execution",
        },
    )
    request = MagicMock()
    request.headers = {"authorization": "Bearer valid-token", "Content-Type": "application/json"}
    request.json = AsyncMock(return_value={"executionUnit": {"href": "http://test-url"}})

    response, content = await ades_client.deploy_workflow(request, "test_workspace")
    assert response.status_code == 200
    assert (
        response.headers["Location"]
        == "http://test-base-url/catalogs/user/catalogs/test_workspace/execution"
    )
    assert content == json.dumps({"Details": "Content"}, indent=2)

    mock_send_request.assert_called_once_with(
        "POST",
        "test_workspace/ogc-api/processes",
        {"Content-Type": "application/json"},
        {"json": {"executionUnit": {"href": "http://test-url"}}},
    )


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.get_workflow_id_from_url", return_value=(False, "Invalid URL"))
async def test_deploy_workflow_invalid_json(mock_get_workflow_id_from_url, ades_client):
    request = MagicMock()
    request.headers = {"authorization": "Bearer valid-token", "Content-Type": "application/json"}
    request.json = AsyncMock(return_value={"executionUnit": {"href": "http://test-url"}})

    with pytest.raises(HTTPException) as excinfo:
        await ades_client.deploy_workflow(request, "test_workspace")
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid URL"


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch("ades_fastapi.ades_client.get_workflow_id_from_file", return_value=(True, "workflow-id"))
async def test_deploy_workflow_cwl(mock_get_workflow_id_from_file, mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(
        status_code=200,
        json=lambda: {"Details": "Content"},
        headers={
            "Content-Type": "application/json",
            "Location": "http://localhost:8080/test_workspace/ogc-api/execution",
        },
    )
    request = MagicMock()
    request.headers = {
        "authorization": "Bearer valid-token",
        "Content-Type": "application/cwl+yaml",
    }
    request.body = AsyncMock(return_value=b"test-cwl-content")

    response, content = await ades_client.deploy_workflow(request, "test_workspace")
    assert response.status_code == 200
    assert (
        response.headers["Location"]
        == "http://test-base-url/catalogs/user/catalogs/test_workspace/execution"
    )
    assert content == json.dumps({"Details": "Content"}, indent=2)

    mock_send_request.assert_called_once_with(
        "POST",
        "test_workspace/ogc-api/processes",
        {"Content-Type": "application/cwl+yaml"},
        {"data": b"test-cwl-content"},
    )


@pytest.mark.asyncio
async def test_deploy_workflow_unsupported_content_type(ades_client):
    request = MagicMock()
    request.headers = {"Content-Type": "text/plain"}

    with pytest.raises(HTTPException) as excinfo:
        await ades_client.deploy_workflow(request, "test_workspace")
    assert excinfo.value.status_code == 415
    assert excinfo.value.detail == (
        "Unsupported content type. Only application/json and " "application/cwl+yaml are supported"
    )


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch("ades_fastapi.ades_client.get_workflow_id_from_url", return_value=(True, "workflow-id"))
async def test_update_workflow_json(mock_get_workflow_id_from_url, mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(
        status_code=200,
        json=lambda: {"Details": "Content"},
        headers={
            "Content-Type": "application/json",
            "Location": "http://localhost:8080/test_workspace/ogc-api/execution",
        },
    )
    request = MagicMock()
    request.headers = {"authorization": "Bearer valid-token", "Content-Type": "application/json"}
    request.json = AsyncMock(return_value={"executionUnit": {"href": "http://test-url"}})

    response, content = await ades_client.update_workflow(request, "test_workspace", "workflow-id")
    assert response.status_code == 200
    assert (
        response.headers["Location"]
        == "http://test-base-url/catalogs/user/catalogs/test_workspace/execution"
    )
    assert content == json.dumps({"Details": "Content"}, indent=2)

    mock_send_request.assert_called_once_with(
        "PUT",
        "test_workspace/ogc-api/processes/workflow-id",
        {"Content-Type": "application/json"},
        {"json": {"executionUnit": {"href": "http://test-url"}}},
    )


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch("ades_fastapi.ades_client.get_workflow_id_from_file", return_value=(True, "workflow-id"))
async def test_update_workflow_cwl(mock_get_workflow_id_from_file, mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(
        status_code=200,
        json=lambda: {"Details": "Content"},
        headers={
            "Content-Type": "application/json",
            "Location": "http://localhost:8080/test_workspace/ogc-api/execution",
        },
    )
    request = MagicMock()
    request.headers = {"Content-Type": "application/cwl+yaml"}
    request.body = AsyncMock(return_value=b"test-cwl-content")

    response, content = await ades_client.update_workflow(request, "test_workspace", "workflow-id")
    assert response.status_code == 200
    assert (
        response.headers["Location"]
        == "http://test-base-url/catalogs/user/catalogs/test_workspace/execution"
    )
    assert content == json.dumps({"Details": "Content"}, indent=2)

    mock_send_request.assert_called_once_with(
        "PUT",
        "test_workspace/ogc-api/processes/workflow-id",
        {"Content-Type": "application/cwl+yaml"},
        {"data": b"test-cwl-content"},
    )


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_get_root(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"message": "OK"})
    response = ades_client.get_root()
    assert response.status_code == 200
    assert response.json() == {"message": "OK"}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_get_workspace_root(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"message": "OK"})
    response, content = ades_client.get_workspace_root("test_workspace")
    assert response.status_code == 200
    assert json.loads(content) == {"message": "OK"}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_undeploy_workflow(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"message": "OK"})
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.undeploy_workflow(headers, "test_workspace", "workflow-id")
    assert response.status_code == 200
    assert json.loads(content) == {"message": "OK"}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch(
    "ades_fastapi.ades_client.ADESClient._check_workflow_access",
    return_value=(True, "Access granted"),
)
# @patch("ades_fastapi.ades_client.replace_href_links", side_effect=lambda x, y: x)
async def test_list_processes(mock_check_workflow_access, mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "processes": [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}, {"id": "5"}],
            "links": [
                {"Title": "link 1", "href": "some-href"},
                {"Title": "link 2", "href": "some-href-2"},
            ],
        },
        headers={"Content-Type": "application/json"},
    )
    request = MagicMock()
    request.headers = {"authorization": "Bearer token"}
    response, content = ades_client.list_processes(request, "test_workspace", limit=2, skip=0)
    mock_send_request.assert_called_once_with(
        "GET",
        "test_workspace/ogc-api/processes",
        {},
    )
    assert response.status_code == 200
    assert json.loads(content) == {
        "processes": [
            {"id": "1", "AccessReasoning": "Access granted"},
            {"id": "2", "AccessReasoning": "Access granted"},
        ],
        "links": [
            {"Title": "link 1", "href": "some-href"},
            {"Title": "link 2", "href": "some-href-2"},
        ],
    }

    request = MagicMock()
    request.headers = {"authorization": "Bearer token"}
    response, content = ades_client.list_processes(request, "test_workspace", limit=5, skip=2)
    mock_send_request.assert_any_call("GET", "test_workspace/ogc-api/processes", {})
    assert response.status_code == 200
    assert json.loads(content) == {
        "processes": [
            {"id": "3", "AccessReasoning": "Access granted"},
            {"id": "4", "AccessReasoning": "Access granted"},
            {"id": "5", "AccessReasoning": "Access granted"},
        ],
        "links": [
            {"Title": "link 1", "href": "some-href"},
            {"Title": "link 2", "href": "some-href-2"},
        ],
    }


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_get_workflow(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"id": "workflow-id"})
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.get_workflow(
        headers, "test_workspace", "workflow-id", WorkflowType.USER_SERVICE
    )
    assert response.status_code == 200
    assert json.loads(content) == {
        "id": "workflow-id",
        "AccessReasoning": "Workflow is a user-service",
    }


def test_configure_execute_request_user_service(ades_client):
    body = {"inputs": {"input": "value"}}
    creds = {
        "calling_workspace": {
            "AccessKeyId": "valid-access-key-id-workspace",
            "SecretAccessKey": "valid-secret-access-key-workspace",
            "SessionToken": "valid-session-token-workspace",
        },
        "executing_workspace": {
            "AccessKeyId": "valid-access-key-id",
            "SecretAccessKey": "valid-secret-access-key",
            "SessionToken": "valid-session-token",
        },
    }
    calling_workspace = "calling-workspace"
    executing_workspace = "executing-workspace"

    ades_client._configure_execute_request(body, creds, calling_workspace, executing_workspace)

    assert body == {
        "inputs": {
            "input": "value",
            "calling_workspace": calling_workspace,
            "executing_workspace": executing_workspace,
            "WORKSPACE_AWS_ACCESS_KEY_ID": "valid-access-key-id-workspace",
            "WORKSPACE_AWS_SECRET_ACCESS_KEY": "valid-secret-access-key-workspace",
            "WORKSPACE_AWS_SESSION_TOKEN": "valid-session-token-workspace",
            "AWS_ACCESS_KEY_ID": "valid-access-key-id",
            "AWS_SECRET_ACCESS_KEY": "valid-secret-access-key",
            "AWS_SESSION_TOKEN": "valid-session-token",
        }
    }


def test_configure_execute_request_workflow(ades_client):
    body = {"inputs": {"input": "value"}}
    creds = {
        "calling_workspace": {
            "AccessKeyId": "valid-access-key-id-workspace",
            "SecretAccessKey": "valid-secret-access-key-workspace",
            "SessionToken": "valid-session-token-workspace",
        },
        "executing_workspace": {},
    }

    calling_workspace = "calling-workspace"

    ades_client._configure_execute_request(body, creds, calling_workspace)

    assert body == {
        "inputs": {
            "input": "value",
            "calling_workspace": calling_workspace,
            "executing_workspace": calling_workspace,
            "WORKSPACE_AWS_ACCESS_KEY_ID": "valid-access-key-id-workspace",
            "WORKSPACE_AWS_SECRET_ACCESS_KEY": "valid-secret-access-key-workspace",
            "WORKSPACE_AWS_SESSION_TOKEN": "valid-session-token-workspace",
            "AWS_ACCESS_KEY_ID": "valid-access-key-id-workspace",
            "AWS_SECRET_ACCESS_KEY": "valid-secret-access-key-workspace",
            "AWS_SESSION_TOKEN": "valid-session-token-workspace",
        }
    }


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.generate_aws_credentials")
@patch("ades_fastapi.ades_client.ADESClient._send_execute_to_ades")
@patch("ades_fastapi.ades_client.get_user_details", return_value=("username", []))
async def test_execute_workflow(
    mock_get_user_details, mock_send_execute_to_ades, mock_generate_aws_credentials, ades_client
):
    # Configure mocks
    mock_generate_aws_credentials.return_value = {
        "calling_workspace": {
            "AccessKeyId": "valid-access-key-id-workspace",
            "SecretAccessKey": "valid-secret-access-key-workspace",
            "SessionToken": "valid-session-token-workspace",
        },
        "executing_workspace": {},
    }
    mock_response = MagicMock(
        status_code=201,
        json=lambda: {"Status": "Running", "jobID": "job_id"},
        headers={"Location": "http://localhost:8080/deploy_workspace/ogc-api/execution"},
    )
    mock_send_execute_to_ades.return_value = mock_response

    request = MagicMock(headers={"authorization": "Bearer valid-token"})
    request.json = AsyncMock(return_value={"inputs": {"input": "value"}})

    response, content = await ades_client.execute_workflow(
        request, "deploy_workspace", "workflow-id"
    )

    mock_send_execute_to_ades.assert_called_once_with(
        "deploy_workspace",
        "workflow-id",
        {
            "inputs": {
                "input": "value",
                "calling_workspace": "username",
                "executing_workspace": "username",
                "WORKSPACE_AWS_ACCESS_KEY_ID": "valid-access-key-id-workspace",
                "WORKSPACE_AWS_SECRET_ACCESS_KEY": "valid-secret-access-key-workspace",
                "WORKSPACE_AWS_SESSION_TOKEN": "valid-session-token-workspace",
                "AWS_ACCESS_KEY_ID": "valid-access-key-id-workspace",
                "AWS_SECRET_ACCESS_KEY": "valid-secret-access-key-workspace",
                "AWS_SESSION_TOKEN": "valid-session-token-workspace",
            }
        },
    )
    assert (
        response.headers["Location"]
        == "http://test-base-url/catalogs/user/catalogs/deploy_workspace/execution"
    )
    assert response.status_code == 201
    assert content == json.dumps({"Status": "Running", "jobID": "job_id"}, indent=2)


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.generate_aws_credentials")
@patch("ades_fastapi.ades_client.ADESClient._send_execute_to_ades")
@patch("ades_fastapi.ades_client.get_user_details", return_value=("username", []))
async def test_execute_user_service(
    mock_get_user_details, mock_send_execute_to_ades, mock_generate_aws_credentials, ades_client
):
    # Configure mocks
    mock_generate_aws_credentials.return_value = {
        "calling_workspace": {
            "AccessKeyId": "valid-access-key-id-workspace",
            "SecretAccessKey": "valid-secret-access-key-workspace",
            "SessionToken": "valid-session-token-workspace",
        },
        "executing_workspace": {
            "AccessKeyId": "valid-access-key-id",
            "SecretAccessKey": "valid-secret-access-key",
            "SessionToken": "valid-session-token",
        },
    }
    mock_response = MagicMock(
        status_code=201,
        json=lambda: {"Status": "Running"},
        headers={"Location": "http://localhost:8080/deploy_workspace/ogc-api/execution"},
    )
    mock_send_execute_to_ades.return_value = mock_response

    request = MagicMock(headers={"authorization": "Bearer valid-token"})
    request.json = AsyncMock(return_value={"inputs": {"input": "value"}})

    response, content = await ades_client.execute_user_service(
        request, "deploy_workspace", "workflow-id"
    )

    mock_send_execute_to_ades.assert_called_once_with(
        "deploy_workspace",
        "workflow-id",
        {
            "inputs": {
                "input": "value",
                "calling_workspace": "username",
                "executing_workspace": "deploy_workspace",
                "WORKSPACE_AWS_ACCESS_KEY_ID": "valid-access-key-id-workspace",
                "WORKSPACE_AWS_SECRET_ACCESS_KEY": "valid-secret-access-key-workspace",
                "WORKSPACE_AWS_SESSION_TOKEN": "valid-session-token-workspace",
                "AWS_ACCESS_KEY_ID": "valid-access-key-id",
                "AWS_SECRET_ACCESS_KEY": "valid-secret-access-key",
                "AWS_SESSION_TOKEN": "valid-session-token",
            }
        },
    )
    assert (
        response.headers["Location"]
        == "http://test-base-url/catalogs/user/catalogs/deploy_workspace/execution"
    )
    assert response.status_code == 201
    assert content == json.dumps({"Status": "Running"}, indent=2)


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.generate_aws_credentials")
@patch("ades_fastapi.ades_client.ADESClient._send_execute_to_ades")
@patch("ades_fastapi.ades_client.get_user_details", return_value=("username", []))
async def test_execute_user_service_missing_executing_creds(
    mock_get_user_details, mock_send_execute_to_ades, mock_generate_aws_credentials, ades_client
):
    # Configure mocks
    mock_generate_aws_credentials.return_value = {
        "calling_workspace": {
            "AccessKeyId": "valid-access-key-id-workspace",
            "SecretAccessKey": "valid-secret-access-key-workspace",
            "SessionToken": "valid-session-token-workspace",
        },
        "executing_workspace": None,
    }
    mock_response = MagicMock(
        status_code=201,
        json=lambda: {"Status": "Running"},
        headers={"Location": "http://localhost:8080/deploy_workspace/ogc-api/execution"},
    )
    mock_send_execute_to_ades.return_value = mock_response

    request = MagicMock(headers={"authorization": "Bearer valid-token"})
    request.json = AsyncMock(return_value={"inputs": {"input": "value"}})

    response, content = await ades_client.execute_user_service(
        request, "deploy_workspace", "workflow-id"
    )

    mock_send_execute_to_ades.assert_called_once_with(
        "deploy_workspace",
        "workflow-id",
        {
            "inputs": {
                "input": "value",
                "calling_workspace": "username",
                "executing_workspace": "deploy_workspace",
                "WORKSPACE_AWS_ACCESS_KEY_ID": "valid-access-key-id-workspace",
                "WORKSPACE_AWS_SECRET_ACCESS_KEY": "valid-secret-access-key-workspace",
                "WORKSPACE_AWS_SESSION_TOKEN": "valid-session-token-workspace",
            }
        },
    )
    assert (
        response.headers["Location"]
        == "http://test-base-url/catalogs/user/catalogs/deploy_workspace/execution"
    )
    assert response.status_code == 201
    assert content == json.dumps({"Status": "Running"}, indent=2)


@patch("ades_fastapi.ades_client.ADESClient._send_request")
def test_send_execute_to_ades(mock_send_request, ades_client):
    mock_response = MagicMock()
    mock_send_request.return_value = mock_response
    headers = {
        "Prefer": "respond-async",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {"inputs": {"input": "value"}}
    response = ades_client._send_execute_to_ades("deploy_workspace", "workflow-id", body)

    mock_send_request.assert_called_once_with(
        "POST", "deploy_workspace/ogc-api/processes/workflow-id/execution", headers, {"json": body}
    )
    assert response == mock_response


@patch("requests.get")
def test_send_request_get_root(mock_request, ades_client):
    mock_response = MagicMock()
    mock_request.return_value = mock_response
    headers = {"Content-Type": "application/json"}
    response = ades_client._send_request("GET", headers=headers)

    mock_request.assert_called_once_with("http://test-service-endpoint", headers=headers)
    assert response == mock_response


@patch("requests.get")
def test_send_request_get_root_no_headers(mock_request, ades_client):
    mock_response = MagicMock()
    mock_request.return_value = mock_response
    response = ades_client._send_request("GET")

    mock_request.assert_called_once_with("http://test-service-endpoint", headers=None)
    assert response == mock_response


@patch("requests.get")
def test_send_request_get_workflow(mock_request, ades_client):
    mock_response = MagicMock()
    mock_request.return_value = mock_response
    headers = {"Content-Type": "application/json"}
    url_path = "test/path"
    data = {"json": {"inputs": {"inputs": "value"}}}
    response = ades_client._send_request("GET", url_path, headers, data)

    mock_request.assert_called_once_with(
        "http://test-service-endpoint/test/path", headers=headers, **data
    )
    assert response == mock_response


@patch("requests.post")
def test_send_request_execute_workflow(mock_request, ades_client):
    mock_response = MagicMock()
    mock_request.return_value = mock_response
    headers = {"Content-Type": "application/json"}
    url_path = "deploy_workspace/ogc-api/workflow-id"
    data = {"json": {"inputs": {"inputs": "value"}}}
    response = ades_client._send_request("POST", url_path, headers, data)

    mock_request.assert_called_once_with(
        "http://test-service-endpoint/deploy_workspace/ogc-api/workflow-id", headers=headers, **data
    )
    assert response == mock_response


@patch("requests.put")
def test_send_request_update_workflow(mock_request, ades_client):
    mock_response = MagicMock()
    mock_request.return_value = mock_response
    headers = {"Content-Type": "application/json"}
    url_path = "deploy_workspace/ogc-api/workflow-id"
    data = {"data": "some workflow content"}
    response = ades_client._send_request("PUT", url_path, headers, data)

    mock_request.assert_called_once_with(
        "http://test-service-endpoint/deploy_workspace/ogc-api/workflow-id", headers=headers, **data
    )
    assert response == mock_response


@patch("requests.post")
def test_send_request_deploy_workflow(mock_request, ades_client):
    mock_response = MagicMock()
    mock_request.return_value = mock_response
    headers = {"Content-Type": "application/json"}
    url_path = "deploy_workspace/ogc-api/workflow-id"
    data = {"json": {"execution_body": "http://link/to/workflow"}}
    response = ades_client._send_request("POST", url_path, headers, data)

    mock_request.assert_called_once_with(
        "http://test-service-endpoint/deploy_workspace/ogc-api/workflow-id", headers=headers, **data
    )
    assert response == mock_response


@patch("requests.delete")
def test_send_request_delete_workflow(mock_request, ades_client):
    mock_response = MagicMock()
    mock_request.return_value = mock_response
    headers = {"Content-Type": "application/json"}
    url_path = "deploy_workspace/ogc-api/workflow-id"
    response = ades_client._send_request("DELETE", url_path, headers)

    mock_request.assert_called_once_with(
        "http://test-service-endpoint/deploy_workspace/ogc-api/workflow-id", headers=headers
    )
    assert response == mock_response


@patch("requests.delete")
def test_send_request_delete_job(mock_request, ades_client):
    mock_response = MagicMock()
    mock_request.return_value = mock_response
    headers = {"Content-Type": "application/json"}
    url_path = "deploy_workspace/ogc-api/jobs/job_id"
    response = ades_client._send_request("DELETE", url_path, headers)

    mock_request.assert_called_once_with(
        "http://test-service-endpoint/deploy_workspace/ogc-api/jobs/job_id", headers=headers
    )
    assert response == mock_response


@patch("requests.get")
def test_send_request_view_log(mock_request, ades_client):
    mock_response = MagicMock()
    mock_request.return_value = mock_response
    headers = {"Content-Type": "application/json"}
    url_path = "deploy_workspace/temp/workflow-id-12345"
    response = ades_client._send_request("GET", url_path, headers)

    mock_request.assert_called_once_with(
        "http://test-service-endpoint/deploy_workspace/temp/workflow-id-12345", headers=headers
    )
    assert response == mock_response


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_get_job_status(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "status": "running",
            "links": [
                {
                    "rel": "monitor",
                    "href": "http://localhost:8080/test_workspace/ogc-api/jobs/job-id",
                }
            ],
        },
    )
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.get_job_status(headers, "test_workspace", "job-id")
    assert response.status_code == 200
    assert json.loads(content) == {
        "status": "running",
        "links": [
            {
                "rel": "monitor",
                "href": "http://test-base-url/catalogs/user/catalogs/test_workspace/jobs/job-id",
            }
        ],
    }


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_get_job_results(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"result": "success"})
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.get_job_results(headers, "test_workspace", "job-id")
    assert response.status_code == 200
    assert json.loads(content) == {"result": "success"}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch("ades_fastapi.ades_client.get_user_details", return_value=("username", []))
async def test_get_deployed_workspaced_jobs(mock_get_user_details, mock_send_request, ades_client):
    mock_job_saver = MagicMock()
    mock_job_saver.get_job_details.return_value = {
        "jobID": "job_1",
        "workflow_id": "convert-url-test",
        "workflow_type": "workflow",
        "deploy_workspace": "username",
        "calling_workspace": "username",
    }
    mock_send_request.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "jobs": [
                {"jobID": "job-1"},
                {"jobID": "job-2"},
                {"jobID": "job-3"},
                {"jobID": "job-4"},
                {"jobID": "job-5"},
                {"jobID": "job-6"},
            ]
        },
    )
    request = MagicMock()
    request.headers = {"authorization": "Bearer token"}
    # Test limit
    response, content = ades_client.get_deployed_workspaced_jobs(
        request, "test_workspace", mock_job_saver
    )
    mock_send_request.assert_any_call("GET", "test_workspace/ogc-api/jobs", {}, data={"params": {}})
    assert response.status_code == 200
    assert json.loads(content) == {
        "jobs": [
            {"jobID": "job-1"},
            {"jobID": "job-2"},
            {"jobID": "job-3"},
            {"jobID": "job-4"},
            {"jobID": "job-5"},
            {"jobID": "job-6"},
        ],
        "numberTotal": 6,
    }

    # Test limit and skip
    response, content = ades_client.get_deployed_workspaced_jobs(
        request, "test_workspace", mock_job_saver, limit=3, skip=4
    )
    mock_send_request.assert_any_call("GET", "test_workspace/ogc-api/jobs", {}, data={"params": {}})
    assert response.status_code == 200
    assert json.loads(content) == {
        "jobs": [{"jobID": "job-5"}, {"jobID": "job-6"}],
        "numberTotal": 2,
    }

    # Test status
    response, content = ades_client.get_deployed_workspaced_jobs(
        request, "test_workspace", mock_job_saver, status="running,failed", limit=2
    )
    mock_send_request.assert_any_call(
        "GET",
        "test_workspace/ogc-api/jobs",
        {},
        data={"params": {"status": "running,failed"}},
    )
    assert response.status_code == 200
    assert json.loads(content) == {
        "jobs": [{"jobID": "job-1"}, {"jobID": "job-2"}],
        "numberTotal": 2,
    }

    # Test datetime
    response, content = ades_client.get_deployed_workspaced_jobs(
        request,
        "test_workspace",
        mock_job_saver,
        datetime="2021-01-01T00:00:00Z/2021-01-02T00:00:00Z",
        limit=3,
    )
    mock_send_request.assert_any_call(
        "GET",
        "test_workspace/ogc-api/jobs",
        {},
        data={"params": {"datetime": "2021-01-01T00:00:00Z/2021-01-02T00:00:00Z"}},
    )
    assert response.status_code == 200
    assert json.loads(content) == {
        "jobs": [{"jobID": "job-1"}, {"jobID": "job-2"}, {"jobID": "job-3"}],
        "numberTotal": 3,
    }


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch("ades_fastapi.ades_client.get_user_details", return_value=("test-workspace", []))
async def test_get_all_jobs(mock_get_user_details, mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(
        status_code=200, json=lambda: {"jobID": "job-id-details"}
    )
    request = MagicMock()
    request.headers = {"authorization": "Bearer token", "Content-Type": "application/json"}
    workspace_jobs = {
        "test-workspace": [
            {"deploy_workspace": "test_workspace-1", "jobID": "job-id-1"},
            {"deploy_workspace": "test_workspace-2", "jobID": "job-id-2"},
        ]
    }
    content = ades_client.get_all_jobs(request, workspace_jobs)
    assert json.loads(content) == {
        "workspace": "test-workspace",
        "jobs": [{"jobID": "job-id-details"}, {"jobID": "job-id-details"}],
    }

    calls = mock_send_request.call_args_list

    assert calls[0][0] == (
        "GET",
        "test_workspace-1/ogc-api/jobs/job-id-1",
        {"Content-Type": "application/json"},
    )
    assert calls[1][0] == (
        "GET",
        "test_workspace-2/ogc-api/jobs/job-id-2",
        {"Content-Type": "application/json"},
    )


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_get_log(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, content="log content")
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.get_log(
        "workflow-job-id", "file-name", "test_workspace", headers
    )
    assert response.status_code == 200
    assert content == "log content"


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_delete_job(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"message": "Deleted"})
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.delete_job(headers, "test_workspace", "job-id")
    assert response.status_code == 200
    assert json.loads(content) == {"message": "Deleted"}


@patch("ades_fastapi.ades_client.get_user_details")
@patch("ades_fastapi.ades_client.boto3.client")
@patch("ades_fastapi.ades_client.logger")
def test_check_workflow_access_public(
    mock_logger,
    mock_boto3_client,
    mock_get_user_details,
    ades_client,
):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client

    mock_get_user_details.return_value = "test-workspace", []

    mock_s3_client.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=json.dumps({"public": True}).encode("utf-8")))
    }

    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Bearer testtoken"}

    deploy_workspace = "deployed-workspace"
    workflow_id = "test_workflow"

    result = ades_client._check_workflow_access(
        request,
        deploy_workspace,
        workflow_id=workflow_id,
    )
    assert result[0] is True
    assert result[1] == "Workflow is public"
    mock_s3_client.get_object.assert_called_once_with(
        Bucket="test-policy-bucket",
        Key=f"test-policy-prefix/{deploy_workspace}/test_workflow.access-policy.json",
    )

    mock_logger.info.assert_any_call(
        "Checking user %s has access to workflow %s in workspace %s",
        "test-workspace",
        workflow_id,
        deploy_workspace,
    )


@patch("ades_fastapi.ades_client.get_user_details")
@patch("ades_fastapi.ades_client.boto3.client")
@patch("ades_fastapi.ades_client.logger")
def test_check_workflow_access_workspace_owner(
    mock_logger,
    mock_boto3_client,
    mock_get_user_details,
    ades_client,
):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client

    mock_get_user_details.return_value = "deployed-workspace", []

    mock_s3_client.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=json.dumps({"public": True}).encode("utf-8")))
    }

    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Bearer testtoken"}

    deploy_workspace = "deployed-workspace"
    workflow_id = "test_workflow"

    result = ades_client._check_workflow_access(
        request,
        deploy_workspace,
        workflow_id=workflow_id,
    )
    assert result[0] is True
    assert result[1] == "Workspace owns this workflow"
    mock_boto3_client.assert_not_called()


@patch("ades_fastapi.ades_client.get_user_details")
@patch("ades_fastapi.ades_client.boto3.client")
@patch("ades_fastapi.ades_client.logger")
def test_check_workflow_access_user_service(
    mock_logger,
    mock_boto3_client,
    mock_get_user_details,
    ades_client,
):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client

    mock_get_user_details.return_value = "test-workspace", []

    mock_s3_client.get_object.return_value = {
        "Body": MagicMock(
            read=MagicMock(return_value=json.dumps({"user_service": True}).encode("utf-8"))
        )
    }

    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Bearer testtoken"}

    deploy_workspace = "deployed-workspace"
    workflow_id = "test_workflow"

    result = ades_client._check_workflow_access(
        request,
        deploy_workspace,
        workflow_id=workflow_id,
    )
    assert result[0] is True
    assert result[1] == "Workflow is a user-service"
    mock_s3_client.get_object.assert_called_once_with(
        Bucket="test-policy-bucket",
        Key=f"test-policy-prefix/{deploy_workspace}/test_workflow.access-policy.json",
    )

    mock_logger.info.assert_any_call(
        "Checking user %s has access to workflow %s in workspace %s",
        "test-workspace",
        workflow_id,
        deploy_workspace,
    )


@patch("ades_fastapi.ades_client.get_user_details")
@patch("ades_fastapi.ades_client.boto3.client")
@patch("ades_fastapi.ades_client.logger")
def test_check_workflow_access_user_access(
    mock_logger,
    mock_boto3_client,
    mock_get_user_details,
    ades_client,
):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client

    mock_get_user_details.return_value = "test-workspace", []

    mock_s3_client.get_object.return_value = {
        "Body": MagicMock(
            read=MagicMock(
                return_value=json.dumps(
                    {"allowed_access": {"workspaces": ["test-workspace"]}}
                ).encode("utf-8")
            )
        )
    }

    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Bearer testtoken"}

    deploy_workspace = "deployed-workspace"
    workflow_id = "test_workflow"

    result = ades_client._check_workflow_access(
        request,
        deploy_workspace,
        workflow_id=workflow_id,
    )
    assert result[0] is True
    assert result[1] == "Workspace has access to this workflow (user)"
    mock_s3_client.get_object.assert_called_once_with(
        Bucket="test-policy-bucket",
        Key=f"test-policy-prefix/{deploy_workspace}/test_workflow.access-policy.json",
    )


@patch("ades_fastapi.ades_client.get_user_details")
@patch("ades_fastapi.ades_client.boto3.client")
@patch("ades_fastapi.ades_client.logger")
def test_check_workflow_access_no_user_access(
    mock_logger,
    mock_boto3_client,
    mock_get_user_details,
    ades_client,
):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client

    mock_get_user_details.return_value = "test-workspace", []

    mock_s3_client.get_object.return_value = {
        "Body": MagicMock(
            read=MagicMock(
                return_value=json.dumps(
                    {"allowed_access": {"workspaces": ["another-workspace"]}}
                ).encode("utf-8")
            )
        )
    }

    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Bearer testtoken"}

    deploy_workspace = "deployed-workspace"
    workflow_id = "test_workflow"

    result = ades_client._check_workflow_access(
        request,
        deploy_workspace,
        workflow_id=workflow_id,
    )
    assert result[0] is False
    assert result[1] == ""
    mock_s3_client.get_object.assert_called_once_with(
        Bucket="test-policy-bucket",
        Key=f"test-policy-prefix/{deploy_workspace}/test_workflow.access-policy.json",
    )


@patch("ades_fastapi.ades_client.get_user_details")
@patch("ades_fastapi.ades_client.boto3.client")
@patch("ades_fastapi.ades_client.logger")
def test_check_workflow_access_no_policy(
    mock_logger,
    mock_boto3_client,
    mock_get_user_details,
    ades_client,
):
    mock_s3_client = MagicMock()
    error_response = {
        "Error": {
            "Code": "NoSuchKey",
            "Message": "The specified key does not exist.",
        }
    }
    operation_name = "GetObject"
    mock_s3_client.get_object.side_effect = botocore.exceptions.ClientError(
        error_response, operation_name
    )
    mock_boto3_client.return_value = mock_s3_client

    mock_get_user_details.return_value = "test-workspace", []

    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Bearer testtoken"}

    deploy_workspace = "deployed-workspace"
    workflow_id = "test_workflow"

    result = ades_client._check_workflow_access(
        request,
        deploy_workspace,
        workflow_id=workflow_id,
    )
    assert result[0] is False
    assert result[1] == ""
    mock_s3_client.get_object.assert_called_once_with(
        Bucket="test-policy-bucket",
        Key=f"test-policy-prefix/{deploy_workspace}/test_workflow.access-policy.json",
    )


@patch("ades_fastapi.ades_client.get_user_details")
@patch("ades_fastapi.ades_client.boto3.client")
@patch("ades_fastapi.ades_client.logger")
def test_check_workflow_access_invalid_policy(
    mock_logger,
    mock_boto3_client,
    mock_get_user_details,
    ades_client,
):
    mock_s3_client = MagicMock()
    mock_s3_client.get_object.return_value = {
        "Body": MagicMock(
            read=MagicMock(
                return_value='{"allowed_access":{"workspaces":"another-workspace"]}}'.encode(
                    "utf-8"
                )
            )
        )
    }
    mock_boto3_client.return_value = mock_s3_client

    mock_get_user_details.return_value = "test-workspace", []

    request = MagicMock(spec=Request)
    request.headers = {"authorization": "Bearer testtoken"}

    deploy_workspace = "deployed-workspace"
    workflow_id = "test_workflow"

    result = ades_client._check_workflow_access(
        request,
        deploy_workspace,
        workflow_id=workflow_id,
    )
    assert result[0] is False
    assert result[1] == ""
    mock_s3_client.get_object.assert_called_once_with(
        Bucket="test-policy-bucket",
        Key=f"test-policy-prefix/{deploy_workspace}/test_workflow.access-policy.json",
    )
