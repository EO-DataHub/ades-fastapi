import json
import logging
import os

import requests

logger = logging.getLogger(__name__)  # Add this line to define the logger


class WorkflowExecutionException(Exception):
    pass


class JobSaver:
    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        self.job_owners = {}
        self.workspace_jobs = {}
        self.job_owner_filename = "job-owners.json"
        self.workspace_jobs_filename = "workspace-jobs.json"
        self.load_data()

    def record_owner(
        self, response: requests.Response, deploy_workspace: str, calling_workspace: str
    ):
        """Record workspace of job owner"""
        try:
            job_id = response.json()["jobID"]
        except KeyError as e:
            logger.error("KeyError: %s", e)
            raise WorkflowExecutionException("Job ID not found in response") from e

        # Record jobID and, along with deployed workspace, relate to calling workspace for job/log access
        self.update_job_owners(deploy_workspace, calling_workspace, job_id)

        # Record jobID against calling workspace

        logger.info(
            "Job owner for the job %s deployed in workspace %s is %s",
            job_id,
            deploy_workspace,
            calling_workspace,
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

    def update_job_owners(self, deploy_workspace: str, calling_workspace: str, job_id: str):
        """Update job owners"""
        deploy_workspace_and_job_id = f"{deploy_workspace}-{job_id}"
        new_job_dict = {deploy_workspace_and_job_id: calling_workspace}
        self.job_owners.update(new_job_dict)

        if calling_workspace not in self.workspace_jobs:
            self.workspace_jobs[calling_workspace] = []
        self.workspace_jobs[calling_workspace].append(
            ({"deploy_workspace": deploy_workspace, "jobID": job_id})
        )

        self.save_to_file()
