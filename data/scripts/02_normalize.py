import pandas as pd
from pathlib import Path

# Paths relative to the script's location
BASE_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = BASE_DIR / "cleaned"

def load_normalized_data():
    """Load cleaned CSVs and transform them into relational structures with surrogate keys."""
    
    # Load files
    try:
        drugs_df = pd.read_csv(CLEAN_DIR / "DRUGS_cleaned.csv")
        suppliers_raw_df = pd.read_csv(CLEAN_DIR / "SUPPLIER_cleaned.csv")
        presc_df = pd.read_csv(CLEAN_DIR / "PRESCRIPTIONS_cleaned.csv")
    except FileNotFoundError as e:
        print(f"[!] Error: Cleaned files not found. Run 01_clean.py first. ({e})")
        return None

    # --- 1. Normalized Suppliers ---
    suppliers_df = suppliers_raw_df[['name', 'phone', 'supid']].copy()
    suppliers_df = suppliers_df.drop_duplicates(subset=['supid'])
    suppliers_df['id'] = range(1, len(suppliers_df) + 1)
    
    # Map natural key (supid) -> surrogate key (id)
    sup_id_map = suppliers_df.set_index('supid')['id'].to_dict()

    # --- 2. Normalized Medicines ---
    # Extract unique medicines by NDC
    medicines_df = drugs_df[['brandname', 'genericname', 'ndc', 'supid']].copy()
    medicines_df = medicines_df.drop_duplicates(subset=['ndc'])
    medicines_df['id'] = range(1, len(medicines_df) + 1)
    
    # Map NDC -> medicine_id
    med_id_map = medicines_df.set_index('ndc')['id'].to_dict()
    
    # Map preferred_supplier_id using sup_id_map
    medicines_df['preferred_supplier_id'] = medicines_df['supid'].map(sup_id_map)
    
    # Cleanup medicines columns
    medicines_df = medicines_df.rename(columns={'brandname': 'name', 'genericname': 'generic_name'})
    medicines_df = medicines_df[['id', 'name', 'generic_name', 'ndc', 'preferred_supplier_id']]

    # --- 3. Normalized Batches ---
    batches_df = drugs_df.copy()
    batches_df['medicine_id'] = batches_df['ndc'].map(med_id_map)
    batches_df['supplier_id'] = batches_df['supid'].map(sup_id_map)
    batches_df['quantity_received'] = 500  # Assumption
    batches_df['quantity_remaining'] = 500
    batches_df['batch_number'] = "B-" + batches_df['ndc'].astype(str) + "-" + batches_df.index.astype(str)
    
    batches_df = batches_df.rename(columns={'expdate': 'expiry_date', 'purchaseprice': 'purchase_price'})
    batches_df = batches_df[['medicine_id', 'supplier_id', 'batch_number', 'quantity_received', 'quantity_remaining', 'expiry_date', 'purchase_price']]

    # --- 4. Normalized Sales & Sale Items ---
    sales_data = []
    sale_items_data = []

    for idx, row in presc_df.iterrows():
        sale_id = idx + 1
        
        # Sale record
        sales_data.append({
            'id': sale_id,
            'sale_date': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_amount': 0, # Will be calculated via unit prices
            'notes': f"Prescription ID: {row['patientid']}"
        })

        # Find unit price from drugs data
        matching_drug = drugs_df[drugs_df['ndc'] == row['ndc']].iloc[0] if row['ndc'] in drugs_df['ndc'].values else None
        unit_price = matching_drug['sellprice'] if matching_drug is not None else 0

        # Sale Item record
        sale_items_data.append({
            'sale_id': sale_id,
            'medicine_id': med_id_map.get(row['ndc']),
            'quantity_sold': row['qty'],
            'unit_price': unit_price,
            'ndc_temp': row['ndc'] # Useful for FEFO resolution later in seed script
        })

    sales_df = pd.DataFrame(sales_data)
    sale_items_df = pd.DataFrame(sale_items_data)

    return {
        "suppliers": suppliers_df[['id', 'name', 'phone']],
        "medicines": medicines_df,
        "batches": batches_df,
        "sales": sales_df,
        "sale_items": sale_items_df
    }

if __name__ == "__main__":
    data = load_normalized_data()
    if data:
        print("[+] Custom Relational DataFrames Prepared:")
        for table, df in data.items():
            print(f"  - {table}: {len(df)} rows")
