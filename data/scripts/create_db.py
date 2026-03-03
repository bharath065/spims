import os
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from dotenv import load_dotenv
from pathlib import Path

# Load DB_URL from .env
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")
DB_URL = os.getenv("DB_URL")

if not DB_URL:
    print("[!] Error: DB_URL not found in .env")
    exit(1)

# Extract components to connect to default 'postgres' db
# Assuming URL format: postgresql://user:pass@host:port/dbname
base_url, db_name = DB_URL.rsplit('/', 1)
postgres_url = f"{base_url}/postgres"

print(f"[*] Connecting to {postgres_url} to create '{db_name}'...")
engine = create_engine(postgres_url, isolation_level="AUTOCOMMIT")

try:
    with engine.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {db_name}"))
    print(f"[+] Success: '{db_name}' database created.")
except ProgrammingError as e:
    if "already exists" in str(e):
        print(f"[*] Database '{db_name}' already exists.")
    else:
        print(f"[!] Error: {e}")
except Exception as e:
    print(f"[!] Unexpected Error: {e}")
finally:
    engine.dispose()
