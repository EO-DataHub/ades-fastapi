import copy
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import pytest
import requests_mock

from ades_fastapi.aws_client import (
    generate_aws_credentials,
    generate_token,
    get_credentials,
)


@patch("ades_fastapi.aws_client.get_credentials")
def test_generate_aws_credentials_user_service(mock_get_credentials):
    # Configure mocks
    def side_effect(role_arn, token, workspace, creds_dict, key, service_scope):
        creds_dict = copy.deepcopy(creds_dict)
        creds_dict[key] = {"key": "value"}
        return creds_dict

    mock_get_credentials.side_effect = side_effect

    token = "valid-token"
    calling_workspace = "calling_workspace"
    executing_workspace = "executing_workspace"

    result = generate_aws_credentials(token, calling_workspace, executing_workspace)

    assert result == {
        "calling_workspace": {"key": "value"},
        "executing_workspace": {"key": "value"},
    }

    assert mock_get_credentials.call_count == 2

    mock_get_credentials.assert_any_call(
        "role-arn-workspace",
        token,
        calling_workspace,
        {"calling_workspace": {}, "executing_workspace": {}},
        "calling_workspace",
        False,
    )
    mock_get_credentials.assert_any_call(
        "role-arn-service",
        token,
        executing_workspace,
        {"calling_workspace": {"key": "value"}, "executing_workspace": {}},
        "executing_workspace",
        True,
    )


@patch("ades_fastapi.aws_client.get_credentials")
def test_generate_aws_credentials_workflow(mock_get_credentials):
    # Configure mocks
    def side_effect(role_arn, token, workspace, creds_dict, key, service_scope):
        creds_dict = copy.deepcopy(creds_dict)
        creds_dict[key] = {"key": "value"}
        return creds_dict

    mock_get_credentials.side_effect = side_effect

    token = "valid-token"
    calling_workspace = "calling_workspace"
    executing_workspace = "calling_workspace"

    result = generate_aws_credentials(token, calling_workspace, executing_workspace)

    assert result == {"calling_workspace": {"key": "value"}, "executing_workspace": {}}

    assert mock_get_credentials.call_count == 1

    mock_get_credentials.assert_called_once_with(
        "role-arn-workspace",
        token,
        calling_workspace,
        {"calling_workspace": {}, "executing_workspace": {}},
        "calling_workspace",
        False,
    )


@patch("ades_fastapi.aws_client.generate_token")
@patch("boto3.client")
def test_get_credentials_workflow(mock_boto_client, mock_generate_token):
    mock_sts_instance = MagicMock()
    mock_sts_instance.assume_role_with_web_identity.return_value = {"Credentials": {"key": "value"}}
    mock_boto_client.return_value = mock_sts_instance
    mock_generate_token.return_value = "valid-token"

    creds_dict = {"calling_workspace": {}, "executing_workspace": {}}

    result = get_credentials(
        role_arn="role_arn",
        token="initial-token",
        workspace="workspace",
        creds_dict=creds_dict,
        key="calling_workspace",
        service_scope=False,
    )

    assert result == {"calling_workspace": {"key": "value"}, "executing_workspace": {}}
    mock_generate_token.assert_called_once_with("initial-token", "workspace", "workspace:workspace")
    mock_sts_instance.assume_role_with_web_identity.assert_called_once_with(
        RoleArn="role_arn",
        RoleSessionName="calling_workspace_session",
        WebIdentityToken="valid-token",
    )


@patch("ades_fastapi.aws_client.generate_token")
@patch("boto3.client")
def test_get_credentials_workflow_invalid_token(mock_boto_client, mock_generate_token):
    mock_sts_instance = MagicMock()
    mock_sts_instance.assume_role_with_web_identity.side_effect = Exception("Invalid token")
    mock_boto_client.return_value = mock_sts_instance
    mock_generate_token.return_value = "invalid-token"

    creds_dict = {"calling_workspace": {}, "executing_workspace": {}}

    result = get_credentials(
        role_arn="role_arn",
        token="initial-token",
        workspace="workspace",
        creds_dict=creds_dict,
        key="calling_workspace",
        service_scope=False,
    )

    assert result == {"calling_workspace": None, "executing_workspace": {}}
    mock_generate_token.assert_called_once_with("initial-token", "workspace", "workspace:workspace")
    mock_sts_instance.assume_role_with_web_identity.assert_called_once_with(
        RoleArn="role_arn",
        RoleSessionName="calling_workspace_session",
        WebIdentityToken="invalid-token",
    )


@patch("ades_fastapi.aws_client.generate_token")
@patch("boto3.client")
def test_get_credentials_user_service(mock_boto_client, mock_generate_token):
    mock_sts_instance = MagicMock()
    mock_sts_instance.assume_role_with_web_identity.return_value = {"Credentials": {"key": "value"}}
    mock_boto_client.return_value = mock_sts_instance
    mock_generate_token.return_value = "valid-token"

    creds_dict = {"calling_workspace": {}, "executing_workspace": {}}

    result = get_credentials(
        role_arn="role_arn",
        token="initial-token",
        workspace="workspace",
        creds_dict=creds_dict,
        key="executing_workspace",
        service_scope=True,
    )

    assert result == {"calling_workspace": {}, "executing_workspace": {"key": "value"}}
    mock_generate_token.assert_called_once_with(
        "initial-token", "workspace", "user_services:workspace"
    )
    mock_sts_instance.assume_role_with_web_identity.assert_called_once_with(
        RoleArn="role_arn",
        RoleSessionName="executing_workspace_session",
        WebIdentityToken="valid-token",
    )


@patch("ades_fastapi.aws_client.generate_token")
@patch("boto3.client")
def test_get_credentials_user_service_invalid_token(mock_boto_client, mock_generate_token):
    mock_sts_instance = MagicMock()
    mock_sts_instance.assume_role_with_web_identity.side_effect = Exception("Invalid token")
    mock_boto_client.return_value = mock_sts_instance
    mock_generate_token.return_value = "invalid-token"

    creds_dict = {"calling_workspace": {}, "executing_workspace": {}}

    result = get_credentials(
        role_arn="role_arn",
        token="initial-token",
        workspace="workspace",
        creds_dict=creds_dict,
        key="executing_workspace",
        service_scope=True,
    )

    assert result == {"calling_workspace": {}, "executing_workspace": None}
    mock_generate_token.assert_called_once_with(
        "initial-token", "workspace", "user_services:workspace"
    )
    mock_sts_instance.assume_role_with_web_identity.assert_called_once_with(
        RoleArn="role_arn",
        RoleSessionName="executing_workspace_session",
        WebIdentityToken="invalid-token",
    )


def test_generate_token_workflow():
    # Configure mocks
    keycloak_url = "https://keycloak-base-url/realms/realm/protocol/openid-connect/token"
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
    keycloak_url = "https://keycloak-base-url/realms/realm/protocol/openid-connect/token"
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
    keycloak_url = "https://keycloak-base-url/realms/realm/protocol/openid-connect/token"
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
    keycloak_url = "https://keycloak-base-url/realms/realm/protocol/openid-connect/token"
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
    keycloak_url = "https://keycloak-base-url/realms/realm/protocol/openid-connect/token"
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
