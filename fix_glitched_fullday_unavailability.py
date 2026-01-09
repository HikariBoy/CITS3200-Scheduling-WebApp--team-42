#!/usr/bin/env python3
"""
Fix glitched full-day unavailability that conflicts with auto-generated (scheduled) entries.

THE BUG:
- User checked full-day on an orange day (with scheduled sessions)
- This created conflicting unavailability: both full-day AND scheduled session
- Now can't uncheck full-day from UI (glitched state)

THE FIX:
- Find all full-day unavailability records
- Check if same user+date has auto-generated (source_session_id IS NOT NULL)
- Delete the full-day record (keep the auto-generated one)
"""

import os
import sys

# Add parent directory to path to import application
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from application import app, db
from models import Unavailability

def fix_glitched_fullday():
    with app.app_context():
        # Find all full-day unavailability records
        fullday_records = Unavailability.query.filter_by(
            is_full_day=True,
            unit_id=None  # Global unavailability
        ).all()
        
        print(f"Found {len(fullday_records)} full-day unavailability records")
        
        deleted_count = 0
        
        for record in fullday_records:
            # Check if same user+date has auto-generated unavailability
            auto_generated = Unavailability.query.filter(
                Unavailability.user_id == record.user_id,
                Unavailability.date == record.date,
                Unavailability.unit_id.is_(None),
                Unavailability.source_session_id.isnot(None)  # Auto-generated
            ).first()
            
            if auto_generated:
                # Conflict found! Delete the full-day record
                print(f"🐛 GLITCH FOUND: User {record.user_id}, Date {record.date}")
                print(f"   - Full-day unavailability (ID: {record.id})")
                print(f"   - Auto-generated session (ID: {auto_generated.id}, Reason: {auto_generated.reason})")
                print(f"   → Deleting full-day record...")
                
                db.session.delete(record)
                deleted_count += 1
        
        if deleted_count > 0:
            db.session.commit()
            print(f"\n✅ Fixed {deleted_count} glitched full-day unavailability records")
        else:
            print("\n✅ No glitched records found! Database is clean.")

if __name__ == '__main__':
    print("=" * 60)
    print("FIX GLITCHED FULL-DAY UNAVAILABILITY")
    print("=" * 60)
    print()
    
    fix_glitched_fullday()
    
    print()
    print("=" * 60)
    print("DONE!")
    print("=" * 60)
