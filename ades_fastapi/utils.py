import json
import logging
import os
from enum import Enum

import boto3
import botocore
import jwt
import requests
import yaml
from fastapi import Request

logger = logging.getLogger(__name__)  # Add this line to define the logger

ILLEGAL_WORKFLOW_INPUTS_RAW = os.getenv("ILLEGAL_WORKFLOW_INPUTS", "token").split(",")
ILLEGAL_WORKFLOW_INPUTS = [input.strip() for input in ILLEGAL_WORKFLOW_INPUTS_RAW]


class WorkflowType(Enum):
    DEFAULT = "default"
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
    logger.debug("Token: %s", stripped_token)
    if stripped_token:
        credentials = jwt.decode(
            stripped_token,
            options={"verify_signature": False},
            algorithms=["HS256"],
        )
        logger.debug("Credentials: ", credentials)
        username = credentials.get("preferred_username", "")
        workspace = credentials.get("workspace", "")
        roles = credentials.get("realm_access", {}).get("roles", [])
    else:
        username = ""
        workspace = ""
        roles = []
    return username, workspace, roles


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


def replace_href_link(link: str, base_url: str, catalog_root: str, workspace: str) -> str:
    """Replace href links in the JSON response"""
    replace_prefix = f"http://localhost:8080/{workspace}/ogc-api"
    new_prefix = f"{base_url}/catalogs/{catalog_root}/catalogs/{workspace}"
    return link.replace(replace_prefix, new_prefix, 1)


def replace_href_links(
    content_dict: dict, base_url: str, catalog_root: str, workspace: str
) -> dict:
    """Replace href links in the JSON response"""
    if "links" in content_dict:
        for link in content_dict["links"]:
            old_link = link["href"]
            new_link = replace_href_link(old_link, base_url, catalog_root, workspace)
            link["href"] = new_link
    return content_dict


def check_workflow_inputs(data: dict) -> tuple:
    inputs = data.get("inputs", {})
    if isinstance(inputs, list):
        for input in inputs:
            if input["id"] in ILLEGAL_WORKFLOW_INPUTS:
                return False, f"Input {input['id']} is not allowed in workflow"
    elif isinstance(inputs, dict):
        for key, _ in inputs.items():
            if key in ILLEGAL_WORKFLOW_INPUTS:
                return False, f"Input {key} is not allowed in workflow"
    return True, data["id"]


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
            success, details = check_workflow_inputs(item)
            return success, details
    return False, "No Workflow found in CWL file"


def get_workflow_id_from_url(url: str) -> tuple:
    # Need to mimic browser headers to get around some sites blocking requests
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
            success, details = check_workflow_inputs(item)
            return success, details
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
