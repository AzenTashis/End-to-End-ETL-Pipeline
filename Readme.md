# End-to-End ETL Pipeline

An automated Data Engineering pipeline that extracts data from multiple sources (CSVs and APIs), performs robust data cleaning and transformation, and loads the structured data into a PostgreSQL database. The entire workflow is scheduled and orchestrated using Apache Airflow.

## 🚀 Features

* **Data Extraction:** Dynamically pulls raw data from multiple CSV files and external REST APIs.
* **Data Cleaning:** Automatically handles missing values, removes duplicates, and standardizes data formats to ensure high data quality.
* **Data Transformation:** Restructures and aggregates the raw data into a normalized, analysis-ready schema.
* **Database Loading:** Safely connects and writes the transformed data into a relational PostgreSQL database.
* **Automated Orchestration:** Uses Apache Airflow DAGs to schedule, monitor, and execute the ETL pipeline at regular intervals without manual intervention.

## 🛠️ Tech Stack

* **Language:** Python 3.x
* **Orchestration:** Apache Airflow
* **Database:** PostgreSQL
* **Libraries:** `pandas` (for data manipulation), `requests` (for API calls), `psycopg2` / `SQLAlchemy` (for database connections)

## 🏗️ Pipeline Architecture

1. **Extract (`extract_task`):** Connects to configured APIs and reads local/remote CSV files into Pandas DataFrames.
2. **Transform (`transform_task`):** 
   * Drops or imputes `NaN`/`Null` values.
   * Drops duplicate rows.
   * Standardizes column names and data types.
   * Applies business logic to structure the data.
3. **Load (`load_task`):** Connects to the PostgreSQL instance and performs bulk inserts or upserts of the transformed data into the target tables.
4. **Schedule:** The Airflow DAG triggers this sequence based on a defined cron schedule (e.g., daily at midnight).

## 📋 Prerequisites

Before you begin, ensure you have the following installed:
* Python 3.8+
* PostgreSQL
* Apache Airflow
* Git

## ⚙️ Setup and Installation

**1. Clone the repository**
```bash
git clone https://github.com/yourusername/end-to-end-etl-pipeline.git
cd end-to-end-etl-pipeline
```

**2. Set up a virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Configure PostgreSQL**
* Create a database in PostgreSQL for the pipeline.
* Update your database credentials in the project's configuration file (e.g., `.env` or `config.py`):
```env
DB_HOST=localhost
DB_PORT=5432
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=etl_db
```

**5. Initialize Apache Airflow**
Set your Airflow home directory and initialize the metadata database:
```bash
export AIRFLOW_HOME=$(pwd)/airflow
airflow db init
airflow users create --username admin --password admin --firstname Admin --lastname User --role Admin --email admin@example.com
```

## 🚀 Running the Pipeline

**1. Start the Airflow Webserver and Scheduler**
Open two separate terminal windows:
```bash
# Terminal 1: Start the webserver
airflow webserver -p 8080

# Terminal 2: Start the scheduler
airflow scheduler
```

**2. Trigger the DAG**
* Open your browser and navigate to `http://localhost:8080`.
* Log in using the credentials you created.
* Locate the ETL DAG (e.g., `main_etl_dag`), unpause it, and click the **Trigger** button to run it manually, or let it run on its configured schedule.

## 🗂️ Project Structure

```text
├── dags/
│   └── etl_dag.py           # Airflow DAG definition
├── scripts/
│   ├── extract.py           # Data extraction logic (CSV/APIs)
│   ├── transform.py         # Data cleaning and transformation logic
│   └── load.py              # PostgreSQL database loading logic
├── data/
│   ├── raw/                 # Source CSV files
│   └── processed/           # Temporary storage for transformed data
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variables template
└── README.md                # Project documentation
```

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! 
1. Fork the project.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

## 📝 License

Distributed under the MIT License. See `LICENSE` for more information.