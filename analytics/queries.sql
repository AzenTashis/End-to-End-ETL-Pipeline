-- ===========================================================================
-- Business questions answered with SQL on the sales_dw database.
-- Each query starts with a "-- name:" line so analytics/run_queries.py can
-- find it. You can also copy any query into pgAdmin or psql directly.
--
-- Revenue always means final_amount (after discount), in INR.
-- ===========================================================================

-- name: total_revenue
-- Q1. How much money did we make in total, and how much did we give away as discounts?
SELECT
    COUNT(*)                        AS transactions,
    SUM(quantity)                   AS units_sold,
    ROUND(SUM(total_amount), 2)     AS gross_revenue,
    ROUND(SUM(discount_amount), 2)  AS total_discount,
    ROUND(SUM(final_amount), 2)     AS net_revenue
FROM sales_transactions;

-- name: monthly_revenue
-- Q2. Revenue for every month, oldest first. Shows growth and seasonality (festive Oct and Nov).
SELECT
    transaction_year,
    transaction_month,
    ROUND(SUM(final_amount), 2) AS revenue
FROM sales_transactions
GROUP BY transaction_year, transaction_month
ORDER BY transaction_year, transaction_month;

-- name: top_10_products
-- Q3. The 10 best-selling products by units sold (revenue shown alongside).
SELECT
    p.product_id,
    p.product_name,
    p.category,
    SUM(s.quantity)               AS units_sold,
    ROUND(SUM(s.final_amount), 2) AS revenue
FROM sales_transactions AS s
JOIN products AS p ON p.product_id = s.product_id
GROUP BY p.product_id, p.product_name, p.category
ORDER BY units_sold DESC, revenue DESC
LIMIT 10;

-- name: revenue_by_category
-- Q4. Revenue per product category, with each category's share of the total.
SELECT
    p.category,
    COUNT(*)                                                            AS transactions,
    ROUND(SUM(s.final_amount), 2)                                       AS revenue,
    ROUND(100.0 * SUM(s.final_amount) / SUM(SUM(s.final_amount)) OVER (), 2) AS revenue_share_pct
FROM sales_transactions AS s
JOIN products AS p ON p.product_id = s.product_id
GROUP BY p.category
ORDER BY revenue DESC;

-- name: sales_by_region
-- Q5. Transactions, units and revenue per region.
SELECT
    region,
    COUNT(*)                      AS transactions,
    SUM(quantity)                 AS units_sold,
    ROUND(SUM(final_amount), 2)   AS revenue
FROM sales_transactions
GROUP BY region
ORDER BY revenue DESC;

-- name: average_transaction_value
-- Q6. Average bill size per branch and overall (ROLLUP-free version that works everywhere).
SELECT branch_id,
       COUNT(*)                     AS transactions,
       ROUND(AVG(final_amount), 2)  AS avg_transaction_value
FROM sales_transactions
GROUP BY branch_id
UNION ALL
SELECT 'ALL', COUNT(*), ROUND(AVG(final_amount), 2)
FROM sales_transactions
ORDER BY branch_id;

-- name: most_active_customers
-- Q7. Top 10 customers by number of purchases (placeholder customers excluded).
SELECT
    c.customer_id,
    c.customer_name,
    c.city,
    COUNT(*)                      AS transactions,
    ROUND(SUM(s.final_amount), 2) AS total_spent
FROM sales_transactions AS s
JOIN customers AS c ON c.customer_id = s.customer_id
WHERE c.is_placeholder = FALSE
GROUP BY c.customer_id, c.customer_name, c.city
ORDER BY transactions DESC, total_spent DESC
LIMIT 10;

-- name: monthly_transaction_volume
-- Q8. Number of transactions and distinct buyers per month.
SELECT
    transaction_year,
    transaction_month,
    COUNT(*)                    AS transactions,
    COUNT(DISTINCT customer_id) AS distinct_customers
FROM sales_transactions
GROUP BY transaction_year, transaction_month
ORDER BY transaction_year, transaction_month;

-- name: payment_method_distribution
-- Q9. How customers pay: count and percentage of transactions per payment method.
SELECT
    payment_method,
    COUNT(*)                                           AS transactions,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS share_pct
FROM sales_transactions
GROUP BY payment_method
ORDER BY transactions DESC;

-- name: highest_revenue_category
-- Q10. The single category that earned the most.
SELECT
    p.category,
    ROUND(SUM(s.final_amount), 2) AS revenue
FROM sales_transactions AS s
JOIN products AS p ON p.product_id = s.product_id
GROUP BY p.category
ORDER BY revenue DESC
LIMIT 1;

-- name: month_over_month_growth
-- Q11. Revenue growth compared with the previous month (window function LAG).
WITH monthly AS (
    SELECT transaction_year, transaction_month, SUM(final_amount) AS revenue
    FROM sales_transactions
    GROUP BY transaction_year, transaction_month
)
SELECT
    transaction_year,
    transaction_month,
    ROUND(revenue, 2) AS revenue,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY transaction_year, transaction_month))
          / LAG(revenue) OVER (ORDER BY transaction_year, transaction_month), 2) AS growth_pct
FROM monthly
ORDER BY transaction_year, transaction_month;

-- name: quarterly_revenue_by_branch
-- Q12. Revenue per branch per quarter: which branch is growing fastest?
SELECT
    transaction_year,
    transaction_quarter,
    branch_id,
    ROUND(SUM(final_amount), 2) AS revenue
FROM sales_transactions
GROUP BY transaction_year, transaction_quarter, branch_id
ORDER BY transaction_year, transaction_quarter, branch_id;

-- name: revenue_by_customer_state
-- Q13. Revenue by the customer's home state (only customers we know).
SELECT
    c.state,
    COUNT(DISTINCT c.customer_id) AS customers,
    ROUND(SUM(s.final_amount), 2) AS revenue
FROM sales_transactions AS s
JOIN customers AS c ON c.customer_id = s.customer_id
WHERE c.is_placeholder = FALSE
GROUP BY c.state
ORDER BY revenue DESC;

-- name: pipeline_run_history
-- Q14. Recent pipeline runs from the etl_logs table.
SELECT execution_id, execution_timestamp, execution_status,
       records_extracted, records_transformed, records_loaded, records_rejected, run_source
FROM etl_logs
ORDER BY execution_timestamp DESC
LIMIT 10;
