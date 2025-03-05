from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from starlette.requests import Request

from ades_fastapi.api import app
from ades_fastapi.job_saver import JobSaver
from ades_fastapi.utils import WorkflowType

client = TestClient(app)


def override_opa_dependency_workflow():
    return WorkflowType.WORKFLOW


def override_opa_dependency_user_service():
    return WorkflowType.USER_SERVICE


def override_opa_dependency_other():
    return WorkflowType.OTHER


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.get_root")
def test_root(mock_get_root, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    mock_get_root.return_value = MagicMock(
        status_code=200, text="Reponse content", headers={"Content-Type": "text/html"}
    )
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades", headers=headers)
    mock_get_root.assert_called_once()
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.content.decode("utf-8") == "<h1>ADES HOMEPAGE</h1><p>Status: available</p>"


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.get_workspace_root")
def test_workspace_root(mock_get_workspace_root, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    mock_get_workspace_root.return_value = (
        MagicMock(
            status_code=200,
            headers={"Content-Type": "application/json"},
        ),
        '{"Data": "Response Data"}',
    )
    headers = {"authorization": "Bearer valid_token"}
    response = client.get("/ades/test_workspace/ogc-api", headers=headers)
    calls = mock_get_workspace_root.call_args
    assert calls[0][0] == "test_workspace"
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Data": "Response Data"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.undeploy_workflow")
def test_undeploy_processes(mock_undeploy_workflow, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_response = MagicMock(status_code=200)
    mock_response.headers = {"Content-Type": "application/json"}
    mock_undeploy_workflow.return_value = mock_response, '{"Result": "undeployed"}'

    deploy_workspace = "test_workspace"
    workflow_id = "test_workflow"
    response = client.delete(f"/{deploy_workspace}/ogc-api/processes/{workflow_id}")
    calls = mock_undeploy_workflow.call_args
    assert isinstance(calls[0][0], dict)
    assert calls[0][1] == deploy_workspace
    assert calls[0][2] == workflow_id
    assert response.status_code == 200
    assert response.json() == {"Result": "undeployed"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.list_workflows")
def test_list_processes(mock_list_workflows, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_list_workflows.return_value = (
        MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
        '{"workflowID": "test-workflow"}',
    )
    deploy_workspace = "test_workspace"
    response = client.get(f"/{deploy_workspace}/ogc-api/processes")
    calls = mock_list_workflows.call_args
    assert isinstance(calls[0][0], Request)
    assert calls[0][1] == deploy_workspace
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"workflowID": "test-workflow"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.deploy_workflow")
def test_deploy_workflow(mock_deploy_workflow, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_deploy_workflow.return_value = (
        MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
        '{"Result": "deployed"}',
    )
    deploy_workspace = "test_workspace"
    response = client.post(f"/{deploy_workspace}/ogc-api/processes")
    calls = mock_deploy_workflow.call_args
    assert isinstance(calls[0][0], Request)
    assert calls[0][1] == deploy_workspace
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Result": "deployed"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.update_workflow")
def test_update_workflow(mock_update_workflow, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_update_workflow.return_value = (
        MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
        '{"Result": "updated"}',
    )
    deploy_workspace = "test_workspace"
    workflow_id = "test_workflow"
    response = client.put(f"/{deploy_workspace}/ogc-api/processes/{workflow_id}")
    calls = mock_update_workflow.call_args
    assert isinstance(calls[0][0], Request)
    assert calls[0][1] == deploy_workspace
    assert calls[0][2] == workflow_id
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Result": "updated"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.get_workflow")
def test_process_details(mock_get_workflow, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_get_workflow.return_value = (
        MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
        '{"Details": "workflow"}',
    )
    deploy_workspace = "test_workspace"
    workflow_id = "test_workflow"
    response = client.get(f"/{deploy_workspace}/ogc-api/processes/{workflow_id}")
    calls = mock_get_workflow.call_args
    assert isinstance(calls[0][0], dict)
    assert calls[0][1] == deploy_workspace
    assert calls[0][2] == workflow_id
    assert calls[0][3] == WorkflowType.WORKFLOW
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Details": "workflow"}


@patch("ades_fastapi.api.get_user_details")
@patch("ades_fastapi.api.job_saver")
@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.execute_user_service")
def test_execute_process_user_service(
    mock_execute_user_service, mock_check_access, mock_job_saver, mock_get_user_details
):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.USER_SERVICE
    # Configure mocks
    mock_get_user_details.return_value = "test_user", []
    mock_job_saver.record_owner.return_value = None
    mock_response = MagicMock(status_code=201, headers={"Content-Type": "application/json"})
    mock_execute_user_service.return_value = (
        mock_response,
        '{"Status": "executing"}',
    )
    deploy_workspace = "test_workspace"
    workflow_id = "test_workflow"
    response = client.post(f"/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution")
    calls = mock_execute_user_service.call_args
    assert isinstance(calls[0][0], Request)
    assert calls[0][1] == deploy_workspace
    assert calls[0][2] == workflow_id
    assert response.status_code == 201
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Status": "executing"}
    mock_job_saver.record_owner.assert_called_once_with(
        mock_response, workflow_id, deploy_workspace, "test_user", WorkflowType.USER_SERVICE
    )


@patch("asyncio.sleep")
@patch("ades_fastapi.api.get_user_details")
@patch("ades_fastapi.api.job_saver")
@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.execute_workflow")
def test_execute_process_workflow(
    mock_execute_workflow, mock_check_access, mock_job_saver, mock_get_user_details, mock_sleep
):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_sleep.return_value = None
    mock_get_user_details.return_value = "test_user", []
    mock_job_saver.record_owner.return_value = None
    mock_response = MagicMock(status_code=201, headers={"Content-Type": "application/json"})
    mock_execute_workflow.return_value = (
        mock_response,
        '{"Status": "executing"}',
    )
    deploy_workspace = "test_workspace"
    workflow_id = "test_workflow"
    response = client.post(f"/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution")
    calls = mock_execute_workflow.call_args
    assert isinstance(calls[0][0], Request)
    assert calls[0][1] == deploy_workspace
    assert calls[0][2] == workflow_id
    assert response.status_code == 201
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Status": "executing"}
    mock_job_saver.record_owner.assert_called_once_with(
        mock_response, workflow_id, deploy_workspace, "test_user", WorkflowType.WORKFLOW
    )
    # Check rate limit was checked and waited
    assert mock_sleep.call_count == 1


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
def test_execute_process_other(mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.OTHER
    deploy_workspace = "test_workspace"
    workflow_id = "test_workflow"
    response = client.post(f"/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution")
    assert response.status_code == 400
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"detail": "Invalid workflow type"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.get_job_status")
def test_execute_process_status(mock_get_job_status, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_get_job_status.return_value = (
        MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
        '{"Status": "executing"}',
    )
    deploy_workspace = "test_workspace"
    job_id = "job_1234"
    response = client.get(f"/{deploy_workspace}/ogc-api/jobs/{job_id}")
    calls = mock_get_job_status.call_args
    assert isinstance(calls[0][0], dict)
    assert calls[0][1] == deploy_workspace
    assert calls[0][2] == job_id
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Status": "executing"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.get_job_results")
def test_execute_process_results(mock_get_job_results, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_get_job_results.return_value = (
        MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
        '{"Results": "available"}',
    )
    deploy_workspace = "test_workspace"
    job_id = "job_1234"
    response = client.get(f"/{deploy_workspace}/ogc-api/jobs/{job_id}/results")
    calls = mock_get_job_results.call_args
    assert isinstance(calls[0][0], dict)
    assert calls[0][1] == deploy_workspace
    assert calls[0][2] == job_id
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Results": "available"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.get_deployed_workspaced_jobs")
def test_get_deployed_workspaced_jobs(mock_get_deployed_workspaced_jobs, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_get_deployed_workspaced_jobs.return_value = (
        MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
        '{"jobs": [{"jobID": "job_1234"}]}',
    )
    deploy_workspace = "test_workspace"
    response = client.get(
        f"/{deploy_workspace}/ogc-api/jobs",
        params={
            "limit": 10,
            "skip": 2,
            "status": ["successful", "failed"],
            "datetime": "2021-01-01T00:00:00Z/2021-01-02T00:00:00Z",
        },
    )
    calls = mock_get_deployed_workspaced_jobs.call_args
    assert isinstance(calls[0][0], Request)
    assert calls[0][1] == deploy_workspace
    assert isinstance(calls[0][2], JobSaver)
    assert calls[1]["limit"] == 10
    assert calls[1]["skip"] == 2
    assert calls[1]["status"] == ["successful", "failed"]
    assert calls[1]["datetime"] == "2021-01-01T00:00:00Z/2021-01-02T00:00:00Z"

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"jobs": [{"jobID": "job_1234"}]}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.get_all_jobs")
def ignore_test_get_all_jobs(mock_get_all_jobs, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_get_all_jobs.return_value = '{"jobs": [{"jobID": "job_1234"}]}'
    response = client.get("/ogc-api/jobs")
    calls = mock_get_all_jobs.call_args
    assert isinstance(calls[0][0], dict)
    assert isinstance(calls[0][1], dict)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"jobs": [{"jobID": "job_1234"}]}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.get_log")
def test_get_log(mock_get_log, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_get_log.return_value = MagicMock(
        status_code=200, headers={"Content-Type": "application/json"}, content="Some log text"
    )
    deploy_workspace = "test_workspace"
    workflow_job_id = "test-workflow-1234"
    log_name = "test.log"
    response = client.get(f"/{deploy_workspace}/temp/{workflow_job_id}/{log_name}")
    calls = mock_get_log.call_args
    assert calls[0][0] == workflow_job_id
    assert calls[0][1] == log_name
    assert calls[0][2] == deploy_workspace
    assert isinstance(calls[0][3], dict)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.text == "Some log text"


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.delete_job")
def test_delete_job(mock_delete_job, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_delete_job.return_value = (
        MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
        '{"Result": "deleted"}',
    )
    deploy_workspace = "test_workspace"
    job_id = "job_1234"
    response = client.delete(f"/{deploy_workspace}/ogc-api/jobs/{job_id}")
    calls = mock_delete_job.call_args
    assert isinstance(calls[0][0], dict)
    assert calls[0][1] == deploy_workspace
    assert calls[0][2] == job_id
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Result": "deleted"}
