#!/usr/bin/env python3
"""
Delete all assignments for a specific facilitator.
Usage: python3 delete_facilitator_assignments.py <email>
"""

import sys
from application import app, db
from models import User, Assignment, Session, Module, Unit

def delete_facilitator_assignments(email):
    """Delete all assignments for a facilitator by email."""
    
    with app.app_context():
        # Find the facilitator
        facilitator = User.query.filter_by(email=email).first()
        
        if not facilitator:
            print(f'❌ Facilitator with email {email} not found!')
            return False
        
        print(f'Found facilitator: {facilitator.full_name} (ID: {facilitator.id})')
        print(f'Email: {facilitator.email}')
        print()
        
        # Get all assignments
        assignments = Assignment.query.filter_by(facilitator_id=facilitator.id).all()
        
        if not assignments:
            print('✅ No assignments found for this facilitator.')
            return True
        
        print(f'Found {len(assignments)} assignments')
        print()
        
        # Group by unit for summary
        unit_counts = {}
        for a in assignments:
            session = Session.query.get(a.session_id)
            if session:
                module = Module.query.get(session.module_id)
                if module:
                    unit = Unit.query.get(module.unit_id)
                    if unit:
                        unit_code = unit.unit_code
                        if unit_code not in unit_counts:
                            unit_counts[unit_code] = 0
                        unit_counts[unit_code] += 1
        
        print('Assignments by unit:')
        for unit_code, count in unit_counts.items():
            print(f'  {unit_code}: {count} assignments')
        print()
        
        # Confirm deletion
        response = input(f'⚠️  Delete all {len(assignments)} assignments? (yes/no): ')
        
        if response.lower() != 'yes':
            print('❌ Deletion cancelled.')
            return False
        
        # Delete all assignments
        deleted_count = 0
        for assignment in assignments:
            db.session.delete(assignment)
            deleted_count += 1
        
        db.session.commit()
        
        print(f'✅ Successfully deleted {deleted_count} assignments for {facilitator.full_name}')
        return True

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python3 delete_facilitator_assignments.py <email>')
        print('Example: python3 delete_facilitator_assignments.py armaansinghwa@gmail.com')
        sys.exit(1)
    
    email = sys.argv[1]
    success = delete_facilitator_assignments(email)
    sys.exit(0 if success else 1)
