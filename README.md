# smartjob-trigger-service

## What is it?

This is a **generic** GCP/Cloud Run Service (docker image):

- to receive GCP/EventArc notifications about new objects created in a bucket (event type: `google.cloud.storage.object.v1.finalized`)
- and to launch a GCP/Cloud Run Job (or Vertex Custom Job) with the [smartjob](https://github.com/fabien-marty/smartjob) library

## Features

- [x] download the object that triggered the event and inject it in the Cloud Run Job as an input parameter (thanks to the [smartjob](https://github.com/fabien-marty/smartjob) library) under the name `incoming_file`
- [x] inject the triggering file full path (starting with `gs://...`) in an env var: `SMARTJOB_TRIGGER_SERVICE_FULL_PATH` (available in the job container)
- [x] can wait for the job completion or just schedule the execution
- [x] support for the event type: `storage.objects.create` for advanced filtering capabilities (in EventArc)

## Installation / configuration

1️⃣ Create a Cloud Run Service with following parameters:

- docker image: `docker.io/fabienmarty/smartjob-trigger-service:latest`
- environment variables:
    - `SMARTJOB_PROJECT=your-gcp-project` **(mandatory)**
    - `SMARTJOB_REGION=your-gcp-region` **(mandatory)**
    - `SMARTJOB_STAGING_BUCKET=gs://a-bucket-for-hosting-inputs-outputs-of-the-job` **(mandatory)**
    - `SMARTJOB_DOCKER_IMAGE=full-path-of-a-docker-image` **(mandatory)** (example: `docker.io/python:3.12`)
    - `SMARTJOB_EXECUTOR=cloudrun` *(optional, `cloudrun` for launching Cloud Run Job or `vertex` for launching Vertex Custom Job)*
    - `SMARTJOB_LOG_LEVEL=INFO` *(optional, log level of the service, default to `INFO`)*
    - `SMARTJOB_TIMEOUT_SECONDS=number-of-seconds` *(optional, timeout of the job in seconds, default to `3600`)*
    - `SMARTJOB_MAX_ATTEMPTS=max-attempts` *(optional, number of attempts, default to `3`)*
    - `SMARTJOB_SERVICE_ACCOUNT=service-account-email` *(optional, service account to use for the job, default to GCP default)*
    - `SMARTJOB_CPU=1.0` *(optional, number of CPUs required for the job, default to `1.0`, can be fractional, specific to `executor=cloudrun`, limited to 8)*
    - `SMARTJOB_MEMORY_GB=0.5` *(optional, number of GB of memory required for the job, default to `0.5`, can be fractional, specific to `executor=cloudrun`, limited to 32)*
    - `SMARTJOB_MACHINE_TYPE=n2-standard-64` *(optional, specific to `executor=vertex`, machine type to use)*
    - `SMARTJOB_VPC_CONNECTOR_NETWORK=...` *(optional, VPC network to connect to)*
    - `SMARTJOB_VPC_CONNECTOR_SUBNETWORK=...` *(optional, VPC subnetwork to connect to)*
    - `SMARTJOB_EXTRA_ENV_*=env-value` *(optional, if set it will inject extra variables into the job env, example: `SMARTJOB_EXTRA_ENV_FOO_BAR=baz` will inject `FOO_BAR=baz` into the job env)*
    - `SMARTJOB_LABEL_*=label-value` *(optional, if set it will add corresponding labels to the created job, example: `SMARTJOB_LABEL_FOO=bar` will add a label `foo=bar`)*

2️⃣ Create an EventArc configuration with following parameters:

- Trigger type: `Google sources`
- Event provider: `Cloud Storage`
- Event type: `google.cloud.storage.objects.v1.finalized` **(at this time, this is the only event type supported)**
- Event data content type: `application/json`
- Bucket: `your-bucket-that-will-trigger-the-job` **(WARNING: don't use here the "staging bucket" to avoid an infinite loop!)**
- Event destination: `Cloud Run`
- Cloud Run Service: `your-cloudrun-service-previously-created`
- Service URL path:
    - `/schedule/{job-namespace}/{job-name}` for triggering the job without waiting for completion (probably the one you want)
    - or `/run/{job-namespace}/{job-name}` for running the job and wait for its completion (warning: you have to increase the default "acknowledgement deadline" (default to 10 seconds) but as you can't increase it over 600 seconds, you can't use this option for long running jobs)

> [!WARNING]  
> The default EventArc "acknowledgement deadline" (you can find it in the automatically generated PubSub configuration in the "subscription" part of the configuration) is very low by default: 10 seconds!
>
> - For the "run and wait" feature (`/run/...`), it's clearly too low! But note that you can't increase it over 600 seconds, so you can't use this feature for long running jobs.
> - For the "schedule only"  feature (`schedule/...`), it can be too low, increase it at its maximum to be safe
