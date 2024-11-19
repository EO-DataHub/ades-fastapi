import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from ades_fastapi.ades_client import ADESClient
from ades_fastapi.utils import WorkflowType


@pytest.fixture
def ades_client():
    return ADESClient(
        service_endpoint="http://test-service-endpoint",
        base_url="http://test-base-url",
        policy_bucket="test-policy-bucket",
        policy_prefix="test-policy-prefix",
    )


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.get_workflow_id_from_file", return_value=(False, "Invalid CWL"))
async def test_deploy_workflow_invalid_cwl(mock_get_workflow_id_from_file, ades_client):
    request = MagicMock()
    request.headers = {"Content-Type": "application/cwl+yaml"}
    request.body = AsyncMock(return_value=b"test-cwl-content")

    with pytest.raises(HTTPException) as excinfo:
        await ades_client.deploy_workflow(request, "test-deploy-workspace")
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid CWL"


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch("ades_fastapi.ades_client.get_workflow_id_from_url", return_value=(True, "workflow-id"))
async def test_deploy_workflow_json(mock_get_workflow_id_from_url, mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(
        status_code=200,
        json=lambda: {"Details": "Content"},
        headers={"Content-Type": "application/json"},
    )
    request = MagicMock()
    request.headers = {"Content-Type": "application/json"}
    request.json = AsyncMock(return_value={"executionUnit": {"href": "http://test-url"}})

    response, content = await ades_client.deploy_workflow(request, "test-deploy-workspace")
    assert response.status_code == 200
    assert content == json.dumps({"Details": "Content"}, indent=2)


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.get_workflow_id_from_url", return_value=(False, "Invalid URL"))
async def test_deploy_workflow_invalid_json(mock_get_workflow_id_from_url, ades_client):
    request = MagicMock()
    request.headers = {"Content-Type": "application/json"}
    request.json = AsyncMock(return_value={"executionUnit": {"href": "http://test-url"}})

    with pytest.raises(HTTPException) as excinfo:
        await ades_client.deploy_workflow(request, "test-deploy-workspace")
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid URL"


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch("ades_fastapi.ades_client.get_workflow_id_from_file", return_value=(True, "workflow-id"))
async def test_deploy_workflow_cwl(mock_get_workflow_id_from_file, mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(
        status_code=200,
        json=lambda: {"Details": "Content"},
        headers={"Content-Type": "application/json"},
    )
    request = MagicMock()
    request.headers = {"Content-Type": "application/cwl+yaml"}
    request.body = AsyncMock(return_value=b"test-cwl-content")

    response, content = await ades_client.deploy_workflow(request, "test-deploy-workspace")
    assert response.status_code == 200
    assert content == json.dumps({"Details": "Content"}, indent=2)


@pytest.mark.asyncio
async def test_deploy_workflow_unsupported_content_type(ades_client):
    request = MagicMock()
    request.headers = {"Content-Type": "text/plain"}

    with pytest.raises(HTTPException) as excinfo:
        await ades_client.deploy_workflow(request, "test-deploy-workspace")
    assert excinfo.value.status_code == 415
    assert excinfo.value.detail == (
        "Unsupported content type. Only application/json and " "application/cwl+yaml are supported"
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
    response, content = ades_client.get_workspace_root("test-deploy-workspace")
    assert response.status_code == 200
    assert json.loads(content) == {"message": "OK"}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_undeploy_workflow(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"message": "OK"})
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.undeploy_workflow(
        headers, "test-deploy-workspace", "workflow-id"
    )
    assert response.status_code == 200
    assert json.loads(content) == {"message": "OK"}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch(
    "ades_fastapi.ades_client.ADESClient._check_workflow_access",
    return_value=(True, "Access granted"),
)
@patch("ades_fastapi.ades_client.replace_href_links", side_effect=lambda x, y: x)
async def test_list_workflows(
    mock_replace_href_links, mock_check_workflow_access, mock_send_request, ades_client
):
    mock_send_request.return_value = MagicMock(
        status_code=200,
        json=lambda: {"processes": [], "links": []},
        headers={"Content-Type": "application/json"},
    )
    request = MagicMock()
    request.headers = {"authorization": "Bearer token"}
    response, content = ades_client.list_workflows(request, "test-deploy-workspace")
    assert response.status_code == 200
    assert json.loads(content) == {"processes": [], "links": []}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_get_workflow(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"id": "workflow-id"})
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.get_workflow(
        headers, "test-deploy-workspace", "workflow-id", WorkflowType.USER_SERVICE
    )
    assert response.status_code == 200
    assert json.loads(content) == {
        "id": "workflow-id",
        "AccessReasoning": "Workflow is a user-service",
    }


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_get_job_status(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"status": "running"})
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.get_job_status(headers, "test-deploy-workspace", "job-id")
    assert response.status_code == 200
    assert json.loads(content) == {"status": "running"}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_get_job_results(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"result": "success"})
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.get_job_results(headers, "test-deploy-workspace", "job-id")
    assert response.status_code == 200
    assert json.loads(content) == {"result": "success"}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch("ades_fastapi.ades_client.get_user_details", return_value=("username", "details"))
