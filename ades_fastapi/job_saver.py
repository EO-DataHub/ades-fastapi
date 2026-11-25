import json
import logging
import os
import re
import time
from typing import Any

import requests
from botocore.exceptions import BotoCoreError, ClientError

from .utils import WorkflowType

logger = logging.getLogger(__name__)  # Add this line to define the logger


class WorkflowExecutionException(Exception):
    pass


WORKFLOWS_BUCKET = os.getenv("WORKFLOWS_BUCKET", "workflows-bucket")

CALLER_INDEX_PREFIX = "_by-caller/"
_REVERSE_MS_BASE = 9999999999999


def reverse_ms(epoch_ms: int) -> str:
    """Return a 13-digit key component that sorts newer times first."""
    return f"{_REVERSE_MS_BASE - epoch_ms:013d}"


# The caller index key layout is defined here and nowhere else:
#   _by-caller/{calling_workspace}/{reverse_ms}/{deploy_workspace}/{job_id}
# The part after the calling workspace is also the `after` cursor for scope=called.
_CALLED_AFTER_PATTERN = re.compile(r"\d{13}/([^/]+)/([^/]+)")
_CALLER_INDEX_KEY_PATTERN = re.compile(rf"{re.escape(CALLER_INDEX_PREFIX)}([^/]+)/({_CALLED_AFTER_PATTERN.pattern})")


def caller_index_key(calling_workspace: str, epoch_ms: int, deploy_workspace: str, job_id: str) -> str:
    return f"{CALLER_INDEX_PREFIX}{calling_workspace}/{reverse_ms(epoch_ms)}/{deploy_workspace}/{job_id}"


def is_valid_called_after(after: str) -> bool:
    """Whether `after` has the shape of a scope=called cursor."""
    return _CALLED_AFTER_PATTERN.fullmatch(after) is not None


def owner_key_from_caller_index_key(key: str) -> str | None:
    """The owner record key (``deploy_workspace/job_id``) an index key points at; None if malformed."""
    match = _CALLER_INDEX_KEY_PATTERN.fullmatch(key)
    if match is None:
        return None
    _calling_workspace, _cursor, deploy_workspace, job_id = match.groups()
    return f"{deploy_workspace}/{job_id}"


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

        body = json.dumps(job_details)
        self.s3_client.put_object(
            Bucket=WORKFLOWS_BUCKET,
            Key=f"{deploy_workspace}/{job_id}",
            Body=body,
            ContentType="application/json",
        )

        if deploy_workspace != calling_workspace:
            index_key = caller_index_key(calling_workspace, time.time_ns() // 1_000_000, deploy_workspace, job_id)
            try:
                self.s3_client.put_object(
                    Bucket=WORKFLOWS_BUCKET,
                    Key=index_key,
                    Body=body,
                    ContentType="application/json",
                )
            except (BotoCoreError, ClientError):
                logger.warning("Failed to write caller index record %s for job %s", index_key, job_id, exc_info=True)

    def list_called(
        self, calling_workspace: str, limit: int, after: str | None
    ) -> tuple[list[tuple[str, str]], str | None]:
        """One page of the caller index for a workspace, newest first.

        Returns the ``(deploy_workspace, job_id)`` pairs on the page, and the cursor for the next
        page, or None on the last page. Raises botocore errors if the listing fails.
        """
        prefix = f"{CALLER_INDEX_PREFIX}{calling_workspace}/"
        list_kwargs: dict[str, Any] = {"Bucket": WORKFLOWS_BUCKET, "Prefix": prefix, "MaxKeys": limit}
        if after:
            # StartAfter is a full key, so it needs the prefix too
            list_kwargs["StartAfter"] = f"{prefix}{after}"
        listing = self.s3_client.list_objects_v2(**list_kwargs)

        targets: list[tuple[str, str]] = []
        last_cursor: str | None = None
        for obj in listing.get("Contents", []):
            key = obj["Key"]
            cursor = key[len(prefix) :]
            match = _CALLED_AFTER_PATTERN.fullmatch(cursor)
            if match is None:
                logger.warning("Skipping malformed caller index key %s", key)
                continue
            deploy_workspace, job_id = match.groups()
            targets.append((deploy_workspace, job_id))
            last_cursor = cursor

        if not listing.get("IsTruncated"):
            return targets, None
        if last_cursor is None:
            logger.warning(
                "No well-formed caller index key on a truncated page for workspace %s, omitting next link",
                calling_workspace,
            )
        return targets, last_cursor

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
