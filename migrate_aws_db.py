#!/usr/bin/env python3
"""
Migration script to add missing columns to AWS database
Run this on AWS EC2 instance
"""
from application import app, db
from sqlalchemy import text

with app.app_context():
    try:
        print("Checking database schema...")
        
        # Get current columns in unit table
        result = db.session.execute(text("PRAGMA table_info(unit)"))
        existing_columns = [row[1] for row in result]
        print(f"Existing columns: {existing_columns}")
        
        # List of columns to add
        columns_to_add = [
            ('csv_report_filename', 'TEXT'),
            ('csv_report_generated_at', 'DATETIME'),
            ('published_assignments_snapshot', 'TEXT')
        ]
        
        # Add missing columns
        for column_name, column_type in columns_to_add:
            if column_name not in existing_columns:
                print(f"Adding column: {column_name} ({column_type})")
                db.session.execute(text(f"ALTER TABLE unit ADD COLUMN {column_name} {column_type}"))
                db.session.commit()
                print(f"✓ Added {column_name}")
            else:
                print(f"✓ {column_name} already exists")
        
        print("\n✅ Database migration complete!")
        print("\nUpdated columns:")
        result = db.session.execute(text("PRAGMA table_info(unit)"))
        for row in result:
            print(f"  - {row[1]} ({row[2]})")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.session.rollback()
        import traceback
        traceback.print_exc()
