import json
import logging
import os

import boto3
import requests

from .utils import WorkflowType

logger = logging.getLogger(__name__)  # Add this line to define the logger


class WorkflowExecutionException(Exception):
    pass


WORKFLOWS_BUCKET = os.getenv("WORKFLOWS_BUCKET", "workflows-bucket")


class JobSaver:
    def __init__(self, storage_dir: str):
        self.s3_client = boto3.client("s3")
        self.storage_dir = storage_dir
        self.job_owners = {}
        self.workspace_jobs = {}
        self.job_owner_filename = "job-owners.json"
        self.workspace_jobs_filename = "workspace-jobs.json"
        self.load_data()

    def record_owner(
        self,
        response: requests.Response,
        workflow_id: str,
        deploy_workspace: str,
        calling_workspace: str,
        workflow_type: WorkflowType = WorkflowType.WORKFLOW,
    ):
        """Record workspace of job owner"""
        try:
            job_id = response.json()["jobID"]
        except KeyError as e:
            logger.error("KeyError: %s", e)
            raise WorkflowExecutionException("Job ID not found in response") from e

        # Record jobID and, along with deployed workspace, relate to calling workspace for job/log access
        self.update_job_owners(deploy_workspace, calling_workspace, job_id, workflow_type)

        # Record jobID against calling workspace
        logger.info(
            "Job owner for the job %s deployed in workspace %s is %s",
            job_id,
            deploy_workspace,
            calling_workspace,
        )

        job_details = {}
        job_details["jobID"] = job_id
        job_details["workflow_id"] = workflow_id
        job_details["workflow_type"] = workflow_type.value
        job_details["deploy_workspace"] = deploy_workspace
        job_details["calling_workspace"] = calling_workspace

        self.s3_client.put_object(
            Bucket=WORKFLOWS_BUCKET,
            Key=f"{deploy_workspace}/{job_id}",
            Body=json.dumps(job_details),
            ContentType="application/json",
        )

    def save_to_file(self):
        """Save job owners and workspace jobs to file"""

        with open(f"{self.storage_dir}/{self.job_owner_filename}", "w") as f:
            json.dump(self.job_owners, f)
        with open(f"{self.storage_dir}/{self.workspace_jobs_filename}", "w") as f:
            json.dump(self.workspace_jobs, f)

    def load_data(self) -> dict:
        """Load job owners and workspace jobs from files"""
        if os.path.exists(f"{self.storage_dir}/{self.job_owner_filename}"):
            try:
                with open(f"{self.storage_dir}/{self.job_owner_filename}", "r") as file:
                    self.job_owners = json.load(file)
            except Exception as e:
                logger.error("Failed to load job owners from file: %s", e)
        if os.path.exists(f"{self.storage_dir}/{self.workspace_jobs_filename}"):
            try:
                with open(f"{self.storage_dir}/{self.workspace_jobs_filename}", "r") as file:
                    self.workspace_jobs = json.load(file)
            except Exception as e:
                logger.error("Failed to load workpace jobs from file: %s", e)

    def update_job_owners(
        self,
        deploy_workspace: str,
        calling_workspace: str,
        job_id: str,
        workflow_type: WorkflowType,
    ):
        """Update job owners"""
        deploy_workspace_and_job_id = f"{deploy_workspace}-{job_id}"
        allowed_workspaces = {"calling": calling_workspace, "deployed": None}
        if workflow_type == WorkflowType.USER_SERVICE:
            allowed_workspaces.update({"deployed": deploy_workspace})
        new_job_dict = {deploy_workspace_and_job_id: allowed_workspaces}
        self.job_owners.update(new_job_dict)

        if calling_workspace not in self.workspace_jobs:
            self.workspace_jobs[calling_workspace] = []
        self.workspace_jobs[calling_workspace].append(
            ({"deploy_workspace": deploy_workspace, "jobID": job_id})
        )

        self.save_to_file()

    def get_job_details(self, workspace: str, workflow_id: str, job_id: str) -> dict:
        """Get job owner from S3 job details"""
        try:
            job_details = self.s3_client.get_object(
                Bucket=WORKFLOWS_BUCKET,
                Key=f"{workspace}/{job_id}",
            )
        except self.s3_client.exceptions.NoSuchKey:
            logger.error("Job details not found for job %s in workspace %s", job_id, workspace)
            return None
        return json.loads(job_details.get("Body").read().decode("utf-8"))

    def get_job_owner(self, workspace: str, workflow_id: str, job_id: str):
        job_details = self.get_job_details(workspace, workflow_id, job_id)
        return job_details["calling_workspace"]
