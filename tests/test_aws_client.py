import copy
import os
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import pytest
import requests_mock

from ades_fastapi.aws_client import (
    generate_aws_credentials,
    generate_token,
    get_credentials,
)

ROLE_ARN_WORKSPACE = os.environ.get("AWS_ROLE_ARN_WORKSPACE", "role-arn-workspace")
ROLE_ARN_SERVICE = os.environ.get("AWS_ROLE_ARN_USER_SERVICE", "role-arn-service")
KEYCLOAK_BASE_URL = os.environ.get("KEYCLOAK_BASE_URL", "example/keycloak/realms/test")
CLIENT_ID = os.environ.get("CLIENT_ID", "client-id")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "client-secret")


@patch("ades_fastapi.aws_client.get_credentials")
@patch("ades_fastapi.aws_client.generate_token")
def test_generate_aws_credentials_user_service(mock_generate_token, mock_get_credentials):
    # Configure mocks
    def side_effect(
        role_arn, token, workspace, creds_dict, key, workflow_id, username, service_scope
    ):
        creds_dict = copy.deepcopy(creds_dict)
        if key == "calling_workspace":
            creds_dict[key]["aws_creds"] = {"key": "value-calling"}
        else:
            creds_dict[key]["aws_creds"] = {"key": "value-executing"}
        return creds_dict

    def get_ades_token(token, workspace, scope):
        if "user_services" in scope:
            return "longer-lasting-token-executing"
        return "longer-lasting-token-calling"

    mock_get_credentials.side_effect = side_effect
    mock_generate_token.side_effect = get_ades_token

    token = "valid-token"
    username = "username"
    calling_workspace = "calling_workspace"
    executing_workspace = "executing_workspace"

    result = generate_aws_credentials(
        token, username, calling_workspace, executing_workspace, "workflow-id"
    )

    assert result == {
        "calling_workspace": {
            "aws_creds": {},
            "api_token": "longer-lasting-token-calling",
        },
        "executing_workspace": {
            "aws_creds": {"key": "value-executing"},
            "api_token": "longer-lasting-token-executing",
        },
    }

    assert mock_get_credentials.call_count == 1

    mock_get_credentials.assert_any_call(
        "role-arn-service",
        token,
        executing_workspace,
        {
            "calling_workspace": {
                "aws_creds": {},
                "api_token": "longer-lasting-token-calling",
            },
            "executing_workspace": {"aws_creds": {}, "api_token": "longer-lasting-token-executing"},
        },
        "executing_workspace",
        "workflow-id",
        username=username,
        service_scope=True,
    )


@patch("ades_fastapi.aws_client.generate_token")
@patch("ades_fastapi.aws_client.get_credentials")
def test_generate_aws_credentials_workflow(mock_get_credentials, mock_generate_token):
    # Configure mocks
    def side_effect(
        role_arn, token, workspace, creds_dict, key, workflow_id, username, service_scope
    ):
        creds_dict = copy.deepcopy(creds_dict)
        if key == "calling_workspace":
            creds_dict[key]["aws_creds"] = {"key": "value-calling"}
        else:
            creds_dict[key]["aws_creds"] = {"key": "value-executing"}
        return creds_dict

    def get_ades_token(token, workspace, scope):
        if "user_services" in scope:
            return "longer-lasting-token-executing"
        return "longer-lasting-token-calling"

    mock_get_credentials.side_effect = side_effect
    mock_generate_token.side_effect = get_ades_token

    token = "valid-token"
    username = "username"
    calling_workspace = "calling_workspace"
    executing_workspace = "calling_workspace"

    result = generate_aws_credentials(
        token, username, calling_workspace, executing_workspace, "workflow-id"
    )

    assert result == {
        "calling_workspace": {
            "aws_creds": {},
            "api_token": "longer-lasting-token-calling",
        },
        "executing_workspace": {
            "aws_creds": {"key": "value-executing"},
            "api_token": "longer-lasting-token-calling",
        },
    }

    assert mock_get_credentials.call_count == 1

    mock_get_credentials.assert_any_call(
        ROLE_ARN_SERVICE,
        token,
        calling_workspace,
        {
            "calling_workspace": {
                "aws_creds": {},
                "api_token": "longer-lasting-token-calling",
            },
            "executing_workspace": {"aws_creds": {}, "api_token": "longer-lasting-token-calling"},
        },
        "executing_workspace",
        "workflow-id",
        username=username,
        service_scope=True,
    )


