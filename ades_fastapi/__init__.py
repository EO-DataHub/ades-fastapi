import json
import logging
import os
from distutils.util import strtobool
from json import JSONDecodeError

import requests
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .utils import (
    check_job_access,
    check_policy,
    check_workflow_access,
    convert_username_to_workspace,
    get_processes,
    get_user_details,
    get_workflow_id_from_file,
    get_workflow_id_from_url,
    rate_limiter_dependency,
    replace_href_links,
    save_data,
    user_is_workspace_owner,
)

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

# ADES service endpoint
ADES_SERVICE_ENDPOINT = os.getenv("ADES_SERVICE_ENDPOINT", "http://zoo-project-dru-service:80")

# Used for local testing where OPA is not available
ENABLE_OPA_POLICY_CHECK = strtobool(os.getenv("ENABLE_OPA_POLICY_CHECK", "true"))

# Root path for FastAPI
ADES_FASTAPI_ROOT_PATH = os.getenv("ADES_FASTAPI_ROOT_PATH", "/ades")

# ADES Policy bucket name
ADES_POLICY_BUCKET = os.getenv("ADES_POLICY_BUCKET", "ades-policy")

# Job owner storage directory
JOB_OWNER_STORAGE_DIR = os.getenv("JOB_OWNER_STORAGE_DIR", "/job-data")


app = FastAPI(
    title="EODHP ADES",
    description="This is the Application, Deployment and Execution Service (ADES) for the EODHP project.\n"
    "The following endpoints are currently implemented.",
    version="0.1.0",
    root_path=ADES_FASTAPI_ROOT_PATH,
)

# Define static file path
static_filepath = os.getenv("STATIC_FILE_PATH", "static")

# Mount static files with STAC FastApi
app.mount("/static", StaticFiles(directory=static_filepath), name="static")

# Define global variables to store job and workspace owners
job_deployed_workspace = {}  # used to link workflow id and job id to deploying workspace
job_owners = {}  # used to link deploying workspace and job id to executing user

# Load job owners from file
if os.path.exists(f"{JOB_OWNER_STORAGE_DIR}/job-owners.json"):
    with open(f"{JOB_OWNER_STORAGE_DIR}/job-owners.json", "r") as file:
        job_owners = json.load(file)
else:
    job_owners = {}

# Load job workspace owners from file
if os.path.exists(f"{JOB_OWNER_STORAGE_DIR}/job-workspace-owners.json"):
    with open(f"{JOB_OWNER_STORAGE_DIR}/job-workspace-owners.json", "r") as file:
        job_deployed_workspace = json.load(file)
else:
    job_deployed_workspace = {}


@app.middleware("http")
async def opa_middleware(request: Request, call_next):
    """Middleware to check OPA policy before allowing access to the endpoint"""
    if ENABLE_OPA_POLICY_CHECK:
        if check_policy(
            request, job_deployed_workspace, job_owners, OPA_SERVICE_ENDPOINT, ADES_POLICY_BUCKET
        ):
            response = await call_next(request)
            return response
        return JSONResponse(status_code=403, content={"detail": "Access denied"})
    else:
        response = await call_next(request)
        return response


@app.get("")
def root():
    """Root endpoint for ADES API Docs, used by Swagger UI"""
    logger.debug("Getting ADES API docs")
    try:
        response = requests.get(f"{ADES_SERVICE_ENDPOINT}")
    except requests.exceptions.ConnectionError:
        return JSONResponse(content={"message": "Service Unavailable"}, status_code=503)
    if response.status_code == 200:
        return HTMLResponse(content="<h1>ADES HOMEPAGE</h1><p>Status: available</p>")
    else:
        return JSONResponse(content={"message": "Service Unavailable"}, status_code=503)


@app.get("/{deploy_workspace}/ogc-api")
def workspace_root(deploy_workspace: str):
    """Root endpoint for user's workspace"""
    logger.debug("Getting root of workspace %s", deploy_workspace)
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/")
    result = json.dumps(response.json())
    return StreamingResponse(
        content=result,
        status_code=response.status_code,
        headers=response.headers,
    )


