import json
from unittest import mock

import botocore
from fastapi import Request

from ades_fastapi.utils import (
    check_policy,
    check_workflow_access,
    convert_username_to_workspace,
    convert_workspace_to_username,
    get_access_policy,
    get_path_params,
    get_user_details,
    get_workflow_id_from_file,
    get_workflow_id_from_url,
    list_jobs_dict,
    opa_request,
    replace_href_links,
    save_data,
)


# Mock the logger to avoid unnecessary logging during tests
@mock.patch("ades_fastapi.utils.logger")
def test_get_path_params(mock_logger):
    request = mock.Mock(spec=Request)
    request.scope = {"path_params": {"key": "value"}}
    result = get_path_params(request)
    assert result == {"key": "value"}
    mock_logger.debug.assert_called_once_with("CALCULATING PATH PARAMETERS")


def test_save_data(tmp_path):
    job_owner_storage_dir = tmp_path
    job_owners = {"owner1": "data1"}

    save_data(job_owner_storage_dir, job_owners)

    with open(f"{job_owner_storage_dir}/job-owners.json", "r") as f:
        assert json.load(f) == job_owners


@mock.patch("ades_fastapi.utils.requests.post")
@mock.patch("ades_fastapi.utils.logger")
def test_opa_request(mock_logger, mock_post):
    input_data = {"key": "value"}
    opa_service_endpoint = "http://opa-service"

    mock_response = mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"result": True}
    mock_post.return_value = mock_response

    response = opa_request(input_data, opa_service_endpoint)

    assert response.status_code == 200
    assert response.json() == {"result": True}
    mock_logger.debug.assert_called_once_with(
        "Sending request to OPA service with input: %s", input_data
    )
    mock_post.assert_called_once_with(opa_service_endpoint, json=input_data)


@mock.patch("ades_fastapi.utils.jwt.decode")
def test_get_user_details(mock_jwt_decode):
    request = mock.Mock(spec=Request)
    request.headers = {"authorization": "Bearer testtoken"}

    mock_jwt_decode.return_value = {
        "preferred_username": "my-workspace",
        "realm_access": {"roles": ["role1", "role2"]},
    }

    username, roles = get_user_details(request)

    assert username == "my-workspace"
    assert roles == ["role1", "role2"]
    mock_jwt_decode.assert_called_once_with(
        "testtoken",
        options={"verify_signature": False},
        algorithms=["HS256"],
    )


@mock.patch("ades_fastapi.utils.boto3.client")
@mock.patch("ades_fastapi.utils.logger")
def test_get_access_policy(mock_logger, mock_boto3_client):
    mock_s3_client = mock.Mock()
    mock_boto3_client.return_value = mock_s3_client

    mock_s3_client.get_object.return_value = {
        "Body": mock.Mock(read=mock.Mock(return_value=json.dumps({"public": True}).encode("utf-8")))
    }

    ades_policy_bucket = "test-bucket"
    ades_policy_prefix = "test-prefix"
    deploy_workspace = "test-workspace"
    workflow_id = "test_workflow"

    result = get_access_policy(
        deploy_workspace, workflow_id, ades_policy_bucket, ades_policy_prefix
    )

    assert result == {"public": True}
    mock_s3_client.get_object.assert_called_once_with(
        Bucket=ades_policy_bucket,
        Key=f"{ades_policy_prefix}/{deploy_workspace}/{workflow_id}.access-policy.json",
    )

    # Test for NoSuchKey error
    mock_s3_client.get_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "NoSuchKey"}}, "get_object"
    )

    result = get_access_policy(
        deploy_workspace, workflow_id, ades_policy_bucket, ades_policy_prefix
    )
    assert result is None
    mock_logger.info.assert_any_call(
        "No access policy found for workflow %s in workspace %s",
        workflow_id,
        deploy_workspace,
    )

    # Test for other ClientError
    mock_s3_client.get_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "SomeOtherError"}}, "get_object"
    )

    result = get_access_policy(
        deploy_workspace, workflow_id, ades_policy_bucket, ades_policy_prefix
    )
    assert result is None
    mock_logger.info.assert_any_call(
        "Error getting access policy for workflow %s in workspace %s",
        workflow_id,
        deploy_workspace,
    )


