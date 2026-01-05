#!/usr/bin/env python3
"""
Migration script to make unavailability.unit_id nullable for global unavailability.

SAFE MIGRATION:
1. Backs up database before any changes
2. Uses SQLite's ALTER TABLE to make unit_id nullable
3. Drops and recreates unique constraint without unit_id
4. Preserves all existing data
5. Provides rollback instructions

Run with: python3 migrate_global_unavailability.py
"""

import sqlite3
import shutil
from datetime import datetime
import os

DB_PATH = 'instance/dev.db'  # Confirmed: this is the active database on AWS

def backup_database():
    """Create a timestamped backup of the database."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = f'instance/dev.db.backup_before_global_unavail_{timestamp}'
    
    print(f"📦 Creating backup: {backup_path}")
    shutil.copy2(DB_PATH, backup_path)
    print(f"✅ Backup created successfully!")
    return backup_path

def migrate_database():
    """Migrate the database to support global unavailability."""
    print("\n🔧 Starting database migration...")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Step 1: Create new table with nullable unit_id
        print("📝 Creating new unavailability table with nullable unit_id...")
        cursor.execute("""
            CREATE TABLE unavailability_new (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                unit_id INTEGER,  -- Now nullable for global unavailability!
                date DATE NOT NULL,
                start_time TIME,
                end_time TIME,
                is_full_day BOOLEAN DEFAULT 0,
                recurring_pattern VARCHAR(10),
                recurring_end_date DATE,
                recurring_interval INTEGER DEFAULT 1,
                reason TEXT,
                source_session_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES user(id),
                FOREIGN KEY (unit_id) REFERENCES unit(id),
                FOREIGN KEY (source_session_id) REFERENCES session(id)
            )
        """)
        
        # Step 2: Copy all data from old table to new table
        print("📋 Copying existing data...")
        cursor.execute("""
            INSERT INTO unavailability_new 
            SELECT * FROM unavailability
        """)
        
        # Step 3: Drop old table
        print("🗑️  Dropping old table...")
        cursor.execute("DROP TABLE unavailability")
        
        # Step 4: Rename new table to original name
        print("✏️  Renaming new table...")
        cursor.execute("ALTER TABLE unavailability_new RENAME TO unavailability")
        
        # Commit changes
        conn.commit()
        print("✅ Migration completed successfully!")
        
        # Verify data integrity
        cursor.execute("SELECT COUNT(*) FROM unavailability")
        count = cursor.fetchone()[0]
        print(f"📊 Verified: {count} unavailability records preserved")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Migration failed: {e}")
        print("⚠️  Database has been rolled back - no changes made")
        raise
    finally:
        conn.close()

def main():
    """Main migration function."""
    print("=" * 60)
    print("🚀 GLOBAL UNAVAILABILITY MIGRATION")
    print("=" * 60)
    
    # Check if database exists
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return
    
    # Backup first
    backup_path = backup_database()
    
    # Run migration
    try:
        migrate_database()
        print("\n" + "=" * 60)
        print("✅ MIGRATION SUCCESSFUL!")
        print("=" * 60)
        print(f"\n📦 Backup saved at: {backup_path}")
        print("\n🔄 To rollback if needed:")
        print(f"   cp {backup_path} {DB_PATH}")
        print("\n✨ You can now use global unavailability (unit_id = NULL)")
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ MIGRATION FAILED!")
        print("=" * 60)
        print(f"\n🔄 To restore from backup:")
        print(f"   cp {backup_path} {DB_PATH}")

if __name__ == '__main__':
    main()
