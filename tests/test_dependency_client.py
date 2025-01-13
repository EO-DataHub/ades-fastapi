from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

from ades_fastapi.dependency_client import DependencyClient, WorkflowType


@pytest.fixture
def dependency_client():
    return DependencyClient(
        opa_service_endpoint="http://opa-service",
        ades_policy_bucket="test-bucket",
        ades_policy_prefix="test-prefix",
        enable_opa_policy_check=True,
    )


@pytest.fixture
def mock_request():
    request = MagicMock(spec=Request)
    request.url.path = "/test/path"
    request.method = "GET"
    request.scope = {"path_params": {}}
    return request


@pytest.fixture
def job_owners():
    return {
        "workspace-job_id": {"calling": "test_workspace", "deployed": None},
        "test_workspace-job_1234": {"calling": "test_user", "deployed": None},
        "test_workspace-e4eaaaf2-d142-11e1-b3e4-080027620cdd": {
            "calling": "test_user",
            "deployed": None,
        },
        "another_workspace-aaaaaaaa-bbbb-cccc-dddd-000000000000": {
            "calling": "someother_workspace",
            "deployed": "another_user",
        },
    }


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.dependency_client.get_access_policy")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_policy_get_workflow(
    mock_opa_request, mock_get_access_policy, mock_get_user_details, dependency_client, job_owners
):
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_get_access_policy.return_value = {
        "public": True,
        "allowed_access": {"workspaces": ["test_workspace"]},
        "user_service": False,
    }
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    mock_request = MagicMock(
        method="GET",
        url=MagicMock(path="/test/path"),
        scope={
            "path_params": {"deploy_workspace": "test_workspace", "workflow_id": "test_workflow"}
        },
    )

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    expected_input_data = {
        "input": {
            "roles": ["role1", "role2"],
            "path": "/test/path",
            "workspace": "test_user",
            "method": "GET",
            "is_public": True,
            "allowed_workspaces": ["test_workspace"],
            "is_user_service": False,
        }
    }

    mock_opa_request.assert_called_once_with(expected_input_data)

    assert passed is True
    assert workflow_type == WorkflowType.WORKFLOW


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.dependency_client.get_access_policy")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_policy_execute_workflow(
    mock_opa_request, mock_get_access_policy, mock_get_user_details, dependency_client, job_owners
):
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_get_access_policy.return_value = {
        "public": True,
        "allowed_access": {"workspaces": ["test_workspace"]},
        "user_service": False,
    }
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    mock_request = MagicMock(
        method="POST",
        url=MagicMock(path="/test/path"),
        scope={
            "path_params": {"deploy_workspace": "test_workspace", "workflow_id": "test_workflow"}
        },
    )

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    expected_input_data = {
        "input": {
            "roles": ["role1", "role2"],
            "path": "/test/path",
            "workspace": "test_user",
            "method": "POST",
            "is_public": True,
            "allowed_workspaces": ["test_workspace"],
            "is_user_service": False,
        }
    }

    mock_opa_request.assert_called_once_with(expected_input_data)

    assert passed is True
    assert workflow_type == WorkflowType.WORKFLOW


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_policy_get_job(
    mock_opa_request, mock_get_user_details, dependency_client, job_owners
):
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    mock_request = MagicMock(
        method="GET",
        url=MagicMock(path="/test/path"),
        scope={"path_params": {"deploy_workspace": "test_workspace", "job_id": "job_1234"}},
    )

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    expected_input_data = {
        "input": {
            "roles": ["role1", "role2"],
            "path": "/test/path",
            "workspace": "test_user",
            "method": "GET",
            "calling_workspace": "test_user",
        }
    }

    mock_opa_request.assert_called_once_with(expected_input_data)

    assert passed is True
    assert workflow_type == WorkflowType.DEFAULT


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_policy_deploy_workflow(
    mock_opa_request, mock_get_user_details, dependency_client, job_owners
):
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    mock_request = MagicMock(
        method="POST",
        url=MagicMock(path="/test/path"),
        scope={"path_params": {"deploy_workspace": "test_workspace"}},
    )

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    expected_input_data = {
        "input": {
            "roles": ["role1", "role2"],
            "path": "/test/path",
            "workspace": "test_user",
            "method": "POST",
        }
    }

    mock_opa_request.assert_called_once_with(expected_input_data)

    assert passed is True
    assert workflow_type == WorkflowType.DEFAULT


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_policy_update_workflow(
    mock_opa_request, mock_get_user_details, dependency_client, job_owners
):
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    mock_request = MagicMock(
        method="PUT",
        url=MagicMock(path="/test/path"),
        scope={
            "path_params": {"deploy_workspace": "test_workspace", "workflow_id": "test_workflow"}
        },
    )

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    expected_input_data = {
        "input": {
            "roles": ["role1", "role2"],
            "path": "/test/path",
            "workspace": "test_user",
            "method": "PUT",
        }
    }

    mock_opa_request.assert_called_once_with(expected_input_data)

    assert passed is True
    assert workflow_type == WorkflowType.DEFAULT


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_policy_logs(mock_opa_request, mock_get_user_details, dependency_client, job_owners):
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    mock_request = MagicMock(
        method="GET",
        url=MagicMock(path="/test/path"),
        scope={
            "path_params": {
                "deploy_workspace": "test_workspace",
                "workflow_job_id": "test_workflow-e4eaaaf2-d142-11e1-b3e4-080027620cdd",
            }
        },
    )

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    expected_input_data = {
        "input": {
            "roles": ["role1", "role2"],
            "path": "/test/path",
            "workspace": "test_user",
            "method": "GET",
            "calling_workspace": "test_user",
        }
    }

    mock_opa_request.assert_called_once_with(expected_input_data)

    assert passed is True
    assert workflow_type == WorkflowType.DEFAULT


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.dependency_client.get_access_policy")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_policy_execute_workflow_no_policy(
    mock_opa_request, mock_get_access_policy, mock_get_user_details, dependency_client, job_owners
):
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_get_access_policy.return_value = {}
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    mock_request = MagicMock(
        method="POST",
        url=MagicMock(path="/test/path"),
        scope={
            "path_params": {"deploy_workspace": "test_workspace", "workflow_id": "test_workflow"}
        },
    )

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    expected_input_data = {
        "input": {
            "roles": ["role1", "role2"],
            "path": "/test/path",
            "workspace": "test_user",
            "method": "POST",
        }
    }

    mock_opa_request.assert_called_once_with(expected_input_data)

    assert passed is True
    assert workflow_type == WorkflowType.WORKFLOW


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.dependency_client.get_access_policy")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_policy_execute_workflow_user_service(
    mock_opa_request, mock_get_access_policy, mock_get_user_details, dependency_client, job_owners
):
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_get_access_policy.return_value = {"user_service": True}
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    mock_request = MagicMock(
        method="POST",
        url=MagicMock(path="/test/path"),
        scope={
            "path_params": {"deploy_workspace": "test_workspace", "workflow_id": "test_workflow"}
        },
    )

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    expected_input_data = {
        "input": {
            "roles": ["role1", "role2"],
            "path": "/test/path",
            "workspace": "test_user",
            "method": "POST",
            "is_user_service": True,
            "is_public": False,
            "allowed_workspaces": [],
        }
    }

    mock_opa_request.assert_called_once_with(expected_input_data)

    assert passed is True
    assert workflow_type == WorkflowType.USER_SERVICE


