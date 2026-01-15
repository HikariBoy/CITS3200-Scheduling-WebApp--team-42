#!/usr/bin/env python3
"""
Fix auto-unavailability for existing swaps that happened before the fix.
This script updates unavailability records for swaps that already occurred.
"""

from application import app, db
from models import SwapRequest, Assignment, Session, Module, Unit, User, Unavailability, SwapStatus
from datetime import datetime

def fix_existing_swaps():
    """Fix auto-unavailability for all existing approved swaps."""
    
    with app.app_context():
        # Get all approved swaps
        swaps = SwapRequest.query.filter_by(status=SwapStatus.APPROVED).all()
        
        print(f"Found {len(swaps)} approved swaps to check")
        print("=" * 80)
        
        fixed_count = 0
        
        for swap in swaps:
            assignment = Assignment.query.get(swap.requester_assignment_id)
            if not assignment:
                continue
            
            session = Session.query.get(assignment.session_id)
            if not session:
                continue
            
            # Only fix if session is published
            if session.status != 'published':
                print(f"Swap {swap.id}: Session {session.id} not published, skipping")
                continue
            
            module = Module.query.get(session.module_id)
            if not module:
                continue
            
            unit = Unit.query.get(module.unit_id)
            
            print(f"\nSwap ID {swap.id}:")
            print(f"  Session: {module.module_name} on {session.start_time}")
            print(f"  From: {User.query.get(swap.requester_id).full_name if User.query.get(swap.requester_id) else 'Unknown'}")
            print(f"  To: {User.query.get(swap.target_id).full_name if User.query.get(swap.target_id) else 'Unknown'}")
            
            session_date = session.start_time.date()
            session_start_time = session.start_time.time()
            session_end_time = session.end_time.time()
            
            # 1. Remove old facilitator's auto-unavailability
            old_unavail = Unavailability.query.filter_by(
                user_id=swap.requester_id,
                unit_id=None,
                source_session_id=session.id
            ).first()
            
            if old_unavail:
                db.session.delete(old_unavail)
                print(f"  ✓ Removed old facilitator's auto-unavailability")
            else:
                print(f"  - Old facilitator had no auto-unavailability")
            
            # 2. Create new auto-unavailability for target facilitator
            existing_unavail = Unavailability.query.filter_by(
                user_id=swap.target_id,
                unit_id=None,
                date=session_date,
                start_time=session_start_time,
                end_time=session_end_time,
                source_session_id=session.id
            ).first()
            
            if not existing_unavail:
                module_name = module.module_name if module else "Session"
                session_type = session.session_type or "Session"
                unit_code = unit.unit_code if unit else "Unknown"
                reason = f"Scheduled: {unit_code} - {module_name} ({session_type})"
                
                new_unavail = Unavailability(
                    user_id=swap.target_id,
                    unit_id=None,  # Global unavailability
                    date=session_date,
                    start_time=session_start_time,
                    end_time=session_end_time,
                    is_full_day=False,
                    reason=reason,
                    source_session_id=session.id
                )
                
                db.session.add(new_unavail)
                print(f"  ✓ Created auto-unavailability for target facilitator")
                fixed_count += 1
            else:
                print(f"  - Target facilitator already has auto-unavailability")
        
        # Commit all changes
        try:
            db.session.commit()
            print(f"\n{'=' * 80}")
            print(f"✅ Successfully fixed {fixed_count} swaps!")
            print(f"{'=' * 80}")
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Error committing changes: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    fix_existing_swaps()
