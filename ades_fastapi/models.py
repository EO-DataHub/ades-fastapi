from pydantic import BaseModel, Field


class PingResponse(BaseModel):
    status: str

    class Config:
        schema_extra = {"example": {"status": "PONG"}}


class InputsResponse(BaseModel):
    title: str
    description: str
    schema: dict
    extended_schema: dict = Field(alias="extended-schema", default=None)


class OutputsResponse(BaseModel):
    title: str
    description: str
    schema: dict
    extended_schema: dict = Field(alias="extended-schema", default=None)


class LinksResponse(BaseModel):
    title: str
    rel: str
    type: str
    href: str


class EmptyResponse(BaseModel):
    status: str
    title: str
    type: str
    detail: str

    class Config:
        schema_extra = {
            "example": {},
            "error_example": {
                "title": "NoSuchProcess",
                "type": "http://www.opengis.net/def/rel/ogc/1.0/exception/no-such-process",
                "detail": "Unable to parse the ZCFG file: workflow.zcfg (No message provided)",
            },
        }


class ProcessDetailsResponse(BaseModel):
    id: str
    title: str
    description: str
    mutable: bool
    version: str
    metadata: list[dict]
    jobControlOptions: list[str]
    outputTransmission: list[str]
    links: list[LinksResponse]
    AccessReasoning: str


class ListProcessesResponse(BaseModel):
    processes: list[ProcessDetailsResponse]

    class Config:
        schema_extra = {
            "example": {
                "processes": [
                    {
                        "id": "workflowID",
                        "title": "workflow title",
                        "description": "workflow description",
                        "mutable": False,
                        "version": "2.0.0",
                        "metadata": [{"title": "Demo"}],
                        "jobControlOptions": ["sync-execute", "async-execute", "dismiss"],
                        "outputTransmission": ["value", "reference"],
                        "links": [
                            {
                                "rel": "self",
                                "type": "application/json",
                                "title": "Process Description",
                                "href": "https://prod.eodatahub.org.uk/api/catalogue/stac/catalogs/user/catalogs/workspace/processes/echo",
                            }
                        ],
                        "AccessReasoning": "Workspace owns this workflow",
                    }
                ]
            }
        }


