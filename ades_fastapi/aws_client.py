import copy
import logging
import os

import boto3
import requests

logger = logging.getLogger(__name__)  # Add this line to define the logger

ROLE_ARN_WORKSPACE = os.environ.get("AWS_ROLE_ARN_WORKSPACE", "role-arn-workspace")
ROLE_ARN_SERVICE = os.environ.get("AWS_ROLE_ARN_USER_SERVICE", "role-arn-service")
KEYCLOAK_BASE_URL = os.environ.get("KEYCLOAK_BASE_URL", "example/keycloak/realms/test")
CLIENT_ID = os.environ.get("CLIENT_ID", "client-id")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "client-secret")

KEYCLOAK_URL = f"https://{KEYCLOAK_BASE_URL}/protocol/openid-connect/token"


def generate_token(token: str, workspace: str, scope: str) -> str:

    logger.info("Generating token for workspace %s and scope %s", workspace, scope)

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": token,
        "scope": scope,
    }

    response = requests.post(
        KEYCLOAK_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != 200:
        logger.error("Failed to generate workspace token: %s", response.text)
        raise ValueError(f"Failed to generate workspace token: {response.text}")

    try:
        access_token = response.json().get("access_token")
        logger.info("Access token generated successfully for scope %s", scope)
    except Exception as e:
        logger.error("Failed to generate workspace token: %s", e)
        logger.error("Response was %s with status code: %s", response.text, response.status_code)
        raise ValueError(f"Failed to generate workspace token: {response.text}") from e

    if not access_token:
        logger.error("Failed to generate workspace token, token is None: %s", response.text)
        raise ValueError(f"Failed to generate workspace token: {response.text}")

    return access_token


def get_credentials(
    role_arn: str,
    token: str,
    workspace: str,
    creds_dict: dict,
    key: str,
    workflow_id: str,
    username: str,
    service_scope: bool = False,
) -> dict:

    # Generate AWS credentials
    sts_client = boto3.client("sts")

    # copy inpit dict
    creds_dict = copy.deepcopy(creds_dict)

    if service_scope:
        session_name = f"{workspace}-{username}-{workflow_id}"
        scope = f"user_services:{workspace}"
        workspace_token = generate_token(token, workspace, scope)
    else:
        # Input token is already scoped to workspace
        session_name = f"{workspace}-{username}-{workflow_id}"
        workspace_token = token

    # Limit session name to 64 characters
    if len(session_name) > 64:
        session_name = session_name[:64]

    logger.info("Assuming role %s with session name %s", role_arn, session_name)
    logger.info("Workspace token: %s", workspace_token)

    duration_seconds = 43200

    logger.debug("Assuming role for %s duration seconds", duration_seconds)

    try:
        role = sts_client.assume_role_with_web_identity(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            WebIdentityToken=workspace_token,
            DurationSeconds=duration_seconds,
        )
        creds_dict[key]["aws_creds"] = role["Credentials"]
    except Exception as e:
        logger.error("Failed to assume role: %s", e)
        workspace_type = "executing" if service_scope else "calling"
        logger.error("Failed to get AWS credentials for %s workspace %s", workspace_type, workspace)
        creds_dict[key]["aws_creds"] = {}

    return creds_dict


def generate_aws_credentials(
    token: str,
    username: str,
    calling_workspace: str,
    executing_workspace: str,
    workflow_id: str,
) -> dict:

    creds_dict = {
        "calling_workspace": {
            "aws_creds": {},
            "api_token": generate_token(token, calling_workspace, f"workspace:{calling_workspace}"),
        },
        "executing_workspace": {
            "aws_creds": {},
            "api_token": generate_token(
                token,
                executing_workspace,
                (
                    f"user_services:{executing_workspace}"
                    if calling_workspace != executing_workspace
                    else f"workspace:{executing_workspace}"
                ),
            ),
        },
    }

    logger.info(f"Incoming token is {token}")

    # Generate credentials for calling workspace
    creds_dict = get_credentials(
        ROLE_ARN_WORKSPACE,
        token,
        calling_workspace,
        creds_dict,
        "calling_workspace",
        workflow_id,
        username=username,
        service_scope=False,
    )

    # Generate credentials for executing workspace
    creds_dict = get_credentials(
        ROLE_ARN_SERVICE,
        token,
        executing_workspace,
        creds_dict,
        "executing_workspace",
        workflow_id,
        username=username,
        service_scope=True,
    )

    return creds_dict