@patch("ades_fastapi.aws_client.generate_token")
@patch("boto3.client")
def test_get_credentials_workflow(mock_boto_client, mock_generate_token):
    mock_sts_instance = MagicMock()
    mock_sts_instance.assume_role_with_web_identity.return_value = {"Credentials": {"key": "value"}}
    mock_boto_client.return_value = mock_sts_instance

    creds_dict = {
        "calling_workspace": {"aws_creds": {}, "api_token": "some-token"},
        "executing_workspace": {"aws_creds": {}, "api_token": "some-token"},
    }

    result = get_credentials(
        role_arn="role_arn",
        token="valid-token",
        workspace="workspace",
        creds_dict=creds_dict,
        key="calling_workspace",
        workflow_id="workflow-id",
        username="username",
        service_scope=False,
    )

    assert result == {
        "calling_workspace": {"aws_creds": {"key": "value"}, "api_token": "some-token"},
        "executing_workspace": {"aws_creds": {}, "api_token": "some-token"},
    }
    mock_generate_token.assert_not_called()
    mock_sts_instance.assume_role_with_web_identity.assert_called_once_with(
        RoleArn="role_arn",
        RoleSessionName="workspace-username-workflow-id",
        WebIdentityToken="valid-token",
        DurationSeconds=43200,
    )


@patch("ades_fastapi.aws_client.generate_token")
@patch("boto3.client")
def test_get_credentials_workflow_invalid_token(mock_boto_client, mock_generate_token):
    mock_sts_instance = MagicMock()
    mock_sts_instance.assume_role_with_web_identity.side_effect = Exception("Invalid token")
    mock_boto_client.return_value = mock_sts_instance

    creds_dict = {
        "calling_workspace": {"aws_creds": {}, "api_token": "some-token"},
        "executing_workspace": {"aws_creds": {}, "api_token": "some-token"},
    }

    result = get_credentials(
        role_arn="role_arn",
        token="invalid-token",
        workspace="workspace",
        creds_dict=creds_dict,
        key="calling_workspace",
        workflow_id="workflow-id",
        username="username",
        service_scope=False,
    )

    assert result == {
        "calling_workspace": {"aws_creds": {}, "api_token": "some-token"},
        "executing_workspace": {"aws_creds": {}, "api_token": "some-token"},
    }
    mock_generate_token.assert_not_called()
    mock_sts_instance.assume_role_with_web_identity.assert_called_once_with(
        RoleArn="role_arn",
        RoleSessionName="workspace-username-workflow-id",
        WebIdentityToken="invalid-token",
        DurationSeconds=43200,
    )


@patch("ades_fastapi.aws_client.generate_token")
@patch("boto3.client")
def test_get_credentials_user_service(mock_boto_client, mock_generate_token):
    mock_sts_instance = MagicMock()
    mock_sts_instance.assume_role_with_web_identity.return_value = {"Credentials": {"key": "value"}}
    mock_boto_client.return_value = mock_sts_instance
    mock_generate_token.return_value = "valid-token"

    creds_dict = {
        "calling_workspace": {"aws_creds": {}, "api_token": "some-token"},
        "executing_workspace": {"aws_creds": {}, "api_token": "some-token"},
    }

    result = get_credentials(
        role_arn="role_arn",
        token="initial-token",
        workspace="workspace",
        creds_dict=creds_dict,
        key="executing_workspace",
        workflow_id="workflow-id",
        username="username",
        service_scope=True,
    )

    assert result == {
        "calling_workspace": {"aws_creds": {}, "api_token": "some-token"},
        "executing_workspace": {"aws_creds": {"key": "value"}, "api_token": "some-token"},
    }
    mock_generate_token.assert_called_once_with(
        "initial-token", "workspace", "user_services:workspace"
    )
    mock_sts_instance.assume_role_with_web_identity.assert_called_once_with(
        RoleArn="role_arn",
        RoleSessionName="workspace-username-workflow-id",
        WebIdentityToken="valid-token",
        DurationSeconds=43200,
    )


