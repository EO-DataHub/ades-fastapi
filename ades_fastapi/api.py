import logging
import os
from distutils.util import strtobool
from typing import List, Literal, Optional

import boto3
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .ades_client import ADESClient
from .dependency_client import DependencyClient
from .job_saver import JobSaver
from .models import (
    DeleteJobResponse,
    DeployProcessResponse,
    EmptyResponse,
    ExecuteProcessResponse,
    GetAllJobStatusResponse,
    GetJobResultsResponse,
    GetJobStatusResponse,
    GetProcessResponse,
    ListProcessesResponse,
    PingResponse,
)
from .utils import WorkflowType, get_user_details

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)  # Add this line to define the logger

# Ingress path for ADES
ADES_INGRESS_PATH = os.getenv("ADES_INGRESS_PATH", "https://example-path")

# OPA service endpoint
OPA_SERVICE_ENDPOINT = os.getenv(
    "OPA_SERVICE_ENDPOINT", "http://opal-client.opal:8181/v1/data/ades/allow"
)

# Root path for FastAPI
ADES_FASTAPI_ROOT_PATH = os.getenv("ADES_FASTAPI_ROOT_PATH", "/api/catalogue/stac")
API_DOCS_ROOT = os.getenv("API_DOCS_ROOT", "/api/docs")

# ADES service endpoint
ADES_SERVICE_ENDPOINT = os.getenv("ADES_SERVICE_ENDPOINT", "http://zoo-project-dru-service:80")

# Used for local testing where OPA is not available
ENABLE_OPA_POLICY_CHECK = strtobool(os.getenv("ENABLE_OPA_POLICY_CHECK", "true"))

# Root Catalogs for processes
PUBLIC_CATALOG_ROOT = os.getenv("PUBLIC_CATALOG_ROOT", "public")
USER_CATALOG_ROOT = os.getenv("USER_CATALOG_ROOT", "user")

# ADES Policy bucket name
ADES_POLICY_BUCKET = os.getenv("ADES_POLICY_BUCKET", "ades-policy")

# ADES policy prefix
ADES_POLICY_PREFIX = os.getenv("ADES_POLICY_PREFIX", "")

app = FastAPI(
    title="EODHP ADES",
    description="This is the Application, Deployment and Execution Service (ADES) for the EODHP project.\n"
    "The following endpoints are currently implemented.",
    version="0.1.0",
    docs_url=f"{API_DOCS_ROOT}/workflow-runner",
    openapi_url=f"{API_DOCS_ROOT}/workflow-runner/openapi.json",
)

logger.info(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs"
)

# Define static file path
static_filepath = os.getenv("STATIC_FILE_PATH", "static")

# Mount static files with STAC FastApi
app.mount("/static", StaticFiles(directory=static_filepath), name="static")


def configure_job_saver():
    """Configure the job saver"""
    s3_client = boto3.client("s3")
    return JobSaver(s3_client)


# Create clients used by the API
job_saver = configure_job_saver()

ades_client = ADESClient(
    ADES_SERVICE_ENDPOINT,
    ADES_INGRESS_PATH,
    ADES_POLICY_BUCKET,
    ADES_POLICY_PREFIX,
    USER_CATALOG_ROOT,
)

dependency_client = DependencyClient(
    ADES_FASTAPI_ROOT_PATH,
    OPA_SERVICE_ENDPOINT,
    ADES_POLICY_BUCKET,
    ADES_POLICY_PREFIX,
    ENABLE_OPA_POLICY_CHECK,
)

# Create rate-limiting storage
workspace_rates = {}


bearer_scheme = HTTPBearer(auto_error=False)


def opa_dependency(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),  # noqa: B008
) -> WorkflowType:
    """Dependency to check if the user is authorized to access the endpoint"""
    passed, wf_type = dependency_client.check_access(request, job_saver)

    if not passed:
        if not get_user_details(request)[0]:
            # User not authenticated
            raise HTTPException(status_code=401, detail="Not Authenticated")
        else:
            # User is not authorized
            raise HTTPException(status_code=403, detail="Not Authorized")

    return wf_type


@app.get(
    f"{API_DOCS_ROOT}/workflow-runner/ping",
    summary="Ping the Workflow Runner API",
    description="A status endpoint for the Workflow Runner API to check the availability of the service",
    response_model=PingResponse,
    responses={
        200: {
            "description": "Service is reachable and returned 'PONG'",
        },
        502: {"description": "Service is not reachable"},
    },
)
def ping():
    """A status endpoint for the Workflow Runner API to check the availability of the service"""
    logger.info("Getting Workflow Runner PING endpoint")
    response = ades_client.get_root()
    if response.status_code == 200:
        return {"status": "PONG"}
    else:
        return Response(
            content={"status": "Failed to connect to ADES"},
            status_code=502,
        )


