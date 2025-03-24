import json
from unittest import mock

import botocore
from fastapi import Request

from ades_fastapi.utils import (
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
)


# Mock the logger to avoid unnecessary logging during tests
@mock.patch("ades_fastapi.utils.logger")
def test_get_path_params(mock_logger):
    request = mock.Mock(spec=Request)
    request.scope = {"path_params": {"key": "value"}}
    result = get_path_params(request)
    assert result == {"key": "value"}
    mock_logger.debug.assert_called_once_with("CALCULATING PATH PARAMETERS")


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
        "preferred_username": "username",
        "workspace": "my-workspace",
        "realm_access": {"roles": ["role1", "role2"]},
    }

    username, workspace, roles = get_user_details(request)

    assert workspace == "my-workspace"
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


def test_convert_workspace_to_username():
    assert convert_workspace_to_username("test_workspace") == "test-workspace"


def test_convert_username_to_workspace():
    assert convert_username_to_workspace("test-username") == "test_username"
    assert convert_username_to_workspace("") == ""


def test_replace_href_links():
    content_dict = {
        "links": [
            {"href": "http://localhost:8080/test-workspace/ogc-api/extra/path/test1"},
            {"href": "http://localhost:8080/test-workspace/ogc-api/extra/path/test2"},
        ]
    }
    ades_ingress_path = "http://ades-ingress/path"
    result = replace_href_links(content_dict, ades_ingress_path, "user", "test-workspace")
    assert (
        result["links"][0]["href"]
        == "http://ades-ingress/path/catalogs/user/catalogs/test-workspace/extra/path/test1"
    )
    assert (
        result["links"][1]["href"]
        == "http://ades-ingress/path/catalogs/user/catalogs/test-workspace/extra/path/test2"
    )


@mock.patch("ades_fastapi.utils.requests.get")
def test_get_workflow_id_from_url(mock_get):
    mock_response = mock.Mock()
    mock_response.text = """
    $graph:
      - class: Workflow
        id: test_workflow_id
        inputs:
          input1:
            type: string
          input2:
            type: string
    """
    mock_get.return_value = mock_response

    url = "http://test-url"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    success, result = get_workflow_id_from_url(url)
    assert result == "test_workflow_id"
    assert success
    mock_get.assert_called_once_with(url, headers=headers)


@mock.patch("ades_fastapi.utils.requests.get")
def test_get_workflow_id_from_url_illegal_input(mock_get):
    mock_response = mock.Mock()
    mock_response.text = """
    $graph:
      - class: Workflow
        id: test_workflow_id
        inputs:
          token:
            type: string
          input2:
            type: string
    """
    mock_get.return_value = mock_response

    url = "http://test-url"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    success, result = get_workflow_id_from_url(url)
    assert result == "Input token is not allowed in workflow"
    assert not success
    mock_get.assert_called_once_with(url, headers=headers)


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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    success, result = get_workflow_id_from_url(url)
    assert result == "No Workflow found in CWL file"
    assert not success
    mock_get.assert_called_once_with(url, headers=headers)


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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    success, result = get_workflow_id_from_url(url)
    assert result == "Error decoding CWL file as YAML"
    assert not success
    mock_get.assert_called_once_with(url, headers=headers)


def test_get_workflow_id_from_file_missing_workflow():
    cwl_str = """
    $graph:
      - class: CommandLineTool
        id: test_workflow_id
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "No Workflow found in CWL file"
    assert not success


def test_get_workflow_id_from_file():
    cwl_str = """
    $graph:
      - class: Workflow
        id: test_workflow_id
        inputs:
            input1:
                type: string
            input2:
                type: string
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "test_workflow_id"
    assert success


def test_get_workflow_id_from_file_illegal_input():
    cwl_str = """
    $graph:
      - class: Workflow
        id: test_workflow_id
        inputs:
            token:
                type: string
            input2:
                type: string
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "Input token is not allowed in workflow"
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
