import json
import os
from contextlib import asynccontextmanager

import stlog
from fastapi import FastAPI, HTTPException, Request
from smartjob import CloudRunSmartJob, GcsInput, Input, get_executor_service_singleton


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


@app.get("/")
async def hello():
    return {"message": "Hello World"}


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


async def get_job_and_input(
    request: Request, namespace: str, name: str
) -> tuple[CloudRunSmartJob, Input]:
    logger = stlog.getLogger("smartjob-trigger-service")
    try:
        body = await request.json()
    except json.decoder.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    logger.debug("received body: %s" % json.dumps(body, indent=4))
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
    job = CloudRunSmartJob(
        name=name,
        namespace=namespace,
        docker_image=os.environ["SMARTJOB_DOCKER_IMAGE"],
        timeout_seconds=int(os.environ.get("SMARTJOB_TIMEOUT_SECONDS", 3600)),
        service_account=os.environ.get("SMARTJOB_SERVICE_ACCOUNT"),
        cpu=get_smartjob_cpu_from_env(os.environ.get("SMARTJOB_CPU")),
        memory_gb=get_smartjob_memory_gb_from_env(os.environ.get("SMARTJOB_MEMORY_GB")),
        add_envs={
            "SMARTJOB_TRIGGER_SERVICE_FULL_PATH": gcs_path,
        },
    )
    return job, input


@app.post("/schedule/{namespace}/{name}")
async def schedule(request: Request, namespace: str, name: str):
    logger = stlog.getLogger("smartjob-trigger-service")
    logger.info("received schedule request")
    executor_service = get_executor_service_singleton()
    job, input = await get_job_and_input(request, namespace, name)
    future = await executor_service.schedule(job, inputs=[input])
    execution_id = future.execution_id
    log_url = future.log_url
    future._cancel()  # we don't want to be notified about the job completion
    return {
        "message": "job scheduled",
        "execution_id": execution_id,
        "log_url": log_url,
    }


@app.post("/run/{namespace}/{name}")
async def run(request: Request, namespace: str, name: str):
    logger = stlog.getLogger("smartjob-trigger-service")
    logger.info("received run request")
    executor_service = get_executor_service_singleton()
    job, input = await get_job_and_input(request, namespace, name)
    result = await executor_service.run(job, inputs=[input])
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
