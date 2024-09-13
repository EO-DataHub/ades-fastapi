import base64
import json
import logging
import os
import time
from distutils.util import strtobool
from json import JSONDecodeError

import jwt
import requests
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from kubernetes import client, config
from pydantic import BaseModel

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

# Environment used for calls to airbus API
AIRBUS_ENV = os.getenv("AIRBUS_ENV", "dev")

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


@app.get("/{workspace}/ogc-api")
def workspace_root(workspace: str):
    """Root endpoint for user's workspace"""
    logger.debug("Getting root of workspace %s", workspace)
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/")
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


last_deploy_times = {}


# Dependency to check the last call time
def rate_limit(workspace: str):
    current_time = time.time()
    last_call_time = last_deploy_times.get(workspace, 0)
    if current_time - last_call_time < 5:
        raise HTTPException(
            status_code=429, detail="Too Many Requests: Please wait 5 seconds before retrying."
        )
    last_deploy_times[workspace] = current_time


def get_workspace(request: Request):
    return request.path_params["workspace"]


def rate_limiter_dependency(workspace=Depends(get_workspace)):  # noqa: B008
    rate_limit(workspace)


def get_processes(workspace: str):
    headers = {"Accept": "application/cwl+json"}
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes", headers=headers
    )
    try:
        processes_dict = response.json()
    except JSONDecodeError as err:
        logger.error("Error decoding JSON response from ADES list processes")
        raise err
    return processes_dict


def get_workflow_id_from_file(data: str):
    cwl_dict = yaml.safe_load(data)
    return cwl_dict["$graph"][0]["id"]


def get_workflow_id_from_url(url: str):
    response = requests.get(url)
    cwl_dict = yaml.safe_load(response.text)
    return cwl_dict["$graph"][0]["id"]


@app.post("/{workspace}/ogc-api/processes")
async def deploy_process(
    workspace: str,
    request: Request,
    rate_limiter=Depends(rate_limiter_dependency),  # noqa: B008
):
    """Endpoint to deploy a workflow to a workspace"""
    headers = dict(request.headers)
    headers.pop("Authorization", None)

    if "application/json" in request.headers["Content-Type"]:
        logger.info("Deploying workflow from URL to workspace %s", workspace)
        # Handle HTTP file content
        data = {"json": await request.json()}
        workflow_id = get_workflow_id_from_url(data["json"]["executionUnit"]["href"])
    elif "application/cwl+yaml" in request.headers["Content-Type"]:
        logger.info("Deploying workflow from CWL file content to workspace %s", workspace)
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
    processes_dict = get_processes(workspace)
    for process in processes_dict["processes"]:
        if process["id"] == workflow_id:
            raise HTTPException(status_code=409, detail="Workflow already deployed")

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


def get_secret_airbus_api_key(username):
    """Get API key from secrets for a given user"""
    config.load_incluster_config()
    api_instance = client.CustomObjectsApi()

    # Find the namespace for the user from the workspace CRD
    workspace = api_instance.get_namespaced_custom_object(
        group="core.telespazio-uk.io",
        version="v1alpha1",
        namespace="workspaces",
        plural="workspaces",
        name=username,
    )
    namespace = workspace["spec"]["namespace"]

    # Get the secret in the user namespace
    v1 = client.CoreV1Api()
    secret = v1.read_namespaced_secret("api-keys", namespace)
    api_key = base64.b64decode(secret.data["airbus-key"]).decode("utf-8")
    return api_key


def generate_access_token(request: Request):
    """Generate access token for Airbus API"""
    if AIRBUS_ENV == "prod":
        url = "https://authenticate.foundation.api.oneatlas.airbus.com/auth/realms/IDP/protocol/openid-connect/token"
    else:
        url = "https://authenticate-int.idp.private.geoapi-airbusds.com/auth/realms/IDP/protocol/openid-connect/token"

    username, _ = get_user_details(request)
    api_key = get_secret_airbus_api_key(username)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = [
        ("apikey", api_key),
        ("grant_type", "api_key"),
        ("client_id", "IDP"),
    ]

    response = requests.post(url, headers=headers, data=data)

    return response.json().get("access_token")


def get_quote_from_airbus(url: str, body: dict, headers: dict) -> dict:
    """Get a quote from Airbus API"""
    response = requests.post(f"{url}/v1/sar/prices", json=body, headers=headers)
    response.raise_for_status()
    return response.json()


class QuoteRequest(BaseModel):
    """Request body for quote endpoint"""

    acquisitionId: str


@app.post("/quotes")
def quote(request: Request, body: QuoteRequest):
    """Return a quote for a given acquisition ID"""
    if AIRBUS_ENV == "prod":
        url = "https://sar.api.oneatlas.airbus.com"
    else:
        url = "https://dev.sar.api.oneatlas.airbus.com"

    access_token = generate_access_token(request)
    if not access_token:
        return JSONResponse(status_code=500, content={"detail": "Failed to generate access token"})

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    acquisition_id = body.acquisitionId
    request_body = {"acquisitions": [acquisition_id]}

    try:
        response_body = get_quote_from_airbus(url, request_body, headers)
    except requests.RequestException as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

    for item in response_body:
        if item.get("acquisitionId") == acquisition_id:
            return JSONResponse(
                content=item,
                status_code=200,
            )

    return JSONResponse(
        status_code=404, content={"detail": "Quote not found for given acquisition ID"}
    )