@mock.patch("ades_fastapi.utils.opa_request")
@mock.patch("ades_fastapi.utils.get_user_details")
@mock.patch("ades_fastapi.utils.get_access_policy")
@mock.patch("ades_fastapi.utils.logger")
def test_check_policy(
    mock_logger,
    mock_get_access_policy,
    mock_get_user_details,
    mock_opa_request,
):
    request = mock.Mock(spec=Request)
    request.method = "GET"
    request.url.path = "/test/path"
    request.headers = {"authorization": "Bearer testtoken"}

    path_params = {"deploy_workspace": "test_workspace", "workflow_id": "test_workflow"}
    job_owners = {}
    opa_service_endpoint = "http://opa-service"
    ades_policy_bucket = "test-bucket"
    ades_policy_prefix = "test-prefix"

    mock_get_user_details.return_value = ("my-workspace", ["role1", "role2"])
    mock_get_access_policy.return_value = {
        "public": True,
        "allowed_access": {"workspaces": ["test-workspace"]},
    }
    mock_opa_request.return_value = mock.Mock(
        status_code=200, json=mock.Mock(return_value={"result": True})
    )

    result = check_policy(
        request,
        path_params,
        job_owners,
        opa_service_endpoint,
        ades_policy_bucket,
        ades_policy_prefix,
    )
    assert result[0] is True
    assert result[1] is False
    mock_logger.info.assert_any_call("Logged in as user: %s", "my-workspace")
    mock_logger.info.assert_any_call("Roles: %s", ["role1", "role2"])
    mock_logger.debug.assert_any_call("Input parameters from path: %s", path_params)
    mock_logger.info.assert_any_call("Checking policy for workflow access")
    mock_logger.info.assert_any_call(
        "Access policy is: %s",
        {"public": True, "allowed_access": {"workspaces": ["test-workspace"]}},
    )
    mock_opa_request.assert_called_once_with(
        {
            "input": {
                "roles": ["role1", "role2"],
                "path": "/test/path",
                "workspace": "my-workspace",
                "method": "GET",
                "is_public": True,
                "allowed_workspaces": ["test-workspace"],
                "is_user_service": False,
            }
        },
        opa_service_endpoint,
    )

    # Test for job monitoring
    path_params = {"deploy_workspace": "test-workspace", "job_id": "test_job"}
    job_owners = {"test-workspace-test_job": "my-workspace"}
    result = check_policy(
        request,
        path_params,
        job_owners,
        opa_service_endpoint,
        ades_policy_bucket,
        ades_policy_prefix,
    )
    assert result[0] is True
    assert result[1] is False
    mock_logger.info.assert_any_call("Checking job owner for job access")
    mock_opa_request.assert_called_with(
        {
            "input": {
                "roles": ["role1", "role2"],
                "path": "/test/path",
                "workspace": "my-workspace",
                "method": "GET",
                "calling_workspace": "my-workspace",
            }
        },
        opa_service_endpoint,
    )

    # Test for non-200 response from OPA
    mock_opa_request.return_value = mock.Mock(
        status_code=403, json=mock.Mock(return_value={"result": False})
    )
    result = check_policy(
        request,
        path_params,
        job_owners,
        opa_service_endpoint,
        ades_policy_bucket,
        ades_policy_prefix,
    )
    assert result[0] is False
    assert result[1] is False
    mock_opa_request.assert_called_with(
        {
            "input": {
                "roles": ["role1", "role2"],
                "path": "/test/path",
                "workspace": "my-workspace",
                "method": "GET",
                "calling_workspace": "my-workspace",
            }
        },
        opa_service_endpoint,
    )

    # Test missing access_policy
    path_params = {"deploy_workspace": "test_workspace", "workflow_id": "test_workflow"}
    mock_get_access_policy.return_value = {}
    result = check_policy(
        request,
        path_params,
        job_owners,
        opa_service_endpoint,
        ades_policy_bucket,
        ades_policy_prefix,
    )
    assert result[0] is False
    assert result[1] is False
    mock_opa_request.assert_called_with(
        {
            "input": {
                "roles": ["role1", "role2"],
                "path": "/test/path",
                "workspace": "my-workspace",
                "method": "GET",
            }
        },
        opa_service_endpoint,
    )
    mock_logger.info.assert_any_call("No access policy found")

    # Test user service
    mock_opa_request.return_value = mock.Mock(
        status_code=200, json=mock.Mock(return_value={"result": True})
    )
    mock_get_access_policy.return_value = {"user_service": True}
    result = check_policy(
        request,
        path_params,
        job_owners,
        opa_service_endpoint,
        ades_policy_bucket,
        ades_policy_prefix,
    )
    assert result[0] is True
    assert result[1] is True
    mock_logger.info.assert_any_call("No access policy found")


