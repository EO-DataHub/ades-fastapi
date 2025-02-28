import logging

import requests
from fastapi import Request

from .job_saver import JobSaver
from .utils import WorkflowType, get_access_policy, get_user_details

logger = logging.getLogger(__name__)  # Add this line to define the logger


class DependencyClient:
    def __init__(
        self, opa_service_endpoint, ades_policy_bucket, ades_policy_prefix, enable_opa_policy_check
    ):
        self.opa_service_endpoint = opa_service_endpoint
        self.ades_policy_bucket = ades_policy_bucket
        self.ades_policy_prefix = ades_policy_prefix
        self.enable_opa_policy_check = enable_opa_policy_check

    def _opa_request(self, input_data: dict) -> requests.Response:
        """Send a request to OPA service"""
        logger.debug("Sending request to OPA service with input: %s", input_data)
        return requests.post(self.opa_service_endpoint, json=input_data)

    @staticmethod
    def _get_path_params(request: Request):
        logger.debug("CALCULATING PATH PARAMETERS")
        return request.scope.get("path_params", {})

    def _check_policy(
        self,
        request: Request,
        job_saver: JobSaver,
    ) -> tuple:
        """Check OPA policy to determine if the request is allowed"""
        username, roles = get_user_details(request)
        path_params = self._get_path_params(request)

        # Add values for logs
        logger.info("Logged in as user: %s", username)
        logger.info("Roles: %s", roles)

        # Set default workflow type
        wf_type = WorkflowType.DEFAULT

        input_data = {
            "input": {
                "roles": roles,
                "path": request.url.path,
                "workspace": username,
                "method": request.method,
            }
        }

        # Log path parameters
        logger.debug("Input parameters from path: %s", path_params)

        deploy_workspace = path_params.get("deploy_workspace")
        workflow_id = path_params.get("workflow_id")
        job_id = path_params.get("job_id")
        workflow_job_id = path_params.get("workflow_job_id")

        if (
            deploy_workspace and workflow_id and request.method in ["POST", "GET"]
        ):  # not needed for PUT updates
            # Checking access to workflow for details and execution
            logger.debug(
                "Checking access policy for workflow %s in workspace %s",
                workflow_id,
                deploy_workspace,
            )

            # Set workflow type to WORKFLOW
            wf_type = WorkflowType.WORKFLOW

            ## Load access policy
            access_policy = get_access_policy(
                path_params["deploy_workspace"],
                path_params["workflow_id"],
                self.ades_policy_bucket,
                self.ades_policy_prefix,
            )
            if access_policy:
                logger.info("Access policy is: %s", access_policy)
                input_data["input"]["is_public"] = access_policy.get("public", False)
                input_data["input"]["allowed_workspaces"] = access_policy.get(
                    "allowed_access", {}
                ).get("workspaces", [])
                input_data["input"]["is_user_service"] = access_policy.get("user_service", False)
                # TODO: determine ownership based on workspaces in user group
                if deploy_workspace == username:
                    wf_type = WorkflowType.WORKFLOW
                elif access_policy.get("user_service", False):
                    wf_type = WorkflowType.USER_SERVICE
            else:
                logger.info("No access policy found")

        if deploy_workspace and job_id:
            # Check access to job
            logger.debug(
                "Checking job access for job %s deployed to workspace %s", job_id, deploy_workspace
            )

            job_details = job_saver.get_job_details(deploy_workspace, job_id)

            input_data["input"]["calling_workspace"] = job_details.get("calling_workspace")

            if job_details.get("workflow_type") == "user-service":
                # If job is for a user-service, allow deploying workspace to access
                input_data["input"]["deployed_workspace"] = job_details.get("deploy_workspace")

        if deploy_workspace and workflow_job_id:
            # Checking access to job logs
            job_id = workflow_job_id[-36:]
            workflow_id = workflow_job_id.replace(job_id, "", 1)
            logger.debug(
                "Checking log access for workflow %s running under job %s, deployed to workspace %s",
                workflow_id,
                job_id,
                deploy_workspace,
            )

            job_details = job_saver.get_job_details(deploy_workspace, job_id)

            input_data["input"]["calling_workspace"] = job_details.get("calling_workspace")

            if job_details.get("workflow_type") == "user-service":
                # If job is for a user-service, allow deploying workspace to access
                input_data["input"]["deployed_workspace"] = job_details.get(
                    "deploy_workspace", None
                )

        response = self._opa_request(input_data)

        if response.status_code != 200 or not response.json().get("result", False):
            return False, wf_type
        return True, wf_type

    def check_access(self, request, job_saver):
        passed, workflow_type = self._check_policy(
            request,
            job_saver,
        )
        return passed, workflow_type
