# Custom Airflow image = official Airflow image + the few libraries our ETL code needs.
# Built automatically by `docker compose up --build`.
ARG AIRFLOW_VERSION=3.3.1
FROM apache/airflow:${AIRFLOW_VERSION}

ARG AIRFLOW_VERSION
COPY requirements-airflow.txt /requirements-airflow.txt

# Installing "apache-airflow==<same version>" in the same command stops pip from
# upgrading or downgrading Airflow itself while it installs our libraries.
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /requirements-airflow.txt