@patch("ades_fastapi.dependency_client.DependencyClient._get_path_params")
@patch("ades_fastapi.dependency_client.DependencyClient._check_policy")
def test_check_access(mock_check_policy, mock_get_path_params, dependency_client):
    mock_get_path_params.return_value = {"deploy_workspace": "test-workspace"}
    mock_check_policy.return_value = True, WorkflowType.DEFAULT

    mock_request = MagicMock(method="GET", scope={"deploy_workspace": "test-workspace"})

    passed, workflow_type = dependency_client.check_access(mock_request, job_owners)

    mock_check_policy.assert_called_once_with(mock_request, job_owners)

    assert passed is True
    assert workflow_type == WorkflowType.DEFAULT


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.utils.get_access_policy")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_access_denied(
    mock_opa_request,
    mock_get_access_policy,
    mock_get_user_details,
    dependency_client,
    mock_request,
    job_owners,
):
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_get_access_policy.return_value = {
        "public": True,
        "allowed_access": {"workspaces": ["test_workspace"]},
    }
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": False}

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    assert passed is False
    assert workflow_type == WorkflowType.DEFAULT


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.utils.get_access_policy")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_access_no_access_policy(
    mock_opa_request,
    mock_get_access_policy,
    mock_get_user_details,
    dependency_client,
    mock_request,
    job_owners,
):
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_get_access_policy.return_value = None
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    assert passed is True
    assert workflow_type == WorkflowType.DEFAULT


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.utils.get_access_policy")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_access_job_access(
    mock_opa_request,
    mock_get_access_policy,
    mock_get_user_details,
    dependency_client,
    mock_request,
    job_owners,
):
    mock_request.scope["path_params"] = {"deploy_workspace": "workspace", "job_id": "job_id"}
    mock_get_user_details.return_value = ("test_user", ["role1", "role2"])
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    expected_input_data = {
        "input": {
            "roles": ["role1", "role2"],
            "path": "/test/path",
            "workspace": "test_user",
            "method": "GET",
            "calling_workspace": "test_workspace",
        }
    }

    mock_opa_request.assert_called_once_with(expected_input_data)

    assert passed is True
    assert workflow_type == WorkflowType.DEFAULT


@patch("ades_fastapi.dependency_client.get_user_details")
@patch("ades_fastapi.utils.get_access_policy")
@patch("ades_fastapi.dependency_client.DependencyClient._opa_request")
def test_check_access_job_access_user_service(
    mock_opa_request,
    mock_get_access_policy,
    mock_get_user_details,
    dependency_client,
    mock_request,
    job_owners,
):
    mock_request.scope["path_params"] = {
        "deploy_workspace": "another_workspace",
        "job_id": "aaaaaaaa-bbbb-cccc-dddd-000000000000",
    }
    mock_request.method = "GET"
    mock_get_user_details.return_value = ("another_user", ["role1", "role2"])
    mock_opa_request.return_value.status_code = 200
    mock_opa_request.return_value.json.return_value = {"result": True}

    passed, workflow_type = dependency_client._check_policy(mock_request, job_owners)

    expected_input_data = {
        "input": {
            "roles": ["role1", "role2"],
            "path": "/test/path",
            "workspace": "another_user",
            "method": "GET",
            "calling_workspace": "someother_workspace",
            "deployed_workspace": "another_user",
        }
    }

    mock_opa_request.assert_called_once_with(expected_input_data)

    assert passed is True
    assert workflow_type == WorkflowType.DEFAULT  # check but this is not used after in the code


@patch("requests.post")
def test_opa_request(mock_post_request, dependency_client):
    mock_post_request.return_value = "Response"
    input_data = {"data": "content"}

    response = dependency_client._opa_request(input_data)

    assert response == "Response"

    mock_post_request.assert_called_once_with(
        dependency_client.opa_service_endpoint, json=input_data
    )
