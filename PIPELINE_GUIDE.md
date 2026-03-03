# 💊 Smart Pharmacy Inventory Management System (SPIMS) - Data Pipeline

I have built a robust, professional-grade data pipeline to transform your raw pharmacy records into a fully relational PostgreSQL database.

### 📜 Pipeline Overview

1.  **`01_clean.py`**:
    *   Reads `DRUGS.csv`, `SUPPLIER.csv`, and `PRESCRIPTIONS.csv` from `data/raw/`.
    *   Standardizes columns to `snake_case`.
    *   Performs validation, duplicate removal, and safe date conversion (with 2099-12-31 fallback for invalid dates).
    *   Outputs cleaned CSVs to `data/cleaned/`.

2.  **`02_normalize.py`**:
    *   Loads cleaned CSVs.
    *   Constructs relational DataFrames with **Surrogate Keys** (`suppliers`, `medicines`, `batches`, `sales`, `sale_items`).
    *   Maintains logical linking via mapped IDs rather than natural keys.

3.  **`create_db.py`**:
    *   Utility script to create the `spims_db` database on your local PostgreSQL instance using credentials from `.env`.

4.  **`03_seed_db.py`**:
    *   Uses **SQLAlchemy Core** for efficient database operations.
    *   Implements **FEFO (First Expired, First Out)** logic for sale item allocation.
    *   Handles NumPy-to-Postgres type casting (int/float conversion).
    *   Ensures idempotency (safe to re-run).
    *   Handles transactions with `engine.begin()`.

### 🚀 Usage

To run the pipeline, execute the scripts sequentially from the project root:

```bash
# 1. Setup Database
python data/scripts/create_db.py

# 2. Clean
python data/scripts/01_clean.py

# 3. Normalize (Logical Check)
python data/scripts/02_normalize.py

# 4. Seed (Relational Import + FEFO)
python data/scripts/03_seed_db.py
```

> [!IMPORTANT]
> Ensure you have a `.env` file in the project root with your `DB_URL`.
> `DB_URL=postgresql://postgres:password@localhost:5432/spims_db`

> [!TIP]
> The scripts are built to be robust for hackathon environments, including automatic handling of NaN values, string-to-int casting, and far-future expiration placeholders.
