import json
import logging
import os
from distutils.util import strtobool
from json import JSONDecodeError

import jwt
import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

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


app = FastAPI(
    title="EODHP ADES",
    description="This is the Application, Deployment and Execution Service (ADES) for the EODHP project.\n"
    "The following endpoints are currently implemented.",
    version="0.1.0",
    root_path=ADES_FASTAPI_ROOT_PATH,
)

static_filepath = os.getenv("STATIC_FILE_PATH", "static")

app.mount("/static", StaticFiles(directory=static_filepath), name="static")


def opa_request(input_data: dict):
    """Send a request to OPA service"""
    logger.debug("Sending request to OPA service with input: %s", input_data)
    return requests.post(OPA_SERVICE_ENDPOINT, json=input_data)


def get_user_details(request: Request):
    """Get user details from the request"""
    token = request.headers.get("authorization", "")
    stripped_token = token.replace("Bearer ", "")
    if stripped_token:
        credentials = jwt.decode(
            stripped_token,
            options={"verify_signature": False},
            algorithms=["HS256"],
        )
        username = credentials.get("preferred_username", "")
        roles = credentials.get("realm_access", {}).get("roles", [])
    else:
        username = ""
        roles = []
    return username, roles


def check_policy(request: Request):
    """Check OPA policy to determine if the request is allowed"""
    username, roles = get_user_details(request)
    input_data = {
        "input": {
            "roles": roles,
            "path": request.url.path,
            "username": username,
        }
    }
    logger.info("Logged in as user: %s", username)
    logger.debug("Checking policy with input: %s", input_data)
    response = opa_request(input_data)
    if response.status_code != 200 or not response.json().get("result", False):
        return False
    return True


@app.middleware("http")
async def opa_middleware(request: Request, call_next):
    """Middleware to check OPA policy before allowing access to the endpoint"""
    if ENABLE_OPA_POLICY_CHECK:
        if check_policy(request):
            response = await call_next(request)
            return response
        else:
            return JSONResponse(status_code=403, content={"detail": "Access denied"})
    else:
        response = await call_next(request)
        return response


@app.get("")
def root():
    """Root endpoint for ADES"""
    logger.debug("Getting root of ADES")
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/")
    if response.headers.get("Content-Type") == "text/html":
        return HTMLResponse(content=response.text, status_code=response.status_code)
    else:
        raise HTTPException(status_code=406, detail="Unexpected content type")


@app.get("/{workspace}/ogc-api")
def workspace_root(workspace: str):
    """Root endpoint for user's workspace"""
    logger.debug("Getting root of workspace %s", workspace)
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/")
    if response.headers.get("Content-Type") == "text/html":
        return HTMLResponse(content=response.text, status_code=response.status_code)
    else:
        raise HTTPException(status_code=406, detail="Unexpected content type")


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


@app.delete("/{workspace}/ogc-api/processes/{workflow_id}")
def undeploy_process(workspace: str, workflow_id: str, request: Request):
    """Endpoint to undeploy a workflow"""
    logger.debug("Undeploying workflow %s in workspace %s", workflow_id, workspace)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.delete(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes/{workflow_id}",
        headers=headers,
    )

    try:
        content = json.dumps(response.json())
    except JSONDecodeError:
        content = response.text

    return Response(
        content=content,
        status_code=response.status_code,
    )


@app.get("/{workspace}/ogc-api/processes")
def list_processes(workspace: str, request: Request):
    """Endpoint to list all workflows deployed in a workspace"""
    logger.debug("Listing workflows in workspace %s", workspace)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes", headers=headers
    )

    if "application/json" in response.headers["Content-Type"]:
        content_json = response.json()
        content_json = replace_href_links(content_json)
        for i, process_json in enumerate(content_json["processes"]):
            process_json = replace_href_links(process_json)
            content_json["processes"][i] = process_json
        content = json.dumps(content_json, indent=2)
    else:
        content = response.text
    return Response(
        content=content,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


def replace_href_links(content_dict):
    """Replace href links in the JSON response"""
    if "links" in content_dict:
        for link in content_dict["links"]:
            link["href"] = link["href"].replace("http://localhost:8080", ADES_INGRESS_PATH)
    return content_dict


@app.post("/{workspace}/ogc-api/processes")
async def deploy_process(workspace: str, request: Request):
    """Endpoint to deploy a workflow to a workspace"""
    headers = dict(request.headers)
    headers.pop("Authorization", None)

    if "application/json" in request.headers["Content-Type"]:
        logger.info("Deploying workflow from URL to workspace %s", workspace)
        # Handle HTTP file content
        data = {"json": await request.json()}
    elif "application/cwl+yaml" in request.headers["Content-Type"]:
        logger.info("Deploying workflow from CWL file content to workspace %s", workspace)
        # Handle string file content
        file_content = await request.body()

        # Prepare the payload for the subsequent API request
        data = {"data": file_content}  # Decode bytes to string
    else:
        raise HTTPException(
            status_code=415,
            detail="Unsupported content type. Only application/json and application/cwl+yaml are supported",
        )

    response = requests.post(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes", headers=headers, **data
    )

    if "application/json" in response.headers["Content-Type"]:
        content_json = response.json()
        content_json = replace_href_links(content_json)
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


@app.put("/{workspace}/ogc-api/processes/{workflow_id}")
async def update_process(workspace: str, workflow_id: str, request: Request):
    """Endpoint to update a workflow in a workspace"""
    headers = dict(request.headers)
    headers.pop("Authorization", None)

    if "application/json" in request.headers["Content-Type"]:
        logger.info("Updating workflow from URL to workspace %s", workspace)
        # Handle HTTP file content
        data = {"json": await request.json()}
    elif "application/cwl+yaml" in request.headers["Content-Type"]:
        logger.info("Updating workflow from CWL file content to workspace %s", workspace)
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
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes/{workflow_id}",
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


@app.get("/{workspace}/ogc-api/processes/{workflow_id}")
def process_details(workspace: str, workflow_id: str, request: Request):
    """Endpoint to get details of a workflow in a workspace"""
    logger.debug("Getting details of workflow %s in workspace %s", workflow_id, workspace)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes/{workflow_id}",
        headers=headers,
    )
    try:
        content_json = response.json()
        content_json = replace_href_links(content_json)
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


