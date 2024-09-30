import json
import os
from contextlib import asynccontextmanager

import stlog
from fastapi import Body, FastAPI, HTTPException, Request
from smartjob import (
    ExecutionConfig,
    GcsInput,
    Input,
    RetryConfig,
    SmartJob,
    TimeoutConfig,
    get_executor_service,
)


def check_env_or_raise():
    for env in (
        "SMARTJOB_PROJECT",
        "SMARTJOB_REGION",
        "SMARTJOB_STAGING_BUCKET",
        "SMARTJOB_DOCKER_IMAGE",
    ):
        if env not in os.environ:
            raise Exception(f"Environment variable '{env}' not found")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stlog.setup(level=os.environ.get("SMARTJOB_LOG_LEVEL", "INFO"))
    check_env_or_raise()
    yield


def get_smartjob_cpu_from_env(e: str | None) -> float:
    if e is None:
        return 1.0
    return float(e)


def get_smartjob_memory_gb_from_env(e: str | None) -> float:
    if e is None:
        return 0.5
    return float(e)


app = FastAPI(lifespan=lifespan)

extra_envs: dict[str, str] = {
    k[19:]: v for k, v in os.environ.items() if k.startswith("SMARTJOB_EXTRA_ENV_")
}

execution_config = ExecutionConfig(
    timeout_config=TimeoutConfig(
        timeout_seconds=int(os.environ.get("SMARTJOB_TIMEOUT_SECONDS", "3600"))
    ),
    retry_config=RetryConfig(
        max_attempts=int(os.environ.get("SMARTJOB_MAX_ATTEMPTS", "3"))
    ),
    service_account=os.environ.get("SMARTJOB_SERVICE_ACCOUNT"),
    cpu=get_smartjob_cpu_from_env(os.environ.get("SMARTJOB_CPU")),
    machine_type=os.environ.get("SMARTJOB_MACHINE_TYPE"),
    memory_gb=get_smartjob_memory_gb_from_env(os.environ.get("SMARTJOB_MEMORY_GB")),
    labels={
        k[15:].lower(): v
        for k, v in os.environ.items()
        if k.startswith("SMARTJOB_LABEL_")
    },
    vpc_connector_network=os.environ.get("SMARTJOB_VPC_CONNECTOR_NETWORK"),
    vpc_connector_subnetwork=os.environ.get("SMARTJOB_VPC_CONNECTOR_SUBNETWORK"),
)

executor = os.environ.get("SMARTJOB_EXECUTOR", "cloudrun")


@app.get("/")
async def hello():
    return {"message": "Hello World"}


def get_job_and_input(body: dict, namespace: str, name: str) -> tuple[SmartJob, Input]:
    logger = stlog.getLogger("smartjob-trigger-service")
    logger.debug("received body: %s" % json.dumps(body, indent=4))
    if body.get("kind", "") == "storage#object":
        return get_job_and_input_from_finalized_event(namespace, name, body)
    elif (
        body.get("@type", "")
        == "type.googleapis.com/google.events.cloud.audit.v1.LogEntryData"
    ):
        return get_job_and_input_from_create_event(namespace, name, body)
    else:
        raise HTTPException(
            status_code=400,
            detail="The JSON body must be a storage object finalized event"
            " or a cloud audit log entry",
        )