@app.delete(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes/{{workflow_id}}",
    dependencies=[Depends(opa_dependency)],
    summary="Undeploy a workflow from the given workspace",
    response_model=EmptyResponse,
    responses={
        204: {"description": "Workflow removed from the workspace successfully"},
        404: {"description": "Workflow not deployed to the given workspace"},
        401: {"description": "User not authenticated"},
        403: {"description": "User not authorized to make changes in this workspace"},
    },
)
def undeploy_process(deploy_workspace: str, workflow_id: str, request: Request):
    """An endpoint to undeploy a workflow from the specified workspace"""
    logger.info("Undeploying workflow %s in workspace %s", workflow_id, deploy_workspace)

    response, content = ades_client.undeploy_workflow(
        dict(request.headers), deploy_workspace, workflow_id
    )

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


@app.get(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes",
    dependencies=[Depends(opa_dependency)],
    summary="List all available workflows in the given workspace",
    response_model=ListProcessesResponse,
    responses={
        200: {
            "description": "Workflows available in the specified workspace are returned in a list"
        },
        401: {"description": "User not authenticated"},
    },
)
def list_processes(
    deploy_workspace: str, request: Request, limit: Optional[int] = None, skip: int = 0
):
    """Endpoint to list all workflows deployed in a workspace"""
    logger.info("Listing workflows in workspace %s", deploy_workspace)

    response, content = ades_client.list_processes(
        request, deploy_workspace, limit=limit, skip=skip
    )

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


@app.post(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes",
    dependencies=[Depends(opa_dependency)],
    summary="Deploy a workflow to the specified workspace",
    response_model=DeployProcessResponse,
    responses={
        201: {"description": "Workflow created in the workspace successfully"},
        400: {"description": "Invalid request"},
        409: {"description": "Workflow with the same ID already deployed to the workspace"},
        401: {"description": "User not authenticated"},
        403: {"description": "User not authorized to make changes in this workspace"},
    },
)
async def deploy_workflow(
    deploy_workspace: str,
    request: Request,
):
    """Endpoint to deploy a workflow to a workspace"""
    response, content = await ades_client.deploy_workflow(request, deploy_workspace)

    return Response(
        content=content,
        status_code=response.status_code,
        headers=response.headers,
    )


@app.put(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes/{{workflow_id}}",
    dependencies=[Depends(opa_dependency)],
    summary="Update a workflow in the given workspace",
    response_model=EmptyResponse,
    responses={
        204: {"description": "Workflow updated in the workspace successfully"},
        404: {"description": "Workflow has not been deployed to the given workspace"},
        401: {"description": "User not authenticated"},
        403: {"description": "User not authorized to make changes in this workspace"},
    },
)
async def update_workflow(deploy_workspace: str, workflow_id: str, request: Request):
    """Endpoint to update a workflow in a workspace"""
    logger.info("Updating workflow %s in workspace %s", workflow_id, deploy_workspace)

    response, content = await ades_client.update_workflow(request, deploy_workspace, workflow_id)

    return Response(
        content=content,
        status_code=response.status_code,
        headers=response.headers,
    )


@app.get(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes/{{workflow_id}}",
    dependencies=[Depends(opa_dependency)],
    summary="Get workflow details in the given workspace",
    response_model=GetProcessResponse,
    responses={
        200: {"description": "Workflow details returned successfully"},
        404: {"description": "Workflow not deployed to the given workspace"},
        401: {"description": "User not authenticated"},
        403: {"description": "User not authorized to make changes in this workspace"},
    },
)
def process_details(
    deploy_workspace: str,
    workflow_id: str,
    request: Request,
    wf_type: WorkflowType = Depends(opa_dependency),  # noqa: B008
):
    """Endpoint to get details of a workflow in a workspace"""
    logger.info("Getting details of workflow %s in workspace %s", workflow_id, deploy_workspace)

    response, content = ades_client.get_workflow(
        dict(request.headers), deploy_workspace, workflow_id, wf_type
    )

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


@app.post(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes/{{workflow_id}}/execution",
    dependencies=[Depends(opa_dependency)],
    summary="Execute a workflow from the specified workspace",
    response_model=ExecuteProcessResponse,
    responses={
        201: {"description": "Workflow execution started and job created successfully"},
        404: {"description": "Workflow not deployed to the given workspace"},
        401: {"description": "User not authenticated"},
        403: {"description": "User not authorized to make changes in this workspace"},
    },
)
async def execute_process(
    deploy_workspace: str,
    workflow_id: str,
    request: Request,
    workflow_type: tuple = Depends(opa_dependency),
):
    """Endpoint to execute a workflow in a workspace"""
    log_text = workflow_type.value
    logger.info("Executing %s %s in workspace %s", log_text, workflow_id, deploy_workspace)
    match workflow_type:
        case WorkflowType.USER_SERVICE:
            response, content = await ades_client.execute_user_service(
                request,
                deploy_workspace,
                workflow_id,
            )
        case WorkflowType.WORKFLOW:
            response, content = await ades_client.execute_workflow(
                request,
                deploy_workspace,
                workflow_id,
            )
        case _:
            raise HTTPException(status_code=400, detail="Invalid workflow type")
    if response.status_code == 201:
        username, workspace, _ = get_user_details(request)
        job_saver.record_owner(response, workflow_id, deploy_workspace, workspace, workflow_type)

    return Response(
        content=content,
        status_code=response.status_code,
        headers=response.headers,
    )


