import json
import types
from collections.abc import Generator
from unittest import mock

import botocore.exceptions
import jwt
import jwt.utils
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException, Request

from ades_fastapi import utils
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

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _request_with_token(token: str) -> mock.Mock:
    request = mock.Mock(spec=Request)
    request.headers = {"authorization": f"Bearer {token}"}
    return request


def _token(key: rsa.RSAPrivateKey, aud: str = "account", **claims: object) -> str:
    return jwt.encode({"sub": "test-user", "aud": aud, **claims}, key, algorithm="RS256")


@pytest.fixture(autouse=True)
def mock_jwks() -> Generator[mock.MagicMock, None, None]:
    with mock.patch.object(utils, "_jwks_client") as mock_client:
        mock_client.return_value.get_signing_key_from_jwt.return_value = types.SimpleNamespace(
            key=PRIVATE_KEY.public_key()
        )
        yield mock_client


# Mock the logger to avoid unnecessary logging during tests
@mock.patch("ades_fastapi.utils.logger")
def test_get_path_params(mock_logger: mock.MagicMock) -> None:
    request = mock.Mock(spec=Request)
    request.scope = {"path_params": {"key": "value"}}
    result = get_path_params(request)
    assert result == {"key": "value"}
    mock_logger.debug.assert_called_once_with("CALCULATING PATH PARAMETERS")


@mock.patch("ades_fastapi.utils.requests.post")
@mock.patch("ades_fastapi.utils.logger")
def test_opa_request(mock_logger: mock.MagicMock, mock_post: mock.MagicMock) -> None:
    input_data = {"key": "value"}
    opa_service_endpoint = "http://opa-service"

    mock_response = mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"result": True}
    mock_post.return_value = mock_response

    response = opa_request(input_data, opa_service_endpoint)

    assert response.status_code == 200
    assert response.json() == {"result": True}
    mock_logger.debug.assert_called_once_with("Sending request to OPA service with input: %s", input_data)
    mock_post.assert_called_once_with(opa_service_endpoint, json=input_data)


def test_get_user_details() -> None:
    token = _token(
        PRIVATE_KEY,
        preferred_username="username",
        workspace="my-workspace",
        workspaces=["my-workspace", "another-workspace"],
        realm_access={"roles": ["role1", "role2"]},
    )
    request = _request_with_token(token)

    username, workspace, workspaces, roles = get_user_details(request)

    assert username == "username"
    assert workspace == "my-workspace"
    assert workspaces == ["my-workspace", "another-workspace"]
    assert roles == ["role1", "role2"]


def test_get_user_details_no_token() -> None:
    request = mock.Mock(spec=Request)
    request.headers = {}

    username, workspace, workspaces, roles = get_user_details(request)

    assert username == ""
    assert workspace == ""
    assert workspaces == []
    assert roles == []


def test_get_user_details_forged_signature_is_rejected() -> None:
    """This is the exact bug that shipped: verify_signature was False, so any signature -
    including one that is not cryptographically valid at all - was accepted.
    """
    header = jwt.utils.base64url_encode(b'{"alg":"RS256","typ":"JWT"}').decode()
    payload = jwt.utils.base64url_encode(
        b'{"sub":"attacker","workspaces":["someone-elses-workspace"],"aud":"account"}'
    ).decode()
    forged_signature = jwt.utils.base64url_encode(b"not-a-real-signature").decode()
    forged_token = f"{header}.{payload}.{forged_signature}"
    request = _request_with_token(forged_token)

    with pytest.raises(HTTPException) as raised:
        get_user_details(request)

    assert raised.value.status_code == 401


def test_get_user_details_token_signed_by_a_different_key_is_rejected() -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _token(other_key)
    request = _request_with_token(token)

    with pytest.raises(HTTPException) as raised:
        get_user_details(request)

    assert raised.value.status_code == 401


def test_get_user_details_wrong_audience_is_rejected() -> None:
    token = _token(PRIVATE_KEY, aud="some-other-client")
    request = _request_with_token(token)

    with pytest.raises(HTTPException) as raised:
        get_user_details(request)

    assert raised.value.status_code == 401


@mock.patch("ades_fastapi.utils.boto3.client")
@mock.patch("ades_fastapi.utils.logger")
def test_get_access_policy(mock_logger: mock.MagicMock, mock_boto3_client: mock.MagicMock) -> None:
    mock_s3_client = mock.Mock()
    mock_boto3_client.return_value = mock_s3_client

    mock_s3_client.get_object.return_value = {
        "Body": mock.Mock(read=mock.Mock(return_value=json.dumps({"public": True}).encode("utf-8")))
    }

    ades_policy_bucket = "test-bucket"
    ades_policy_prefix = "test-prefix"
    deploy_workspace = "test-workspace"
    workflow_id = "test_workflow"

    result = get_access_policy(deploy_workspace, workflow_id, ades_policy_bucket, ades_policy_prefix)

    assert result == {"public": True}
    mock_s3_client.get_object.assert_called_once_with(
        Bucket=ades_policy_bucket,
        Key=f"{ades_policy_prefix}/{deploy_workspace}/{workflow_id}.access-policy.json",
    )

    # Test for NoSuchKey error
    mock_s3_client.get_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "NoSuchKey"}}, "get_object"
    )

    result = get_access_policy(deploy_workspace, workflow_id, ades_policy_bucket, ades_policy_prefix)
    assert result is None
    mock_logger.warning.assert_any_call(
        "No access policy found for workflow %s in workspace %s",
        workflow_id,
        deploy_workspace,
    )

    # Test for other ClientError
    mock_s3_client.get_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "SomeOtherError"}}, "get_object"
    )

    result = get_access_policy(deploy_workspace, workflow_id, ades_policy_bucket, ades_policy_prefix)
    assert result is None
    mock_logger.error.assert_any_call(
        "Error getting access policy for workflow %s in workspace %s",
        workflow_id,
        deploy_workspace,
    )


