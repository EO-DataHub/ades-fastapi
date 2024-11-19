from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from ades_fastapi.api import app
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
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Data": "Response Data"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.undeploy_workflow")
def test_undeploy_processes(mock_undeploy_workflow, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_undeploy_workflow.return_value = MagicMock(status_code=200), '{"Result": "undeployed"}'
    deploy_workspace = "test_workspace"
    workflow_id = "test_workflow"
    response = client.delete(f"/{deploy_workspace}/ogc-api/processes/{workflow_id}")
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
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Result": "updated"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.get_workflow")
def test_get_workflow(mock_get_workflow, mock_check_access):
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
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Details": "workflow"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.execute_user_service")
def test_execute_process_user_service(mock_execute_user_service, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.USER_SERVICE
    # Configure mocks
    mock_execute_user_service.return_value = (
        MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
        '{"Status": "executing"}',
    )
    deploy_workspace = "test_workspace"
    workflow_id = "test_workflow"
    response = client.post(f"/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Status": "executing"}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.execute_workflow")
def test_execute_process_workflow(mock_execute_workflow, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_execute_workflow.return_value = (
        MagicMock(status_code=200, headers={"Content-Type": "application/json"}),
        '{"Status": "executing"}',
    )
    deploy_workspace = "test_workspace"
    workflow_id = "test_workflow"
    response = client.post(f"/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Status": "executing"}


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
    response = client.get(f"/{deploy_workspace}/ogc-api/jobs")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"jobs": [{"jobID": "job_1234"}]}


@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.get_all_jobs")
def test_get_all_jobs(mock_get_all_jobs, mock_check_access):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
    mock_get_all_jobs.return_value = '{"jobs": [{"jobID": "job_1234"}]}'
    response = client.get("/ogc-api/jobs")
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
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {"Result": "deleted"}


@patch("ades_fastapi.airbus_client.AirbusClient.get_quote_from_airbus")
@patch("ades_fastapi.airbus_client.AirbusClient.generate_access_token")
def test_quote(mock_generate_access_token, mock_get_quote_from_airbus):
    result = {"acquisitionId": "12345", "price": 100}
    mock_get_quote_from_airbus.return_value = [{"acquisitionId": "otherId", "price": 200}, result]
    mock_generate_access_token.return_value = "valid_token"
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.post("/ades/quotes", headers=headers, json={"acquisitionId": "12345"})
    assert response.status_code == 200
    assert response.json() == result


@patch("ades_fastapi.airbus_client.AirbusClient.generate_access_token")
def test_quote_invalid_token(mock_generate_access_token):
    mock_generate_access_token.return_value = None
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.post("/ades/quotes", headers=headers, json={"acquisitionId": "12345"})
    assert response.status_code == 500


@patch("ades_fastapi.airbus_client.AirbusClient.get_quote_from_airbus")
@patch("ades_fastapi.airbus_client.AirbusClient.generate_access_token")
def test_quote_id_not_matched(mock_generate_access_token, mock_get_quote_from_airbus):
    mock_get_quote_from_airbus.return_value = [{"acquisitionId": "otherId", "price": 200}]
    mock_generate_access_token.return_value = "valid_token"
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.post("/ades/quotes", headers=headers, json={"acquisitionId": "12345"})
    assert response.status_code == 404