@app.get(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs/{{job_id}}",
    dependencies=[Depends(opa_dependency)],
    summary="Get job status",
    response_model=GetJobStatusResponse,
    responses={
        204: {"description": "job status information returned"},
        404: {"description": "Job ID does not exist in given workspace"},
        401: {"description": "User not authenticated"},
        403: {"description": "User not authorized to make changes in this workspace"},
    },
)
def process_status(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to get the status of an executing workflow or job"""
    logger.info("Getting status of job %s in workspace %s", job_id, deploy_workspace)

    response, content = ades_client.get_job_status(dict(request.headers), deploy_workspace, job_id)

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


@app.get(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs/{{job_id}}/results",
    dependencies=[Depends(opa_dependency)],
    summary="Get job results",
    response_model=GetJobResultsResponse,
    responses={
        200: {"description": "Job results returned as a Collection"},
        404: {"description": "Job with this ID does not exist in the workspace"},
        401: {"description": "User not authenticated"},
        403: {"description": "User not authorized to make changes in this workspace"},
    },
)
def process_results(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to get the results of an executed workflow or job"""
    logger.debug("Getting results of job %s in workspace %s", job_id, deploy_workspace)

    response, content = ades_client.get_job_results(dict(request.headers), deploy_workspace, job_id)

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


@app.get(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs",
    dependencies=[Depends(opa_dependency)],
    response_model=GetAllJobStatusResponse,
    summary="Get details for all available jobs in a workspace",
    responses={
        204: {"description": "Job details returned successfully"},
    },
)
def get_deployed_workspaced_jobs(
    deploy_workspace: str,
    request: Request,
    limit: Optional[int] = None,
    skip: Optional[int] = None,
    status: Optional[
        List[Literal["accepted", "running", "successful", "failed", "dismissed"]]
    ] = Query(  # noqa: B008
        None
    ),
    datetime: Optional[str] = Query(
        None,
        description="A date range to filter for the created date of workflow jobs.",
        example="2023-01-01T00:00:00Z/2023-01-02T00:00:00Z",
    ),  # noqa: B008
):
    """Endpoint to list all jobs in a workspace"""
    logger.debug("Listing jobs in workspace %s", deploy_workspace)

    response, content = ades_client.get_deployed_workspaced_jobs(
        request,
        deploy_workspace,
        job_saver,
        limit=limit,
        skip=skip,
        status=status,
        datetime=datetime,
    )

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


##############
## NOT USED ##
##############
# @app.get(f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/jobs",
# dependencies=[Depends(opa_dependency)])
def get_all_jobs(request: Request):
    """Endpoint to list all jobs called by the given user"""

    content = ades_client.get_all_jobs(dict(request.headers), job_saver.workspace_jobs)

    return Response(
        content=content,
        media_type="application/json",
        status_code=200,
    )


@app.get(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs/{{job_id}}/{{file_name}}",
    dependencies=[Depends(opa_dependency)],
    summary="Get job log file",
    responses={
        200: {"description": "Job log file returned successfully"},
        500: {"description": "Error occurred while retrieving the log file"},
        404: {"description": "Job ID or log filename not found"},
        401: {"description": "User not authenticated"},
        403: {"description": "User not authorized to make changes in this workspace"},
    },
)
def get_process_log(deploy_workspace: str, job_id: str, file_name: str, request: Request):
    """Endpoint to get the logs of a job"""
    logger.info("Getting log %s for job %s in workspace %s", file_name, job_id, deploy_workspace)
    response, content = ades_client.get_log(
        job_id, file_name, deploy_workspace, dict(request.headers)
    )

    return Response(
        content=content,
        media_type="text/plain",
        status_code=response.status_code,
    )


@app.delete(
    f"{ADES_FASTAPI_ROOT_PATH}/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs/{{job_id}}",
    dependencies=[Depends(opa_dependency)],
    response_model=DeleteJobResponse,
    summary="Delete job from workspace",
    responses={
        200: {"description": "Job deleted successfully"},
        404: {"description": "Job ID not found"},
        401: {"description": "User not authenticated"},
        403: {"description": "User not authorized to make changes in this workspace"},
    },
)
def delete_job(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to delete a job"""
    logger.info("Deleting job %s in workspace %s", job_id, deploy_workspace)

    response, content = ades_client.delete_job(dict(request.headers), deploy_workspace, job_id)

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )
