#!/bin/bash

export PATH="${POETRY_HOME}/bin:${PATH}"

cd /app || exit 1
exec poetry run fastapi run smartjob_trigger_service/main.py