@app.get("/ogc-api/api")
def docs_root():
    """Root endpoint for ADES API Docs, used by Swagger UI"""
    logger.debug("Getting ADES API docs")
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/ogc-api/api")
    result = json.dumps(response.json())
    return StreamingResponse(
        content=result,
        status_code=response.status_code,
        headers=response.headers,
    )


@app.get("/api")
def swagger_docs():
    """Endpoint for ADES Swagger docs"""
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/swagger-ui/oapip/")

    if response.headers["Content-Type"] == "text/html":
        # Replace paths from ADES API response with paths for swagger files served by this API instead
        html_content = (
            response.text.replace('href="./', 'href="static/swagger-ui/')
            .replace('src="./', 'src="static/swagger-ui/')
            .replace('"index.css', '"static/swagger-ui/index.css')
        )
        return HTMLResponse(content=html_content, status_code=response.status_code)
    else:
        raise HTTPException(status_code=500, detail="Unexpected content type from ADES")


@app.delete("/{deploy_workspace}/ogc-api/processes/{workflow_id}")
def undeploy_process(deploy_workspace: str, workflow_id: str, request: Request):
    """Endpoint to undeploy a workflow"""
    logger.debug("Undeploying workflow %s in workspace %s", workflow_id, deploy_workspace)

    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    # Must be the workspace owner to delete a workflow
    logger.info(
        "Checking user %s has access to undeploy workflow %s in workspace %s",
        user_workspace,
        workflow_id,
        deploy_workspace,
    )

    if not user_is_workspace_owner(user_workspace, deploy_workspace):
        return JSONResponse(
            status_code=403,
            content={"detail": "User does not have access to this workspace, sorry"},
        )

    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.delete(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/processes/{workflow_id}",
        headers=headers,
    )

    print(response.text)

    try:
        content = json.dumps(response.json())
    except JSONDecodeError:
        content = response.text

    return Response(
        content=content,
        status_code=response.status_code,
    )


