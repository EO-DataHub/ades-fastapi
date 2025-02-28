import json
from unittest import mock
from unittest.mock import patch

import pytest
from requests.models import Response

from ades_fastapi.job_saver import JobSaver, WorkflowExecutionException
from ades_fastapi.utils import WorkflowType


@pytest.fixture
def job_saver():
    mock_client_instance = mock.Mock()
    return JobSaver(mock_client_instance)


@patch("boto3.client")
def test_record_owner_success(mock_client, job_saver):
    response = mock.Mock(spec=Response)
    response.json.side_effect = [
        {"jobID": "11111"},
        {"jobID": "22222"},
        {"jobID": "33333"},
        {"jobID": "44444"},
    ]
    job_saver.record_owner(response, "workflow_id", "deploy_workspace_1", "calling_workspace")

    assert job_saver.s3_client.put_object.call_count == 1
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

    assert job_saver.s3_client.put_object.call_count == 2
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
    assert job_saver.s3_client.put_object.call_count == 3
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
    assert job_saver.s3_client.put_object.call_count == 4
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


def test_record_owner_key_error(job_saver):
    response = mock.Mock(spec=Response)
    response.json.return_value = {}

    with pytest.raises(WorkflowExecutionException, match="Job ID not found in response"):
        job_saver.record_owner(response, "workflow_id", "deploy_workspace", "calling_workspace")
