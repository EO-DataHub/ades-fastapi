import json
import logging
import os
from typing import Any

import requests

from .utils import WorkflowType

logger = logging.getLogger(__name__)  # Add this line to define the logger


class WorkflowExecutionException(Exception):
    pass


WORKFLOWS_BUCKET = os.getenv("WORKFLOWS_BUCKET", "workflows-bucket")


class JobSaver:
    def __init__(self, s3_client: Any) -> None:
        self.s3_client = s3_client

    def record_owner(
        self,
        response: requests.Response,
        workflow_id: str,
        deploy_workspace: str,
        calling_workspace: str,
        workflow_type: WorkflowType = WorkflowType.WORKFLOW,
    ) -> None:
        """Record workspace of job owner"""
        try:
            job_id = response.json()["jobID"]
        except KeyError as e:
            logger.error("KeyError: %s", e)
            raise WorkflowExecutionException("Job ID not found in response") from e

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

    def get_job_details(self, workspace: str, job_id: str) -> dict[str, Any]:
        """Get job owner from S3 job details"""
        logger.debug(
            "Identifying job details in bucket %s and key %s",
            WORKFLOWS_BUCKET,
            f"{workspace}/{job_id}",
        )
        try:
            job_details = self.s3_client.get_object(
                Bucket=WORKFLOWS_BUCKET,
                Key=f"{workspace}/{job_id}",
            )
        except self.s3_client.exceptions.NoSuchKey:
            logger.error("Job details not found for job %s in workspace %s", job_id, workspace)
            return {}
        return json.loads(job_details.get("Body").read().decode("utf-8"))

    def get_job_owner(self, workspace: str, job_id: str) -> str | None:
        job_details = self.get_job_details(workspace, job_id)
        return job_details["calling_workspace"] if job_details else None