class GetProcessResponse(BaseModel):
    id: str
    title: str
    description: str
    mutable: bool
    version: str
    metadata: list[dict]
    jobControlOptions: list[str]
    outputTransmission: list[str]
    links: list[LinksResponse]
    inputs: dict[str, InputsResponse]
    outputs: dict[str, OutputsResponse]
    AccessReasoning: str

    class Config:
        schema_extra = {
            "example": {
                "id": "echo",
                "title": "Echo input",
                "description": "Simply echo the value provided as input",
                "mutable": False,
                "version": "2.0.0",
                "metadata": [{"title": "Demo"}],
                "jobControlOptions": ["sync-execute", "async-execute", "dismiss"],
                "outputTransmission": ["value", "reference"],
                "links": [
                    {
                        "rel": "http://www.opengis.net/def/rel/ogc/1.0/execute",
                        "type": "application/json",
                        "title": "Execute End Point",
                        "href": "https://prod.eodatahub.org.uk/api/catalogue/stac/catalogs/user/catalogs/workspace/processes/echo/execution",
                    }
                ],
                "inputs": {
                    "a": {
                        "title": "Literal Input (string)",
                        "description": "An input string",
                        "schema": {"type": "string", "nullable": True},
                    },
                    "b": {
                        "title": "Complex Input",
                        "description": "A complex input ",
                        "extended-schema": {
                            "oneOf": [
                                {
                                    "allOf": [
                                        {"$ref": "http://zoo-project.org/dl/link.json"},
                                        {
                                            "type": "object",
                                            "properties": {
                                                "type": {"enum": ["text/xml", "application/json"]}
                                            },
                                        },
                                    ]
                                },
                                {
                                    "type": "object",
                                    "required": ["value"],
                                    "properties": {
                                        "value": {
                                            "oneOf": [
                                                {
                                                    "type": "string",
                                                    "contentEncoding": "utf-8",
                                                    "contentMediaType": "text/xml",
                                                },
                                                {"type": "object"},
                                            ]
                                        }
                                    },
                                },
                            ],
                            "nullable": True,
                        },
                        "schema": {
                            "oneOf": [
                                {
                                    "type": "string",
                                    "contentEncoding": "utf-8",
                                    "contentMediaType": "text/xml",
                                },
                                {"type": "object"},
                            ]
                        },
                    },
                    "c": {
                        "title": "BoundingBox Input ",
                        "description": "A boundingbox input ",
                        "schema": {
                            "type": "object",
                            "required": ["bbox", "crs"],
                            "properties": {
                                "bbox": {
                                    "type": "array",
                                    "oneOf": [
                                        {"minItems": 4, "maxItems": 4},
                                        {"minItems": 6, "maxItems": 6},
                                    ],
                                    "items": {"type": "number", "format": "double"},
                                },
                                "crs": {
                                    "type": "string",
                                    "format": "uri",
                                    "default": "urn:ogc:def:crs:EPSG:6.6:4326",
                                    "enum": [
                                        "urn:ogc:def:crs:EPSG:6.6:4326",
                                        "urn:ogc:def:crs:EPSG:6.6:3785",
                                    ],
                                },
                            },
                            "nullable": True,
                            "format": "ogc-bbox",
                        },
                    },
                    "pause": {
                        "title": "Literal Input (double)",
                        "description": (
                            "An optional input which can be used to specify"
                            "the number of seconds to pause the service before returning"
                        ),
                        "schema": {
                            "type": "number",
                            "default": 10.0,
                            "format": "double",
                            "nullable": True,
                        },
                    },
                },
                "outputs": {
                    "a": {
                        "title": "The output a",
                        "description": "The output a returned",
                        "schema": {"type": "string"},
                    },
                    "b": {
                        "title": "The output b",
                        "description": "The output b returned",
                        "extended-schema": {
                            "oneOf": [
                                {
                                    "allOf": [
                                        {"$ref": "http://zoo-project.org/dl/link.json"},
                                        {
                                            "type": "object",
                                            "properties": {
                                                "type": {"enum": ["text/xml", "application/json"]}
                                            },
                                        },
                                    ]
                                },
                                {
                                    "type": "object",
                                    "required": ["value"],
                                    "properties": {
                                        "value": {
                                            "oneOf": [
                                                {
                                                    "type": "string",
                                                    "contentEncoding": "utf-8",
                                                    "contentMediaType": "text/xml",
                                                },
                                                {"type": "object"},
                                            ]
                                        }
                                    },
                                },
                            ]
                        },
                        "schema": {
                            "oneOf": [
                                {
                                    "type": "string",
                                    "contentEncoding": "utf-8",
                                    "contentMediaType": "text/xml",
                                },
                                {"type": "object"},
                            ]
                        },
                    },
                    "c": {
                        "title": "BoundingBox output ",
                        "description": "A boundingbox output ",
                        "schema": {
                            "type": "object",
                            "required": ["bbox", "crs"],
                            "properties": {
                                "bbox": {
                                    "type": "array",
                                    "oneOf": [
                                        {"minItems": 4, "maxItems": 4},
                                        {"minItems": 6, "maxItems": 6},
                                    ],
                                    "items": {"type": "number", "format": "double"},
                                },
                                "crs": {
                                    "type": "string",
                                    "format": "uri",
                                    "default": "urn:ogc:def:crs:EPSG:6.6:4326",
                                    "enum": [
                                        "urn:ogc:def:crs:EPSG:6.6:4326",
                                        "urn:ogc:def:crs:EPSG:6.6:3785",
                                    ],
                                },
                            },
                            "format": "ogc-bbox",
                        },
                    },
                },
            },
            "error_example": {
                "title": "NoSuchProcess",
                "type": "http://www.opengis.net/def/rel/ogc/1.0/exception/no-such-process",
                "detail": "Unable to parse the ZCFG file: workflow.zcfg (No message provided)",
            },
        }


