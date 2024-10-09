import json
import logging
import time
from json import JSONDecodeError

import boto3
import botocore
import jwt
import requests
import yaml
from fastapi import Depends, HTTPException, Request

logger = logging.getLogger(__name__)  # Add this line to define the logger


def get_path_params(request: Request):
    logger.debug("CALCULATING PATH PARAMETERS")
    return request.scope.get("path_params", {})


def save_data(job_owner_storage_dir: str, job_owners: dict, job_deployed_workspace: dict):
    """Save job owners to files"""
    with open(f"{job_owner_storage_dir}/job-owners.json", "w") as f:
        json.dump(job_owners, f)
    with open(f"{job_owner_storage_dir}/job-workspace-owners.json", "w") as f:
        json.dump(job_deployed_workspace, f)


def opa_request(input_data: dict, opa_service_endpoint: str) -> requests.Response:
    """Send a request to OPA service"""
    logger.debug("Sending request to OPA service with input: %s", input_data)
    return requests.post(opa_service_endpoint, json=input_data)


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

    deploy_workspace = convert_workspace_to_username(deploy_workspace)

    if ades_policy_prefix:
        key = f"{ades_policy_prefix}/{deploy_workspace}/{workflow_id}.access-policy.json"
    else:
        key = f"workflows/{deploy_workspace}/{workflow_id}.access-policy.json"

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


def check_policy(
    request: Request,
    path_params: dict,
    job_deployed_workspace: dict,
    job_owners: dict,
    opa_service_endpoint: str,
    ades_policy_bucket: str,
    ades_policy_prefix: str = None,
) -> bool:
    """Check OPA policy to determine if the request is allowed"""
    username, roles = get_user_details(request)

    # Add values for logs
    logger.info("Logged in as user: %s", username)
    logger.info("Roles: %s", roles)

    input_data = {
        "input": {
            "roles": roles,
            "path": request.url.path,
            "username": username,
            "method": request.method,
        }
    }

    # Log path parameters
    logger.debug("Input parameters from path: %s", path_params)

    # Add values for workflow access
    if (
        request.method in ["POST", "GET"]
        and path_params.get("deploy_workspace")
        and path_params.get("workflow_id")
    ):
        # User is executing or interrogating a workflow
        logger.info("Checking policy for workflow access")
        # Get access policy for workflow
        access_policy = get_access_policy(
            path_params["deploy_workspace"],
            path_params["workflow_id"],
            ades_policy_bucket,
            ades_policy_prefix,
        )
        logger.info("Access policy is: %s", access_policy)
        if access_policy:
            input_data["input"]["is_public"] = access_policy["public"]
            input_data["input"]["allowed_users"] = access_policy["allowed_access"]["users"]
    elif path_params.get("deploy_workspace") and path_params.get("job_id"):
        # User is monitoring a job
        logger.info("Checking job owner for job access")
        # Get executing workspace for the given job
        deploy_workspace = path_params["deploy_workspace"]
        job_id = path_params["job_id"]

        workspace_job_key = f"{deploy_workspace}-{job_id}"

        # Get executing workspace for the given job
        execute_username = job_owners.get(workspace_job_key)

        execute_workspace = convert_username_to_workspace(execute_username)

        input_data["input"]["executing_user"] = execute_workspace
    elif request.method == "POST" and path_params.get("deploy_workspace"):
        # User is deploying a workflow
        logger.info("Checking policy for workflow deployment")
        # Get deploying workspace
        deploy_workspace = path_params["deploy_workspace"]
        input_data["input"]["deploying_user"] = deploy_workspace
    elif path_params.get("workflow_job_id"):
        # User is accessing logs
        logger.info("Checking job owner for logs access")
        # Get executing workspace for the given job
        workflow_job_id = path_params["workflow_job_id"]

        job_id = workflow_job_id[-36:]

        # Get deployed workspace for the given job
        deploy_workspace = job_deployed_workspace.get(workflow_job_id)

        # Get executing workspace for the given job
        execute_workspace = job_owners.get(f"{deploy_workspace}-{job_id}")

        input_data["input"]["executing_user"] = execute_workspace

    response = opa_request(input_data, opa_service_endpoint)
    if response.status_code != 200 or not response.json().get("result", False):
        return False
    return True


def convert_workspace_to_username(workspace: str) -> str:
    return workspace.replace("_", "-")


def convert_username_to_workspace(username: str) -> str:
    if not username:
        return ""
    return username.replace("-", "_")


def get_workflow_id_from_job_id(
    deploy_workspace: str, job_id: str, ades_service_endpoint: str
) -> str:
    headers = {"Accept": "application/json"}
    response = requests.get(
        f"{ades_service_endpoint}/{deploy_workspace}/ogc-api/jobs/{job_id}", headers=headers
    )
    return response.json()["processID"]