async def test_get_deployed_workspaced_jobs(mock_get_user_details, mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(
        status_code=200, json=lambda: {"jobs": [{"jobID": "job-id"}]}
    )
    request = MagicMock()
    request.headers = {"authorization": "Bearer token"}
    job_owners = {"test-deploy-workspace-job-id": "username"}
    response, content = ades_client.get_deployed_workspaced_jobs(
        request, "test-deploy-workspace", job_owners
    )
    assert response.status_code == 200
    assert json.loads(content) == {"jobs": [{"jobID": "job-id"}]}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
@patch("ades_fastapi.ades_client.get_user_details", return_value=("username", "details"))
async def test_get_all_jobs(mock_get_user_details, mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"jobID": "job-id"})
    request = MagicMock()
    request.headers = {"authorization": "Bearer token"}
    workspace_jobs = {
        "username": [{"deploy_workspace": "test-deploy-workspace", "jobID": "job-id"}]
    }
    content = ades_client.get_all_jobs(request, workspace_jobs)
    assert json.loads(content) == {"workspace": "username", "jobs": [{"jobID": "job-id"}]}


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_get_log(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, text="log content")
    headers = {"authorization": "Bearer token"}
    response = ades_client.get_log("workflow-job-id", "file-name", "test-deploy-workspace", headers)
    assert response.status_code == 200
    assert response.text == "log content"


@pytest.mark.asyncio
@patch("ades_fastapi.ades_client.ADESClient._send_request")
async def test_delete_job(mock_send_request, ades_client):
    mock_send_request.return_value = MagicMock(status_code=200, json=lambda: {"message": "Deleted"})
    headers = {"authorization": "Bearer token"}
    response, content = ades_client.delete_job(headers, "test-deploy-workspace", "job-id")
    assert response.status_code == 200
    assert json.loads(content) == {"message": "Deleted"}


@patch("ades_fastapi.ades_client.get_user_details")
@patch("ades_fastapi.ades_client.boto3.client")
@patch("ades_fastapi.ades_client.logger")
def test_check_workflow_access(
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
    ades_policy_bucket = "test-policy-bucket"
    workflow_id = "test_workflow"

    result = ades_client._check_workflow_access(
        request,
        deploy_workspace,
        workflow_id=workflow_id,
    )
    assert result[0] is True
    assert result[1] == "Workflow is public"
    mock_s3_client.get_object.assert_called_once_with(
        Bucket=ades_policy_bucket,
        Key=f"test-policy-prefix/{deploy_workspace}/test_workflow.access-policy.json",
    )

    mock_logger.info.assert_any_call(
        "Checking user %s has access to workflow %s in workspace %s",
        "test-workspace",
        workflow_id,
        deploy_workspace,
    )
