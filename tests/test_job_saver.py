import json
import logging
import re
import time
from typing import Any
from unittest import mock
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from requests.models import Response

from ades_fastapi.job_saver import JobSaver, WorkflowExecutionException
from ades_fastapi.utils import WorkflowType


def _put_kwargs(job_saver: JobSaver) -> list[dict[str, Any]]:
    return [c.kwargs for c in job_saver.s3_client.put_object.call_args_list]


def _owner_puts(job_saver: JobSaver) -> list[dict[str, Any]]:
    return [kw for kw in _put_kwargs(job_saver) if not kw["Key"].startswith("_")]


def _index_puts(job_saver: JobSaver) -> list[dict[str, Any]]:
    return [kw for kw in _put_kwargs(job_saver) if kw["Key"].startswith("_by-caller/")]


def _job_response(job_id: str) -> mock.Mock:
    response = mock.Mock(spec=Response)
    response.json.return_value = {"jobID": job_id}
    return response


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


@pytest.fixture
def job_saver() -> JobSaver:
    mock_client_instance = mock.Mock()
    return JobSaver(mock_client_instance)


@patch("boto3.client")
def test_record_owner_success(mock_client: mock.MagicMock, job_saver: JobSaver) -> None:
    response = mock.Mock(spec=Response)
    response.json.side_effect = [
        {"jobID": "11111"},
        {"jobID": "22222"},
        {"jobID": "33333"},
        {"jobID": "44444"},
    ]
    job_saver.record_owner(response, "workflow_id", "deploy_workspace_1", "calling_workspace")

    assert len(_owner_puts(job_saver)) == 1
    job_saver.s3_client.put_object.assert_any_call(
        Bucket="workflows-bucket",
        Key="deploy_workspace_1/11111",
        Body=json.dumps(
            {
                "jobID": "11111",
                "workflow_id": "workflow_id",
                "workflow_type": "workflow",
                "deploy_workspace": "deploy_workspace_1",
                "calling_workspace": "calling_workspace",
            }
        ),
        ContentType="application/json",
    )

    # And update again
    job_saver.record_owner(response, "workflow_id", "deploy_workspace_2", "calling_workspace_2")

    assert len(_owner_puts(job_saver)) == 2
    job_saver.s3_client.put_object.assert_any_call(
        Bucket="workflows-bucket",
        Key="deploy_workspace_2/22222",
        Body=json.dumps(
            {
                "jobID": "22222",
                "workflow_id": "workflow_id",
                "workflow_type": "workflow",
                "deploy_workspace": "deploy_workspace_2",
                "calling_workspace": "calling_workspace_2",
            }
        ),
        ContentType="application/json",
    )

    # And one more in the first workspace
    job_saver.record_owner(response, "workflow_id", "deploy_workspace_3", "calling_workspace")
    assert len(_owner_puts(job_saver)) == 3
    job_saver.s3_client.put_object.assert_any_call(
        Bucket="workflows-bucket",
        Key="deploy_workspace_3/33333",
        Body=json.dumps(
            {
                "jobID": "33333",
                "workflow_id": "workflow_id",
                "workflow_type": "workflow",
                "deploy_workspace": "deploy_workspace_3",
                "calling_workspace": "calling_workspace",
            }
        ),
        ContentType="application/json",
    )

    # And one more in the first workspace but this time a user service
    job_saver.record_owner(
        response,
        "workflow_id",
        "deploy_workspace_4",
        "calling_workspace_4",
        WorkflowType.USER_SERVICE,
    )
    assert len(_owner_puts(job_saver)) == 4
    job_saver.s3_client.put_object.assert_any_call(
        Bucket="workflows-bucket",
        Key="deploy_workspace_4/44444",
        Body=json.dumps(
            {
                "jobID": "44444",
                "workflow_id": "workflow_id",
                "workflow_type": "user-service",
                "deploy_workspace": "deploy_workspace_4",
                "calling_workspace": "calling_workspace_4",
            }
        ),
        ContentType="application/json",
    )


def test_record_owner_key_error(job_saver: JobSaver) -> None:
    response = mock.Mock(spec=Response)
    response.json.return_value = {}

    with pytest.raises(WorkflowExecutionException, match="Job ID not found in response"):
        job_saver.record_owner(response, "workflow_id", "deploy_workspace", "calling_workspace")


def test_record_owner_writes_caller_index_for_cross_workspace_job(job_saver: JobSaver) -> None:
    before_ms = _now_ms()
    job_saver.record_owner(_job_response("11111"), "workflow_id", "publisher", "caller")
    after_ms = _now_ms()

    expected_body = json.dumps(
        {
            "jobID": "11111",
            "workflow_id": "workflow_id",
            "workflow_type": "workflow",
            "deploy_workspace": "publisher",
            "calling_workspace": "caller",
        }
    )
    [owner] = _owner_puts(job_saver)
    assert owner["Bucket"] == "workflows-bucket"
    assert owner["Key"] == "publisher/11111"
    assert owner["Body"] == expected_body

    [index] = _index_puts(job_saver)
    assert index["Bucket"] == "workflows-bucket"
    assert index["Body"] == expected_body
    match = re.fullmatch(r"_by-caller/caller/(\d{13})/publisher/11111", index["Key"])
    assert match, index["Key"]
    started_ms = 9999999999999 - int(match.group(1))
    assert before_ms <= started_ms <= after_ms


def test_record_owner_same_workspace_job_writes_no_caller_index(job_saver: JobSaver) -> None:
    job_saver.record_owner(_job_response("11111"), "workflow_id", "caller", "caller")

    assert [kw["Key"] for kw in _put_kwargs(job_saver)] == ["caller/11111"]


def test_record_owner_writes_caller_index_for_user_service_job(job_saver: JobSaver) -> None:
    job_saver.record_owner(_job_response("11111"), "service_id", "provider", "caller", WorkflowType.USER_SERVICE)

    [index] = _index_puts(job_saver)
    assert re.fullmatch(r"_by-caller/caller/\d{13}/provider/11111", index["Key"])
    assert json.loads(index["Body"])["workflow_type"] == "user-service"


def test_record_owner_logs_caller_index_write_failure(job_saver: JobSaver, caplog: pytest.LogCaptureFixture) -> None:
    def put_object(**kwargs: Any) -> dict[str, Any]:
        if kwargs["Key"].startswith("_by-caller/"):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "PutObject")
        return {}

    job_saver.s3_client.put_object.side_effect = put_object

    with caplog.at_level(logging.WARNING):
        job_saver.record_owner(_job_response("11111"), "workflow_id", "publisher", "caller")

    assert [kw["Key"] for kw in _owner_puts(job_saver)] == ["publisher/11111"]
    assert any(r.levelno >= logging.WARNING and r.name.startswith("ades_fastapi") for r in caplog.records)


def test_record_owner_caller_index_sorts_newest_first(job_saver: JobSaver) -> None:
    job_saver.record_owner(_job_response("older"), "workflow_id", "publisher", "caller")
    time.sleep(0.002)
    job_saver.record_owner(_job_response("newer"), "workflow_id", "publisher", "caller")

    keys = sorted(kw["Key"] for kw in _index_puts(job_saver))
    assert [key.rsplit("/", 1)[1] for key in keys] == ["newer", "older"]
