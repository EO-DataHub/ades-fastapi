import json
import logging
from enum import Enum

import boto3
import botocore
import jwt
import requests
import yaml
from fastapi import HTTPException, Request

from .job_saver import JobSaver

logger = logging.getLogger(__name__)  # Add this line to define the logger


class WorkflowType(Enum):
    WORKFLOW = "workflow"
    USER_SERVICE = "user-service"
    OTHER = "other"  # not for prod use


def get_path_params(request: Request):
    logger.debug("CALCULATING PATH PARAMETERS")
    return request.scope.get("path_params", {})


def opa_request(input_data: dict, opa_service_endpoint: str) -> requests.Response:
    """Send a request to OPA service"""
    logger.debug("Sending request to OPA service with input: %s", input_data)
    return requests.post(opa_service_endpoint, json=input_data)


def get_user_token(request: Request) -> str:
    """Get user token from the request"""
    token = request.headers.get("authorization", "")
    return token.replace("Bearer ", "")


def get_user_details(request: Request) -> tuple:
    """Get user details from the request"""
    token = request.headers.get("authorization", "")
    stripped_token = token.replace("Bearer ", "")
    if stripped_token:
        credentials = jwt.decode(
            stripped_token,
            options={"verify_signature": False},
            algorithms=["HS256"],
        )
        username = credentials.get("preferred_username", "")
        roles = credentials.get("realm_access", {}).get("roles", [])

    else:
        username = ""
        roles = []
    return username, roles


def get_access_policy(
    deploy_workspace: str, workflow_id: str, ades_policy_bucket: str, ades_policy_prefix: str = None
) -> dict:
    """Get the access policy for a workflow"""
    s3_client = boto3.client("s3")

    if ades_policy_prefix:
        key = f"{ades_policy_prefix}/{deploy_workspace}/{workflow_id}.access-policy.json"
    else:
        key = f"{deploy_workspace}/{workflow_id}.access-policy.json"

    try:
        s3_data = s3_client.get_object(Bucket=ades_policy_bucket, Key=key)
    except botocore.exceptions.ClientError as err:
        if err.response["Error"]["Code"] == "NoSuchKey":
            logger.info(
                "No access policy found for workflow %s in workspace %s",
                workflow_id,
                deploy_workspace,
            )
            return None
        else:
            logger.info(
                "Error getting access policy for workflow %s in workspace %s",
                workflow_id,
                deploy_workspace,
            )
            return None
    return json.loads(s3_data.get("Body").read().decode("utf-8"))


def convert_workspace_to_username(workspace: str) -> str:
    return workspace.replace("_", "-")


def convert_username_to_workspace(username: str) -> str:
    if not username:
        return ""
    return username.replace("-", "_")


def replace_href_links(content_dict: dict, ades_ingress_path: str) -> dict:
    """Replace href links in the JSON response"""
    if "links" in content_dict:
        for link in content_dict["links"]:
            link["href"] = link["href"].replace("http://localhost:8080", ades_ingress_path)
    return content_dict


def get_workflow_id_from_file(data: str) -> tuple:
    try:
        cwl_dict = yaml.safe_load(data)
    except yaml.YAMLError:
        logger.error("Error decoding CWL file")
        return False, "Error decoding CWL file as YAML"
    if not isinstance(cwl_dict, dict):
        return False, "CWL file is not valid YAML, was it passed in correctly?"
    if "$graph" not in cwl_dict:
        return False, "No '$graph' found in CWL"
    for item in cwl_dict["$graph"]:
        if item.get("class") == "Workflow":
            return True, item["id"]
    return False, "No Workflow found in CWL file"


def get_workflow_id_from_url(url: str) -> tuple:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    response = requests.get(url, headers=headers)
    try:
        cwl_dict = yaml.safe_load(response.text)
    except yaml.YAMLError:
        logger.error("Error decoding CWL file")
        logger.error(response.text)
        return False, "Error decoding CWL file as YAML"
    if not isinstance(cwl_dict, dict):
        return False, "CWL file is not valid YAML"
    if "$graph" not in cwl_dict:
        return False, "No '$graph' found in CWL"
    for item in cwl_dict["$graph"]:
        if item.get("class") == "Workflow":
            return True, item["id"]
    return False, "No Workflow found in CWL file"


def list_jobs_dict(deploy_workspace: str, request: Request, ades_service_endpoint: str) -> dict:
    """Local function to list all jobs in a workspace, returned as a dictionary"""
    logger.debug("Listing jobs in workspace %s", deploy_workspace)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ades_service_endpoint}/{deploy_workspace}/ogc-api/jobs", headers=headers
    )

    return response.json()


def configure_request(
    body: dict, token: str, calling_workspace: str, executing_workspace: str = None
):
    # Add calling workspace to body
    logger.info("Setting calling workspace to %s", calling_workspace)
    try:
        body["inputs"].update({"calling_workspace": calling_workspace})
        logger.info(
            "Setting executing workspace to %s",
            executing_workspace if executing_workspace else calling_workspace,
        )
        body["inputs"].update(
            {
                "executing_workspace": (
                    executing_workspace if executing_workspace else calling_workspace
                )
            }
        )
        # Add user token to body
        logger.info("Setting user token in execution call")
        body["inputs"].update({"user_token": token})
    except KeyError as e:
        logger.error("KeyError: %s", e)
        raise HTTPException(status_code=400, detail="Invalid input payload") from e


async def execute_user_service(
    request: requests.Request,
    deployed_workspace: str,
    base_url: str,
    service_url: str,
    workflow_id: str,
    job_saver: JobSaver,
) -> requests.Response:
    calling_workspace, _ = get_user_details(request)
    token = get_user_token(request)
    body = await request.json()
    configure_request(body, token, calling_workspace, deployed_workspace)
    response = send_execute_to_ades(service_url, deployed_workspace, workflow_id, body)
    # Record the calling workspace for the generated jobID
    if response.status_code == 201:
        job_saver.record_owner(response, deployed_workspace, calling_workspace)
        try:
            content_json = replace_href_links(response.json(), base_url)
            content = json.dumps(content_json, indent=2)
        except json.JSONDecodeError:
            content = response.text

        if "Location" in response.headers:
            response.headers["Location"] = response.headers["Location"].replace(
                "http://localhost:8080", base_url
            )
    else:
        content = response.text
    return response, content


async def execute_workflow(
    request: requests.Request,
    deployed_workspace: str,
    service_url: str,
    base_url: str,
    workflow_id: str,
    job_saver: JobSaver,
) -> requests.Response:
    calling_workspace, _ = get_user_details(request)
    token = get_user_token(request)
    body = await request.json()
    configure_request(body, token, calling_workspace)
    response = send_execute_to_ades(service_url, deployed_workspace, workflow_id, body)
    # Record the calling workspace for the generated jobID
    if response.status_code == 201:
        job_saver.record_owner(response, deployed_workspace, calling_workspace)
        try:
            content_json = replace_href_links(response.json(), base_url)
            content = json.dumps(content_json, indent=2)
        except json.JSONDecodeError:
            content = response.text

        if "Location" in response.headers:
            response.headers["Location"] = response.headers["Location"].replace(
                "http://localhost:8080", base_url
            )
    else:
        content = response.text
    return response, content


def send_execute_to_ades(
    service_url: str, deploy_workspace: str, workflow_id: str, body: dict
) -> requests.Response:
    headers = {
        "Prefer": "respond-async",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    response = requests.post(
        f"{service_url}/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution",
        headers=headers,
        json=body,
    )

    return response
