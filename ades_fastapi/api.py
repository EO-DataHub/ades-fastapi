import logging
import os
from distutils.util import strtobool

import requests
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .ades_client import ADESClient
from .airbus_client import AirbusClient
from .dependency_client import DependencyClient
from .job_saver import JobSaver
from .planet_client import PlanetClient
from .utils import QuoteRequest, WorkflowType, get_user_details

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


def configure_job_saver():
    """Configure the job saver"""
    return JobSaver(JOB_OWNER_STORAGE_DIR)


# Create clients used by the API
job_saver = configure_job_saver()

ades_client = ADESClient(
    ADES_SERVICE_ENDPOINT, ADES_INGRESS_PATH, ADES_POLICY_BUCKET, ADES_POLICY_PREFIX
)

airbus_client = AirbusClient(AIRBUS_ENV)
planet_client = PlanetClient()

dependency_client = DependencyClient(
    OPA_SERVICE_ENDPOINT, ADES_POLICY_BUCKET, ADES_POLICY_PREFIX, ENABLE_OPA_POLICY_CHECK
)


def opa_dependency(request: Request) -> WorkflowType:  # noqa: B008
    passed, wf_type = dependency_client.check_access(request, job_saver.job_owners)

    if not passed:
        if not get_user_details(request)[0]:
            # User not authenticated
            raise HTTPException(status_code=401, detail="Not Authenticated")
        else:
            # User is not authorized
            raise HTTPException(status_code=403, detail="Not Authorized")

    return wf_type


@app.get("", dependencies=[Depends(opa_dependency)])
def root():
    """Root endpoint for ADES API Docs, used by Swagger UI"""
    logger.info("Getting ADES root")
    response = ades_client.get_root()
    if response.status_code == 200:
        return HTMLResponse(content="<h1>ADES HOMEPAGE</h1><p>Status: available</p>")
    else:
        return HTMLResponse(
            content="<h1>ADES HOMEPAGE</h1><p>Status: Unavailable</p>", status_code=503
        )


@app.get("/{deploy_workspace}/ogc-api", dependencies=[Depends(opa_dependency)])
def workspace_root(deploy_workspace: str):
    """Root endpoint for user's workspace"""
    logger.info("Getting root of workspace %s", deploy_workspace)

    response, content = ades_client.get_workspace_root(deploy_workspace)

    return StreamingResponse(
        content=content,
        status_code=response.status_code,
        headers=response.headers,
        media_type=response.headers.get("Content-Type"),
    )


@app.delete(
    "/{deploy_workspace}/ogc-api/processes/{workflow_id}", dependencies=[Depends(opa_dependency)]
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
        media_type=response.headers.get("Content-Type"),
    )


@app.get("/{deploy_workspace}/ogc-api/processes", dependencies=[Depends(opa_dependency)])
def list_processes(deploy_workspace: str, request: Request):
    """Endpoint to list all workflows deployed in a workspace"""
    logger.info("Listing workflows in workspace %s", deploy_workspace)

    response, content = ades_client.list_workflows(request, deploy_workspace)

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


@app.post("/{deploy_workspace}/ogc-api/processes", dependencies=[Depends(opa_dependency)])
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
        media_type=response.headers.get("Content-Type"),
    )