class DeployProcessResponse(BaseModel):
    id: str
    title: str
    description: str
    mutable: bool
    version: str
    metadata: list[dict]
    outputTransmission: list[str]
    jobControlOptions: list[str]
    links: list[LinksResponse]

    class Config:
        schema_extra = {
            "example": {
                "id": "workflowID",
                "title": "Workflow title",
                "description": "Workflow description",
                "mutable": True,
                "version": "0.1.2",
                "metadata": [{"role": "https://schema.org/softwareVersion", "value": "0.1.2"}],
                "outputTransmission": ["value", "reference"],
                "jobControlOptions": ["async-execute", "dismiss"],
                "links": [
                    {
                        "rel": "http://www.opengis.net/def/rel/ogc/1.0/execute",
                        "type": "application/json",
                        "title": "Execute End Point",
                        "href": "https://prod.eodatahub.org.uk/api/catalogue/stac/catalogs/user/catalogs/workspace/processes/workflowID/execution",
                    }
                ],
            }
        }


class ExecuteProcessResponse(BaseModel):
    progress: int
    id: str
    jobID: str
    type: str
    processID: str
    created: str
    started: str
    updated: str
    status: str
    message: str
    links: list[LinksResponse]

    class Config:
        schema_extra = {
            "example": {
                "progress": 0,
                "id": "806e3380-152e-11f0-b600-82b2cc669c52",
                "jobID": "806e3380-152e-11f0-b600-82b2cc669c52",
                "type": "process",
                "processID": "workflowID",
                "created": "2025-04-09T10:36:31.830Z",
                "started": "2025-04-09T10:36:31.830Z",
                "updated": "2025-04-09T10:36:31.830Z",
                "status": "running",
                "message": "ZOO-Kernel accepted to run your service!",
                "links": [
                    {
                        "title": "Status location",
                        "rel": "monitor",
                        "type": "application/json",
                        "href": "https://prod.eodatahub.org.uk/api/catalogue/stac/catalogs/user/catalogs/workspace/jobs/806e3380-152e-11f0-b600-82b2cc669c52",
                    }
                ],
            },
            "error_example": {"detail": "Invalid input pyload, not valid JSON"},
        }


class GetJobStatusResponse(BaseModel):
    progress: int
    id: str
    jobID: str
    type: str
    processID: str
    created: str
    started: str
    updated: str
    status: str
    message: str
    links: list[LinksResponse]

    class Config:
        schema_extra = {
            "example": {
                "progress": 0,
                "id": "806e3380-152e-11f0-b600-82b2cc669c52",
                "jobID": "806e3380-152e-11f0-b600-82b2cc669c52",
                "type": "process",
                "processID": "workflowID",
                "created": "2025-04-09T10:36:31.830Z",
                "started": "2025-04-09T10:36:31.830Z",
                "updated": "2025-04-09T10:36:31.830Z",
                "status": "running",
                "message": "ZOO-Kernel accepted to run your service!",
                "links": [
                    {
                        "title": "Status location",
                        "rel": "monitor",
                        "type": "application/json",
                        "href": "https://prod.eodatahub.org.uk/api/catalogue/stac/catalogs/user/catalogs/workspace/jobs/806e3380-152e-11f0-b600-82b2cc669c52",
                    }
                ],
            },
            "error_example": {"detail": "Invalid input pyload, not valid JSON"},
        }


class GetAllJobStatusResponse(BaseModel):
    jobs: list[GetJobStatusResponse]

    class Config:
        schema_extra = {
            "example": {
                "jobs": [
                    {
                        "progress": 0,
                        "id": "806e3380-152e-11f0-b600-82b2cc669c52",
                        "jobID": "806e3380-152e-11f0-b600-82b2cc669c52",
                        "type": "process",
                        "processID": "workflowID",
                        "created": "2025-04-09T10:36:31.830Z",
                        "started": "2025-04-09T10:36:31.830Z",
                        "updated": "2025-04-09T10:36:31.830Z",
                        "status": "running",
                        "message": "ZOO-Kernel accepted to run your service!",
                        "links": [
                            {
                                "title": "Status location",
                                "rel": "monitor",
                                "type": "application/json",
                                "href": "https://prod.eodatahub.org.uk/api/catalogue/stac/catalogs/user/catalogs/workspace/jobs/806e3380-152e-11f0-b600-82b2cc669c52",
                            }
                        ],
                    }
                ]
            },
            "error_example": {"detail": "Invalid input pyload, not valid JSON"},
        }


