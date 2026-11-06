-- Runs automatically the FIRST time the PostgreSQL container starts
-- (when its data volume is still empty).
-- The "airflow" database is created by POSTGRES_DB in docker-compose.yml.
-- Here we add the separate database for our business data.
-- If you change SALES_DB_NAME in .env, change the name here too.
CREATE DATABASE sales_dw;
