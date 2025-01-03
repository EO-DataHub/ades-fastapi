import json
from unittest import mock
from unittest.mock import patch

import pytest
from requests.models import Response

from ades_fastapi.job_saver import JobSaver, WorkflowExecutionException


@pytest.fixture
def job_saver(tmpdir):
    return JobSaver(storage_dir=tmpdir)


def test_record_owner_success(job_saver):
    response = mock.Mock(spec=Response)
    response.json.return_value = {"jobID": "12345"}
    job_saver.record_owner(response, "deploy_workspace_1", "calling_workspace")

    assert job_saver.job_owners == {"deploy_workspace_1-12345": "calling_workspace"}
    assert job_saver.workspace_jobs == {
        "calling_workspace": [{"deploy_workspace": "deploy_workspace_1", "jobID": "12345"}]
    }

    # And update again
    job_saver.record_owner(response, "deploy_workspace_2", "calling_workspace_2")
    assert job_saver.job_owners == {
        "deploy_workspace_1-12345": "calling_workspace",
        "deploy_workspace_2-12345": "calling_workspace_2",
    }
    assert job_saver.workspace_jobs == {
        "calling_workspace": [{"deploy_workspace": "deploy_workspace_1", "jobID": "12345"}],
        "calling_workspace_2": [{"deploy_workspace": "deploy_workspace_2", "jobID": "12345"}],
    }

    # And one more in the first workspace
    job_saver.record_owner(response, "deploy_workspace_3", "calling_workspace")
    assert job_saver.job_owners == {
        "deploy_workspace_1-12345": "calling_workspace",
        "deploy_workspace_2-12345": "calling_workspace_2",
        "deploy_workspace_3-12345": "calling_workspace",
    }
    assert job_saver.workspace_jobs == {
        "calling_workspace": [
            {"deploy_workspace": "deploy_workspace_1", "jobID": "12345"},
            {"deploy_workspace": "deploy_workspace_3", "jobID": "12345"},
        ],
        "calling_workspace_2": [{"deploy_workspace": "deploy_workspace_2", "jobID": "12345"}],
    }


def test_record_owner_key_error(job_saver):
    response = mock.Mock(spec=Response)
    response.json.return_value = {}

    with pytest.raises(WorkflowExecutionException, match="Job ID not found in response"):
        job_saver.record_owner(response, "deploy_workspace", "calling_workspace")


def test_save_to_file(job_saver, tmpdir):
    job_saver.job_owners = {"deploy_workspace-12345": "calling_workspace"}
    job_saver.workspace_jobs = {
        "calling_workspace": [{"deploy_workspace": "deploy_workspace", "jobID": "12345"}]
    }
    job_saver.save_to_file()

    with open(f"{tmpdir}/job-owners.json", "r") as f:
        job_owners = json.load(f)
    with open(f"{tmpdir}/workspace-jobs.json", "r") as f:
        workspace_jobs = json.load(f)

    assert job_owners == {"deploy_workspace-12345": "calling_workspace"}
    assert workspace_jobs == {
        "calling_workspace": [{"deploy_workspace": "deploy_workspace", "jobID": "12345"}]
    }


def test_load_data(job_saver, tmpdir):
    job_owners = {"deploy_workspace-12345": "calling_workspace"}
    workspace_jobs = {
        "calling_workspace": [{"deploy_workspace": "deploy_workspace", "jobID": "12345"}]
    }

    with open(f"{tmpdir}/job-owners.json", "w") as f:
        json.dump(job_owners, f)
    with open(f"{tmpdir}/workspace-jobs.json", "w") as f:
        json.dump(workspace_jobs, f)

    job_saver.load_data()

    assert job_saver.job_owners == job_owners
    assert job_saver.workspace_jobs == workspace_jobs


@patch("ades_fastapi.job_saver.JobSaver.save_to_file")
def test_update_job_owners(mock_save_to_file, job_saver):
    mock_save_to_file.return_value = None
    job_saver.update_job_owners("deploy_workspace", "calling_workspace", "12345")

    assert job_saver.job_owners == {"deploy_workspace-12345": "calling_workspace"}
    assert job_saver.workspace_jobs == {
        "calling_workspace": [{"deploy_workspace": "deploy_workspace", "jobID": "12345"}]
    }

    mock_save_to_file.assert_called_once()
