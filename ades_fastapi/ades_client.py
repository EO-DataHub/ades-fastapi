import json
import logging
import os
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
    replace_href_link,
    replace_href_links,
)

logger = logging.getLogger(__name__)  # Add this line to define the logger

JOBS_TIMEOUT = int(os.getenv("JOBS_TIMEOUT", "60"))


class ADESClient:
    def __init__(
        self,
        service_endpoint: str,
        base_url: str,
        policy_bucket: str,
        policy_prefix: str,
        catalog_root: str,
    ):
        self.service_endpoint = service_endpoint
        self.base_url = base_url
        self.policy_bucket = policy_bucket
        self.policy_prefix = policy_prefix
        self.catalog_root = catalog_root

    def _check_workflow_access(
        self,
        request: Request,
        deploy_workspace: str,
        workflow_id: str,
    ) -> tuple:
        """Check if the workflow is accessible to the current user"""
        username, workspace, workspaces, _ = get_user_details(request)

        if deploy_workspace in workspaces:
            return True, "User has access to the owning workspace"

        logger.info(
            "Checking user %s has access to workflow %s in workspace %s",
            username,
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
            workspaces_set = set(workspaces)
            if workspaces_set & set(
                workflow_policy.get("allowed_access", {}).get("workspaces", set())
            ):
                logger.info(
                    "User has access to a workspace in the allowed list for workflow %s in workspace %s",
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
        timeout: int = 10,
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
                response = func(url, headers=headers, timeout=timeout, **data)
            else:
                logger.info("Sending %s request to %s", verb, url)
                response = func(url, headers=headers, timeout=timeout)
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
            content = json.dumps(
                replace_href_links(content_json, self.base_url, self.catalog_root, deploy_workspace)
            )
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

    def list_processes(
        self,
        request: requests.Request,
        deploy_workspace: str,
        limit: Optional[int],
        skip: Optional[int],
    ):
        headers = dict(request.headers)
        headers.pop("authorization", None)

        final_content = {}
        final_content["processes"] = []

        # For now, request all workflows and filter by access, using limit and skip after
        # TODO: maybe add some limit value here for some configured maximum number of
        # workflows and then loop
        response = self._send_request(
            "GET",
            f"{deploy_workspace}/ogc-api/processes",
            headers,
        )

        allowed_count = 0
        if "application/json" in response.headers["Content-Type"]:
            content_json = response.json()
            content_json = replace_href_links(
                content_json, self.base_url, self.catalog_root, deploy_workspace
            )
            final_content["links"] = content_json.get("links")
            for process_json in content_json.get("processes", []):
                access, description = self._check_workflow_access(
                    request,
                    deploy_workspace,
                    process_json["id"],
                )
                if access:
                    allowed_count += 1
                    if skip and allowed_count <= skip:
                        continue
                    process_json = replace_href_links(
                        process_json, self.base_url, self.catalog_root, deploy_workspace
                    )
                    process_json.update({"AccessReasoning": description})
                    final_content["processes"].append(process_json)
                    if len(final_content["processes"]) == limit:
                        break
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
            content_json = replace_href_links(
                content_json, self.base_url, self.catalog_root, deploy_workspace
            )
            content = json.dumps(content_json, indent=2)
        else:
            content = response.text

        # Need to include Location header from ADES to support deploy status endpoint
        response.headers = {
            "Location": replace_href_link(
                response.headers.get("Location", ""),
                self.base_url,
                self.catalog_root,
                deploy_workspace,
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
                "Location": replace_href_link(
                    response.headers.get("Location", ""),
                    self.base_url,
                    self.catalog_root,
                    deploy_workspace,
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
            content_json = replace_href_links(
                content_json, self.base_url, self.catalog_root, deploy_workspace
            )
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

        api_token_calling = creds.get("calling_workspace", {}).get("api_token", {})
        aws_creds_executing = creds.get("executing_workspace", {}).get("aws_creds", {})
        api_token_executing = creds.get("executing_workspace", {}).get("api_token", {})

        try:
            # Add calling workspace to body
            logger.info("Setting calling workspace to %s", calling_workspace)
            body["inputs"].update({"calling_workspace": calling_workspace})
            # Add executing workspace to body
            logger.info("Setting executing workspace to %s", executing_workspace)
            body["inputs"].update({"executing_workspace": executing_workspace})
            # Add calling credentials
            logger.info("Setting user token in execution call")
            body["inputs"].update({"CALLING_WORKSPACE_ACCESS_TOKEN": api_token_calling})
            # Add executing credentials
            if not (
                body["inputs"].get("AWS_ACCESS_KEY_ID") and body["inputs"].get("aws_access_key_id")
            ):
                body["inputs"].update(
                    {"AWS_ACCESS_KEY_ID": aws_creds_executing.get("AccessKeyId", "null")}
                )
            if not (
                body["inputs"].get("AWS_SECRET_ACCESS_KEY")
                and body["inputs"].get("aws_secret_access_key")
            ):
                body["inputs"].update(
                    {"AWS_SECRET_ACCESS_KEY": aws_creds_executing.get("SecretAccessKey", "null")}
                )
            if not (
                body["inputs"].get("AWS_SESSION_TOKEN") and body["inputs"].get("aws_session_token")
            ):
                body["inputs"].update(
                    {"AWS_SESSION_TOKEN": aws_creds_executing.get("SessionToken", "null")}
                )
            # TODO: Allow user service tokens to be generate when needed
            body["inputs"].update({"WORKSPACE_ACCESS_TOKEN": api_token_executing})
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
        deploy_workspace: str,
        workflow_id: str,
    ) -> requests.Response:
        username, workspace, workspaces, _ = get_user_details(
            request
        )  # check this is the correct way to extract calling workspace
        token = get_user_token(request)
        aws_creds = generate_aws_credentials(
            token, username, workspace, deploy_workspace, workflow_id
        )
        try:
            body = await request.json()
        except json.JSONDecodeError as err:
            raise HTTPException(
                status_code=400, detail="Invalid input payload, not valid JSON"
            ) from err
        self._configure_execute_request(body, aws_creds, workspace, deploy_workspace)
        response = self._send_execute_to_ades(deploy_workspace, workflow_id, body)
        # Record the calling workspace for the generated jobID
        if response.status_code == 201:
            try:
                content_json = replace_href_links(
                    response.json(), self.base_url, self.catalog_root, deploy_workspace
                )
                content = json.dumps(content_json, indent=2)
            except json.JSONDecodeError:
                content = response.text

            if "Location" in response.headers:
                response.headers["Location"] = replace_href_link(
                    response.headers["Location"], self.base_url, self.catalog_root, deploy_workspace
                )

        else:
            content = response.text
        return response, content

    async def execute_workflow(
        self,
        request: requests.Request,
        deploy_workspace: str,
        workflow_id: str,
    ) -> requests.Response:
        username, workspace, workspaces, _ = get_user_details(request)
        token = get_user_token(request)
        aws_creds = generate_aws_credentials(
            token, username, workspace, deploy_workspace, workflow_id
        )
        try:
            body = await request.json()
        except json.JSONDecodeError as err:
            raise HTTPException(
                status_code=400, detail="Invalid input payload, not valid JSON"
            ) from err
        self._configure_execute_request(body, aws_creds, workspace, workspace)
        response = self._send_execute_to_ades(deploy_workspace, workflow_id, body)
        # Record the calling workspace for the generated jobID
        if response.status_code == 201:
            try:
                content_json = replace_href_links(
                    response.json(), self.base_url, self.catalog_root, deploy_workspace
                )
                content = json.dumps(content_json, indent=2)
            except json.json.JSONDecodeError:
                content = response.text

            if "Location" in response.headers:
                response.headers["Location"] = replace_href_link(
                    response.headers["Location"], self.base_url, self.catalog_root, deploy_workspace
                )
        else:
            content = response.text
        return response, content

    def _format_execution_link(self, links: list, workspace: str, workflow_id: str) -> list:
        """Format the status link to include the base URL"""
        for link in links:
            if link["rel"] == "monitor":
                link["href"] = (
                    f"{self.base_url}/catalogs/user/catalogs/{workspace}/processes/{workflow_id}/execution"
                )
        return links

    def _format_log_links(self, links: list, workspace: str, job_id: str) -> list:
        """Format the status link to include the base URL"""
        for link in links:
            if link["rel"] == "related":
                log_name = link["href"].rsplit("/", 1)[1]
                link["href"] = (
                    f"{self.base_url}/catalogs/user/catalogs/{workspace}/jobs/{job_id}/{log_name}"
                )
        return links

    def get_job_status(self, headers: dict, deploy_workspace: str, job_id: str):
        headers.pop("authorization", None)
        response = self._send_request("GET", f"{deploy_workspace}/ogc-api/jobs/{job_id}", headers)

        content_json = replace_href_links(
            response.json(), self.base_url, self.catalog_root, deploy_workspace
        )

        content_json["links"] = self._format_log_links(
            content_json["links"], deploy_workspace, job_id
        )

        content = json.dumps(content_json, indent=2)

        return response, content

    def get_job_results(self, headers: dict, deploy_workspace: str, job_id: str):
        headers.pop("authorization", None)
        response = self._send_request(
            "GET", f"{deploy_workspace}/ogc-api/jobs/{job_id}/results", headers
        )
        try:
            content = json.dumps(response.json())
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
        username, workspace, workspaces, _ = get_user_details(request)

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

        filtered_jobs = []

        # Get all jobs in the deployed workspace
        response = self._send_request(
            "GET",
            f"{deploy_workspace}/ogc-api/jobs",
            headers,
            data={"params": params},
            timeout=JOBS_TIMEOUT,
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
            return response, json.dumps({"jobs": jobs, "numberTotal": 0})

        logger.info(
            "Filtering jobs to those that were called by workspaces %s deployed in workspace %s",
            workspaces,
            deploy_workspace,
        )
        for job in jobs:
            job_id = job.get("jobID", "")
            job_details = job_saver.get_job_details(deploy_workspace, job_id)
            if job_details.get("calling_workspace") in workspaces:
                job = replace_href_links(job, self.base_url, self.catalog_root, deploy_workspace)
                job["links"] = self._format_log_links(job["links"], deploy_workspace, job_id)
                filtered_jobs.append(job)
                if limit and len(filtered_jobs) == limit:
                    break
            elif job_details.get("workflow_type") == "user-service":
                if job_details.get("deploy_workspace") in workspaces:
                    job = replace_href_links(
                        job, self.base_url, self.catalog_root, deploy_workspace
                    )
                    job["links"] = self._format_log_links(job["links"], deploy_workspace, job_id)
                    filtered_jobs.append(job)
                    if limit and len(filtered_jobs) == limit:
                        break

        response_json["jobs"] = filtered_jobs
        response_json["numberTotal"] = len(filtered_jobs)

        response_json = replace_href_links(
            response_json, self.base_url, self.catalog_root, deploy_workspace
        )

        content = json.dumps(response_json)

        return response, content

    def get_all_jobs(self, request, workspace_jobs):
        username, workspace, workspaces, _ = get_user_details(request)

        headers = dict(request.headers)
        headers.pop("authorization", None)

        job_details_list = []

        for job in workspace_jobs.get(workspace, []):
            deploy_workspace = job["deploy_workspace"]
            job_id = job["jobID"]
            response = self._send_request(
                "GET", f"{deploy_workspace}/ogc-api/jobs/{job_id}", headers
            )
            job_details = response.json()
            job_details = replace_href_links(
                job_details, self.base_url, self.catalog_root, deploy_workspace
            )
            job_details_list.append(job_details)

        response_json = {"workspace": workspace, "jobs": job_details_list}

        content = json.dumps(response_json)

        return content

    def _get_workflow_id_from_job_id(
        self, deploy_workspace: str, job_id: str, headers: dict
    ) -> str:
        response = self._send_request("GET", f"{deploy_workspace}/ogc-api/jobs/{job_id}", headers)
        workflow_id = response.json().get("processID", "")
        return workflow_id

    def get_log(
        self,
        job_id: str,
        file_name: str,
        deploy_workspace: str,
        headers: dict,
    ) -> tuple:
        workflow_id = self._get_workflow_id_from_job_id(deploy_workspace, job_id, headers)

        if not workflow_id:
            raise HTTPException(status_code=404, detail="Workflow ID for given jobID not found")

        logger.info(
            "Accessing logs: %s for job: %s and workflow: %s", file_name, job_id, workflow_id
        )

        workflow_job_id = f"{workflow_id}-{job_id}"

        headers.pop("authorization", None)

        response = self._send_request(
            "GET", f"{deploy_workspace}/temp/{workflow_job_id}/{file_name}", headers
        )

        return response, response.content

    def delete_job(self, headers: dict, deploy_workspace: str, job_id: str):
        headers.pop("authorization", None)
        response = self._send_request(
            "DELETE", f"{deploy_workspace}/ogc-api/jobs/{job_id}", headers
        )

        try:
            response_json = response.json()
            response_json = replace_href_links(
                response_json, self.base_url, self.catalog_root, deploy_workspace
            )
            content = json.dumps(response_json)
        except json.JSONDecodeError:
            content = response.text

        return response, content
