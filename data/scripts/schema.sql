-- SPIMS Database Schema
-- Optimized for PostgreSQL 15

-- 1. Suppliers Table
CREATE TABLE IF NOT EXISTS suppliers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Medicines Table
CREATE TABLE IF NOT EXISTS medicines (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    generic_name VARCHAR(255),
    ndc VARCHAR(50) UNIQUE NOT NULL,
    preferred_supplier_id INTEGER REFERENCES suppliers(id),
    unit VARCHAR(50) DEFAULT 'UNIT',
    reorder_threshold INTEGER DEFAULT 10,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Batches Table (Inventory)
CREATE TABLE IF NOT EXISTS batches (
    id SERIAL PRIMARY KEY,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    supplier_id INTEGER REFERENCES suppliers(id),
    batch_number VARCHAR(100) NOT NULL,
    quantity_received INTEGER NOT NULL,
    quantity_remaining INTEGER NOT NULL,
    expiry_date DATE NOT NULL,
    purchase_price DECIMAL(10, 2),
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Sales Table
CREATE TABLE IF NOT EXISTS sales (
    id SERIAL PRIMARY KEY,
    sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_amount DECIMAL(10, 2) DEFAULT 0.00,
    notes TEXT
);

-- 5. Sale Items Table (Linkage to Batches for FEFO)
CREATE TABLE IF NOT EXISTS sale_items (
    id SERIAL PRIMARY KEY,
    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    quantity_sold INTEGER NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL
);

-- Indexes for Performance
CREATE INDEX idx_batches_expiry ON batches(expiry_date);
CREATE INDEX idx_batches_medicine ON batches(medicine_id);
CREATE INDEX idx_sale_items_sale ON sale_items(sale_id);
CREATE INDEX idx_medicines_ndc ON medicines(ndc);
