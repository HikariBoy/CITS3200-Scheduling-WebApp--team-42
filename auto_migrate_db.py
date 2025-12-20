#!/usr/bin/env python3
"""
Automatic database migration script
Compares models.py schema with actual database and adds missing columns
Run this on AWS after pulling new code with schema changes
"""
from application import app, db
from sqlalchemy import text, inspect
from models import Unit, User, Module, Session, Assignment, Unavailability, FacilitatorSkill, SwapRequest, EmailToken, Venue, Notification, UnitFacilitator, UnitVenue

def get_table_columns(table_name):
    """Get existing columns in a table"""
    result = db.session.execute(text(f"PRAGMA table_info({table_name})"))
    return {row[1]: row[2] for row in result}  # {column_name: column_type}

def get_model_columns(model):
    """Get columns defined in SQLAlchemy model"""
    inspector = inspect(model)
    columns = {}
    for column in inspector.columns:
        col_type = str(column.type)
        # Map SQLAlchemy types to SQLite types
        if 'VARCHAR' in col_type or 'TEXT' in col_type or 'STRING' in col_type:
            sqlite_type = 'TEXT'
        elif 'INTEGER' in col_type or 'BIGINT' in col_type:
            sqlite_type = 'INTEGER'
        elif 'DATETIME' in col_type:
            sqlite_type = 'DATETIME'
        elif 'BOOLEAN' in col_type:
            sqlite_type = 'INTEGER'  # SQLite uses INTEGER for BOOLEAN
        elif 'FLOAT' in col_type or 'NUMERIC' in col_type or 'DECIMAL' in col_type:
            sqlite_type = 'REAL'
        else:
            sqlite_type = 'TEXT'  # Default fallback
        
        columns[column.name] = sqlite_type
    return columns

def migrate_table(model, table_name):
    """Migrate a single table"""
    print(f"\n📋 Checking table: {table_name}")
    
    # Get existing and expected columns
    existing_cols = get_table_columns(table_name)
    expected_cols = get_model_columns(model)
    
    # Find missing columns
    missing_cols = {k: v for k, v in expected_cols.items() if k not in existing_cols}
    
    if not missing_cols:
        print(f"  ✓ {table_name} is up to date")
        return 0
    
    # Add missing columns
    added = 0
    for col_name, col_type in missing_cols.items():
        try:
            print(f"  + Adding column: {col_name} ({col_type})")
            db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
            db.session.commit()
            added += 1
            print(f"    ✓ Added {col_name}")
        except Exception as e:
            print(f"    ⚠️  Could not add {col_name}: {e}")
            db.session.rollback()
    
    return added

with app.app_context():
    try:
        print("=" * 60)
        print("🔄 AUTOMATIC DATABASE MIGRATION")
        print("=" * 60)
        
        # Map of models to table names
        tables_to_migrate = [
            (Unit, 'unit'),
            (User, 'user'),
            (Module, 'module'),
            (Session, 'session'),
            (Assignment, 'assignment'),
            (Unavailability, 'unavailability'),
            (FacilitatorSkill, 'facilitator_skill'),
            (SwapRequest, 'swap_request'),
            (EmailToken, 'email_token'),
            (Venue, 'venue'),
            (Notification, 'notification'),
            (UnitFacilitator, 'unit_facilitator'),
            (UnitVenue, 'unit_venue'),
        ]
        
        total_added = 0
        for model, table_name in tables_to_migrate:
            added = migrate_table(model, table_name)
            total_added += added
        
        print("\n" + "=" * 60)
        if total_added > 0:
            print(f"✅ Migration complete! Added {total_added} column(s)")
        else:
            print("✅ Database is up to date! No changes needed")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        db.session.rollback()
        import traceback
        traceback.print_exc()