class ExtentSpatial(BaseModel):
    bbox: list[list[float, float, float, float]] = Field(
        ...,
        description="A list of coordinates defining the surrounding bbox for the collection",
        example=[[-170, -89, 179, 89]],
    )


class ExtentTemporal(BaseModel):
    interval: list[list[str, str]] = Field(
        ...,
        description=(
            "A list of temporal intervals, where each interval "
            "is a list containing a start and end time."
        ),
        example=[["2025-04-09T10:00:00Z", "2025-04-09T12:00:00Z"]],
    )


class Extent(BaseModel):
    spatial: ExtentSpatial
    temporal: ExtentTemporal


class GetJobResultsResponse(BaseModel):
    type: str
    id: str
    stac_version: str
    description: str
    title: str
    extent: Extent
    license: str
    keywords: list[str]
    links: list[LinksResponse]

    class Config:
        schema_extra = {
            "example": {
                "type": "Collection",
                "id": "col_185e5c6a-152f-11f0-9687-82b2cc669c52",
                "stac_version": "1.0.0",
                "description": "description",
                "links": [
                    {
                        "rel": "root",
                        "href": "https://workspace.prod.eodatahub-workspaces.org.uk/files/workspaces-eodhp-prod/processing-results/workflow.json",
                        "type": "application/json",
                        "title": "workflow Outputs Catalog",
                    },
                    {
                        "rel": "item",
                        "href": "https://workspace.prod.eodatahub-workspaces.org.uk/files/workspaces-eodhp-prod/processing-results/workflow/output-catalog/col_185e5c6a-152f-11f0-9687-82b2cc669c52/output-item.json",
                        "type": "application/json",
                    },
                    {
                        "rel": "self",
                        "href": "https://workspace.prod.eodatahub-workspaces.org.uk/files/workspaces-eodhp-prod/processing-results/workflow/output-catalog/col_185e5c6a-152f-11f0-9687-82b2cc669c52.json",
                        "type": "application/json",
                    },
                    {
                        "rel": "parent",
                        "href": "https://workspace.prod.eodatahub-workspaces.org.uk/files/workspaces-eodhp-prod/processing-results/workflow/output-catalog.json",
                        "type": "application/json",
                    },
                ],
                "title": "Result Collection for Job 185e5c6a-152f-11f0-9687-82b2cc669c52",
                "extent": {
                    "spatial": {"bbox": [[-180, -90, 180, 90]]},
                    "temporal": {
                        "interval": [["2025-04-09T10:41:10.071152Z", "2025-04-09T10:41:10.071152Z"]]
                    },
                },
                "license": "proprietary",
                "keywords": ["eoepca"],
            },
            "error_example": {
                "title": "ResultNotReady",
                "type": "http://www.opengis.net/def/rel/ogc/1.0/exception/result-not-ready",
                "detail": "The job is still running.",
            },
        }


class DeleteJobResponse(BaseModel):
    id: str
    jobID: str
    status: str
    message: str
    links: list[LinksResponse]
    type: str
    processID: str
    created: str
    started: str
    updated: str

    class Config:
        schema_extra = {
            "example": {
                "id": "13c9aaf4-1531-11f0-b8cf-82b2cc669c52",
                "jobID": "13c9aaf4-1531-11f0-b8cf-82b2cc669c52",
                "status": "dismissed",
                "message": "ZOO-Kernel successfully dismissed your service!",
                "links": [
                    {
                        "title": "The job list for the current process",
                        "rel": "parent",
                        "type": "application/json",
                        "href": "https://prod.eodatahub.org.uk/api/catalogue/stac/catalogs/user/catalogs/workspace/jobs",
                    }
                ],
                "type": "process",
                "processID": "workflowID",
                "created": "2025-04-09T10:54:58.105Z",
                "started": "2025-04-09T10:54:58.105Z",
                "updated": "2025-04-09T10:54:58.955Z",
            },
            "error_example": {
                "title": "NoSuchJob",
                "type": "http://www.opengis.net/def/rel/ogc/1.0/exception/no-such-job",
                "detail": "The JobID from the request does not match any of the Jobs running on this server",
            },
        }


class GetJobLogResponse(BaseModel):

    class Config:
        schema_extra = {
            "example": "Some log file contents",
        }
