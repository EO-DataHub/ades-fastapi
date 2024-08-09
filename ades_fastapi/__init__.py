import json
import os

import jwt
import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

# OPA service endpoint
OPA_SERVICE_ENDPOINT = os.getenv(
    "OPA_SERVICE_ENDPOINT", "http://opal-client.opal:8181/v1/data/ades/allow"
)

# ADES service endpoint
ADES_SERVICE_ENDPOINT = os.getenv("ADES_SERVICE_ENDPOINT", "http://zoo-project-dru-service:80")

app = FastAPI()


def opa_request(input_data: dict):
    return requests.post(OPA_SERVICE_ENDPOINT, json=input_data)


def check_policy(request: Request):
    token = request.headers.get("authorization", "")
    stripped_token = token.replace("Bearer ", "")
    if stripped_token:
        credentials = jwt.decode(
            stripped_token,
            options={"verify_signature": False},
            algorithms=["HS256"],
        )
        username = credentials.get("preferred_username", "")
        roles = credentials.get("resource_access", {}).get("roles", [])
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
    response = opa_request(input_data)
    if response.status_code != 200 or not response.json().get("result", False):
        return False
    return True


@app.middleware("http")
async def opa_middleware(request: Request, call_next):
    if check_policy(request):
        response = await call_next(request)
        return response
    else:
        return JSONResponse(status_code=403, content={"detail": "Access denied"})


@app.get("/ades")
def root():
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/")
    if response.headers.get("Content-Type") == "text/html":
        return HTMLResponse(content=response.text, status_code=response.status_code)
    else:
        raise HTTPException(status_code=406, detail="Unexpected content type")
    # if response.status_code != 200:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to fetch swagger docs")


@app.get("/ades/{workspace}/ogc-api")
def workspace_root(workspace: str):
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/")
    if response.headers.get("Content-Type") == "text/html":
        return HTMLResponse(content=response.text, status_code=response.status_code)
    else:
        raise HTTPException(status_code=406, detail="Unexpected content type")
    # if response.status_code != 200:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to fetch swagger docs")


@app.get("/ades/api")
def swagger_docs():
    response = requests.get(f"{ADES_SERVICE_ENDPOINT}/swagger-ui/oapip/#/")
    if response.headers.get("Content-Type") == "text/html":
        return HTMLResponse(content=response.text, status_code=response.status_code)
    else:
        raise HTTPException(status_code=406, detail="Unexpected content type")


# endpoint to delete process
@app.delete("/ades/{workspace}/ogc-api/processes/{workflow_id}")
def undeploy_process(workspace: str, workflow_id: str):
    workspace = workspace.replace("-", "_")
    response = requests.delete(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes/{workflow_id}"
        # headers=dict(request.headers),
    )
    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")
    # try:
    #     result = json.dumps(response.json())
    # except Exception:
    result = response.text

    return Response(
        content=result,
        status_code=response.status_code,
    )