@mock.patch("ades_fastapi.utils.boto3.client")
@mock.patch("ades_fastapi.utils.logger")
def test_get_access_policy_json_decode_error(mock_logger: mock.MagicMock, mock_boto3_client: mock.MagicMock) -> None:
    mock_s3_client = mock.Mock()
    mock_boto3_client.return_value = mock_s3_client

    mock_s3_client.get_object.return_value = {"Body": mock.Mock(read=mock.Mock(return_value=b"invalid json"))}

    ades_policy_bucket = "test-bucket"
    ades_policy_prefix = "test-prefix"
    deploy_workspace = "test-workspace"
    workflow_id = "test_workflow"

    result = get_access_policy(deploy_workspace, workflow_id, ades_policy_bucket, ades_policy_prefix)

    assert result is None
    mock_logger.error.assert_any_call(
        "Error decoding access policy JSON: %s",
        mock.ANY,
    )


def test_convert_workspace_to_username() -> None:
    assert convert_workspace_to_username("test_workspace") == "test-workspace"


def test_convert_username_to_workspace() -> None:
    assert convert_username_to_workspace("test-username") == "test_username"
    assert convert_username_to_workspace("") == ""


def test_replace_href_links() -> None:
    content_dict = {
        "links": [
            {"href": "http://localhost:8080/test-workspace/ogc-api/extra/path/test1"},
            {"href": "http://localhost:8080/test-workspace/ogc-api/extra/path/test2"},
        ]
    }
    ades_ingress_path = "http://ades-ingress/path"
    result = replace_href_links(content_dict, ades_ingress_path, "user", "test-workspace")
    assert (
        result["links"][0]["href"] == "http://ades-ingress/path/catalogs/user/catalogs/test-workspace/extra/path/test1"
    )
    assert (
        result["links"][1]["href"] == "http://ades-ingress/path/catalogs/user/catalogs/test-workspace/extra/path/test2"
    )


@mock.patch("ades_fastapi.utils.requests.get")
def test_get_workflow_id_from_url(mock_get: mock.MagicMock) -> None:
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
def test_get_workflow_id_from_url_illegal_input(mock_get: mock.MagicMock) -> None:
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
def test_get_workflow_id_from_url_missing_workflow(mock_get: mock.MagicMock) -> None:
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
def test_get_workflow_id_from_url_not_yaml(mock_get: mock.MagicMock) -> None:
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


def test_get_workflow_id_from_file_missing_workflow() -> None:
    cwl_str = """
    $graph:
      - class: CommandLineTool
        id: test_workflow_id
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "No Workflow found in CWL file"
    assert not success


def test_get_workflow_id_from_file() -> None:
    cwl_str = """
    $graph:
      - class: Workflow
        id: test_workflow_id
        inputs:
            input1:
                type: string
            input2:
                type: string
        steps:
            step1:
                run: some_tool.cwl
            step2:
                run: another_tool.cwl
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "test_workflow_id"
    assert success


def test_get_workflow_id_from_file_list() -> None:
    cwl_str = """
    $graph:
      - class: Workflow
        id: test_workflow_id
        inputs:
        - id: input1
          type: string
        - id: input2
          type: string
        steps:
        - id: step1
          run: some_tool.cwl
        - id: step2
          run: another_tool.cwl
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "test_workflow_id"
    assert success


def test_get_workflow_id_from_file_illegal_input() -> None:
    cwl_str = """
    $graph:
      - class: Workflow
        id: test_workflow_id
        inputs:
            token:
                type: string
            input2:
                type: string
        steps:
            step1:
                run: some_tool.cwl
            step2:
                run: another_tool.cwl
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "Input token is not allowed in workflow"
    assert not success


def test_get_workflow_id_from_file_illegal_step() -> None:
    cwl_str = """
    $graph:
      - class: Workflow
        id: test_workflow_id
        inputs:
            input1:
                type: string
            input2:
                type: string
        steps:
            node_stage_in-xxx:
                run: some_tool.cwl
            step2:
                run: another_tool.cwl
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "Step node_stage_in-xxx is not allowed in workflow"
    assert not success


def test_get_workflow_id_from_file_list_illegal_input() -> None:
    cwl_str = """
    $graph:
      - class: Workflow
        id: test_workflow_id
        inputs:
        - id: input1
          type: string
        - id: input2
          type: string
        steps:
        - id: step1
          run: some_tool.cwl
        - id: node_stage_out
          run: another_tool.cwl
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "Step node_stage_out is not allowed in workflow"
    assert not success


def test_get_workflow_id_from_file_list_illegal_step() -> None:
    cwl_str = """
    $graph:
      - class: Workflow
        id: test_workflow_id
        inputs:
        - id: token
          type: string
        - id: input2
          type: string
        steps:
        - id: step1
          run: some_tool.cwl
        - id: step2
          run: another_tool.cwl
    """

    success, result = get_workflow_id_from_file(cwl_str)
    assert result == "Input token is not allowed in workflow"
    assert not success


def test_get_workflow_id_from_file_not_yaml() -> None:
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
def test_list_jobs_dict(mock_logger: mock.MagicMock, mock_get: mock.MagicMock) -> None:
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
