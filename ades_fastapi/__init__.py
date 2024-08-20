import json
import os
from json import JSONDecodeError

import jwt
import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ADES_INGRESS_PATH = os.getenv("ADES_INGRESS_PATH", "/ades")

# OPA service endpoint
OPA_SERVICE_ENDPOINT = os.getenv(
    "OPA_SERVICE_ENDPOINT", "http://opal-client.opal:8181/v1/data/ades/allow"
)

# ADES service endpoint
ADES_SERVICE_ENDPOINT = os.getenv("ADES_SERVICE_ENDPOINT", "http://zoo-project-dru-service:80")

# Used for local testing where OPA is not available
ENABLE_OPA_POLICY_CHECK = os.getenv("ENABLE_OPA_POLICY_CHECK", "true")

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
    return requests.post(OPA_SERVICE_ENDPOINT, json=input_data)


def check_policy(request: Request):
    """Check OPA policy to determine if the request is allowed"""
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
    input_data = {
        "input": {
            "roles": roles,
            "path": request.url.path,
            "username": username,
        }
    }
    print("Logged in as user:", username)
    print("Path is ", request.url.path)
    print("Roles are ", roles)
    response = opa_request(input_data)
    if response.status_code != 200 or not response.json().get("result", False):
        return False
    return True


@app.middleware("http")
async def opa_middleware(request: Request, call_next):
    """Middleware to check OPA policy before allowing access to the endpoint"""
    print("opa policy check is ", ENABLE_OPA_POLICY_CHECK)
    if ENABLE_OPA_POLICY_CHECK == "true":
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
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/")
    if response.headers.get("Content-Type") == "text/html":
        return HTMLResponse(content=response.text, status_code=response.status_code)
    else:
        raise HTTPException(status_code=406, detail="Unexpected content type")


@app.get("/{workspace}/ogc-api")
def workspace_root(workspace: str):
    """Root endpoint for user's workspace"""
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/")
    if response.headers.get("Content-Type") == "text/html":
        return HTMLResponse(content=response.text, status_code=response.status_code)
    else:
        raise HTTPException(status_code=406, detail="Unexpected content type")


@app.get("/ogc-api/api")
def docs_root():
    """Root endpoint for ADES API Docs, used by Swagger UI"""
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
    # workspace = workspace.replace("-", "_")
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
    # workspace = workspace.replace("-", "_")
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes", headers=headers
    )

    if "application/json" in response.headers["Content-Type"]:
        result = json.dumps(response.json())
    else:
        result = response.text
    return Response(
        content=result,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.post("/{workspace}/ogc-api/processes")
async def deploy_process(workspace: str, request: Request):
    """Endpoint to deploy a workflow to a workspace"""
    # workspace = workspace.replace("-", "_")

    headers = dict(request.headers)
    headers.pop("Authorization", None)

    if "application/json" in request.headers["Content-Type"]:
        # Handle HTTP file content
        data = {"json": await request.json()}
    elif "application/cwl+yaml" in request.headers["Content-Type"]:
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
        content = json.dumps(response.json(), indent=2)
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
    # workspace = workspace.replace("-", "_")

    headers = dict(request.headers)
    headers.pop("Authorization", None)

    if "application/json" in request.headers["Content-Type"]:
        # Handle HTTP file content
        data = {"json": await request.json()}
    elif "application/cwl+yaml" in request.headers["Content-Type"]:
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


@app.get("/{workspace}/ogc-api/processes/{workflow_id}")
def process_details(workspace: str, workflow_id: str, request: Request):
    """Endpoint to get details of a workflow in a workspace"""
    # workspace = workspace.replace("-", "_")
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes/{workflow_id}",
        headers=headers,
    )
    try:
        content = json.dumps(response.json())
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
    headers = dict(request.headers)
    headers.pop("authorization", None)
    # headers.pop("prefer", None)

    # headers = {"prefer": "respond-async"}

    print("Headers are ", headers)

    body = await request.json()

    print("Body is ", body)

    response = requests.post(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes/{workflow_id}/execution",
        headers=headers,
        json=body,
    )

    print("response is ", response.text)
    print("status code is ", response.status_code)
    print("headers are ", response.headers)

    try:
        content = json.dumps(response.json(), indent=2)
    except JSONDecodeError:
        content = response.text

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
    # workspace = workspace.replace("-", "_")
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs/{job_id}", headers=headers
    )
    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")
    return Response(
        content=json.dumps(response.json()),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.get("/{workspace}/ogc-api/jobs/{job_id}/results")
def processing_results(workspace: str, job_id: str, request: Request):
    """Endpoint to get the results of an executed workflow or job"""
    # workspace = workspace.replace("-", "_")
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs/{job_id}/results",
        headers=headers,
    )
    return Response(
        content=json.dumps(response.json()),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.get("/{workspace}/ogc-api/jobs")
def list_jobs(workspace: str, request: Request):
    """Endpoint to list all jobs in a workspace"""
    # workspace = workspace.replace("-", "_")
    headers = dict(request.headers)
    headers.pop("Authorization", None)
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs", headers=headers)

    return Response(
        content=json.dumps(response.json()),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


@app.delete("/{workspace}/ogc-api/jobs/{job_id}")
def delete_job(workspace: str, job_id: str, request: Request):
    """Endpoint to delete a job"""
    # workspace = workspace.replace("-", "_")
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