# endpoint to list processes
@app.get("/ades/{workspace}/ogc-api/processes")
def list_processes(workspace: str, request: Request):
    workspace = workspace.replace("-", "_")
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes"  # , headers=dict(request.headers)
    )

    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")
    try:
        result = json.dumps(response.json())
    except Exception:
        result = response.text
    return Response(
        content=result,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


# deploy process
@app.post("/ades/{workspace}/ogc-api/processes")
async def deploy_process(workspace: str, request: Request):
    workspace = workspace.replace("-", "_")

    headers = dict(request.headers)
    new_headers = {"accept": headers["accept"], "content-type": headers["content-type"]}

    try:
        data = {"json": await request.json()}
    except Exception:
        # Handle file content
        file_content = await request.body()
        # Prepare the payload for the subsequent API request
        data = {"content": file_content}  # Decode bytes to string

    response = requests.post(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes", headers=new_headers, **data
    )

    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")

    response_headers = {"Location": response.headers.get("Location")}
    # response_headers.pop("content-length", None)
    # use streamingresponse to avoid content-length header being set automatically, causing issues
    # with Transfer-Encoding
    return StreamingResponse(
        content=json.dumps(response.json()),
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response_headers,
    )


# update process
@app.put("/ades/{workspace}/ogc-api/processes/{workflow_id}")
async def update_process(workspace: str, workflow_id: str, request: Request):
    workspace = workspace.replace("-", "_")

    headers = dict(request.headers)
    new_headers = {"accept": headers["accept"], "content-type": headers["content-type"]}

    try:
        data = {"json": await request.json()}
    except Exception:
        # Handle file content
        file_content = await request.body()
        # Prepare the payload for the subsequent API request
        data = {"content": file_content}  # Decode bytes to string

    response = requests.put(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes", headers=new_headers, **data
    )

    try:
        content = json.dumps(response.json())
    except Exception:
        content = ""

    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")

    # use streamingresponse to avoid content-length header being set automatically, causing issues
    # with Transfer-Encoding
    return Response(
        content=content,
        status_code=response.status_code,
        headers=response.headers,
    )


# # update process
# @app.put("/ades/{workspace}/ogc-api/processes/{workflow_id}")
# async def update_process(
#     workspace: str, workflow_id: str, request: Request, file: UploadFile = File(...)
# ):
#     workspace = workspace.replace("-", "_")

#     body = await request.json()
#     file_content = await file.read()

#     # Prepare the data to be sent in the request
#     data = {
#         "headers": dict(request.headers),
#         "files": {"file": (file.filename, file_content, file.content_type)},
#         "json": body,
#     }

#     response = requests.put(
#         f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes/{workflow_id}",
#         # headers=dict(request.headers),
#         **data,
#     )
#     # if response.status_code < 200 or response.status_code >= 300:
#     #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")
#     return Response(
#         content=json.dumps(response.json()),
#         media_type=response.headers["Content-Type"],
#         status_code=response.status_code,
#     )


# get process details
@app.get("/ades/{workspace}/ogc-api/processes/{workflow_id}")
def process_details(workspace: str, workflow_id: str, request: Request):
    workspace = workspace.replace("-", "_")
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes/{workflow_id}",
        # headers=dict(request.headers),
    )
    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")
    return Response(
        content=json.dumps(response.json()),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


# execute process
@app.post("/ades/{workspace}/ogc-api/processes/{workflow_id}/execution")
async def execute_process(workspace: str, workflow_id: str, request: Request):
    workspace = workspace.replace("-", "_")

    body = await request.json()

    response = requests.post(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/processes/{workflow_id}/execution",
        # headers=dict(request.headers),
        json=body,
    )
    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")
    # use streamingresponse to avoid content-length header being set automatically, causing issues
    # with Transfer-Encoding
    return StreamingResponse(
        content=json.dumps(response.json()),
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
        headers=response.headers,
    )


# get execute status
@app.get("/ades/{workspace}/ogc-api/jobs/{job_id}")
def execute_status(workspace: str, job_id: str, request: Request):
    workspace = workspace.replace("-", "_")
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs/{job_id}",  # headers=dict(request.headers)
    )
    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")
    return Response(
        content=json.dumps(response.json()),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


# get processing results
@app.get("/ades/{workspace}/ogc-api/jobs/{job_id}/results")
def processing_results(workspace: str, job_id: str, request: Request):
    workspace = workspace.replace("-", "_")
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs/{job_id}/results",
        # headers=dict(request.headers),
    )
    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")
    return Response(
        content=json.dumps(response.json()),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


# list jobs
@app.get("/ades/{workspace}/ogc-api/jobs")
def list_jobs(workspace: str, request: Request):
    workspace = workspace.replace("-", "_")
    response = requests.get(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs",  # headers=dict(request.headers)
    )
    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete process")
    return Response(
        content=json.dumps(response.json()),
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )


# delete job (not working)
@app.delete("/ades/{workspace}/ogc-api/jobs/{job_id}")
def delete_job(workspace: str, job_id: str, request: Request):
    workspace = workspace.replace("-", "_")
    return Response(
        content="Endpoint not implemented yet",
        status_code=501,
    )
    response = requests.delete(
        f"{ADES_SERVICE_ENDPOINT}/{workspace}/ogc-api/jobs/{job_id}", headers=dict(request.headers)
    )
    # if response.status_code < 200 or response.status_code >= 300:
    #     raise HTTPException(status_code=response.status_code, detail="Failed to delete job")
    return Response(
        content=response.text,
        media_type=response.headers["Content-Type"],
        status_code=response.status_code,
    )
