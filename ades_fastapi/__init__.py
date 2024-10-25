import base64
import json
import logging
import os
from distutils.util import strtobool
from json import JSONDecodeError

import requests
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from kubernetes import client, config
from pydantic import BaseModel

from .utils import (
    check_policy,
    check_workflow_access,
    convert_username_to_workspace,
    get_path_params,
    get_user_details,
    replace_href_links,
    save_data,
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

# ADES policy prefix
ADES_POLICY_PREFIX = os.getenv("ADES_POLICY_PREFIX", "")

# Job owner storage directory
JOB_OWNER_STORAGE_DIR = os.getenv("JOB_OWNER_STORAGE_DIR", "/job-data")

# Environment used for calls to airbus API
AIRBUS_ENV = os.getenv("AIRBUS_ENV", "dev")


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
job_owners = {}  # used to link deploying workspace and job id to executing user

# Load job owners from file
if os.path.exists(f"{JOB_OWNER_STORAGE_DIR}/job-owners.json"):
    with open(f"{JOB_OWNER_STORAGE_DIR}/job-owners.json", "r") as file:
        job_owners = json.load(file)
else:
    job_owners = {}


def opa_dependency(request: Request, path_params: dict = Depends(get_path_params)):  # noqa: B008
    if ENABLE_OPA_POLICY_CHECK:
        if not check_policy(
            request,
            path_params,
            job_owners,
            OPA_SERVICE_ENDPOINT,
            ADES_POLICY_BUCKET,
            ADES_POLICY_PREFIX,
        ):
            raise HTTPException(status_code=403, detail="Access denied")


@app.get("", dependencies=[Depends(opa_dependency)])
def root():
    """Root endpoint for ADES API Docs, used by Swagger UI"""
    logger.info("Getting ADES API docs")

    try:
        response = requests.get(f"{ADES_SERVICE_ENDPOINT}")
    except requests.exceptions.ConnectionError:
        return JSONResponse(content={"message": "Service Unavailable"}, status_code=503)
    if response.status_code == 200:
        return HTMLResponse(content="<h1>ADES HOMEPAGE</h1><p>Status: available</p>")
    else:
        return JSONResponse(content={"message": "Service Unavailable"}, status_code=503)


@app.get("/{deploy_workspace}/ogc-api", dependencies=[Depends(opa_dependency)])
def workspace_root(deploy_workspace: str):
    """Root endpoint for user's workspace"""
    logger.info("Getting root of workspace %s", deploy_workspace)
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/")

    result = json.dumps(response.json())
    return StreamingResponse(
        content=result,
        status_code=response.status_code,
        headers=response.headers,
    )


@app.get("/ogc-api/api", dependencies=[Depends(opa_dependency)])
def docs_root():
    """Root endpoint for ADES API Docs, used by Swagger UI"""
    logger.info("Getting ADES API docs")
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/ogc-api/api")
    result = json.dumps(response.json())
    return StreamingResponse(
        content=result,
        status_code=response.status_code,
        headers=response.headers,
    )


@app.get("/api", dependencies=[Depends(opa_dependency)])
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


@app.delete(
    "/{deploy_workspace}/ogc-api/processes/{workflow_id}", dependencies=[Depends(opa_dependency)]
)
def undeploy_process(deploy_workspace: str, workflow_id: str, request: Request):
    """Endpoint to undeploy a workflow"""
    logger.info("Undeploying workflow %s in workspace %s", workflow_id, deploy_workspace)

    headers = dict(request.headers)
    headers.pop("authorization", None)
    response = requests.delete(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/processes/{workflow_id}",
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


@app.get("/{deploy_workspace}/ogc-api/processes", dependencies=[Depends(opa_dependency)])
def list_processes(deploy_workspace: str, request: Request):
    """Endpoint to list all workflows deployed in a workspace"""
    logger.info("Listing workflows in workspace %s", deploy_workspace)
    headers = dict(request.headers)
    headers.pop("authorization", None)
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
                process_json["id"],
                ADES_POLICY_PREFIX,
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


@app.post("/{deploy_workspace}/ogc-api/processes", dependencies=[Depends(opa_dependency)])
async def deploy_process(
    deploy_workspace: str,
    request: Request,
):
    """Endpoint to deploy a workflow to a workspace"""

    headers = dict(request.headers)
    headers.pop("authorization", None)

    if "application/json" in request.headers["Content-Type"]:
        logger.info("Deploying workflow from URL to workspace %s", deploy_workspace)
        # Handle HTTP file content
        data = {"json": await request.json()}
    elif "application/cwl+yaml" in request.headers["Content-Type"]:
        logger.info("Deploying workflow from CWL file content to workspace %s", deploy_workspace)
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


@app.put(
    "/{deploy_workspace}/ogc-api/processes/{workflow_id}", dependencies=[Depends(opa_dependency)]
)
async def update_process(deploy_workspace: str, workflow_id: str, request: Request):
    """Endpoint to update a workflow in a workspace"""
    logger.info("Updating workflow %s in workspace %s", workflow_id, deploy_workspace)

    username, _ = get_user_details(request)

    headers = dict(request.headers)
    headers.pop("authorization", None)

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


@app.get(
    "/{deploy_workspace}/ogc-api/processes/{workflow_id}", dependencies=[Depends(opa_dependency)]
)
def process_details(deploy_workspace: str, workflow_id: str, request: Request):
    """Endpoint to get details of a workflow in a workspace"""
    logger.info("Getting details of workflow %s in workspace %s", workflow_id, deploy_workspace)

    headers = dict(request.headers)
    headers.pop("authorization", None)
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


@app.post(
    "/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution",
    dependencies=[Depends(opa_dependency)],
)
async def execute_process(deploy_workspace: str, workflow_id: str, request: Request):
    """Endpoint to execute a workflow in a workspace"""
    logger.info("Executing workflow %s in workspace %s", workflow_id, deploy_workspace)
    headers = dict(request.headers)

    headers = {
        "Prefer": "respond-async",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    try:
        body = await request.json()
        # Add workspace to body
        logger.info("Setting executing workspace to %s", username)
        body["inputs"].update({"workspace": username})

    except JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from err

    response = requests.post(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution",
        headers=headers,
        json=body,
    )

    # Record the executing workspace and deployed workspace for the generate jobID
    if response.status_code == 201:
        logger.info("Response from ADES: %s", response.text)

        job_id = response.json()["jobID"]

        deploy_workspace_and_job_id = f"{deploy_workspace}-{job_id}"
        workflow_id_and_job_id = f"{workflow_id}-{job_id}"

        # Record job_id and relate to executing (user) workspace and deployed workspace
        job_owners[deploy_workspace_and_job_id] = user_workspace

        logger.info("Job owner for the job %s is %s", deploy_workspace_and_job_id, user_workspace)
        logger.info(
            "Deployed workspace for the job %s is %s", workflow_id_and_job_id, deploy_workspace
        )

        save_data(JOB_OWNER_STORAGE_DIR, job_owners)

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


@app.get("/{deploy_workspace}/ogc-api/jobs/{job_id}", dependencies=[Depends(opa_dependency)])
def process_status(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to get the status of an executing workflow or job"""
    logger.info("Getting status of job %s in workspace %s", job_id, deploy_workspace)

    headers = dict(request.headers)
    headers.pop("authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/jobs/{job_id}", headers=headers
    )

    return Response(
        content=json.dumps(response.json()).replace("http://localhost:8080", ADES_INGRESS_PATH),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.get(
    "/{deploy_workspace}/ogc-api/jobs/{job_id}/results", dependencies=[Depends(opa_dependency)]
)
def processing_results(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to get the results of an executed workflow or job"""
    logger.debug("Getting results of job %s in workspace %s", job_id, deploy_workspace)

    headers = dict(request.headers)
    headers.pop("authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/jobs/{job_id}/results",
        headers=headers,
    )
    return Response(
        content=json.dumps(response.json()).replace("http://localhost:8080", ADES_INGRESS_PATH),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.get("/{deploy_workspace}/ogc-api/jobs", dependencies=[Depends(opa_dependency)])
def list_jobs(deploy_workspace: str, request: Request):
    """Endpoint to list all jobs in a workspace"""
    logger.debug("Listing jobs in workspace %s", deploy_workspace)

    username, _ = get_user_details(request)

    user_workspace = convert_username_to_workspace(username)

    headers = dict(request.headers)
    headers.pop("authorization", None)

    # Get all jobs in the deployed workspace
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


@app.get(
    "/{deploy_workspace}/temp/{workflow_job_id}/{file_name}", dependencies=[Depends(opa_dependency)]
)
def get_logs(deploy_workspace: str, workflow_job_id: str, file_name: str, request: Request):
    """Endpoint to get the logs of a job"""

    # Extract workflow and job ids
    workflow_id = workflow_job_id[:-37]
    job_id = workflow_job_id[-36:]

    logger.info("Accessing logs: %s for workflow: %s and job: %s", file_name, workflow_id, job_id)

    headers = dict(request.headers)
    headers.pop("authorization", None)

    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/temp/{workflow_job_id}/{file_name}",
        headers=headers,
    )

    # Here, headers are generated by FastApi automatically
    return Response(
        content=response.content,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.delete("/{deploy_workspace}/ogc-api/jobs/{job_id}", dependencies=[Depends(opa_dependency)])
def delete_job(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to delete a job"""
    logger.info("Deleting job %s in workspace %s", job_id, deploy_workspace)

    headers = dict(request.headers)
    headers.pop("authorization", None)
    response = requests.delete(
        f"{ADES_SERVICE_ENDPOINT}/{deploy_workspace}/ogc-api/jobs/{job_id}", headers=headers
    )

    try:
        response_content = json.dumps(response.json()).replace(
            "http://localhost:8080", ADES_INGRESS_PATH
        )
    except JSONDecodeError:
        response_content = response.text

    return Response(
        content=response_content,
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
