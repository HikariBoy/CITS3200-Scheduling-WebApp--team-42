#!/usr/bin/env python3
"""
Quick script to add csv_report_filename and csv_report_generated_at columns to Unit table
"""
from application import app, db
from sqlalchemy import text

with app.app_context():
    try:
        # Check if columns already exist
        result = db.session.execute(text("PRAGMA table_info(unit)"))
        columns = [row[1] for row in result]
        
        if 'csv_report_filename' not in columns:
            print("Adding csv_report_filename column...")
            db.session.execute(text("ALTER TABLE unit ADD COLUMN csv_report_filename VARCHAR(255)"))
            db.session.commit()
            print("✓ Added csv_report_filename")
        else:
            print("✓ csv_report_filename already exists")
        
        if 'csv_report_generated_at' not in columns:
            print("Adding csv_report_generated_at column...")
            db.session.execute(text("ALTER TABLE unit ADD COLUMN csv_report_generated_at DATETIME"))
            db.session.commit()
            print("✓ Added csv_report_generated_at")
        else:
            print("✓ csv_report_generated_at already exists")
        
        print("\n✅ Database migration complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.session.rollback()
