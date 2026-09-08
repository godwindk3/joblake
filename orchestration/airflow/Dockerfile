ARG AIRFLOW_BASE_IMAGE=apache/airflow:3.3.1
FROM ${AIRFLOW_BASE_IMAGE}

USER root
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/joblake && chown airflow:0 /opt/joblake
USER airflow
WORKDIR /opt/joblake
COPY --chown=airflow:0 pyproject.toml requirements.txt ./
COPY --chown=airflow:0 src ./src
# Keep crawler dependencies separate from Airflow's constrained environment.
RUN python -m venv /opt/joblake/venv \
    && /opt/joblake/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && /opt/joblake/venv/bin/pip install --no-cache-dir --no-deps -e .
USER root
RUN /opt/joblake/venv/bin/python -m playwright install-deps chromium
USER airflow
RUN /opt/joblake/venv/bin/python -m cloakbrowser install
WORKDIR /opt/airflow
