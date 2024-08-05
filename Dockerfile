FROM python:3.12

ENV POETRY_HOME=/opt/poetry

RUN python3 -m venv $POETRY_HOME
RUN $POETRY_HOME/bin/pip install poetry==1.8
RUN $POETRY_HOME/bin/poetry config virtualenvs.in-project true
RUN mkdir /app
COPY smartjob_trigger_service /app/smartjob_trigger_service
COPY README.md pyproject.toml entrypoint.sh poetry.lock /app/
RUN cd /app && $POETRY_HOME/bin/poetry install --without dev

ENTRYPOINT ["/app/entrypoint.sh"]