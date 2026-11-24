import importlib
import json
import re
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from ades_fastapi.job_saver import WORKFLOWS_BUCKET


def run_backfill(*args: str) -> None:
    module = importlib.import_module("ades_fastapi.backfill_caller_index")
    module.main(list(args))


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


def count(output: str, word: str) -> int:
    """The number on the printed counts line that contains `word` (key lines have slashes)."""
    lines = [line for line in output.splitlines() if re.search(rf"\b{word}", line, re.IGNORECASE) and "/" not in line]
    return int(re.findall(r"\d+", lines[-1])[-1])


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


def test_stage4_cross_workspace_owner_record_gets_index_from_last_modified(s3: Any) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))

    run_backfill("--apply")

    index_key = expected_index_key(s3, "publisher/job-1", "caller")
    assert keys(s3, "_by-caller/") == [index_key]
    assert body_of(s3, index_key) == body_of(s3, "publisher/job-1")


def test_stage4_same_workspace_owner_record_writes_nothing(s3: Any) -> None:
    put(s3, "caller/job-1", owner_body("job-1", "caller", "caller"))

    run_backfill("--apply")

    assert keys(s3, "_by-caller/") == []


def test_stage4_already_indexed_job_writes_nothing(s3: Any) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))
    existing = "_by-caller/caller/8235000000001/publisher/job-1"
    put(s3, existing, owner_body("job-1", "publisher", "caller"))

    run_backfill("--apply")

    assert keys(s3, "_by-caller/") == [existing]


def test_stage4_underscore_keys_are_not_read_as_owner_records(s3: Any, capsys: pytest.CaptureFixture[str]) -> None:
    put(s3, "_scratch/job-9", owner_body("job-9", "publisher", "caller"))
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))

    run_backfill("--apply")

    index_keys = keys(s3, "_by-caller/")
    assert [key.rsplit("/", 1)[1] for key in index_keys] == ["job-1"]
    assert count(capsys.readouterr().out, "read") == 1


def test_stage4_dry_run_writes_nothing_and_prints_counts(s3: Any, capsys: pytest.CaptureFixture[str]) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))
    put(s3, "publisher/job-2", owner_body("job-2", "publisher", "caller"))
    put(s3, "publisher/job-3", owner_body("job-3", "publisher", "publisher"))
    put(s3, "publisher/job-4", owner_body("job-4", "publisher", "caller"))
    put(s3, "_by-caller/caller/8235000000001/publisher/job-4", owner_body("job-4", "publisher", "caller"))
    before = keys(s3)

    run_backfill()

    assert keys(s3) == before
    out = capsys.readouterr().out
    assert expected_index_key(s3, "publisher/job-1", "caller") in out
    assert count(out, "same") == 1
    assert count(out, "already") == 1
    assert count(out, "writ") == 2
    assert count(out, "fail") == 0


def test_stage4_failure_on_one_record_is_counted_and_others_are_written(
    s3: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))
    put(s3, "publisher/job-bad", owner_body("job-bad", "publisher", "caller"))
    put(s3, "publisher/job-3", owner_body("job-3", "publisher", "caller"))
    real_client = boto3.client

    def client_failing_one_read(*args: Any, **kwargs: Any) -> Any:
        client = real_client(*args, **kwargs)
        get_object = client.get_object

        def failing_get_object(**params: Any) -> Any:
            if params["Key"] == "publisher/job-bad":
                raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject")
            return get_object(**params)

        client.get_object = failing_get_object  # pyright: ignore[reportAttributeAccessIssue]
        return client

    monkeypatch.setattr(boto3, "client", client_failing_one_read)

    run_backfill("--apply")

    assert sorted(key.rsplit("/", 1)[1] for key in keys(s3, "_by-caller/")) == ["job-1", "job-3"]
    out = capsys.readouterr().out
    assert count(out, "fail") == 1
    assert count(out, "writ") == 2


def test_stage4_second_run_after_apply_writes_nothing(s3: Any, capsys: pytest.CaptureFixture[str]) -> None:
    put(s3, "publisher/job-1", owner_body("job-1", "publisher", "caller"))
    put(s3, "other/job-2", owner_body("job-2", "other", "caller"))
    run_backfill("--apply")
    first_index_keys = keys(s3, "_by-caller/")
    capsys.readouterr()

    run_backfill("--apply")

    assert keys(s3, "_by-caller/") == first_index_keys
    out = capsys.readouterr().out
    assert count(out, "writ") == 0
    assert count(out, "already") == 2
