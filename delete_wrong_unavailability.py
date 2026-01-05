#!/usr/bin/env python3
"""
Delete unavailability records that were created for the wrong user (user_id=2)
These were created by the recurring endpoint bug before the fix.
"""

import os
os.chdir('/Users/aj/Desktop/scheduleME/CITS3200-Scheduling-WebApp--team-42')

from application import app, db
from models import Unavailability, User

with app.app_context():
    # Find all unavailability records for user_id=2 with recurring_pattern set
    wrong_records = Unavailability.query.filter_by(
        user_id=2,
        unit_id=None
    ).filter(Unavailability.recurring_pattern.isnot(None)).all()
    
    print(f"Found {len(wrong_records)} records for user_id=2 with recurring pattern:")
    for record in wrong_records:
        print(f"  - ID={record.id}, date={record.date}, pattern={record.recurring_pattern}")
    
    if wrong_records:
        # Get user info
        user = User.query.get(2)
        if user:
            print(f"\nUser ID 2: {user.email}")
        
        # Delete them
        for record in wrong_records:
            db.session.delete(record)
        
        db.session.commit()
        print(f"\n✅ Deleted {len(wrong_records)} records")
    else:
        print("\nNo records found to delete")
