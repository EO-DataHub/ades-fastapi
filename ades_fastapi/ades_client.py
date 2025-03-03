import json
import logging
from typing import List, Optional

import boto3
import botocore
import requests
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .aws_client import generate_aws_credentials
from .job_saver import JobSaver
from .utils import (
    WorkflowType,
    get_user_details,
    get_user_token,
    get_workflow_id_from_file,
    get_workflow_id_from_url,
    replace_href_links,
)

logger = logging.getLogger(__name__)  # Add this line to define the logger


class ADESClient:
    def __init__(
        self, service_endpoint: str, base_url: str, policy_bucket: str, policy_prefix: str
    ):
        self.service_endpoint = service_endpoint
        self.base_url = base_url
        self.policy_bucket = policy_bucket
        self.policy_prefix = policy_prefix

    def _check_workflow_access(
        self,
        request: Request,
        deploy_workspace: str,
        workflow_id: str,
    ) -> tuple:
        """Check if the workflow is accessible to the current user"""
        username, workspace, _ = get_user_details(request)

        if workspace == deploy_workspace:
            return True, "Workspace owns this workflow"

        logger.info(
            "Checking workspace %s has access to workflow %s in workspace %s",
            workspace,
            workflow_id,
            deploy_workspace,
        )

        user_groups = set()  # temporary while waiting for group support

        # Creat S3 client
        s3_client = boto3.client("s3")

        if self.policy_prefix:
            key = f"{self.policy_prefix}/{deploy_workspace}/{workflow_id}.access-policy.json"
        else:
            key = f"{deploy_workspace}/{workflow_id}.access-policy.json"

        logger.debug("Policy key is %s", key)
        logger.debug("Policy bucket is %s", self.policy_bucket)

        try:
            s3_data = s3_client.get_object(Bucket=self.policy_bucket, Key=key)
        except botocore.exceptions.ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchKey":
                logger.info(
                    "No access policy found for workflow %s in workspace %s",
                    workflow_id,
                    deploy_workspace,
                )
                return False, ""
            else:
                logger.info(
                    "Error getting access policy for workflow %s in workspace %s",
                    workflow_id,
                    deploy_workspace,
                )
                return False, ""

        try:
            workflow_policy = json.loads(s3_data["Body"].read().decode("utf-8"))
        except json.JSONDecodeError:
            logger.error(
                "Policy for workflow %s in workspace %s is not valid JSON",
                workflow_id,
                deploy_workspace,
            )
            return False, ""

        logger.info("Workflow policy is: %s", workflow_policy)

        ## TODO: Could also use OPA check here instead

        # Check if workflow is a user service
        if workflow_policy.get("user_service"):
            logger.info(
                "Workflow %s in workspace %s is a user service", workflow_id, deploy_workspace
            )
            return True, "Workflow is a user-service"
        # Check if workflow is public
        elif workflow_policy.get("public"):
            logger.info("Workflow %s in workspace %s is public", workflow_id, deploy_workspace)
            return True, "Workflow is public"
        else:
            # Check if user is in the allowed list
            if workspace in workflow_policy.get("allowed_access", {}).get("workspaces", {}):
                logger.info(
                    "Workspace %s is in the allowed list for workflow %s in workspace %s",
                    workspace,
                    workflow_id,
                    deploy_workspace,
                )
                return True, "Workspace has access to this workflow (user)"
            else:
                allowed_groups = set(workflow_policy.get("allowed_access", {}).get("groups", set()))
                if user_groups & allowed_groups:
                    logger.info(
                        "Workspace %s is in the allowed groups for workflow %s in workspace %s",
                        workspace,
                        workflow_id,
                        deploy_workspace,
                    )
                    return True, "Workspace has access to this workflow (group)"
        return False, ""

    def _send_request(
        self,
        verb: str,
        url_path: str = "",
        headers: Optional[dict] = None,
        data: Optional[dict] = None,
    ):
        # Construct requests function
        if verb == "GET":
            func = requests.get
        elif verb == "POST":
            func = requests.post
        elif verb == "PUT":
            func = requests.put
        elif verb == "DELETE":
            func = requests.delete

        if url_path:
            url = f"{self.service_endpoint}/{url_path}"
        else:
            url = self.service_endpoint

        try:
            if data:
                logger.info("Sending %s request to %s with data %s", verb, url, data)
                response = func(url, headers=headers, **data)
            else:
                logger.info("Sending %s request to %s", verb, url)
                response = func(url, headers=headers)
        except requests.exceptions.ConnectionError:
            return JSONResponse(content={"message": "Service Unavailable"}, status_code=503)

        return response

    def get_root(self):
        try:
            response = self._send_request("GET")
        except requests.exceptions.ConnectionError:
            return JSONResponse(content={"message": "Service Unavailable"}, status_code=503)
        return response

    def get_workspace_root(self, deploy_workspace: str):
        try:
            url = f"{deploy_workspace}/ogc-api/"
            response = self._send_request("GET", url)
            content_json = response.json()
            content = json.dumps(replace_href_links(content_json, self.base_url))
        except requests.exceptions.ConnectionError:
            return JSONResponse(content={"message": "Service Unavailable"}, status_code=503)
        except json.JSONDecodeError:
            content = response.text
        return response, content

    def undeploy_workflow(self, headers: dict, deploy_workspace: str, workflow_id: str):
        headers.pop("authorization", None)
        response = self._send_request(
            "DELETE", f"{deploy_workspace}/ogc-api/processes/{workflow_id}", headers
        )

        try:
            content = json.dumps(response.json())
        except json.JSONDecodeError:
            content = response.text

        return response, content

    def list_workflows(
        self, request: requests.Request, deploy_workspace: str, limit: Optional[int], skip: int
    ):
        headers = dict(request.headers)
        headers.pop("authorization", None)

        # Add limit to data params
        params = {}
        if limit:
            params["limit"] = limit
        if skip:
            params["skip"] = skip

        response = self._send_request(
            "GET", f"{deploy_workspace}/ogc-api/processes", headers, data={"params": params}
        )

        if "application/json" in response.headers["Content-Type"]:
            final_content = {}
            final_content["processes"] = []
            content_json = response.json()
            content_json = replace_href_links(content_json, self.base_url)
            final_content["links"] = content_json.get("links")
            for process_json in content_json.get("processes", []):
                access, description = self._check_workflow_access(
                    request,
                    deploy_workspace,
                    process_json["id"],
                )
                if access:
                    process_json = replace_href_links(process_json, self.base_url)
                    process_json.update({"AccessReasoning": description})
                    final_content["processes"].append(process_json)
            content = json.dumps(final_content)
        else:
            content = response.text

        return response, content

    async def deploy_workflow(self, request: requests.Request, deploy_workspace: str):
        headers = dict(request.headers)
        headers.pop("authorization", None)

        if "application/json" in request.headers["Content-Type"]:
            logger.info("Deploying workflow from URL to workspace %s", deploy_workspace)
            # Handle HTTP file content
            data = {"json": await request.json()}
            success, detail = get_workflow_id_from_url(data["json"]["executionUnit"]["href"])
            if not success:
                raise HTTPException(status_code=400, detail=detail)

        elif "application/cwl+yaml" in request.headers["Content-Type"]:
            logger.info(
                "Deploying workflow from CWL file content to workspace %s", deploy_workspace
            )
            # Handle string file content
            file_content = await request.body()

            # Prepare the payload for the subsequent API request
            data = {"data": file_content}  # Decode bytes to string
            success, detail = get_workflow_id_from_file(file_content)
            if not success:
                raise HTTPException(status_code=400, detail=detail)

        else:
            raise HTTPException(
                status_code=415,
                detail=(
                    "Unsupported content type. Only application/json and "
                    "application/cwl+yaml are supported"
                ),
            )
        response = self._send_request(
            "POST", f"{deploy_workspace}/ogc-api/processes", headers, data
        )

        if "application/json" in response.headers["Content-Type"]:
            content_json = response.json()
            content_json = replace_href_links(content_json, self.base_url)
            content = json.dumps(content_json, indent=2)
        else:
            content = response.text

        # Need to include Location header from ADES to support deploy status endpoint
        response.headers = {
            "Location": response.headers.get("Location", "").replace(
                "http://localhost:8080", self.base_url
            ),
            "Content-Type": response.headers["Content-Type"],
        }

        return response, content

    async def update_workflow(
        self, request: requests.Request, deploy_workspace: str, workflow_id: str
    ):
        headers = dict(request.headers)
        headers.pop("authorization", None)

        if "application/json" in request.headers["Content-Type"]:
            logger.info("Updating workflow from URL to workspace %s", deploy_workspace)
            # Handle HTTP file content
            data = {"json": await request.json()}
            success, detail = get_workflow_id_from_url(data["json"]["executionUnit"]["href"])
            if not success:
                raise HTTPException(status_code=400, detail=detail)
        elif "application/cwl+yaml" in request.headers["Content-Type"]:
            logger.info("Updating workflow from CWL file content to workspace %s", deploy_workspace)
            # Handle string file content
            file_content = await request.body()

            # Prepare the payload for the subsequent API request
            data = {"data": file_content}  # Decode bytes to string
            success, detail = get_workflow_id_from_file(data["data"])
            if not success:
                raise HTTPException(status_code=400, detail=detail)
        else:
            raise HTTPException(
                status_code=415,
                detail=(
                    "Unsupported content type. Only application/json and "
                    "application/cwl+yaml are supported"
                ),
            )

        response = self._send_request(
            "PUT", f"{deploy_workspace}/ogc-api/processes/{detail}", headers, data
        )

        try:
            content = json.dumps(response.json(), indent=2)
        except json.JSONDecodeError:
            content = response.text if response.text else ""

        # Need to include Location header from ADES to support deploy status endpoint
        response.headers.update(
            {
                "Location": response.headers.get("Location", "").replace(
                    "http://localhost:8080", self.base_url
                ),
            }
        )

        return response, content

    def get_workflow(
        self, headers: dict, deploy_workspace: str, workflow_id: str, wf_type: WorkflowType
    ):
        headers.pop("authorization", None)
        response = self._send_request(
            "GET", f"{deploy_workspace}/ogc-api/processes/{workflow_id}", headers
        )
        try:
            content_json = response.json()
            content_json = replace_href_links(content_json, self.base_url)
            if wf_type is WorkflowType.USER_SERVICE:
                content_json.update({"AccessReasoning": "Workflow is a user-service"})
            content = json.dumps(content_json, indent=2)
        except json.JSONDecodeError:
            # Update Content-Type header to avoid warning generated by ADES response
            response.headers["Content-Type"] = "text/plain"
            content = response.text

        return response, content

    @staticmethod
    def _configure_execute_request(
        body: dict, creds: dict, calling_workspace: str, executing_workspace: str = None
    ):

        try:
            # Add calling workspace to body
            logger.info("Setting calling workspace to %s", calling_workspace)
            body["inputs"].update({"calling_workspace": calling_workspace})
            # Add executing workspace to body
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
            # Add AWS credentials to body
            logger.info("Setting user token in execution call")
            body["inputs"].update(
                {
                    "WORKSPACE_AWS_ACCESS_KEY_ID": creds.get("calling_workspace", {}).get(
                        "AccessKeyId", "null"
                    )
                }
            )
            body["inputs"].update(
                {
                    "WORKSPACE_AWS_SECRET_ACCESS_KEY": creds.get("calling_workspace", {}).get(
                        "SecretAccessKey", "null"
                    )
                }
            )
            body["inputs"].update(
                {
                    "WORKSPACE_AWS_SESSION_TOKEN": creds.get("calling_workspace", {}).get(
                        "SessionToken", "null"
                    )
                }
            )
            # Add service credentials only when required
            if executing_workspace and creds.get("executing_workspace"):
                body["inputs"].update(
                    {
                        "AWS_ACCESS_KEY_ID": creds.get("executing_workspace", {}).get(
                            "AccessKeyId", "null"
                        )
                    }
                )
                body["inputs"].update(
                    {
                        "AWS_SECRET_ACCESS_KEY": creds.get("executing_workspace", {}).get(
                            "SecretAccessKey", "null"
                        )
                    }
                )
                body["inputs"].update(
                    {
                        "AWS_SESSION_TOKEN": creds.get("executing_workspace", {}).get(
                            "SessionToken", "null"
                        )
                    }
                )
            # If not a user service set AWS credentials to that of the calling workspace again
            elif not executing_workspace:
                body["inputs"].update(
                    {
                        "AWS_ACCESS_KEY_ID": creds.get("calling_workspace", {}).get(
                            "AccessKeyId", "null"
                        )
                    }
                )
                body["inputs"].update(
                    {
                        "AWS_SECRET_ACCESS_KEY": creds.get("calling_workspace", {}).get(
                            "SecretAccessKey", "null"
                        )
                    }
                )
                body["inputs"].update(
                    {
                        "AWS_SESSION_TOKEN": creds.get("calling_workspace", {}).get(
                            "SessionToken", "null"
                        )
                    }
                )
            else:
                logger.warning("No AWS credentials provided for executing workspace")
                logger.warning(
                    "Continuing, but this may prevent the workflow from executing correctly, "
                    "if AWS creds are required in workflow steps"
                )
        except KeyError as e:
            logger.error("KeyError: %s", e)
            raise HTTPException(status_code=400, detail="Invalid input payload") from e

    def _send_execute_to_ades(
        self, deploy_workspace: str, workflow_id: str, body: dict
    ) -> requests.Response:
        headers = {
            "Prefer": "respond-async",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = {"json": body}
        response = self._send_request(
            "POST", f"{deploy_workspace}/ogc-api/processes/{workflow_id}/execution", headers, data
        )

        return response

    async def execute_user_service(
        self,
        request: requests.Request,
        deployed_workspace: str,
        workflow_id: str,
    ) -> requests.Response:
        username, workspace, _ = get_user_details(
            request
        )  # check this is the correct way to extract calling workspace
        token = get_user_token(request)
        aws_creds = generate_aws_credentials(token, workspace, deployed_workspace, workflow_id)
        try:
            body = await request.json()
        except json.JSONDecodeError as err:
            raise HTTPException(
                status_code=400, detail="Invalid input payload, not valid JSON"
            ) from err
        self._configure_execute_request(body, aws_creds, workspace, deployed_workspace)
        response = self._send_execute_to_ades(deployed_workspace, workflow_id, body)
        # Record the calling workspace for the generated jobID
        if response.status_code == 201:
            try:
                content_json = replace_href_links(response.json(), self.base_url)
                content = json.dumps(content_json, indent=2)
            except json.JSONDecodeError:
                content = response.text

            if "Location" in response.headers:
                response.headers["Location"] = response.headers["Location"].replace(
                    "http://localhost:8080", self.base_url
                )
        else:
            content = response.text
        return response, content

    async def execute_workflow(
        self,
        request: requests.Request,
        deployed_workspace: str,
        workflow_id: str,
    ) -> requests.Response:
        username, workspace, _ = get_user_details(request)
        token = get_user_token(request)
        aws_creds = generate_aws_credentials(token, workspace, deployed_workspace, workflow_id)
        try:
            body = await request.json()
        except json.JSONDecodeError as err:
            raise HTTPException(
                status_code=400, detail="Invalid input payload, not valid JSON"
            ) from err
        self._configure_execute_request(body, aws_creds, workspace)
        response = self._send_execute_to_ades(deployed_workspace, workflow_id, body)
        # Record the calling workspace for the generated jobID
        if response.status_code == 201:
            try:
                content_json = replace_href_links(response.json(), self.base_url)
                content = json.dumps(content_json, indent=2)
            except json.json.JSONDecodeError:
                content = response.text

            if "Location" in response.headers:
                response.headers["Location"] = response.headers["Location"].replace(
                    "http://localhost:8080", self.base_url
                )
        else:
            content = response.text
        return response, content

    def get_job_status(self, headers: dict, deploy_workspace: str, job_id: str):
        headers.pop("authorization", None)
        response = self._send_request("GET", f"{deploy_workspace}/ogc-api/jobs/{job_id}", headers)

        content = replace_href_links(response.json(), self.base_url)

        content = json.dumps(content).replace("http://localhost:8080", self.base_url)

        return response, content

    def get_job_results(self, headers: dict, deploy_workspace: str, job_id: str):
        headers.pop("authorization", None)
        response = self._send_request(
            "GET", f"{deploy_workspace}/ogc-api/jobs/{job_id}/results", headers
        )
        try:
            content = json.dumps(response.json()).replace("http://localhost:8080", self.base_url)
        except json.JSONDecodeError:
            content = response.text

        return response, content

    def get_deployed_workspaced_jobs(
        self,
        request,
        deploy_workspace: str,
        job_saver: JobSaver,
        limit: Optional[int] = None,
        skip: Optional[int] = None,
        status: Optional[List[str]] = None,
        datetime: Optional[str] = None,
    ):
        username, workspace, _ = get_user_details(request)

        headers = dict(request.headers)
        headers.pop("authorization", None)

        # Add limit to data params
        params = {}
        if limit:
            params.update({"limit": limit})
        if skip:
            params.update({"skip": skip})
        if status:
            params.update({"status": status})
        if datetime:
            params.update({"datetime": datetime})

        # Get all jobs in the deployed workspace
        response = self._send_request(
            "GET", f"{deploy_workspace}/ogc-api/jobs", headers, data={"params": params}
        )
        try:
            response_json = response.json()
            jobs = response_json["jobs"]
        except json.JSONDecodeError:
            logger.error("Response is not JSON serializable")
            return response, response.text
        except KeyError:
            logger.error("No jobs found in workspace %s", deploy_workspace)
            jobs = []

        filtered_jobs = []

        logger.info(
            "Filtering jobs to those that were called by workspace %s deployed in workspace %s",
            workspace,
            deploy_workspace,
        )
        for job in jobs:
            job_id = job.get("jobID", "")
            job_details = job_saver.get_job_details(job_id, {})
            if job_details.get("calling_workspace") == workspace:
                filtered_jobs.append(job)
            elif job_details.get("workflow_type") == "user-service":
                if job_details.get("deploy_workspace") == workspace:
                    filtered_jobs.append(job)

        response_json["jobs"] = filtered_jobs
        response_json["numberTotal"] = len(filtered_jobs)

        content = json.dumps(response_json).replace("http://localhost:8080", self.base_url)

        return response, content

    def get_all_jobs(self, request, workspace_jobs):
        username, workspace, _ = get_user_details(request)

        headers = dict(request.headers)
        headers.pop("authorization", None)

        job_details_list = []

        for job in workspace_jobs.get(workspace, []):
            deploy_workspace = job["deploy_workspace"]
            job_id = job["jobID"]
            response = self._send_request(
                "GET", f"{deploy_workspace}/ogc-api/jobs/{job_id}", headers
            )
            job_details_list.append(response.json())

        response_json = {"workspace": workspace, "jobs": job_details_list}

        content = json.dumps(response_json).replace("http://localhost:8080", self.base_url)

        return content

    def get_log(
        self,
        workflow_job_id: str,
        file_name: str,
        deploy_workspace: str,
        headers: dict,
    ):
        # Extract workflow and job ids
        workflow_id = workflow_job_id[:-37]
        job_id = workflow_job_id[-36:]

        logger.info(
            "Accessing logs: %s for workflow: %s and job: %s", file_name, workflow_id, job_id
        )

        headers.pop("authorization", None)

        response = self._send_request(
            "GET", f"{deploy_workspace}/temp/{workflow_job_id}/{file_name}", headers
        )

        return response

    def delete_job(self, headers: dict, deploy_workspace: str, job_id: str):
        headers.pop("authorization", None)
        response = self._send_request(
            "DELETE", f"{deploy_workspace}/ogc-api/jobs/{job_id}", headers
        )

        try:
            content = json.dumps(response.json()).replace("http://localhost:8080", self.base_url)
        except json.JSONDecodeError:
            content = response.text

        return response, content
