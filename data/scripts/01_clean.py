import pandas as pd
import os
from pathlib import Path

# Paths relative to the script's location (data/scripts)
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw"
CLEAN_DIR = BASE_DIR / "cleaned"

# Column validations
REQUIRED_COLUMNS = {
    "DRUGS.csv": ["brandName", "genericName", "NDC", "supID", "expDate", "purchasePrice", "sellPrice"],
    "SUPPLIER.csv": ["name", "phone", "supID"],
    "PRESCRIPTIONS.csv": ["patientID", "NDC", "qty", "status"]
}

def clean_column_names(df):
    """Standardize column names to lowercase snake_case."""
    df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]
    return df

def process_file(file_name):
    """Read, clean, and save a CSV file."""
    raw_path = RAW_DIR / file_name
    if not raw_path.exists():
        print(f"[-] Warning: {file_name} not found in {RAW_DIR}")
        return

    print(f"[*] Processing {file_name}...")
    
    # Read CSV file
    try:
        df = pd.read_csv(raw_path)
    except Exception as e:
        print(f"[!] Error reading {file_name}: {e}")
        return

    # Validate required columns
    required = REQUIRED_COLUMNS.get(file_name, [])
    missing = [col for col in required if col not in df.columns]
    if missing:
        print(f"[!] Error: {file_name} is missing required columns: {missing}")
        return

    # Remove duplicate rows
    initial_count = len(df)
    df = df.drop_duplicates()
    if len(df) < initial_count:
        print(f"[*] Removed {initial_count - len(df)} duplicate rows.")

    # Convert expDate to datetime if it exists
    if "expDate" in df.columns:
        df["expDate"] = pd.to_datetime(df["expDate"], errors="coerce")
        # Log rows with invalid dates
        invalid_dates = df["expDate"].isna().sum()
        if invalid_dates > 0:
            print(f"[-] Warning: {invalid_dates} invalid dates found in {file_name}")

    # Standardize column names
    df = clean_column_names(df)

    # Save to cleaned CSV
    output_name = file_name.replace(".csv", "_cleaned.csv")
    output_path = CLEAN_DIR / output_name
    df.to_csv(output_path, index=False)
    print(f"[+] Success: Cleaned {file_name} -> {output_name} ({len(df)} rows)")

def main():
    # Ensure cleaned directory exists
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    
    files_to_process = ["DRUGS.csv", "SUPPLIER.csv", "PRESCRIPTIONS.csv"]
    for file in files_to_process:
        process_file(file)

if __name__ == "__main__":
    main()