@app.post("/{workspace}/ogc-api/processes/{workflow_id}/execution")
async def execute_process(workspace: str, workflow_id: str, request: Request):
    """Endpoint to execute a workflow in a workspace"""
    logger.debug("Executing workflow %s in workspace %s", workflow_id, workspace)
    headers = dict(request.headers)
    headers.pop("authorization", None)
    headers.pop("content-type", None)

    try:
        body = await request.json()
    except JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from err

    response = requests.post(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes/{workflow_id}/execution",
        headers=headers,
        json=body,
    )

    try:
        content_json = response.json()
        content_json = replace_href_links(content_json)
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


@app.get("/{workspace}/ogc-api/jobs/{job_id}")
def execute_status(workspace: str, job_id: str, request: Request):
    """Endpoint to get the status of an executing workflow or job"""
    logger.debug("Getting status of job %s in workspace %s", job_id, workspace)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs/{job_id}", headers=headers
    )

    return Response(
        content=json.dumps(response.json()).replace("http://localhost:8080", ADES_INGRESS_PATH),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.get("/{workspace}/ogc-api/jobs/{job_id}/results")
def processing_results(workspace: str, job_id: str, request: Request):
    """Endpoint to get the results of an executed workflow or job"""
    logger.debug("Getting results of job %s in workspace %s", job_id, workspace)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs/{job_id}/results",
        headers=headers,
    )
    return Response(
        content=json.dumps(response.json()).replace("http://localhost:8080", ADES_INGRESS_PATH),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.get("/{workspace}/ogc-api/jobs")
def list_jobs(workspace: str, request: Request):
    """Endpoint to list all jobs in a workspace"""
    logger.debug("Listing jobs in workspace %s", workspace)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs", headers=headers)

    response_json = json.dumps(response.json()).replace("http://localhost:8080", ADES_INGRESS_PATH)

    return Response(
        content=response_json,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


def list_jobs_dict(workspace: str, request: Request) -> dict:
    """Local function to list all jobs in a workspace, returned as a dictionary"""
    logger.debug("Listing jobs in workspace %s", workspace)
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs", headers=headers)

    return response.json()


def check_job_access(workspace: str, workflow_id: str, job_id: str, request: Request):
    """Check if the job was run in this user workspace"""

    # Get all jobs in user workspace
    jobs_dict = list_jobs_dict(workspace, request)
    all_jobs = jobs_dict["jobs"]

    # TODO: Add check for group workspace as well

    # Check if the job is in the list
    for job in all_jobs:
        if job["jobID"] == job_id and job["processID"] == workflow_id:
            return True
    return False


@app.get("/temp/{workflow_job_id}/{file_name}")
def get_logs(workflow_job_id: str, file_name: str, request: Request):
    """Endpoint to get the logs of a job"""
    # Get username and roles
    username, _ = get_user_details(request)

    # Remove "-" from username
    username = username.replace("-", "_")

    # Extract workflow and job ids
    workflow_id = workflow_job_id[:-37]
    job_id = workflow_job_id[-36:]

    # Check job was run in this user workspace
    if not check_job_access(username, workflow_id, job_id, request):
        return JSONResponse(status_code=403, content={"detail": "Access denied"})

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


@app.delete("/{workspace}/ogc-api/jobs/{job_id}")
def delete_job(workspace: str, job_id: str, request: Request):
    """Endpoint to delete a job"""
    logger.debug("Deleting job %s in workspace %s", job_id, workspace)
    return Response(
        content="Endpoint not implemented yet",
        status_code=501,
    )
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.delete(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs/{job_id}", headers=headers
    )
    return Response(
        content=response.text,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )
