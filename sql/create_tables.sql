-- ===========================================================================
-- Database schema for the Meridian Retail sales warehouse (database: sales_dw)
--
-- Relationships:
--   customers 1 ───< many sales_transactions >─── 1 products
--   (one customer can have many sales; one product can appear in many sales)
--   etl_logs stands alone: one row per pipeline run.
--
-- Every statement uses IF NOT EXISTS, so running this file twice is safe
-- (the pipeline runs it at the start of every load).
-- ===========================================================================

CREATE TABLE IF NOT EXISTS customers (
    customer_id        VARCHAR(20)   PRIMARY KEY,           -- e.g. C0042, or UNKNOWN
    customer_name      VARCHAR(150)  NOT NULL,
    email              VARCHAR(255),
    city               VARCHAR(100),
    state              VARCHAR(100),
    registration_date  DATE,
    is_placeholder     BOOLEAN       NOT NULL DEFAULT FALSE, -- TRUE = created by ETL for an unknown ID
    updated_at         TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    product_id         INTEGER       PRIMARY KEY,           -- same ID as the product API
    product_name       VARCHAR(255)  NOT NULL,
    category           VARCHAR(100)  NOT NULL,
    unit_price         NUMERIC(12,2) CHECK (unit_price IS NULL OR unit_price > 0),  -- catalogue price in INR
    description        TEXT,
    is_placeholder     BOOLEAN       NOT NULL DEFAULT FALSE,
    updated_at         TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sales_transactions (
    branch_id            VARCHAR(10)   NOT NULL,             -- B1, B2, B3
    transaction_id       VARCHAR(30)   NOT NULL,             -- unique only within a branch
    customer_id          VARCHAR(20)   NOT NULL REFERENCES customers (customer_id),
    product_id           INTEGER       NOT NULL REFERENCES products (product_id),
    transaction_date     DATE          NOT NULL,
    quantity             INTEGER       NOT NULL CHECK (quantity > 0),
    unit_price           NUMERIC(12,2) NOT NULL CHECK (unit_price > 0),   -- price actually charged
    discount             NUMERIC(5,4)  NOT NULL DEFAULT 0 CHECK (discount >= 0 AND discount < 1),  -- 0.10 = 10%
    total_amount         NUMERIC(14,2) NOT NULL,             -- quantity * unit_price
    discount_amount      NUMERIC(14,2) NOT NULL,             -- total_amount * discount
    final_amount         NUMERIC(14,2) NOT NULL,             -- total_amount - discount_amount
    region               VARCHAR(20)   NOT NULL,
    payment_method       VARCHAR(30)   NOT NULL,
    transaction_year     SMALLINT      NOT NULL,
    transaction_month    SMALLINT      NOT NULL CHECK (transaction_month BETWEEN 1 AND 12),
    transaction_quarter  SMALLINT      NOT NULL CHECK (transaction_quarter BETWEEN 1 AND 4),
    source_file          VARCHAR(255),
    loaded_at            TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Business key: the same transaction number can exist in two branches.
    PRIMARY KEY (branch_id, transaction_id)
);

-- Indexes make filtering and joining on these columns fast.
CREATE INDEX IF NOT EXISTS idx_sales_customer_id      ON sales_transactions (customer_id);
CREATE INDEX IF NOT EXISTS idx_sales_product_id       ON sales_transactions (product_id);
CREATE INDEX IF NOT EXISTS idx_sales_transaction_date ON sales_transactions (transaction_date);
CREATE INDEX IF NOT EXISTS idx_sales_region           ON sales_transactions (region);
CREATE INDEX IF NOT EXISTS idx_products_category      ON products (category);

CREATE TABLE IF NOT EXISTS etl_logs (
    execution_id         VARCHAR(120)  PRIMARY KEY,          -- the pipeline run ID
    execution_timestamp  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    records_extracted    INTEGER       NOT NULL DEFAULT 0,
    records_transformed  INTEGER       NOT NULL DEFAULT 0,
    records_loaded       INTEGER       NOT NULL DEFAULT 0,
    records_rejected     INTEGER       NOT NULL DEFAULT 0,
    execution_status     VARCHAR(20)   NOT NULL CHECK (execution_status IN ('SUCCESS', 'FAILED')),
    error_message        TEXT,
    run_source           VARCHAR(20)                         -- 'cli' or 'airflow'
);

CREATE INDEX IF NOT EXISTS idx_etl_logs_timestamp ON etl_logs (execution_timestamp);