@mock.patch("ades_fastapi.utils.opa_request")
@mock.patch("ades_fastapi.utils.get_user_details")
@mock.patch("ades_fastapi.utils.get_access_policy")
@mock.patch("ades_fastapi.utils.logger")
def test_check_policy_partial_policy(
    mock_logger,
    mock_get_access_policy,
    mock_get_user_details,
    mock_opa_request,
):
    request = mock.Mock(spec=Request)
    request.method = "GET"
    request.url.path = "/test/path"
    request.headers = {"authorization": "Bearer testtoken"}

    path_params = {"deploy_workspace": "test_workspace", "workflow_id": "test_workflow"}
    job_owners = {}
    opa_service_endpoint = "http://opa-service"
    ades_policy_bucket = "test-bucket"
    ades_policy_prefix = "test-prefix"

    # Missing public and allowed users from policy
    mock_get_user_details.return_value = ("my-workspace", ["role1", "role2"])
    mock_get_access_policy.return_value = {"id": "test_workflow"}
    mock_opa_request.return_value = mock.Mock(
        status_code=200, json=mock.Mock(return_value={"result": False})
    )

    result = check_policy(
        request,
        path_params,
        job_owners,
        opa_service_endpoint,
        ades_policy_bucket,
        ades_policy_prefix,
    )

    assert result[0] is False
    assert result[1] is False
    mock_logger.info.assert_any_call("Access policy is: %s", {"id": "test_workflow"})
    mock_opa_request.assert_called_once_with(
        {
            "input": {
                "roles": ["role1", "role2"],
                "path": "/test/path",
                "workspace": "my-workspace",
                "method": "GET",
                "is_public": False,
                "allowed_workspaces": [],
                "is_user_service": False,
            }
        },
        opa_service_endpoint,
    )

    # Missing policy
    mock_get_access_policy.return_value = {}
    mock_opa_request.return_value = mock.Mock(
        status_code=200, json=mock.Mock(return_value={"result": False})
    )

    result = check_policy(
        request,
        path_params,
        job_owners,
        opa_service_endpoint,
        ades_policy_bucket,
        ades_policy_prefix,
    )

    assert result[0] is False
    assert result[1] is False
    mock_logger.info.assert_any_call("No access policy found")
    mock_opa_request.assert_called_with(
        {
            "input": {
                "roles": ["role1", "role2"],
                "path": "/test/path",
                "workspace": "my-workspace",
                "method": "GET",
            }
        },
        opa_service_endpoint,
    )


def test_convert_workspace_to_username():
    assert convert_workspace_to_username("test_workspace") == "test-workspace"


def test_convert_username_to_workspace():
    assert convert_username_to_workspace("test-username") == "test_username"
    assert convert_username_to_workspace("") == ""


