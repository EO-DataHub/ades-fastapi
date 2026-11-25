import importlib
import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from ades_fastapi.backfill_caller_index import Counts, backfill, main
from ades_fastapi.job_saver import WORKFLOWS_BUCKET


def owner_body(job_id: str, deploy_workspace: str, calling_workspace: str) -> str:
    return json.dumps(
        {
            "jobID": job_id,
            "workflow_id": "workflow_id",
            "workflow_type": "workflow",
            "deploy_workspace": deploy_workspace,
            "calling_workspace": calling_workspace,
        }
    )


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket=WORKFLOWS_BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-west-2"})
        yield client


def put(s3: Any, key: str, body: str) -> None:
    s3.put_object(Bucket=WORKFLOWS_BUCKET, Key=key, Body=body, ContentType="application/json")


def keys(s3: Any, prefix: str = "") -> list[str]:
    listing = s3.list_objects_v2(Bucket=WORKFLOWS_BUCKET, Prefix=prefix)
    return [obj["Key"] for obj in listing.get("Contents", [])]


def expected_index_key(s3: Any, owner_key: str, calling_workspace: str) -> str:
    [obj] = s3.list_objects_v2(Bucket=WORKFLOWS_BUCKET, Prefix=owner_key)["Contents"]
    reverse_ms = 9999999999999 - int(obj["LastModified"].timestamp() * 1000)
    return f"_by-caller/{calling_workspace}/{reverse_ms:013d}/{owner_key}"


def body_of(s3: Any, key: str) -> str:
    return s3.get_object(Bucket=WORKFLOWS_BUCKET, Key=key)["Body"].read().decode("utf-8")


def test_backfill_writes_caller_index_from_last_modified(s3: Any) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))

    counts = backfill(s3, apply=True)

    assert counts == Counts(read=1, written=1)
    index_key = expected_index_key(s3, "publisher/job-1", "caller")
    assert keys(s3, "_by-caller/") == [index_key]
    assert body_of(s3, index_key) == body_of(s3, "publisher/job-1")


def test_backfill_same_workspace_job_writes_nothing(s3: Any) -> None:
    put(s3, "caller/job-1", owner_body("job-1", "caller", "caller"))

    counts = backfill(s3, apply=True)

    assert counts == Counts(read=1, same_workspace=1)
    assert keys(s3, "_by-caller/") == []


def test_backfill_already_indexed_job_writes_nothing(s3: Any) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))
    existing = "_by-caller/caller/8235000000001/publisher/job-1"
    put(s3, existing, owner_body("job-1", "publisher", "caller"))

    counts = backfill(s3, apply=True)

    assert counts == Counts(already_indexed=1)
    assert keys(s3, "_by-caller/") == [existing]


def test_backfill_skips_underscore_keys(s3: Any) -> None:
    put(s3, "_scratch/job-9", owner_body("job-9", "publisher", "caller"))
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))

    counts = backfill(s3, apply=True)

    index_keys = keys(s3, "_by-caller/")
    assert [key.rsplit("/", 1)[1] for key in index_keys] == ["job-1"]
    assert counts == Counts(read=1, written=1)


def test_backfill_counts_failure_and_writes_others(s3: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))
    put(s3, "publisher/job-bad", owner_body("job-bad", "publisher", "caller"))
    put(s3, "publisher/job-3", owner_body("job-3", "publisher", "caller"))
    get_object = s3.get_object

    def failing_get_object(**params: Any) -> Any:
        if params["Key"] == "publisher/job-bad":
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject")
        return get_object(**params)

    monkeypatch.setattr(s3, "get_object", failing_get_object)

    counts = backfill(s3, apply=True)

    assert sorted(key.rsplit("/", 1)[1] for key in keys(s3, "_by-caller/")) == ["job-1", "job-3"]
    assert counts == Counts(read=2, written=2, failed=1)


def test_backfill_dry_run_then_apply_twice(s3: Any) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))
    put(s3, "other/job-2", owner_body("job-2", "other", "caller"))
    put(s3, "publisher/job-3", owner_body("job-3", "publisher", "publisher"))
    put(s3, "publisher/job-4", owner_body("job-4", "publisher", "caller"))
    put(s3, "_by-caller/caller/8235000000001/publisher/job-4", owner_body("job-4", "publisher", "caller"))
    before = keys(s3)

    # Dry run: counts what it would write and writes nothing.
    counts = backfill(s3, apply=False)

    assert keys(s3) == before
    assert counts == Counts(read=3, same_workspace=1, already_indexed=1, written=2)

    # First apply writes the two missing index records.
    counts = backfill(s3, apply=True)

    first_index_keys = keys(s3, "_by-caller/")
    assert len(first_index_keys) == 3
    assert counts == Counts(read=3, same_workspace=1, already_indexed=1, written=2)

    # Second apply finds every job already indexed and writes nothing.
    counts = backfill(s3, apply=True)

    assert keys(s3, "_by-caller/") == first_index_keys
    assert counts == Counts(read=1, same_workspace=1, already_indexed=3)


def test_main_dry_run_prints_keys_and_summary(s3: Any, capsys: pytest.CaptureFixture[str]) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))
    put(s3, "publisher/job-2", owner_body("job-2", "publisher", "publisher"))
    before = keys(s3)

    main([])

    assert keys(s3) == before
    out = capsys.readouterr().out.splitlines()
    assert out == [
        f"would write {expected_index_key(s3, 'publisher/job-1', 'caller')}",
        "Dry run: no changes made. Add --apply to store the index records.",
        "owner records read: 2",
        "same-workspace jobs skipped: 1",
        "already indexed: 0",
        "index records to write: 1",
        "failed: 0",
    ]


def test_backfill_does_not_reindex_job_started_during_run(s3: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))
    live_index = "_by-caller/caller/8235000000001/publisher/job-1"
    module = importlib.import_module("ades_fastapi.backfill_caller_index")
    list_objects = module._list_objects

    def list_then_start_job(s3_client: Any, prefix: str = "") -> Iterator[dict[str, Any]]:
        yield from list_objects(s3_client, prefix)
        if prefix == "":
            # The live code indexes job-1 while the backfill is running
            put(s3, live_index, owner_body("job-1", "publisher", "caller"))

    monkeypatch.setattr(module, "_list_objects", list_then_start_job)

    backfill(s3, apply=True)

    assert keys(s3, "_by-caller/") == [live_index]