@app.put(
    "/{deploy_workspace}/ogc-api/processes/{workflow_id}", dependencies=[Depends(opa_dependency)]
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
    "/{deploy_workspace}/ogc-api/processes/{workflow_id}", dependencies=[Depends(opa_dependency)]
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
    "/{deploy_workspace}/ogc-api/processes/{workflow_id}/execution",
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
        job_saver.record_owner(response, deploy_workspace, calling_workspace)
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

    response, content = ades_client.get_job_status(dict(request.headers), deploy_workspace, job_id)

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


@app.get(
    "/{deploy_workspace}/ogc-api/jobs/{job_id}/results", dependencies=[Depends(opa_dependency)]
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


@app.get("/{deploy_workspace}/ogc-api/jobs", dependencies=[Depends(opa_dependency)])
def get_deployed_workspaced_jobs(deploy_workspace: str, request: Request):
    """Endpoint to list all jobs in a workspace"""
    logger.debug("Listing jobs in workspace %s", deploy_workspace)

    response, content = ades_client.get_deployed_workspaced_jobs(
        request, deploy_workspace, job_saver.job_owners
    )

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


@app.get("/ogc-api/jobs", dependencies=[Depends(opa_dependency)])
def get_all_jobs(request: Request):
    """Endpoint to list all jobs called by the given user"""

    content = ades_client.get_all_jobs(dict(request.headers), job_saver.workspace_jobs)

    return Response(
        content=content,
        media_type="application/json",
        status_code=200,
    )


@app.get(
    "/{deploy_workspace}/temp/{workflow_job_id}/{file_name}", dependencies=[Depends(opa_dependency)]
)
def get_process_log(deploy_workspace: str, workflow_job_id: str, file_name: str, request: Request):
    """Endpoint to get the logs of a job"""

    response = ades_client.get_log(
        workflow_job_id, file_name, deploy_workspace, dict(request.headers)
    )

    return Response(
        content=response.content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


@app.delete("/{deploy_workspace}/ogc-api/jobs/{job_id}", dependencies=[Depends(opa_dependency)])
def delete_job(deploy_workspace: str, job_id: str, request: Request):
    """Endpoint to delete a job"""
    logger.info("Deleting job %s in workspace %s", job_id, deploy_workspace)

    response, content = ades_client.delete_job(dict(request.headers), deploy_workspace, job_id)

    return Response(
        content=content,
        media_type=response.headers.get("Content-Type"),
        status_code=response.status_code,
    )


@app.post("/quotes")
def quote(request: Request, body: QuoteRequest):
    """Return a quote for a given acquisition ID"""

    catalogue_name = body.catalogueId.lower()
    collection_id = body.collectionId
    acquisition_id = body.acquisitionId

    if catalogue_name == "airbus":
        if collection_id == "airbus_sar_data":
            if AIRBUS_ENV == "prod":
                url = "https://sar.api.oneatlas.airbus.com/v1/sar/prices"
            else:
                url = "https://dev.sar.api.oneatlas.airbus.com/v1/sar/prices"
            request_body = {"acquisitions": [acquisition_id]}
        else:
            url = "https://order.api.oneatlas.airbus.com/api/v1/prices"
            spectral_processing = "bundle"
            if collection_id == "airbus_pneo_data":
                product_type = "PleiadesNeoArchiveMono"
                contract_id = "CTR24005241"
                item_uuids = body.item_uuids
                item_id = None
                if len(item_uuids) > 1:
                    product_type = "PleiadesNeoArchiveMulti"
                    spectral_processing = "full_bundle"
            elif collection_id == "airbus_phr_data":
                product_type = "PleiadesArchiveMono"
                contract_id = "UNIVERSITY_OF_LEICESTER_Orders"
                item_uuids = None
                item_id = body.acquisitionId
            elif collection_id == "airbus_spot_data":
                product_type = "SPOTArchive1.5Mono"
                contract_id = "UNIVERSITY_OF_LEICESTER_Orders"
                item_uuids = None
                item_id = body.acquisitionId
            else:
                return JSONResponse(
                    status_code=404,
                    content={"detail": f"Collection {collection_id} not recognised"},
                )
            request_body = {
                "aoi": [
                    {
                        "id": 1,
                        "name": "Polygon 1",
                        "geometry": {"type": "Polygon", "coordinates": body.coordinates},
                    }
                ],
                "programReference": "",
                "contractId": contract_id,
                "items": [
                    {
                        "notifications": [],
                        "stations": [],
                        "productTypeId": product_type,
                        "aoiId": 1,
                        "properties": [],
                    }
                ],
                "primaryMarket": "NQUAL",
                "secondaryMarket": "",
                "customerReference": "Polygon 1",
                "optionsPerProductType": [
                    {
                        "productTypeId": product_type,
                        "options": [
                            {"key": "delivery_method", "value": "on_the_flow"},
                            {"key": "fullStrip", "value": "false"},
                            {"key": "image_format", "value": "dimap_geotiff"},
                            {"key": "licence", "value": "standard"},
                            {"key": "pixel_coding", "value": "12bits"},
                            {"key": "priority", "value": "standard"},
                            {"key": "processing_level", "value": "primary"},
                            {"key": "radiometric_processing", "value": "reflectance"},
                            {"key": "spectral_processing", "value": spectral_processing},
                        ],
                    }
                ],
                "orderGroup": "",
                "delivery": {"type": "network"},
            }

            if item_uuids:
                data_source_ids = []
                for item_uuid in item_uuids:
                    data_source_ids.append({"catalogId": "PublicMOC", "catalogItemId": item_uuid})
                request_body["items"][0]["dataSourceIds"] = data_source_ids

            if item_id:
                request_body["items"][0]["datastripIds"] = [item_id]

        access_token = airbus_client.generate_access_token(request)
        if not access_token:
            return JSONResponse(
                status_code=500, content={"detail": "Failed to generate access token"}
            )

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        try:
            response_body = airbus_client.get_quote_from_airbus(url, request_body, headers)
        except requests.RequestException as e:
            return JSONResponse(status_code=500, content={"detail": str(e)})

        price_json = {}
        if collection_id == "airbus_sar_data":
            for item in response_body:
                if item.get("acquisitionId") == acquisition_id:
                    price_json = {
                        "currency": item["price"]["currency"],
                        "price": item["price"]["total"],
                    }
                    break
        else:
            price_json = {
                "currency": response_body["currency"],
                "price": response_body["totalAmount"],
            }

        if price_json:
            return JSONResponse(
                content=price_json,
                status_code=200,
            )
        return JSONResponse(
            status_code=404, content={"detail": "Quote not found for given acquisition ID"}
        )

    elif catalogue_name == "planet":
        request_body = {"acquisitions": [acquisition_id], "collection": collection_id}
        response_body = planet_client.get_quote_from_planet(request_body)

        return JSONResponse(
            content=response_body,
            status_code=200,
        )

    else:
        return JSONResponse(
            content={"message:" f"{catalogue_name} not recognised"},
            status_code=404,
        )
