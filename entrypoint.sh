#!/bin/bash

export PATH="${POETRY_HOME}/bin:${PATH}"

if test "${K_SERVICE:-}" != ""; then
    echo "CloudRun env detected"
    export STLOG_OUTPUT="json-gcp" # change log format
fi

cd /app || exit 1
exec poetry run fastapi run --port "${PORT:-8080}" smartjob_trigger_service/main.py
