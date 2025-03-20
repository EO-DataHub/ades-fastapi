import logging
import os
from distutils.util import strtobool
from typing import List, Literal, Optional

import boto3
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles

from .ades_client import ADESClient
from .dependency_client import DependencyClient
from .job_saver import JobSaver
from .utils import WorkflowType, get_user_details

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)  # Add this line to define the logger

# Ingress path for ADES
ADES_INGRESS_PATH = os.getenv("ADES_INGRESS_PATH", "https://example-path/ades")

# OPA service endpoint
OPA_SERVICE_ENDPOINT = os.getenv(
    "OPA_SERVICE_ENDPOINT", "http://opal-client.opal:8181/v1/data/ades/allow"
)

# Root path for FastAPI
ADES_FASTAPI_ROOT_PATH = os.getenv("ADES_FASTAPI_ROOT_PATH", "/api/catalogue/stac")

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

# ADES execution rate limit in seconds
RATE_LIMIT = int(os.getenv("RATE_LIMIT", 5))


app = FastAPI(
    title="EODHP ADES",
    description="This is the Application, Deployment and Execution Service (ADES) for the EODHP project.\n"
    "The following endpoints are currently implemented.",
    version="0.1.0",
    docs_url="/workflow-runner/docs",
    openapi_url="/workflow-runner/openapi.json",
    root_path=ADES_FASTAPI_ROOT_PATH,
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


def opa_dependency(request: Request) -> WorkflowType:  # noqa: B008

    passed, wf_type = dependency_client.check_access(request, job_saver)

    if not passed:
        if not get_user_details(request)[0]:
            # User not authenticated
            raise HTTPException(status_code=401, detail="Not Authenticated")
        else:
            # User is not authorized
            raise HTTPException(status_code=403, detail="Not Authorized")

    return wf_type


@app.get("/workflow-runner/ping")
def ping():
    """Root endpoint for ADES API Docs, used by Swagger UI"""
    logger.info("Getting ADES root")
    response = ades_client.get_root()
    if response.status_code == 200:
        return {"status": "pong"}
    else:
        return {"status": "Failed to connect to ADES"}


@app.delete(
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes/{{workflow_id}}",
    dependencies=[Depends(opa_dependency)],
)
def undeploy_process(deploy_workspace: str, workflow_id: str, request: Request):
    """Endpoint to undeploy a workflow"""
    logger.info("Undeploying workflow %s in workspace %s", workflow_id, deploy_workspace)

    response, content = ades_client.undeploy_workflow(
        dict(request.headers), deploy_workspace, workflow_id
    )

    return Response(
        content=content,
        status_code=response.status_code,
        headers=response.headers,
        # media_type=response.headers.get("Content-Type"),
    )


@app.get(
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes",
    dependencies=[Depends(opa_dependency)],
)
def list_processes(
    deploy_workspace: str, request: Request, limit: Optional[int] = None, skip: int = 0
):
    """Endpoint to list all workflows deployed in a workspace"""
    logger.info("Listing workflows in workspace %s", deploy_workspace)

    response, content = ades_client.list_workflows(
        request, deploy_workspace, limit=limit, skip=skip
    )

    return Response(
        content=content,
        # media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response.headers,
    )


@app.post(
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes",
    dependencies=[Depends(opa_dependency)],
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
        # media_type=response.headers.get("Content-Type"),
    )


@app.put(
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes/{{workflow_id}}",
    dependencies=[Depends(opa_dependency)],
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
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes/{{workflow_id}}",
    dependencies=[Depends(opa_dependency)],
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
        # media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response.headers,
    )


@app.post(
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/processes/{{workflow_id}}/execution",
    dependencies=[Depends(opa_dependency)],
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
        calling_workspace, _ = get_user_details(request)
        job_saver.record_owner(
            response, workflow_id, deploy_workspace, calling_workspace, workflow_type
        )

    return Response(
        content=content,
        # media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response.headers,
    )


@app.get(
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs/{{job_id}}",
    dependencies=[Depends(opa_dependency)],
)
def process_status(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to get the status of an executing workflow or job"""
    logger.info("Getting status of job %s in workspace %s", job_id, deploy_workspace)

    response, content = ades_client.get_job_status(dict(request.headers), deploy_workspace, job_id)

    return Response(
        content=content,
        # media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response.headers,
    )


@app.get(
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs/{{job_id}}/results",
    dependencies=[Depends(opa_dependency)],
)
def process_results(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to get the results of an executed workflow or job"""
    logger.debug("Getting results of job %s in workspace %s", job_id, deploy_workspace)

    response, content = ades_client.get_job_results(dict(request.headers), deploy_workspace, job_id)

    return Response(
        content=content,
        # media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response.headers,
    )


@app.get(
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs",
    dependencies=[Depends(opa_dependency)],
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
        # media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response.headers,
    )


##############
## NOT USED ##
##############
# @app.get(f"/catalogs/{USER_CATALOG_ROOT}/jobs", dependencies=[Depends(opa_dependency)])
def get_all_jobs(request: Request):
    """Endpoint to list all jobs called by the given user"""

    content = ades_client.get_all_jobs(dict(request.headers), job_saver.workspace_jobs)

    return Response(
        content=content,
        media_type="application/json",
        status_code=200,
    )


@app.get(
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs/{{job_id}}/{{file_name}}",
    dependencies=[Depends(opa_dependency)],
)
def get_process_log(deploy_workspace: str, job_id: str, file_name: str, request: Request):
    """Endpoint to get the logs of a job"""
    logger.info("Getting log %s for job %s in workspace %s", file_name, job_id, deploy_workspace)
    response, content = ades_client.get_log(
        job_id, file_name, deploy_workspace, dict(request.headers)
    )

    return Response(
        content=content,
        # media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response.headers,
    )


@app.delete(
    f"/catalogs/{USER_CATALOG_ROOT}/catalogs/{{deploy_workspace}}/jobs/{{job_id}}",
    dependencies=[Depends(opa_dependency)],
)
def delete_job(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to delete a job"""
    logger.info("Deleting job %s in workspace %s", job_id, deploy_workspace)

    response, content = ades_client.delete_job(dict(request.headers), deploy_workspace, job_id)

    return Response(
        content=content,
        # media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response.headers,
    )
