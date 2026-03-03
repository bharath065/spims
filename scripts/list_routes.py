import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

from app.main import app

print("--- REGISTERED ROUTES ---")
for route in app.routes:
    if hasattr(route, "path"):
        print(f"Path: {route.path}, Name: {getattr(route, 'name', 'N/A')}")
print("-------------------------")