@patch("ades_fastapi.aws_client.generate_token")
@patch("boto3.client")
def test_get_credentials_user_service_invalid_token(mock_boto_client, mock_generate_token):
    mock_sts_instance = MagicMock()
    mock_sts_instance.assume_role_with_web_identity.side_effect = Exception("Invalid token")
    mock_boto_client.return_value = mock_sts_instance
    mock_generate_token.return_value = "invalid-token"

    creds_dict = {
        "calling_workspace": {"aws_creds": {}, "api_token": "some-token"},
        "executing_workspace": {"aws_creds": {}, "api_token": "some-token"},
    }

    result = get_credentials(
        role_arn="role_arn",
        token="initial-token",
        workspace="workspace",
        creds_dict=creds_dict,
        key="executing_workspace",
        workflow_id="workflow-id",
        username="username",
        service_scope=True,
    )

    assert result == {
        "calling_workspace": {"aws_creds": {}, "api_token": "some-token"},
        "executing_workspace": {"aws_creds": {}, "api_token": "some-token"},
    }
    mock_generate_token.assert_called_once_with(
        "initial-token", "workspace", "user_services:workspace"
    )
    mock_sts_instance.assume_role_with_web_identity.assert_called_once_with(
        RoleArn="role_arn",
        RoleSessionName="workspace-username-workflow-id",
        WebIdentityToken="invalid-token",
        DurationSeconds=43200,
    )


def test_generate_token_workflow():
    # Configure mocks
    keycloak_url = "https://example/keycloak/realms/test/protocol/openid-connect/token"
    token = "valid-token"
    workspace = "workspace"
    scope = "workspace:workspace"

    expected_payload = {
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "grant_type": ["urn:ietf:params:oauth:grant-type:token-exchange"],
        "subject_token": [token],
        "scope": [scope],
    }

    with requests_mock.Mocker() as m:
        m.post(
            keycloak_url, status_code=200, json=lambda a, b: {"access_token": "new-access-token"}
        )
        result = generate_token(token, workspace, scope)
        last_request = m.last_request

        assert parse_qs(last_request.text) == expected_payload
        assert last_request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert result == "new-access-token"


def test_generate_token_user_service():
    # Configure mocks
    keycloak_url = "https://example/keycloak/realms/test/protocol/openid-connect/token"
    token = "valid-token"
    workspace = "workspace"
    scope = "user_service:workspace"

    expected_payload = {
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "grant_type": ["urn:ietf:params:oauth:grant-type:token-exchange"],
        "subject_token": [token],
        "scope": [scope],
    }

    with requests_mock.Mocker() as m:
        m.post(
            keycloak_url, status_code=200, json=lambda a, b: {"access_token": "new-access-token"}
        )
        result = generate_token(token, workspace, scope)
        last_request = m.last_request

        assert parse_qs(last_request.text) == expected_payload
        assert last_request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert result == "new-access-token"


def test_generate_token_error():
    # Configure mocks
    keycloak_url = "https://example/keycloak/realms/test/protocol/openid-connect/token"
    token = "valid-token"
    workspace = "workspace"
    scope = "workspace:workspace"

    expected_payload = {
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "grant_type": ["urn:ietf:params:oauth:grant-type:token-exchange"],
        "subject_token": [token],
        "scope": [scope],
    }

    with requests_mock.Mocker() as m:
        m.post(keycloak_url, status_code=500, text="An error was raised")
        with pytest.raises(ValueError):
            generate_token(token, workspace, scope)

        last_request = m.last_request

        assert parse_qs(last_request.text) == expected_payload
        assert last_request.headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_generate_token_blank_token():
    # Configure mocks
    keycloak_url = "https://example/keycloak/realms/test/protocol/openid-connect/token"
    token = "valid-token"
    workspace = "workspace"
    scope = "workspace:workspace"

    expected_payload = {
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "grant_type": ["urn:ietf:params:oauth:grant-type:token-exchange"],
        "subject_token": [token],
        "scope": [scope],
    }

    with requests_mock.Mocker() as m:
        m.post(keycloak_url, status_code=200, json=lambda a, b: {"access_token": None})
        with pytest.raises(ValueError):
            generate_token(token, workspace, scope)

        last_request = m.last_request

        assert parse_qs(last_request.text) == expected_payload
        assert last_request.headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_generate_token_missing_token():
    # Configure mocks
    keycloak_url = "https://example/keycloak/realms/test/protocol/openid-connect/token"
    token = "valid-token"
    workspace = "workspace"
    scope = "workspace:workspace"

    expected_payload = {
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "grant_type": ["urn:ietf:params:oauth:grant-type:token-exchange"],
        "subject_token": [token],
        "scope": [scope],
    }

    with requests_mock.Mocker() as m:
        m.post(keycloak_url, status_code=200, json=lambda a, b: {"another-token": "value"})
        with pytest.raises(ValueError):
            generate_token(token, workspace, scope)

        last_request = m.last_request

        assert parse_qs(last_request.text) == expected_payload
        assert last_request.headers["Content-Type"] == "application/x-www-form-urlencoded"
