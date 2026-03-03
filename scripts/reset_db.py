import os
from sqlalchemy import create_engine, MetaData
from sqlalchemy.schema import DropTable
from dotenv import load_dotenv
from pathlib import Path

# Load DB_URL
load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")
DB_URL = os.getenv("DB_URL")

if not DB_URL:
    print("[!] Error: DB_URL not found.")
    exit(1)

engine = create_engine(DB_URL)
metadata = MetaData()
metadata.reflect(bind=engine)

with engine.begin() as conn:
    print("[*] Dropping all tables...")
    for table in reversed(metadata.sorted_tables):
        print(f"[*] Dropping {table.name}")
        conn.execute(DropTable(table))

print("[+] Database reset successful.")