def check_workflow_access(
    request: Request,
    deploy_workspace: str,
    ades_policy_bucket: str,
    ades_service_endpoint: str,
    workflow_id: str = None,
    job_id: str = None,
) -> bool:
    """Check if the workflow is accessible to the current user"""
    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    if user_workspace == deploy_workspace:
        return True

    logger.info(
        "Checking user %s has access to workflow %s in workspace %s",
        user_workspace,
        workflow_id,
        deploy_workspace,
    )

    user_groups = set()  # temporary while waiting for group support

    # Creat S3 client
    s3_client = boto3.client("s3")

    deploy_workspace = convert_workspace_to_username(deploy_workspace)

    if not workflow_id:
        workflow_id = get_workflow_id_from_job_id(job_id, ades_service_endpoint)

    key = f"workflows/{deploy_workspace}/{workflow_id}.access-policy.json"

    try:
        s3_data = s3_client.get_object(Bucket=ades_policy_bucket, Key=key)
    except botocore.exceptions.ClientError as err:
        if err.response["Error"]["Code"] == "NoSuchKey":
            logger.info(
                "No access policy found for workflow %s in workspace %s",
                workflow_id,
                deploy_workspace,
            )
            return False
        else:
            logger.info(
                "Error getting access policy for workflow %s in workspace %s",
                workflow_id,
                deploy_workspace,
            )
            return False

    workflow_policy = json.loads(s3_data["Body"].read().decode("utf-8"))

    ## TODO: Could also use OPA check here instead

    # Check if workflow is a user service
    if workflow_policy.get("user_service"):
        logger.info("Workflow %s in workspace %s is a user service", workflow_id, deploy_workspace)
        return True
    # Check if workflow is public
    elif workflow_policy.get("public"):
        logger.info("Workflow %s in workspace %s is public", workflow_id, deploy_workspace)
        return True
    else:
        # Check if user is in the allowed list
        if username in workflow_policy.get("allowed_access", {}).get("users"):
            logger.info(
                "User %s is in the allowed list for workflow %s in workspace %s",
                user_workspace,
                workflow_id,
                deploy_workspace,
            )
            return True
        else:
            allowed_groups = set(workflow_policy.get("allowed_access", {}).get("groups", set()))
            if user_groups & allowed_groups:
                logger.info(
                    "User %s is in the allowed groups for workflow %s in workspace %s",
                    user_workspace,
                    workflow_id,
                    deploy_workspace,
                )
                return True
    return False


def replace_href_links(content_dict: dict, ades_ingress_path: str) -> dict:
    """Replace href links in the JSON response"""
    if "links" in content_dict:
        for link in content_dict["links"]:
            link["href"] = link["href"].replace("http://localhost:8080", ades_ingress_path)
    return content_dict


last_deploy_times = {}


# Dependency to check the last call time
def rate_limit(deploy_workspace: str):
    current_time = time.time()
    print(last_deploy_times.get(deploy_workspace, 0))
    last_call_time = last_deploy_times.get(deploy_workspace, 0)
    if current_time - last_call_time < 5:
        raise HTTPException(
            status_code=429, detail="Too Many Requests: Please wait 5 seconds before retrying."
        )
    last_deploy_times[deploy_workspace] = current_time


def get_workspace(request: Request) -> str:
    return request.path_params["deploy_workspace"]


def rate_limiter_dependency(workspace=Depends(get_workspace)):  # noqa: B008
    rate_limit(workspace)


def get_processes(deploy_workspace: str, ades_service_endpoint: str) -> dict:
    headers = {"Accept": "application/cwl+json"}
    response = requests.get(
        f"{ades_service_endpoint}/{deploy_workspace}/ogc-api/processes", headers=headers
    )
    try:
        processes_dict = response.json()
    except JSONDecodeError as err:
        logger.error("Error decoding JSON response from ADES list processes")
        logger.error(response.text)
        raise err
    return processes_dict


def get_workflow_id_from_file(data: str) -> str:
    cwl_dict = yaml.safe_load(data)
    return cwl_dict["$graph"][0]["id"]


def get_workflow_id_from_url(url: str) -> str:
    response = requests.get(url)
    cwl_dict = yaml.safe_load(response.text)
    return cwl_dict["$graph"][0]["id"]


def list_jobs_dict(deploy_workspace: str, request: Request, ades_service_endpoint: str) -> dict:
    """Local function to list all jobs in a workspace, returned as a dictionary"""
    logger.debug("Listing jobs in workspace %s", deploy_workspace)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ades_service_endpoint}/{deploy_workspace}/ogc-api/jobs", headers=headers
    )

    return response.json()


def check_job_access(
    user_workspace: str,
    workflow_id: str,
    job_id: str,
    job_deployed_workspace: dict,
    job_owners: dict,
) -> bool:
    """Check if user has access to this job"""

    # Get deployment workspace
    workflow_id_and_job_id = f"{workflow_id}-{job_id}"
    deploy_workspace = job_deployed_workspace.get(workflow_id_and_job_id)

    logger.info(
        "Checking user %s has access to logs for job %s of workflow %s in workspace %s",
        user_workspace,
        job_id,
        workflow_id,
        deploy_workspace,
    )

    deploy_workspace_and_job_id = f"{deploy_workspace}-{job_id}"

    if job_owners.get(deploy_workspace_and_job_id) == user_workspace:
        return True

    return False
