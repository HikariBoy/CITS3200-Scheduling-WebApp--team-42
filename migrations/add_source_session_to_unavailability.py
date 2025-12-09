"""
Migration: Add source_session_id to Unavailability table

This allows tracking of auto-generated unavailability from published schedules.

To run this migration:
1. Open Python shell in app context: flask shell
2. Run: exec(open('migrations/add_source_session_to_unavailability.py').read())

Or manually run in SQLite:
ALTER TABLE unavailability ADD COLUMN source_session_id INTEGER;
"""

def upgrade(db):
    """Add source_session_id column to unavailability table"""
    try:
        db.session.execute("""
            ALTER TABLE unavailability 
            ADD COLUMN source_session_id INTEGER
        """)
        db.session.commit()
        print("✅ Successfully added source_session_id column to unavailability table")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        print("Column may already exist or there's a database issue")
        db.session.rollback()
        return False

# If running in flask shell context
if __name__ != '__main__':
    try:
        from models import db
        upgrade(db)
    except:
        print("Run this in flask shell context or manually execute the SQL")
