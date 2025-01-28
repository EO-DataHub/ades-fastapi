import json
import os
import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from starlette.requests import Request

from ades_fastapi.api import app, quote
from ades_fastapi.utils import WorkflowType, QuoteRequest

client = TestClient(app)

@pytest.fixture(autouse=True)
def setenvvar(monkeypatch):
    with patch.dict(os.environ, clear=True):
        envvars = {
            "BASE_URL": "https://url.com",
        }
        for k, v in envvars.items():
            monkeypatch.setenv(k, v)
        yield


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
        mock_response, deploy_workspace, "test_user", WorkflowType.USER_SERVICE
    )


@patch("ades_fastapi.api.get_user_details")
@patch("ades_fastapi.api.job_saver")
@patch("ades_fastapi.dependency_client.DependencyClient.check_access")
@patch("ades_fastapi.ades_client.ADESClient.execute_workflow")
def test_execute_process_workflow(
    mock_execute_workflow, mock_check_access, mock_job_saver, mock_get_user_details
):
    # Override dependency
    mock_check_access.return_value = True, WorkflowType.WORKFLOW
    # Configure mocks
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
        mock_response, deploy_workspace, "test_user", WorkflowType.WORKFLOW
    )


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
    response = client.get(f"/{deploy_workspace}/ogc-api/jobs")
    calls = mock_get_deployed_workspaced_jobs.call_args
    assert isinstance(calls[0][0], Request)
    assert calls[0][1] == deploy_workspace
    assert isinstance(calls[0][2], dict)
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


@patch("ades_fastapi.airbus_client.AirbusClient.get_quote_from_airbus")
@patch("ades_fastapi.airbus_client.AirbusClient.generate_access_token")
def test_quote__airbus_sar(mock_generate_airbus_access_token, mock_get_quote_from_airbus):
    result = {"units": "EUR", "value": 100}
    mock_get_quote_from_airbus.return_value = [
        {"acquisitionId": "otherId", "price": 200},
        {"acquisitionId": "12345", "price": {"currency": "EUR", "total": 100}},
    ]
    mock_generate_airbus_access_token.return_value = "valid_token"
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.post(
        "/ades/quotes",
        headers=headers,
        json={"acquisitionId": "12345", "catalogueId": "airbus", "collectionId": "airbus_sar_data"},
    )
    assert response.status_code == 200
    assert response.json() == result


@patch("ades_fastapi.airbus_client.AirbusClient.get_quote_from_airbus")
@patch("ades_fastapi.airbus_client.AirbusClient.generate_access_token")
def test_quote__airbus_optical(mock_generate_airbus_access_token, mock_get_quote_from_airbus):
    result = {"units": "EUR", "value": 100}
    mock_get_quote_from_airbus.return_value = {"currency": "EUR", "totalAmount": 100}
    mock_generate_airbus_access_token.return_value = "valid_token"
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.post(
        "/ades/quotes",
        headers=headers,
        json={
            "acquisitionId": "12345",
            "catalogueId": "airbus",
            "collectionId": "airbus_spot_data",
        },
    )
    assert response.status_code == 200
    assert response.json() == result
    assert len(mock_get_quote_from_airbus.call_args[0][1]["items"][0]["datastripIds"]) == 1


@patch("ades_fastapi.airbus_client.AirbusClient.get_quote_from_airbus")
@patch("ades_fastapi.airbus_client.AirbusClient.generate_access_token")
def test_quote__airbus_optical_multi_order(
    mock_generate_airbus_access_token, mock_get_quote_from_airbus
):
    result = {"units": "EUR", "value": 100}
    mock_get_quote_from_airbus.return_value = {"currency": "EUR", "totalAmount": 100}
    mock_generate_airbus_access_token.return_value = "valid_token"
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.post(
        "/ades/quotes",
        headers=headers,
        json={
            "item_uuids": ["12345", "67890"],
            "catalogueId": "airbus",
            "collectionId": "airbus_pneo_data",
        },
    )
    assert response.status_code == 200
    assert response.json() == result
    assert len(mock_get_quote_from_airbus.call_args[0][1]["items"][0]["dataSourceIds"]) == 2


@patch("ades_fastapi.planet_client.PlanetClient.get_quote_from_planet")
def test_quote__planet(mock_get_quote_from_planet):
    mock_get_quote_from_planet.return_value = "1000 km2"
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.post(
        "/ades/quotes",
        headers=headers,
        json={"acquisitionId": "12345", "catalogueId": "planet", "collectionId": "collection-id"},
    )
    mock_get_quote_from_planet.assert_called_once_with(
        {"acquisitions": ["12345"], "collection": "collection-id"},
    )
    assert response.status_code == 200
    assert response.json() == "1000 km2"


@patch("ades_fastapi.airbus_client.AirbusClient.generate_access_token")
def test_quote_invalid_token(mock_generate_access_token):
    mock_generate_access_token.return_value = None
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.post(
        "/ades/quotes",
        headers=headers,
        json={"acquisitionId": "12345", "catalogueId": "airbus", "collectionId": "airbus_sar_data"},
    )
    assert response.status_code == 500


@patch("ades_fastapi.airbus_client.AirbusClient.get_quote_from_airbus")
@patch("ades_fastapi.airbus_client.AirbusClient.generate_access_token")
def test_quote_id_not_matched(mock_generate_access_token, mock_get_quote_from_airbus):
    mock_get_quote_from_airbus.return_value = [{"acquisitionId": "otherId", "price": 200}]
    mock_generate_access_token.return_value = "valid_token"
    headers = {"authorization": "Bearer valid_token", "accept": "application/json"}
    response = client.post(
        "/ades/quotes", headers=headers, json={"acquisitionId": "12345", "catalogueId": "airbus"}
    )
    assert response.status_code == 404


def test_quote_from_planet(requests_mock):

    expected = {"value": 34, "units": "km2"}

    mock_planet_response = {"geometry": {"coordinates": [[[4, 5], [5, 6], [6, 7]]]}}

    requests_mock.get('https://url.com/api/catalogue/stac/catalogs/supported-datasets/planet/collections/test_collection/items/test_id', json=mock_planet_response)

    body = QuoteRequest(**{"acquisitionId": "test_id", "collectionId": "test_collection", "catalogueId": "planet"})

    response = quote(None, body)

    assert response.status_code == 200
    assert json.loads(response.body.decode("utf-8")) == expected