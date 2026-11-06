# Learning guide: read the code in this order

The project was built in phases. Use this guide to study it the same way: one phase at a time, run something, look at the result, then move on.

| Phase | Read these files | Run this | What you should see / learn |
|---|---|---|---|
| 1. Big picture | `README.md` sections 1 to 6 | nothing | What ETL is, why each tool exists, how a row travels through the pipeline |
| 2. Environment | `docs/WINDOWS_SETUP.md`, `.env.example`, `docker-compose.yml` (postgres part), `config/config.py` | Steps 1 to 9 of the setup guide | Why secrets live in `.env`; how one config file serves Windows and Docker |
| 3. Dataset | `scripts/generate_data.py` | `python scripts\generate_data.py` then open the CSVs in VS Code | Every data problem is injected on purpose; find examples of each in the files |
| 4. Extraction | `src/extraction/*.py`, `scripts/mock_api.py` | `python scripts\mock_api.py` and open http://localhost:8000/products?limit=3 in a browser | What a JSON response looks like; pagination with `limit`/`skip`; why everything is read as text |
| 5. Transformation | `src/transformation/clean_data.py` → `validate_data.py` → `transform_data.py`, `src/monitoring/quality_report.py` | `python -m src.pipeline --skip-load` | Open `data\rejected\<run>\rejected_sales.csv` and `reports\<run>\data_quality_report.md`; match each rejection reason to a rule |
| 6. Loading | `sql/create_tables.sql`, `src/loading/database.py`, `src/loading/load_data.py` | `python -m src.pipeline` twice | Second run: "0 new, N updated". That is idempotency |
| 7. Airflow | `dags/sales_etl_dag.py`, `src/pipeline.py`, rest of `docker-compose.yml` | `docker compose up -d --build`, trigger the DAG | Graph view, task logs, retries |
| 8. Reliability | `src/exceptions.py`, `src/monitoring/logger.py`, the `tracked_step` decorator in `src/pipeline.py` | Rename `data\source\customers.csv`, trigger the DAG, watch retries, then rename it back | How a failure travels: task error → retries → `etl_logs` row with FAILED |
| 9. Testing | `tests/` | `pytest -v` | Each test name says what it proves |
| 10. Analytics | `analytics/queries.sql`, `run_queries.py`, `dashboard.py` | `python -m analytics.run_queries`, `python -m analytics.dashboard` | The pipeline output answers real business questions |
| 11. Documentation | `README.md`, this file | push to GitHub | A project someone else can run from the README alone |

## Small experiments that build understanding

1. **Break a rule on purpose.** In `sales_branch_1.csv` change a quantity to `-9`. Run `python -m src.pipeline --skip-load`. Find that row in `rejected_sales.csv`.
2. **Change a convention.** In `clean_data.py`, add `"phone pe": "UPI"` to `PAYMENT_MAP`. Run the tests. Then add a test for it.
3. **Watch the transaction protect you.** In a Python shell, load the processed files but change one sale's `product_id` to `99999`, call `load_all(...)`, and confirm the customers table did not change either.
4. **Scale up.** `python scripts\generate_data.py --rows-per-branch 100000` and time the pipeline. Which step is slowest? (Hint: look at the timestamps in `logs\pipeline.log`.)
5. **Read an Airflow log.** Open the log of `extract_product_data` and find the line that says whether the API or the snapshot was used.

## Interview questions this project prepares you for

* What is the difference between ETL and ELT?
* Why did you use a LEFT JOIN and not an INNER JOIN for customers?
* How does your pipeline avoid duplicate rows when it runs twice?
* What happens if the database goes down in the middle of a load?
* Why is `transaction_id` not enough as a primary key here?
* How does Airflow decide when to run your DAG? What does `catchup=False` do?
* What is the difference between application logs and Airflow task logs?
* How would you make this pipeline handle 100 million rows?