def get_job_and_input_from_create_event(
    namespace: str, name: str, body: dict
) -> tuple[SmartJob, Input]:
    logger = stlog.getLogger("smartjob-trigger-service")
    if "protoPayload" not in body:
        raise HTTPException(
            status_code=400, detail="'protoPayload' property not found in the JSON body"
        )
    proto_payload = body["protoPayload"]
    if "resourceName" not in proto_payload:
        raise HTTPException(
            status_code=400,
            detail="'resourceName' property not found in the JSON body/protoPayload",
        )
    resource_name = proto_payload["resourceName"]
    # projects/_/buckets/fabien2/objects/copilot mvp.png",
    if not resource_name.startswith("projects/_/buckets/"):
        raise HTTPException(
            status_code=400,
            detail="The 'resourceName' property must start with 'projects/_/buckets/'",
        )
    tmp = resource_name.split("/", 5)
    if len(tmp) != 6:
        raise HTTPException(status_code=400, detail="bad resourceName format")
    bucket = tmp[3]
    path = tmp[5]
    gcs_path = f"gs://{bucket}/{path}"
    logger.debug("gcs input path: %s" % gcs_path)
    input = GcsInput(filename="incoming_file", gcs_path=gcs_path)
    job = SmartJob(
        name=name,
        namespace=namespace,
        docker_image=os.environ["SMARTJOB_DOCKER_IMAGE"],
        add_envs={
            "SMARTJOB_TRIGGER_SERVICE_FULL_PATH": gcs_path,
            **extra_envs,
        },
    )
    return job, input


def get_job_and_input_from_finalized_event(
    namespace: str, name: str, body: dict
) -> tuple[SmartJob, Input]:
    def get_gcs_path_from_body(body: dict) -> str:
        id = body["id"]
        bucket = body["bucket"]
        generation = body["generation"]
        if not id.startswith(bucket):
            raise HTTPException(
                status_code=400,
                detail="The 'id' property must start with the 'bucket' property",
            )
        if not id.endswith(f"/{generation}"):
            raise HTTPException(
                status_code=400,
                detail="The 'id' property must end with the 'generation' property",
            )
        tmp = id[len(bucket) + 1 :]  # +1 because we want also to remove the slash
        path = tmp[: -len(f"/{generation}")]
        return f"gs://{bucket}/{path}"

    logger = stlog.getLogger("smartjob-trigger-service")
    for prop in ("kind", "id", "bucket", "generation"):
        if prop not in body:
            raise HTTPException(
                status_code=400, detail=f"'{prop}' property not found in the JSON body"
            )
    if body["kind"] != "storage#object":
        raise HTTPException(
            status_code=400, detail="The 'kind' property must be 'storage#object'"
        )
    gcs_path = get_gcs_path_from_body(body)
    logger.debug("gcs input path: %s" % gcs_path)
    input = GcsInput(filename="incoming_file", gcs_path=gcs_path)
    job = SmartJob(
        name=name,
        namespace=namespace,
        docker_image=os.environ["SMARTJOB_DOCKER_IMAGE"],
        add_envs={
            "SMARTJOB_TRIGGER_SERVICE_FULL_PATH": gcs_path,
            **extra_envs,
        },
    )
    return job, input


@app.post("/schedule/{namespace}/{name}")
def schedule(request: Request, namespace: str, name: str, body: dict = Body(...)):
    logger = stlog.getLogger("smartjob-trigger-service")
    logger.info("received schedule request")
    executor_service = get_executor_service(executor)
    job, input = get_job_and_input(body, namespace, name)
    details, _ = executor_service.schedule(
        job, inputs=[input], execution_config=execution_config, forget=True
    )
    execution_id = details.execution_id
    log_url = details.log_url
    return {
        "message": "job scheduled",
        "execution_id": execution_id,
        "log_url": log_url,
    }


@app.post("/run/{namespace}/{name}")
def run(request: Request, namespace: str, name: str, body: dict = Body(...)):
    logger = stlog.getLogger("smartjob-trigger-service")
    logger.info("received run request")
    executor_service = get_executor_service(executor)
    job, input = get_job_and_input(body, namespace, name)
    result = executor_service.run(
        job, inputs=[input], execution_config=execution_config
    )
    if not result:
        raise HTTPException(
            status_code=500, detail="Job launch failed, job_log_url=%s" % result.log_url
        )
    execution_id = result.execution_id
    log_url = result.log_url
    if result.json_output is not None:
        logger.info("job output: %s" % json.dumps(result.json_output, indent=4))
    return {
        "message": "job run successfully",
        "execution_id": execution_id,
        "log_url": log_url,
    }
