"""
Migration: Add source_session_id to Unavailability table

This allows tracking of auto-generated unavailability from published schedules.
"""

from app import app, db
from models import Unavailability

def upgrade():
    """Add source_session_id column to unavailability table"""
    with app.app_context():
        # SQLite doesn't support ALTER TABLE ADD COLUMN with FOREIGN KEY directly
        # But we can add the column without the constraint, then it will work
        try:
            db.session.execute("""
                ALTER TABLE unavailability 
                ADD COLUMN source_session_id INTEGER
            """)
            db.session.commit()
            print("✅ Successfully added source_session_id column to unavailability table")
        except Exception as e:
            print(f"❌ Error: {e}")
            print("Column may already exist or there's a database issue")
            db.session.rollback()

def downgrade():
    """Remove source_session_id column from unavailability table"""
    with app.app_context():
        try:
            # SQLite doesn't support DROP COLUMN easily, would need to recreate table
            print("⚠️  Downgrade not implemented for SQLite")
            print("To remove column, you would need to recreate the table")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == '__main__':
    print("Running migration: add_source_session_to_unavailability")
    upgrade()
