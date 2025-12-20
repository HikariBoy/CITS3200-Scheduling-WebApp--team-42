#!/usr/bin/env python3
"""
Quick script to add published_assignments_snapshot column to Unit table
"""
from application import app, db
from sqlalchemy import text

with app.app_context():
    try:
        # Check if column already exists
        result = db.session.execute(text("PRAGMA table_info(unit)"))
        columns = [row[1] for row in result]
        
        if 'published_assignments_snapshot' not in columns:
            print("Adding published_assignments_snapshot column...")
            db.session.execute(text("ALTER TABLE unit ADD COLUMN published_assignments_snapshot TEXT"))
            db.session.commit()
            print("✓ Added published_assignments_snapshot")
        else:
            print("✓ published_assignments_snapshot already exists")
        
        print("\n✅ Database migration complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.session.rollback()
