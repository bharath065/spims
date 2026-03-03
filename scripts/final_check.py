import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv('backend/.env')
db_url = os.getenv('DB_URL')
print(f"Connecting to: {db_url}")
engine = create_engine(db_url)

with engine.connect() as conn:
    med_count = conn.execute(text("SELECT COUNT(*) FROM medicines")).scalar()
    batch_count = conn.execute(text("SELECT COUNT(*) FROM batches")).scalar()
    print(f"Medicines in DB: {med_count}")
    print(f"Batches in DB: {batch_count}")

import urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/medicines") as response:
        content = response.read().decode()
        print(f"Server response: {content}")
except Exception as e:
    print(f"Error calling server: {e}")
