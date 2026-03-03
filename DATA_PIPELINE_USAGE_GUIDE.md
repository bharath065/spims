# 🏥 SPIMS Data Pipeline & Architecture Guide

This document provides a technical blueprint for Backend Developers and ML Engineers to interact with the Smart Pharmacy Inventory Management System (SPIMS) data layer.

---

## SECTION 1: Backend Developer Guide

### 🛠️ Environment Setup

1.  **PostgreSQL Instance**:  
    Use the provided `docker-compose.yml` to spin up a local instance:
    ```bash
    docker-compose up -d
    ```
    *Default settings:* Port `5432`, User `postgres`, Password `postgres123`.

2.  **Configuration**:  
    Create a `.env` file in the project root. The pipeline uses this `DB_URL` to connect:
    ```env
    DB_URL=postgresql://postgres:postgres123@localhost:5432/pharmacy_db
    ```

3.  **Pipeline Execution**:  
    Run the scripts from the root directory in this specific order:
    ```bash
    python data/scripts/create_db.py    # Initializes the database
    python data/scripts/01_clean.py     # RAW -> CLEANED
    python data/scripts/02_normalize.py # Relational mapping
    python data/scripts/03_seed_db.py   # Atomic insertion with FEFO
    ```

### 📊 Database Schema Strategy

| Use Case | Relevant Tables | Key Logic |
| :--- | :--- | :--- |
| **Inventory Tracking** | `batches` | Always SUM `quantity_remaining` by `medicine_id`. |
| **FEFO Logic** | `batches` | Order by `expiry_date ASC` and filter `quantity_remaining > 0`. |
| **Reorder Threshold** | `medicines`, `batches` | Compare `medicines.reorder_threshold` vs total stock in `batches`. |
| **Expiry Alerts** | `batches` | Filter `expiry_date` < (NOW + Offset). |
| **Sales Analytics** | `sales`, `sale_items` | Join `sales` to `sale_items` for revenue and volume reports. |

### 🔍 Critical SQL Queries

**1. Check Current Stock by Medicine**
```sql
SELECT m.name, SUM(b.quantity_remaining) as total_stock
FROM medicines m
JOIN batches b ON m.id = b.medicine_id
GROUP BY m.name;
```

**2. Get Next FEFO Batch to Sell**
```sql
SELECT id, batch_number, expiry_date, quantity_remaining
FROM batches
WHERE medicine_id = :medicine_id AND quantity_remaining > 0
ORDER BY expiry_date ASC
LIMIT 1;
```

**3. Daily Sales Summary**
```sql
SELECT DATE(sale_date) as date, SUM(total_amount) as daily_revenue, COUNT(*) as txn_count
FROM sales
GROUP BY DATE(sale_date)
ORDER BY date DESC;
```

### ⚠️ System Constraints
*   **Transactions Only**: Never update `batches.quantity_remaining` without an atomic link to a `sale_items` insertion. Use `engine.begin()` in SQLAlchemy.
*   **Batch Integrity**: Do not aggregate total stock into the `medicines` table. Always calculate it dynamically from the `batches` table to ensure auditability and FEFO compliance.

### 🔌 Recommended API Structure (REST)
*   `GET /inventory`: Returns comprehensive list with aggregate stock and reorder flags.
*   `POST /sales`: Payload includes `medicine_id` and `qty`. Backend must handle FEFO allocation across batches.
*   `GET /alerts/expiry`: Returns batches expiring within 30/60/90 days.

---

## SECTION 2: ML Model Trainer Guide

### 📈 Demand Forecasting Data
To train models (Prophet, XGBoost, or LSTMs), focus on the temporal relationship between sales and medicine categories.

### 📥 Dataset Extraction Query
Use this query to generate the primary time-series dataset:
```sql
SELECT 
    si.medicine_id,
    DATE(s.sale_date) as sale_date,
    SUM(si.quantity_sold) as daily_qty
FROM sale_items si
JOIN sales s ON si.sale_id = s.id
GROUP BY si.medicine_id, DATE(s.sale_date)
ORDER BY sale_date ASC;
```

### 🛠️ Feature Engineering Suggestions
1.  **Rolling Averages**: Calculate 7-day and 30-day moving averages of `quantity_sold` to capture trends.
2.  **Seasonality**: Extract `day_of_week`, `month`, and `is_weekend` from `sale_date`.
3.  **Stock-out Flags**: Correlate days with `0` sales against the `batches` history to determine if sales were `0` because of low demand or `0` because of zero stock.
4.  **Lag Features**: Use sales from `T-1`, `T-7`, and `T-30` as predictors.

### 🐍 Python Integration (Pandas)
Connect using the same `DB_URL` from the backend to ensure data consistency:
```python
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine(os.getenv("DB_URL"))
query = "SELECT ..." # Use the extraction query above
df = pd.read_sql(query, engine)
```

### 🤖 Model Recommendations
*   **Prophet / ARIMA**: Best for medicines with clear seasonal patterns (e.g., allergy medications).
*   **XGBoost / LightGBM**: Excellent for handling multi-variate features (price changes, supplier delays).
*   **LSTM**: Suitable if you have multiple years of high-frequency data.

### 💾 Storing Predictions
Store generated forecasts back into a specialized `forecasts` table (to be created) to allow the backend to visualize "Predicted Stock-out Dates" on the UI:
```sql
-- Recommendation for Forecast Schema
CREATE TABLE forecasts (
    id SERIAL PRIMARY KEY,
    medicine_id INT REFERENCES medicines(id),
    forecast_date DATE,
    predicted_qty FLOAT,
    confidence_interval_low FLOAT,
    confidence_interval_high FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