@app.get("/{deploy_workspace}/ogc-api/processes")
def list_processes(deploy_workspace: str, request: Request):
    """Endpoint to list all workflows deployed in a workspace"""
    logger.debug("Listing workflows in workspace %s", deploy_workspace)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/processes", headers=headers
    )

    if "application/json" in response.headers["Content-Type"]:
        final_content = {}
        final_content["processes"] = []
        content_json = response.json()
        content_json = replace_href_links(content_json, ADES_INGRESS_PATH)
        final_content["links"] = content_json.get("links")
        for process_json in content_json["processes"]:
            if check_workflow_access(
                request,
                deploy_workspace,
                ADES_POLICY_BUCKET,
                ADES_SERVICE_ENDPOINT,
                workflow_id=process_json["id"],
            ):
                process_json = replace_href_links(process_json, ADES_INGRESS_PATH)
                final_content["processes"].append(process_json)
        content = json.dumps(final_content)
    else:
        content = response.text
    return Response(
        content=content,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.post("/{deploy_workspace}/ogc-api/processes")
async def deploy_process(
    deploy_workspace: str,
    request: Request,
    rate_limiter=Depends(rate_limiter_dependency),  # noqa: B008
):
    """Endpoint to deploy a workflow to a workspace"""

    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    headers = dict(request.headers)
    headers.pop("Authorization", None)

    # Can only deploy to your own workspace
    logger.info("Checking user %s is the owner of workspace %s", user_workspace, deploy_workspace)
    if not user_is_workspace_owner(user_workspace, deploy_workspace):
        return JSONResponse(
            status_code=403,
            content={"detail": "User does not have access to this workspace, sorry"},
        )

    if "application/json" in request.headers["Content-Type"]:
        logger.info("Deploying workflow from URL to workspace %s", deploy_workspace)
        # Handle HTTP file content
        data = {"json": await request.json()}
        workflow_id = get_workflow_id_from_url(data["json"]["executionUnit"]["href"])
    elif "application/cwl+yaml" in request.headers["Content-Type"]:
        logger.info("Deploying workflow from CWL file content to workspace %s", deploy_workspace)
        # Handle string file content
        file_content = await request.body()

        # Prepare the payload for the subsequent API request
        data = {"data": file_content}  # Decode bytes to string
        workflow_id = get_workflow_id_from_file(data["data"])
    else:
        raise HTTPException(
            status_code=415,
            detail="Unsupported content type. Only application/json and application/cwl+yaml are supported",
        )

    # Check if the workflow is already deployed, as this causes a bug in the ADES
    processes_dict = get_processes(deploy_workspace, ADES_SERVICE_ENDPOINT)
    for process in processes_dict["processes"]:
        if process["id"] == workflow_id:
            raise HTTPException(status_code=409, detail="Workflow already deployed")

    response = requests.post(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/processes", headers=headers, **data
    )

    if "application/json" in response.headers["Content-Type"]:
        content_json = response.json()
        content_json = replace_href_links(content_json, ADES_INGRESS_PATH)
        content = json.dumps(content_json, indent=2)
    else:
        content = response.text

    # Need to include Location header from ADES to support deploy status endpoint
    response_headers = {
        "Location": response.headers.get("Location", "").replace(
            "http://localhost:8080", ADES_INGRESS_PATH
        ),
        "Content-Type": response.headers["Content-Type"],
    }

    return Response(
        content=content,
        status_code=response.status_code,
        headers=response_headers,
    )


@app.put("/{deploy_workspace}/ogc-api/processes/{workflow_id}")
async def update_process(deploy_workspace: str, workflow_id: str, request: Request):
    """Endpoint to update a workflow in a workspace"""
    logger.info("Updating workflow %s in workspace %s", workflow_id, deploy_workspace)

    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    headers = dict(request.headers)
    headers.pop("Authorization", None)

    # User can only update a workflow in their own workspace
    logger.info(
        "Checking user %s has access to update workflow %s in workspace %s",
        user_workspace,
        workflow_id,
        deploy_workspace,
    )
    if not user_is_workspace_owner(user_workspace, deploy_workspace):
        return JSONResponse(
            status_code=403,
            content={"detail": "User does not have access to this workspace, sorry"},
        )

    if "application/json" in request.headers["Content-Type"]:
        logger.info("Updating workflow from URL to workspace %s", deploy_workspace)
        # Handle HTTP file content
        data = {"json": await request.json()}
    elif "application/cwl+yaml" in request.headers["Content-Type"]:
        logger.info("Updating workflow from CWL file content to workspace %s", deploy_workspace)
        # Handle string file content
        file_content = await request.body()

        # Prepare the payload for the subsequent API request
        data = {"data": file_content}  # Decode bytes to string
    else:
        raise HTTPException(
            status_code=415,
            detail="Unsupported content type. Only application/json and application/cwl+yaml are supported",
        )

    response = requests.put(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/processes/{workflow_id}",
        headers=headers,
        **data,
    )

    try:
        content = json.dumps(response.json())
    except JSONDecodeError:
        content = response.text if response.text else ""

    logger.info("Status code from ADES: %s", response.status_code)

    logger.info("Response from ADES: %s", content)

    # Need to include Location header from ADES to support deploy status endpoint
    response_headers = {
        "Location": response.headers.get("Location", "").replace(
            "http://localhost:8080", ADES_INGRESS_PATH
        ),
    }

    if response.headers.get("Content-Type"):
        response_headers["Content-Type"] = response.headers["Content-Type"]

    return Response(
        content=content,
        status_code=response.status_code,
        headers=response_headers,
    )


@app.get("/{deploy_workspace}/ogc-api/processes/{workflow_id}")
def process_details(deploy_workspace: str, workflow_id: str, request: Request):
    """Endpoint to get details of a workflow in a workspace"""
    logger.debug("Getting details of workflow %s in workspace %s", workflow_id, deploy_workspace)

    # Check user has access to this workflow
    logger.info(
        "Checking user has access to workflow %s in workspace %s", workflow_id, deploy_workspace
    )
    if not check_workflow_access(
        request,
        deploy_workspace,
        ADES_POLICY_BUCKET,
        ADES_SERVICE_ENDPOINT,
        workflow_id=workflow_id,
    ):
        return JSONResponse(
            status_code=403, content={"detail": "User does not have access to this workflow, sorry"}
        )

    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/processes/{workflow_id}",
        headers=headers,
    )
    try:
        content_json = response.json()
        content_json = replace_href_links(content_json, ADES_INGRESS_PATH)
        content = json.dumps(content_json, indent=2)
    except JSONDecodeError:
        # Update Content-Type header to avoid warning generated by ADES response
        response.headers["Content-Type"] = "text/plain"
        content = response.text

    return Response(
        content=content,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.post("/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution")
async def execute_process(deploy_workspace: str, workflow_id: str, request: Request):
    """Endpoint to execute a workflow in a workspace"""
    logger.debug("Executing workflow %s in workspace %s", workflow_id, deploy_workspace)
    headers = dict(request.headers)

    headers = {
        "Prefer": "respond-async",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    # Check user has access to this workflow
    logger.info(
        "Checking user %s has access to workflow %s in workspace %s",
        user_workspace,
        workflow_id,
        deploy_workspace,
    )
    if not check_workflow_access(
        request,
        deploy_workspace,
        ADES_POLICY_BUCKET,
        ADES_SERVICE_ENDPOINT,
        workflow_id=workflow_id,
    ):
        return JSONResponse(
            status_code=403, content={"detail": "User does not have access to this workflow, sorry"}
        )

    try:
        body = await request.json()
        # Add workspace to body
        logger.info("Setting execution workspace to %s", username)
        body["inputs"].update({"workspace": username})
    except JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from err

    response = requests.post(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution",
        headers=headers,
        json=body,
    )

    if response.status_code == 201:
        logger.info("Response from ADES: %s", response.text)

        job_id = response.json()["jobID"]

        deploy_workspace_and_job_id = f"{deploy_workspace}-{job_id}"
        workflow_id_and_job_id = f"{workflow_id}-{job_id}"

        # Record job_id and relate to executing (user) workspace and deployed workspace
        job_owners[deploy_workspace_and_job_id] = user_workspace
        job_deployed_workspace[workflow_id_and_job_id] = deploy_workspace

        logger.info(
            "Workspace owner for the job %s is %s", deploy_workspace_and_job_id, user_workspace
        )
        logger.info(
            "Deployed workspace for the job %s is %s", workflow_id_and_job_id, deploy_workspace
        )

        save_data(JOB_OWNER_STORAGE_DIR, job_owners, job_deployed_workspace)

    try:
        content_json = response.json()
        content_json = replace_href_links(content_json, ADES_INGRESS_PATH)
        content = json.dumps(content_json, indent=2)
    except JSONDecodeError:
        if response.headers["Content-Type"] == "text/plain":
            content = response.text
        content = response.text

    if "Location" in response.headers:
        response.headers["Location"] = response.headers["Location"].replace(
            "http://localhost:8080", ADES_INGRESS_PATH
        )

    # use streamingresponse to avoid content-length header being set automatically, causing issues
    # with Transfer-Encoding
    return StreamingResponse(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response.headers,
    )


@app.get("/{deploy_workspace}/ogc-api/jobs/{job_id}")
def process_status(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to get the status of an executing workflow or job"""
    logger.debug("Getting status of job %s in workspace %s", job_id, deploy_workspace)

    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    # Check user has access to this workflow
    deploy_workspace_and_job_id = f"{deploy_workspace}-{job_id}"
    logger.info(
        "Checking user %s has access to job %s in workspace %s",
        user_workspace,
        job_id,
        deploy_workspace,
    )
    logger.info("Job owner is %s ", job_owners.get(deploy_workspace_and_job_id))
    if job_owners.get(deploy_workspace_and_job_id) != user_workspace:
        return JSONResponse(
            status_code=403, content={"detail": "User does not have access to this job, sorry"}
        )

    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/jobs/{job_id}", headers=headers
    )

    return Response(
        content=json.dumps(response.json()).replace("http://localhost:8080", ADES_INGRESS_PATH),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.get("/{deploy_workspace}/ogc-api/jobs/{job_id}/results")
def processing_results(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to get the results of an executed workflow or job"""
    logger.debug("Getting results of job %s in workspace %s", job_id, deploy_workspace)

    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    # Check user has access to this job
    deploy_workspace_and_job_id = f"{deploy_workspace}-{job_id}"
    logger.info(
        "Checking user %s has access to job %s in workspace %s",
        user_workspace,
        job_id,
        deploy_workspace,
    )
    if job_owners.get(deploy_workspace_and_job_id) != user_workspace:
        return JSONResponse(
            status_code=403, content={"detail": "User does not have access to these results, sorry"}
        )

    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/jobs/{job_id}/results",
        headers=headers,
    )
    return Response(
        content=json.dumps(response.json()).replace("http://localhost:8080", ADES_INGRESS_PATH),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.get("/{deploy_workspace}/ogc-api/jobs")
def list_jobs(deploy_workspace: str, request: Request):
    """Endpoint to list all jobs in a workspace"""
    logger.debug("Listing jobs in workspace %s", deploy_workspace)

    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    print(user_workspace)

    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/jobs", headers=headers
    )

    response_json = response.json()

    jobs = response_json["jobs"]

    filtered_jobs = []

    logger.info(
        "Filtering jobs to those that were executed by user %s in workspace %s",
        user_workspace,
        deploy_workspace,
    )
    for job in jobs:
        job_id = job["jobID"]
        deploy_workspace_and_job_id = f"{deploy_workspace}-{job_id}"
        if job_owners.get(deploy_workspace_and_job_id) == user_workspace:
            filtered_jobs.append(job)

    response_json["jobs"] = filtered_jobs

    response_json = json.dumps(response_json).replace("http://localhost:8080", ADES_INGRESS_PATH)

    return Response(
        content=response_json,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.get("/temp/{workflow_job_id}/{file_name}")
def get_logs(workflow_job_id: str, file_name: str, request: Request):
    """Endpoint to get the logs of a job"""
    # Get username and roles
    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    # Extract workflow and job ids
    workflow_id = workflow_job_id[:-37]
    job_id = workflow_job_id[-36:]

    # Check job was run in this user workspace
    if not check_job_access(
        user_workspace, workflow_id, job_id, job_deployed_workspace, job_owners
    ):
        return JSONResponse(
            status_code=403, content={"detail": "User does not have access to these logs, sorry"}
        )

    logger.debug("Accessing: %s logs for workflow: %s and job: ", file_name, workflow_id, job_id)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/temp/{workflow_job_id}/{file_name}", headers=headers
    )

    return Response(
        content=response.content,
        headers=response.headers,
        status_code=response.status_code,
    )


@app.delete("/{deploy_workspace}/ogc-api/jobs/{job_id}")
def delete_job(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to delete a job"""
    logger.debug("Deleting job %s in workspace %s", job_id, deploy_workspace)

    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    # Check user has access to this workflow
    deploy_workspace_and_job_id = f"{deploy_workspace}-{job_id}"
    logger.info(
        "Checking user %s has access to job %s in workspace %s",
        user_workspace,
        job_id,
        deploy_workspace,
    )
    if job_owners.get(deploy_workspace_and_job_id) != user_workspace:
        return JSONResponse(
            status_code=403, content={"detail": "User does not have access to this job, sorry"}
        )

    return Response(
        content="Endpoint not implemented yet",
        status_code=501,
    )
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.delete(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/jobs/{job_id}", headers=headers
    )
    return Response(
        content=response.text,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )
