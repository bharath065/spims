import os
import sys
import pandas as pd
from sqlalchemy import create_engine, MetaData, Table, insert, text
from sqlalchemy.exc import SQLAlchemyError
from pathlib import Path
from dotenv import load_dotenv

# Import normalization logic
import importlib.util
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
NORMALIZE_PATH = BASE_DIR / "scripts" / "02_normalize.py"

spec = importlib.util.spec_from_file_location("normalize_module", NORMALIZE_PATH)
normalize_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(normalize_module)
load_normalized_data = normalize_module.load_normalized_data

# Load DB_URL from environment
load_dotenv(BASE_DIR.parent / ".env")
DB_URL = os.getenv("DB_URL")

if not DB_URL:
    print("[!] Error: DB_URL environment variable is not set.")
    sys.exit(1)

engine = create_engine(DB_URL)
metadata = MetaData()

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Date

# Define table objects explicitly to avoid reflection-related crashes in Python 3.13
suppliers_t = Table(
    "suppliers", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String),
    Column("phone", String),
    Column("created_at", DateTime)
)

medicines_t = Table(
    "medicines", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String),
    Column("generic_name", String),
    Column("ndc", String, unique=True),
    Column("preferred_supplier_id", Integer, ForeignKey("suppliers.id")),
    Column("unit", String),
    Column("reorder_threshold", Integer),
    Column("created_at", DateTime)
)

batches_t = Table(
    "batches", metadata,
    Column("id", Integer, primary_key=True),
    Column("medicine_id", Integer, ForeignKey("medicines.id")),
    Column("supplier_id", Integer, ForeignKey("suppliers.id")),
    Column("batch_number", String),
    Column("quantity_received", Integer),
    Column("quantity_remaining", Integer),
    Column("expiry_date", Date),
    Column("purchase_price", Float),
    Column("received_at", DateTime),
    Column("is_active", Boolean, default=True)
)

sales_t = Table(
    "sales", metadata,
    Column("id", Integer, primary_key=True),
    Column("sale_date", DateTime),
    Column("total_amount", Float),
    Column("notes", String)
)

sale_items_t = Table(
    "sale_items", metadata,
    Column("id", Integer, primary_key=True),
    Column("sale_id", Integer, ForeignKey("sales.id")),
    Column("batch_id", Integer, ForeignKey("batches.id")),
    Column("medicine_id", Integer, ForeignKey("medicines.id")),
    Column("quantity_sold", Integer),
    Column("unit_price", Float)
)

def seed_database():
    print("[*] Creating tables if they don't exist...")
    metadata.create_all(engine)
    
    print("[*] Starting database seeding...")
    
    # Load normalized data
    data = load_normalized_data()
    if not data:
        return

    try:
        with engine.begin() as conn:
            # 1. Seed Suppliers
            print("[*] Seeding suppliers...")
            sup_map = {} # old_id -> db_id
            now = pd.Timestamp.now()
            for _, row in data['suppliers'].iterrows():
                # Check for existing by name for idempotency
                existing = conn.execute(
                    text("SELECT id FROM suppliers WHERE name = :name"), 
                    {"name": row['name']}
                ).fetchone()
                
                if existing:
                    db_id = existing[0]
                else:
                    result = conn.execute(
                        suppliers_t.insert().returning(suppliers_t.c.id),
                        {"name": row['name'], "phone": row['phone'], "created_at": now}
                    )
                    db_id = result.fetchone()[0]
                sup_map[row['id']] = db_id

            # 2. Seed Medicines
            print("[*] Seeding medicines...")
            med_map = {} # old_id -> db_id
            for _, row in data['medicines'].iterrows():
                ndc_str = str(row['ndc'])
                existing = conn.execute(
                    text("SELECT id FROM medicines WHERE ndc = :ndc"), 
                    {"ndc": ndc_str}
                ).fetchone()
                
                if existing:
                    db_id = existing[0]
                else:
                    result = conn.execute(
                        medicines_t.insert().returning(medicines_t.c.id),
                        {
                            "name": row['name'],
                            "generic_name": row['generic_name'],
                            "ndc": ndc_str,
                            "preferred_supplier_id": sup_map.get(row['preferred_supplier_id']),
                            "unit": "UNIT",
                            "reorder_threshold": 20,
                            "created_at": now
                        }
                    )
                    db_id = result.fetchone()[0]
                med_map[row['id']] = db_id

            # 3. Seed Batches
            print("[*] Seeding batches...")
            for _, row in data['batches'].iterrows():
                bn_str = str(row['batch_number'])
                existing = conn.execute(
                    text("SELECT id FROM batches WHERE batch_number = :bn"), 
                    {"bn": bn_str}
                ).fetchone()
                
                if not existing:
                    # Handle NaN/invalid expiry dates for PG
                    exp_val = row['expiry_date']
                    if pd.isna(exp_val):
                        exp_val = pd.Timestamp("2099-12-31")

                    conn.execute(
                        batches_t.insert(),
                        {
                            "medicine_id": int(med_map.get(row['medicine_id'])),
                            "supplier_id": int(sup_map.get(row['supplier_id'])),
                            "batch_number": bn_str,
                            "quantity_received": int(row['quantity_received']),
                            "quantity_remaining": int(row['quantity_remaining']),
                            "expiry_date": exp_val,
                            "purchase_price": float(row['purchase_price']),
                            "received_at": now,
                            "is_active": True
                        }
                    )

            # 4 & 5. Sales and Sale Items with FEFO Logic
            print("[*] Seeding sales and items (FEFO)...")
            # We need to map the generated sale IDs to DB IDs
            sale_db_map = {} 

            for _, sale_row in data['sales'].iterrows():
                # Create sale record
                sale_result = conn.execute(
                    sales_t.insert().returning(sales_t.c.id),
                    {"sale_date": sale_row['sale_date'], "total_amount": 0, "notes": sale_row['notes']}
                )
                db_sale_id = sale_result.fetchone()[0]
                sale_db_map[sale_row['id']] = db_sale_id

                # Items for this sale
                items = data['sale_items'][data['sale_items']['sale_id'] == sale_row['id']]
                
                total_sale_amount = 0
                for _, item_row in items.iterrows():
                    db_med_id = med_map.get(item_row['medicine_id'])
                    qty_needed = item_row['quantity_sold']
                    
                    # FEFO Logic: Get expiry-ordered batches
                    batches = conn.execute(
                        text("""
                            SELECT id, quantity_remaining 
                            FROM batches 
                            WHERE medicine_id = :mid AND quantity_remaining > 0 
                            ORDER BY expiry_date ASC
                        """),
                        {"mid": db_med_id}
                    ).fetchall()
                    
                    for b_id, b_rem in batches:
                        if qty_needed <= 0: break
                        
                        qty_to_take = int(min(qty_needed, b_rem))
                        
                        # Insert sale item
                        conn.execute(
                            sale_items_t.insert(),
                            {
                                "sale_id": int(db_sale_id),
                                "batch_id": int(b_id),
                                "medicine_id": int(db_med_id),
                                "quantity_sold": int(qty_to_take),
                                "unit_price": float(item_row['unit_price'])
                            }
                        )
                        
                        # Update batch inventory
                        conn.execute(
                            text("UPDATE batches SET quantity_remaining = quantity_remaining - :q WHERE id = :bid"),
                            {"q": qty_to_take, "bid": b_id}
                        )
                        
                        total_sale_amount += qty_to_take * item_row['unit_price']
                        qty_needed -= qty_to_take
                    
                    if qty_needed > 0:
                        print(f"[-] Warning: Stockout for Medicine ID {db_med_id}. Shortfall: {qty_needed}")
                    
                # Update total amount
                conn.execute(
                    text("UPDATE sales SET total_amount = :amt WHERE id = :sid"),
                    {"amt": float(total_sale_amount), "sid": int(db_sale_id)}
                )

        print("[+] Seeding completed successfully.")

    except SQLAlchemyError as e:
        print(f"[!] Database Error: {e}")
    except Exception as e:
        print(f"[!] Unexpected Error: {e}")

if __name__ == "__main__":
    seed_database()
