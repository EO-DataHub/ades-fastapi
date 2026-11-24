"""Write caller index records for cross-workspace jobs that started before the index existed.

Run ``python -m ades_fastapi.backfill_caller_index`` for a dry run, then add ``--apply`` to write.
"""

import argparse
import json
import logging
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .job_saver import CALLER_INDEX_PREFIX, WORKFLOWS_BUCKET, caller_index_key

logger = logging.getLogger(__name__)


@dataclass
class Counts:
    read: int = 0
    same_workspace: int = 0
    already_indexed: int = 0
    written: int = 0
    failed: int = 0


def _list_objects(s3_client: Any, prefix: str = "") -> Iterator[dict[str, Any]]:
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=WORKFLOWS_BUCKET, Prefix=prefix):
        yield from page.get("Contents", [])


def _indexed_owner_keys(s3_client: Any) -> set[str]:
    """Owner keys (``deploy_workspace/job_id``) that already have an index record."""
    indexed = set()
    for obj in _list_objects(s3_client, CALLER_INDEX_PREFIX):
        # _by-caller/{calling_workspace}/{reverse_ms}/{deploy_workspace}/{job_id}
        parts = obj["Key"][len(CALLER_INDEX_PREFIX) :].split("/", 2)
        if len(parts) == 3:
            indexed.add(parts[2])
    return indexed


def backfill(s3_client: Any, apply: bool) -> Counts:
    counts = Counts()
    indexed = _indexed_owner_keys(s3_client)

    for obj in _list_objects(s3_client):
        owner_key: str = obj["Key"]
        if owner_key.startswith("_"):
            continue
        if owner_key in indexed:
            counts.already_indexed += 1
            continue

        deploy_workspace, sep, job_id = owner_key.partition("/")
        if not sep or not job_id:
            logger.warning("Skipping key %s: not an owner record", owner_key)
            continue

        try:
            response = s3_client.get_object(Bucket=WORKFLOWS_BUCKET, Key=owner_key)
            body = response["Body"].read()
        except (BotoCoreError, ClientError):
            logger.error("Failed to read owner record %s", owner_key, exc_info=True)
            counts.failed += 1
            continue
        counts.read += 1

        try:
            details = json.loads(body)
            calling_workspace = details["calling_workspace"]
            same_workspace = details["deploy_workspace"] == calling_workspace
        except (ValueError, KeyError, TypeError):
            logger.error("Owner record %s has no deploy or calling workspace", owner_key, exc_info=True)
            counts.failed += 1
            continue

        if same_workspace:
            counts.same_workspace += 1
            continue

        epoch_ms = int(obj["LastModified"].timestamp() * 1000)
        index_key = caller_index_key(calling_workspace, epoch_ms, deploy_workspace, job_id)

        if not apply:
            print(f"would write {index_key}")
            counts.written += 1
            continue

        try:
            s3_client.put_object(
                Bucket=WORKFLOWS_BUCKET,
                Key=index_key,
                Body=body,
                ContentType="application/json",
            )
        except (BotoCoreError, ClientError):
            logger.error("Failed to write index record %s", index_key, exc_info=True)
            counts.failed += 1
            continue
        print(f"wrote {index_key}")
        counts.written += 1

    return counts


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m ades_fastapi.backfill_caller_index",
        description="Write caller index records for existing cross-workspace jobs.",
    )
    parser.add_argument("--apply", action="store_true", help="write the index records (default is a dry run)")
    args = parser.parse_args(argv)

    s3_client = boto3.client("s3")
    counts = backfill(s3_client, args.apply)

    if not args.apply:
        print("Dry run: no changes made. Add --apply to store the index records.")
    print(f"owner records read: {counts.read}")
    print(f"same-workspace jobs skipped: {counts.same_workspace}")
    print(f"already indexed: {counts.already_indexed}")
    print(f"index records {'written' if args.apply else 'to write'}: {counts.written}")
    print(f"failed: {counts.failed}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main(sys.argv[1:])