@mock.patch("ades_fastapi.utils.get_user_details")
@mock.patch("ades_fastapi.utils.boto3.client")
@mock.patch("ades_fastapi.utils.logger")
def test_check_workflow_access(
    mock_logger,
    mock_boto3_client,
    mock_get_user_details,
):
    mock_s3_client = mock.Mock()
    mock_boto3_client.return_value = mock_s3_client

    mock_get_user_details.return_value = "test-workspace", []

    mock_s3_client.get_object.return_value = {
        "Body": mock.Mock(read=mock.Mock(return_value=json.dumps({"public": True}).encode("utf-8")))
    }

    request = mock.Mock(spec=Request)
    request.headers = {"authorization": "Bearer testtoken"}

    deploy_workspace = "deployed-workspace"
    ades_policy_bucket = "test-bucket"
    workflow_id = "test_workflow"

    result = check_workflow_access(
        request,
        deploy_workspace,
        ades_policy_bucket,
        workflow_id=workflow_id,
        ades_policy_prefix="test-prefix",
    )
    assert result[0] is True
    assert result[1] == "Workflow is public"
    mock_s3_client.get_object.assert_called_once_with(
        Bucket=ades_policy_bucket,
        Key=f"test-prefix/{deploy_workspace}/test_workflow.access-policy.json",
    )

    mock_logger.info.assert_any_call(
        "Checking user %s has access to workflow %s in workspace %s",
        "test-workspace",
        workflow_id,
        deploy_workspace,
    )


def test_replace_href_links():
    content_dict = {
        "links": [{"href": "http://localhost:8080/test1"}, {"href": "http://localhost:8080/test2"}]
    }
    ades_ingress_path = "http://ades-ingress"
    result = replace_href_links(content_dict, ades_ingress_path)
    assert result["links"][0]["href"] == "http://ades-ingress/test1"
    assert result["links"][1]["href"] == "http://ades-ingress/test2"


@mock.patch("ades_fastapi.utils.requests.get")
def test_get_workflow_id_from_url_missing_workflow(mock_get):
    mock_response = mock.Mock()
    mock_response.text = """
    $graph:
      - class: CommandLineTool
        id: test_workflow_id
    """
    mock_get.return_value = mock_response

    url = "http://test-url"
    success, result = get_workflow_id_from_url(url)
    assert result == "No Workflow found in CWL file"
    assert not success
    mock_get.assert_called_once_with(url)


@mock.patch("ades_fastapi.utils.requests.get")
def test_get_workflow_id_from_url_not_yaml(mock_get):
    mock_response = mock.Mock()
    mock_response.text = """
    $graph
      - class: CommandLineTool
        id test_workflow_id
    """
    mock_get.return_value = mock_response

    url = "http://test-url"
    success, result = get_workflow_id_from_url(url)
    assert result == "Error decoding CWL file as YAML"
    assert not success
    mock_get.assert_called_once_with(url)


def test_get_workflow_id_from_file_missing_workflow():
    cwl_str = """
    $graph:
      - class: CommandLineTool
        id: test_workflow_id
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "No Workflow found in CWL file"
    assert not success


def test_get_workflow_id_from_file_not_yaml():
    cwl_str = """
    $graph
      - class: CommandLineTool
        id test_workflow_id
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "Error decoding CWL file as YAML"
    assert not success


@mock.patch("ades_fastapi.utils.requests.get")
@mock.patch("ades_fastapi.utils.logger")
def test_list_jobs_dict(mock_logger, mock_get):
    mock_response = mock.Mock()
    mock_response.json.return_value = {"jobs": []}
    mock_get.return_value = mock_response

    deploy_workspace = "test_workspace"
    request = mock.Mock(spec=Request)
    request.headers = {"authorization": "Bearer testtoken"}
    ades_service_endpoint = "http://ades-service"

    result = list_jobs_dict(deploy_workspace, request, ades_service_endpoint)
    assert result == {"jobs": []}
    mock_get.assert_called_once_with(
        f"{ades_service_endpoint}/{deploy_workspace}/ogc-api/jobs",
        headers={"authorization": "Bearer testtoken"},
    )
