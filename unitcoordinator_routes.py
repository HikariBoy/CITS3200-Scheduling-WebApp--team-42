import logging
import csv
import re
from io import StringIO, BytesIO
from datetime import datetime, date, timedelta
from sqlalchemy import and_, func
from sqlalchemy import func
# from models import Unit, Module, Session
from datetime import date
from sqlalchemy.orm import aliased
from sqlalchemy import or_

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    jsonify, send_file
)
from auth import login_required, get_current_user
from utils import role_required
from models import db

from models import db, UserRole, Unit, User, Venue, UnitFacilitator, UnitCoordinator, UnitVenue, Module, Session, Assignment, Unavailability, Facilitator, SwapRequest, SwapStatus, FacilitatorSkill, SkillLevel, Notification

# ------------------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

unitcoordinator_bp = Blueprint(
    "unitcoordinator", __name__, url_prefix="/unitcoordinator"
)

# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------

def generate_unavailability_from_schedule(unit_id):
    """
    Auto-generate unavailability entries for facilitators based on their assigned sessions
    in a published schedule. This prevents double-booking across units.
    
    Args:
        unit_id: The unit whose schedule was just published
    """
    from models import ScheduleStatus, UnitFacilitator
    
    unit = Unit.query.get(unit_id)
    if not unit or unit.schedule_status != ScheduleStatus.PUBLISHED:
        return 0
    
    # Get all sessions with assigned facilitators in this unit
    # Sessions are linked through Module, and facilitators through Assignment
    sessions_with_assignments = (
        db.session.query(Session, Assignment)
        .join(Module, Session.module_id == Module.id)
        .join(Assignment, Assignment.session_id == Session.id)
        .filter(Module.unit_id == unit_id)
        .all()
    )
    
    created_count = 0
    
    for session, assignment in sessions_with_assignments:
        facilitator_id = assignment.facilitator_id
        
        if not facilitator_id or not session.start_time or not session.end_time:
            continue
        
        # Get session date from start_time
        session_date = session.start_time.date()
        session_start_time = session.start_time.time()
        session_end_time = session.end_time.time()
        
        # Check if GLOBAL unavailability already exists for this session
        existing = Unavailability.query.filter_by(
            user_id=facilitator_id,
            unit_id=None,  # Global unavailability
            date=session_date,
            start_time=session_start_time,
            end_time=session_end_time,
            source_session_id=session.id
        ).first()
        
        if existing:
            continue  # Already exists
        
        # Create reason text
        module_name = session.module.module_name if session.module else "Session"
        session_type = session.session_type or "Session"
        reason = f"Scheduled: {unit.unit_code} - {module_name} ({session_type})"
        
        # Create GLOBAL unavailability (not tied to any specific unit)
        unavail = Unavailability(
            user_id=facilitator_id,
            unit_id=None,  # Global unavailability
            date=session_date,
            start_time=session_start_time,
            end_time=session_end_time,
            is_full_day=False,
            reason=reason,
            source_session_id=session.id
        )
        
        db.session.add(unavail)
        created_count += 1
    
    try:
        db.session.commit()
        logger.info(f"Created {created_count} auto-generated unavailability entries for unit {unit.unit_code}")
        return created_count
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating auto-generated unavailability: {e}")
        return 0

def remove_unavailability_from_schedule(unit_id):
    """
    Remove auto-generated unavailability entries when a schedule is unpublished.
    
    Args:
        unit_id: The unit whose schedule was unpublished
    """
    # Find all sessions from this unit (sessions are linked through Module)
    session_ids = (
        db.session.query(Session.id)
        .join(Module, Session.module_id == Module.id)
        .filter(Module.unit_id == unit_id)
        .all()
    )
    session_ids = [sid[0] for sid in session_ids]
    
    if not session_ids:
        return 0
    
    # Delete unavailability entries that were generated from these sessions
    deleted = Unavailability.query.filter(Unavailability.source_session_id.in_(session_ids)).delete(synchronize_session=False)
    
    try:
        db.session.commit()
        logger.info(f"Removed {deleted} auto-generated unavailability entries for unit {unit_id}")
        return deleted
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error removing auto-generated unavailability: {e}")
        return 0


# CSV columns for the combined facilitators/venues file
CSV_HEADERS = [
    "facilitator_email",   # optional per row
]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
def _parse_date_multi(s: str):
    """Accept either 'YYYY-MM-DD' or 'DD/MM/YYYY'. Return date or None."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def _valid_email(s: str) -> bool:
    return bool(EMAIL_RE.match(s or ""))

def _get_user_unit_or_404(user, unit_id: int):
    """Return Unit if it exists AND user is a coordinator (or user is admin); else None."""
    try:
        unit_id = int(unit_id)
    except (TypeError, ValueError):
        return None
    unit = Unit.query.get(unit_id)
    if not unit:
        return None
    # Allow access if user is a coordinator for this unit OR is an admin
    if user.role == UserRole.ADMIN:
        return unit
    # Check if user is a coordinator for this unit
    is_coordinator = UnitCoordinator.query.filter_by(
        unit_id=unit_id, 
        user_id=user.id
    ).first() is not None
    if not is_coordinator:
        return None
    return unit

def _iso(d: date) -> str:
    return d.isoformat()

def _parse_dt(s: str):
    """Parse 'YYYY-MM-DDTHH:MM' or 'YYYY-MM-DD HH:MM' to datetime."""
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

def _cleanup_old_temp_files(temp_dir: str, prefix: str, max_age_hours: int = 168):  # 7 days
    """
    Clean up old temporary files to prevent disk space issues.
    
    Args:
        temp_dir: Directory containing temporary files
        prefix: File prefix to match (e.g., "schedule_report_1_")
        max_age_hours: Maximum age of files in hours before deletion
    """
    import os
    import glob
    from datetime import datetime, timedelta
    
    try:
        # Find all files matching the prefix
        pattern = os.path.join(temp_dir, f"{prefix}*.csv")
        files = glob.glob(pattern)
        
        # Calculate cutoff time
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        # Delete old files
        deleted_count = 0
        for file_path in files:
            try:
                file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                if file_mtime < cutoff_time:
                    os.remove(file_path)
                    deleted_count += 1
            except (OSError, IOError):
                # Ignore errors when deleting individual files
                pass
        
        if deleted_count > 0:
            print(f"Cleaned up {deleted_count} old temporary files with prefix '{prefix}'")
            
    except Exception as e:
        # Don't let cleanup errors break the main functionality
        print(f"Warning: Error during temporary file cleanup: {e}")

def _get_or_create_default_module(unit: Unit) -> Module:
    """Get or create a default 'General' module for the unit."""
    m = Module.query.filter_by(unit_id=unit.id, module_name="General").first()
    if not m:
        m = Module(unit_id=unit.id, module_name="General", module_type="general")
        db.session.add(m)
        db.session.commit()
    return m

def _serialize_session(s: Session, venues_by_name=None):
    venue_name = s.location or ""
    vid = None
    if venues_by_name and venue_name:
        vid = venues_by_name.get(venue_name.strip().lower())

    title = s.module.module_name or "Session"
    
    # Get all facilitator information with roles
    facilitators = []
    facilitator = None  # Keep for backward compatibility
    if s.assignments:
        for assignment in s.assignments:
            if assignment.facilitator:
                facilitator_info = {
                    "id": assignment.facilitator.id,
                    "name": assignment.facilitator.full_name,
                    "email": assignment.facilitator.email,
                    "role": getattr(assignment, 'role', 'lead'),  # Default to 'lead' if role not set
                    "is_confirmed": assignment.is_confirmed
                }
                facilitators.append(facilitator_info)
        
        # For backward compatibility, use first facilitator
        if facilitators:
            facilitator = facilitators[0]["name"]
    
    # Determine session status
    status = "unassigned"
    if facilitators:
        status = "assigned"  # Any facilitator assigned, regardless of confirmation status
    
    return {
        "id": str(s.id),  # turn this into a string
        "title": title,
        "start": s.start_time.isoformat(timespec="minutes"),
        "end": s.end_time.isoformat(timespec="minutes"),
        "venue": venue_name,
        "facilitator": facilitator,  # Backward compatibility
        "facilitators": facilitators,  # New: all facilitators with roles
        "status": status,
        "session_name": title,
        "location": s.location,
        "module_type": s.module.module_type or "Workshop",
        "module_id": s.module_id,  # Add module_id for skill lookup
        "attendees": getattr(s, 'attendees', None),
        "extendedProps": {
            "venue": venue_name,
            "venue_id": vid,
            "session_name": title,
            "location": s.location,
            "module_id": s.module_id,  # Add module_id here too
            "facilitator_name": facilitator,  # Backward compatibility
            "facilitator_id": s.assignments[0].facilitator_id if s.assignments else None,
            "lead_staff_required": s.lead_staff_required or 1,
            "support_staff_required": s.support_staff_required or 0,
            "facilitators": facilitators,  # New: all facilitators with roles
        }
    }

def _get_or_create_module_by_name(unit: Unit, name: str) -> Module:
    name = (name or "").strip()
    if not name:
        return _get_or_create_default_module(unit)
    m = Module.query.filter_by(unit_id=unit.id, module_name=name).first()
    if not m:
        m = Module(unit_id=unit.id, module_name=name, module_type="general")
        db.session.add(m)
        db.session.flush()  # no commit yet; caller may commit
    return m

ACTIVITY_ALLOWED = {"workshop", "tutorial", "lab"}

def _coerce_activity_type(s: str) -> str:
    v = (s or "").strip().lower()
    return v if v in ACTIVITY_ALLOWED else "other"

TIME_RANGE_RE = re.compile(
    r"^\s*(\d{1,2})[:\.](\d{2})\s*[-–—]\s*(\d{1,2})[:\.](\d{2})\s*$"
)

def _parse_time_range(s: str):
    """
    Accepts '09:00-11:30', '9.00 – 11.30', etc.
    Returns (start_h, start_m, end_h, end_m) or None.
    """
    if not s: return None
    m = TIME_RANGE_RE.match(s)
    if not m: return None
    h1, m1, h2, m2 = map(int, m.groups())
    if not (0 <= h1 <= 23 and 0 <= h2 <= 23 and 0 <= m1 <= 59 and 0 <= m2 <= 59):
        return None
    return h1, m1, h2, m2

def _pending_swaps_for_unit(unit_id):
    RA = aliased(Assignment)   # requester assignment
    TA = aliased(Assignment)   # target assignment
    RS = aliased(Session)
    TS = aliased(Session)
    RM = aliased(Module)
    TM = aliased(Module)
    RU = aliased(User)         # requester user
    TU = aliased(User)         # target user

    q = (
        db.session.query(
            SwapRequest.id,
            SwapRequest.created_at,
            SwapRequest.reason,

            # assignments and sessions (ids)
            RA.id.label("req_assign_id"),
            TA.id.label("tgt_assign_id"),
            RS.id.label("req_sess_id"),
            TS.id.label("tgt_sess_id"),

            # people
            RU.first_name.label("req_first"),
            RU.last_name.label("req_last"),
            RU.email.label("req_email"),
            TU.first_name.label("tgt_first"),
            TU.last_name.label("tgt_last"),
            TU.email.label("tgt_email"),

            # NEW: module names + times so the card can show nice text
            RM.module_name.label("req_module"),
            TM.module_name.label("tgt_module"),
            RS.start_time.label("req_start"),
            RS.end_time.label("req_end"),
            TS.start_time.label("tgt_start"),
            TS.end_time.label("tgt_end"),
        )
        .join(RA, RA.id == SwapRequest.requester_assignment_id)
        .join(RS, RS.id == RA.session_id)
        .join(RM, RM.id == RS.module_id)
        .join(TA, TA.id == SwapRequest.target_assignment_id)
        .join(TS, TS.id == TA.session_id)
        .join(TM, TM.id == TS.module_id)
        # your schema links Assignment -> User via facilitator_id
        .join(RU, RU.id == RA.facilitator_id)
        .join(TU, TU.id == TA.facilitator_id)
        .filter(or_(RM.unit_id == unit_id, TM.unit_id == unit_id))
        .filter(SwapRequest.status == SwapStatus.PENDING)
        .order_by(SwapRequest.created_at.asc())
    )
    return q.all()



# --- Recurrence helpers -------------------------------------------------------

def _parse_recurrence(d: dict):
    """
    Expect shape like:
      {"occurs":"weekly", "interval":1, "byweekday":[0-6], "count":N, "until":"YYYY-MM-DD" | None}
    Return a normalized dict or {"occurs":"none"}.
    """
    if not isinstance(d, dict):
        return {"occurs": "none"}
    occurs = (d.get("occurs") or "none").lower()
    if occurs != "weekly":
        return {"occurs": "none"}
    interval = int(d.get("interval") or 1)
    if interval < 1:
        interval = 1
    # UI sends weekday of the first start date; we just step weekly from start, so this is informational.
    byweekday = d.get("byweekday") if isinstance(d.get("byweekday"), list) else None

    count = d.get("count")
    try:
        count = int(count) if count is not None else None
    except (TypeError, ValueError):
        count = None
    if count is not None and count < 1:
        count = 1

    until_raw = (d.get("until") or "").strip()
    until_date = _parse_date_multi(until_raw) if until_raw else None

    return {
        "occurs": "weekly",
        "interval": interval,
        "byweekday": byweekday,
        "count": count,
        "until": until_date,  # Python date or None
    }

def _within_unit_range(unit: Unit, dt: datetime) -> bool:
    """Check datetime against unit.start_date/end_date (if set)."""
    d = dt.date()
    if unit.start_date and d < unit.start_date:
        return False
    if unit.end_date and d > unit.end_date:
        return False
    return True

def _iter_weekly_occurrences(unit: Unit, start_dt: datetime, end_dt: datetime, rec: dict):
    """
    Yield (s,e) pairs for a weekly rule starting at (start_dt,end_dt), inclusive.
    Bounds:
      - stop when 'count' reached, OR
      - stop after 'until' (date), OR
      - stop when we step beyond unit.end_date.
    Always includes the first occurrence.
    """
    interval = rec.get("interval", 1) or 1
    count    = rec.get("count")
    until_d  = rec.get("until")  # date | None

    made = 0
    cur_s = start_dt
    cur_e = end_dt
    while True:
        # Stop conditions before yielding if outside range
        if not _within_unit_range(unit, cur_s) or not _within_unit_range(unit, cur_e):
            # If the first one is out of range we still don't yield it.
            pass
        else:
            yield (cur_s, cur_e)
            made += 1
            if count is not None and made >= count:
                break

        # compute next
        cur_s = cur_s + timedelta(weeks=interval)
        cur_e = cur_e + timedelta(weeks=interval)

        # if until is set, next start after 'until' should stop
        if until_d and cur_s.date() > until_d:
            break

        # unit end bound
        if unit.end_date and cur_s.date() > unit.end_date:
            break



# ------------------------------------------------------------------------------
# Views
# ------------------------------------------------------------------------------
# in unitcoordinator_route.py


# unitcoordinator_routes.py
from datetime import date
from sqlalchemy import func
# ...other imports incl. request...

# unitcoordinator_route.py (dashboard)
@unitcoordinator_bp.route("/profile")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def profile():
    """Unit Coordinator Profile Page"""
    from datetime import date
    
    user = get_current_user()
    today = date.today()
    
    # Get user's units for display (via UnitCoordinator relationship)
    units = (
        db.session.query(Unit, func.count(Session.id))
        .join(UnitCoordinator, UnitCoordinator.unit_id == Unit.id)
        .outerjoin(Module, Module.unit_id == Unit.id)
        .outerjoin(Session, Session.module_id == Module.id)
        .filter(UnitCoordinator.user_id == user.id)
        .group_by(Unit.id)
        .order_by(Unit.unit_code.asc())
        .all()
    )
    
    # Add session counts to units
    units_with_counts = []
    for unit, session_count in units:
        setattr(unit, "session_count", int(session_count or 0))
        units_with_counts.append(unit)
    
    return render_template("profile.html", user=user, units=units_with_counts, today=today)

@unitcoordinator_bp.route("/account-settings")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def account_settings():
    """Unit Coordinator Account Settings Page"""
    user = get_current_user()
    
    # Load contact information from preferences
    contact_info = {}
    if hasattr(user, 'preferences') and user.preferences:
        try:
            import json
            preferences = json.loads(user.preferences) if user.preferences else {}
            contact_info = {
                'phone': preferences.get('phone', ''),
                'mobile': preferences.get('mobile', '')
            }
        except:
            contact_info = {'phone': '', 'mobile': ''}
    else:
        contact_info = {'phone': '', 'mobile': ''}
    
    return render_template("account_settings.html", user=user, contact_info=contact_info)

@unitcoordinator_bp.route("/update-personal-info", methods=["POST"])
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def update_personal_info():
    """Update user's personal information (name only - email is locked)"""
    user = get_current_user()
    
    try:
        # Get form data
        full_name = request.form.get('full_name', '').strip()
        
        # Validate required fields
        if not full_name:
            flash('Full name is required', 'error')
            return redirect(url_for('unitcoordinator.account_settings'))
        
        # Parse full name into first and last name
        name_parts = full_name.split(' ', 1)
        first_name = name_parts[0] if name_parts else ''
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        # Update user information (name only - email is locked)
        user.first_name = first_name
        user.last_name = last_name
        # Note: Email is intentionally not updated as it's locked in the UI
        
        db.session.commit()
        flash('Personal information updated successfully', 'success')
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating personal info: {str(e)}")
        flash('An error occurred while updating your information. Please try again.', 'error')
    
    return redirect(url_for('unitcoordinator.account_settings'))

@unitcoordinator_bp.route("/update-contact-info", methods=["POST"])
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def update_contact_info():
    """Update user's contact information"""
    user = get_current_user()
    
    try:
        # Get form data
        phone = request.form.get('phone', '').strip()
        mobile = request.form.get('mobile', '').strip()
        
        # Store contact info in preferences JSON field
        preferences = {}
        if hasattr(user, 'preferences') and user.preferences:
            try:
                import json
                preferences = json.loads(user.preferences) if user.preferences else {}
            except:
                preferences = {}
        
        # Update contact information in preferences
        preferences['phone'] = phone if phone else None
        preferences['mobile'] = mobile if mobile else None
        
        # Save preferences back to user
        import json
        user.preferences = json.dumps(preferences)
        
        db.session.commit()
        flash('Contact information updated successfully', 'success')
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating contact info: {str(e)}")
        flash('An error occurred while updating your contact information. Please try again.', 'error')
    
    return redirect(url_for('unitcoordinator.account_settings'))

@unitcoordinator_bp.route("/change-password", methods=["POST"])
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def change_password():
    """Change user's password"""
    user = get_current_user()
    
    try:
        # Get form data
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validate required fields
        if not current_password:
            flash('Current password is required', 'error')
            return redirect(url_for('unitcoordinator.account_settings'))
        
        if not new_password:
            flash('New password is required', 'error')
            return redirect(url_for('unitcoordinator.account_settings'))
        
        if not confirm_password:
            flash('Please confirm your new password', 'error')
            return redirect(url_for('unitcoordinator.account_settings'))
        
        # Validate password confirmation
        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return redirect(url_for('unitcoordinator.account_settings'))
        
        # Validate current password
        if not user.check_password(current_password):
            flash('Current password is incorrect', 'error')
            return redirect(url_for('unitcoordinator.account_settings'))
        
        # Validate new password strength
        if len(new_password) < 8:
            flash('New password must be at least 8 characters long', 'error')
            return redirect(url_for('unitcoordinator.account_settings'))
        
        # Check for uppercase, lowercase, number, and special character
        has_upper = any(c.isupper() for c in new_password)
        has_lower = any(c.islower() for c in new_password)
        has_digit = any(c.isdigit() for c in new_password)
        has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in new_password)
        
        if not (has_upper and has_lower and has_digit and has_special):
            flash('New password must contain uppercase letters, lowercase letters, numbers, and special characters', 'error')
            return redirect(url_for('unitcoordinator.account_settings'))
        
        # Update password
        user.set_password(new_password)
        db.session.commit()
        flash('Password changed successfully', 'success')
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error changing password: {str(e)}")
        flash('An error occurred while changing your password. Please try again.', 'error')
    
    return redirect(url_for('unitcoordinator.account_settings'))

@unitcoordinator_bp.route("/notifications")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def get_notifications():
    """Get notifications for the current user"""
    user = get_current_user()
    
    # Get notifications from database
    notifications = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc()).all()
    
    # Convert to JSON-serializable format
    notifications_data = []
    for notification in notifications:
        notification_data = {
            'id': notification.id,
            'message': notification.message,
            'is_read': notification.is_read,
            'created_at': notification.created_at.isoformat() if notification.created_at else None,
            'type': 'info',  # Default type, can be extended
            'title': 'Notification'
        }
        notifications_data.append(notification_data)
    
    # Calculate counts
    total_count = len(notifications)
    unread_count = sum(1 for n in notifications if not n.is_read)
    action_required_count = 0  # Can be extended to check for specific notification types
    
    return jsonify({
        'success': True,
        'notifications': notifications_data,
        'counts': {
            'total': total_count,
            'unread': unread_count,
            'action_required': action_required_count
        }
    })

@unitcoordinator_bp.route("/notifications/mark-all-read", methods=["POST"])
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def mark_all_notifications_read():
    """Mark all notifications as read for the current user"""
    user = get_current_user()
    
    try:
        # Mark all notifications as read
        Notification.query.filter_by(user_id=user.id, is_read=False).update({'is_read': True})
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking notifications as read: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@unitcoordinator_bp.route("/notifications/action", methods=["POST"])
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def handle_notification_action():
    """Handle notification actions (accept, decline, etc.)"""
    user = get_current_user()
    
    try:
        data = request.get_json()
        action = data.get('action')
        notification_id = data.get('notification_id')
        
        # Find the notification
        notification = Notification.query.filter_by(id=notification_id, user_id=user.id).first()
        if not notification:
            return jsonify({'success': False, 'error': 'Notification not found'})
        
        # Handle different actions
        if action == 'mark_read':
            notification.is_read = True
            db.session.commit()
        elif action == 'delete':
            db.session.delete(notification)
            db.session.commit()
        # Add more actions as needed
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error handling notification action: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@unitcoordinator_bp.route("/dashboard")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def dashboard():
    from sqlalchemy import func, or_
    from sqlalchemy.orm import aliased
    from datetime import datetime, timedelta, date

    user = get_current_user()

    # Build list of units this UC coordinates + session counts (for the single-card header)
    rows = (
        db.session.query(Unit, func.count(Session.id))
        .join(UnitCoordinator, UnitCoordinator.unit_id == Unit.id)
        .outerjoin(Module, Module.unit_id == Unit.id)
        .outerjoin(Session, Session.module_id == Module.id)
        .filter(UnitCoordinator.user_id == user.id)
        .group_by(Unit.id)
        .order_by(Unit.unit_code.asc())
        .all()
    )
    units = []
    for u, cnt in rows:
        setattr(u, "session_count", int(cnt or 0))
        units.append(u)

    # Which unit is selected (via ?unit=) — otherwise first
    selected_id = request.args.get("unit", type=int)
    current_unit = (
        next((u for u in units if u.id == selected_id), None)
        if selected_id
        else (units[0] if units else None)
    )

    # ----- Staffing tiles (safe if no current_unit) -----
    stats = {"total": 0, "fully": 0, "needs_lead": 0, "unstaffed": 0}
    if current_unit:
        session_rows = (
            db.session.query(
                Session.id.label("sid"),
                func.coalesce(Session.max_facilitators, 1).label("maxf"),
                func.count(Assignment.id).label("assigned"),
            )
            .join(Module, Module.id == Session.module_id)
            .outerjoin(Assignment, Assignment.session_id == Session.id)
            .filter(Module.unit_id == current_unit.id)
            .group_by(Session.id, Session.max_facilitators)
            .all()
        )

        # Get sessions that need a lead facilitator specifically
        sessions_with_lead = (
            db.session.query(Session.id)
            .join(Module, Module.id == Session.module_id)
            .join(Assignment, Assignment.session_id == Session.id)
            .filter(Module.unit_id == current_unit.id)
            .filter(Assignment.role == 'lead')
            .distinct()
            .all()
        )
        
        sessions_with_lead_ids = {s.id for s in sessions_with_lead}

        total_sessions = len(session_rows)
        fully_staffed  = sum(1 for r in session_rows if r.assigned >= r.maxf and r.maxf > 0)
        unstaffed      = sum(1 for r in session_rows if r.assigned == 0)
        needs_lead     = sum(1 for r in session_rows if r.assigned > 0 and r.sid not in sessions_with_lead_ids)

        stats = {
            "total": total_sessions,
            "fully": fully_staffed,
            "needs_lead": needs_lead,
            "unstaffed": unstaffed,
        }

           # ----- NEW: Facilitator stats -----
    fac_stats = {
        "total_schedule": 0,
        "schedule_assigned": 0, 
        "schedule_conflicts": 0,
        "total_facilitators": 0
    }

    if current_unit:
        # Total facilitators associated with this unit
        total_facilitators = (
            db.session.query(func.count(UnitFacilitator.user_id.distinct()))
            .filter(UnitFacilitator.unit_id == current_unit.id)
            .scalar() or 0
        )
        fac_stats["total_facilitators"] = total_facilitators

        # Total schedule slots (sessions * max_facilitators)
        total_schedule_slots = (
            db.session.query(func.sum(func.coalesce(Session.max_facilitators, 1)))
            .join(Module, Module.id == Session.module_id)
            .filter(Module.unit_id == current_unit.id)
            .scalar() or 0
        )
        fac_stats["total_schedule"] = total_schedule_slots

        # Assigned schedule slots (total assignments)
        assigned_slots = (
            db.session.query(func.count(Assignment.id))
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .filter(Module.unit_id == current_unit.id)
            .scalar() or 0
        )
        fac_stats["schedule_assigned"] = assigned_slots

        # Schedule conflicts: Check for assignment conflicts
        conflicts_count = 0
        
        # Get all assignments for this unit
        assignments_query = (
            db.session.query(Assignment, Session, User)
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .join(User, User.id == Assignment.facilitator_id)
            .filter(Module.unit_id == current_unit.id)
            .all()
        )
        
        # Check for facilitator double-booking conflicts
        facilitator_sessions = {}
        for assignment, session, facilitator in assignments_query:
            facilitator_id = facilitator.id
            if facilitator_id not in facilitator_sessions:
                facilitator_sessions[facilitator_id] = []
            
            facilitator_sessions[facilitator_id].append({
                'assignment_id': assignment.id,
                'session_id': session.id,
                'start_time': session.start_time,
                'end_time': session.end_time,
                'facilitator_name': f"{facilitator.first_name} {facilitator.last_name}".strip()
            })
        
        # Detect overlapping sessions for each facilitator
        for facilitator_id, sessions in facilitator_sessions.items():
            sessions.sort(key=lambda x: x['start_time'])
            
            for i in range(len(sessions)):
                current_session = sessions[i]
                current_start = current_session['start_time']
                current_end = current_session['end_time']
                
                # Check for overlaps with subsequent sessions
                for j in range(i + 1, len(sessions)):
                    next_session = sessions[j]
                    next_start = next_session['start_time']
                    next_end = next_session['end_time']
                    
                    # Check if sessions overlap
                    if current_end > next_start:
                        conflicts_count += 1
                        
        # Check for unavailability conflicts
        unavailability_conflicts = (
            db.session.query(Assignment, Unavailability, Session, User)
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .join(User, User.id == Assignment.facilitator_id)
            .join(Unavailability, 
                  db.and_(
                      Unavailability.user_id == Assignment.facilitator_id,
                      Unavailability.unit_id.is_(None),  # Check GLOBAL unavailability only
                      db.func.date(Session.start_time) == Unavailability.date
                  )
            )
            .filter(
                Module.unit_id == current_unit.id,
                db.or_(
                    Unavailability.is_full_day == True,
                    db.and_(
                        Unavailability.start_time <= db.func.time(Session.start_time),
                        Unavailability.end_time >= db.func.time(Session.end_time)
                    )
                )
            )
            .count()
        )
        
        conflicts_count += unavailability_conflicts
        
        fac_stats["schedule_conflicts"] = conflicts_count

    # ----- Facilitator Setup Progress + Details -----
    fac_progress = {"total": 0, "account": 0, "availability": 0, "skills": 0, "ready": 0}
    facilitators = []

    if current_unit:
        # All facilitator links for this unit
        links = (
            db.session.query(UnitFacilitator, User)
            .join(User, UnitFacilitator.user_id == User.id)
            .filter(UnitFacilitator.unit_id == current_unit.id)
            .order_by(User.last_name.asc().nulls_last(), User.first_name.asc().nulls_last())
            .all()
        )

        fac_progress["total"] = len(links)

        for uf, f in links:
            has_profile = bool(
                (getattr(f, "first_name", None) or getattr(f, "last_name", None))
                or getattr(f, "phone_number", None)
                or getattr(f, "staff_number", None)
                or getattr(f, "avatar_url", None)
            )

            # Check if facilitator has availability configured
            # A facilitator is considered to have "availability set" if they either:
            # 1. Have unavailability entries (specific unavailable days), OR
            # 2. Have marked themselves as "Available All Days" for this unit
            has_unavailability = (
                db.session.query(Unavailability.id)
                .filter(Unavailability.user_id == f.id, Unavailability.unit_id.is_(None))  # Global unavailability
                .limit(1)
                .first()
                is not None
            )
            
            # Check if user has marked themselves as "Available All Days" for this unit
            has_available_all_days = False
            if f.preferences:
                try:
                    import json
                    preferences = json.loads(f.preferences)
                    availability_status = preferences.get('availability_status', {})
                    has_available_all_days = availability_status.get(str(current_unit.id)) == 'available_all_days'
                except:
                    pass
            
            has_avail = has_unavailability or has_available_all_days

            # Check if facilitator has skills configured for THIS UNIT specifically
            has_skills = (
                db.session.query(FacilitatorSkill.id)
                .join(Module, FacilitatorSkill.module_id == Module.id)
                .filter(
                    FacilitatorSkill.facilitator_id == f.id,
                    Module.unit_id == current_unit.id
                )
                .limit(1)
                .first()
                is not None
            )

            is_ready = has_profile and has_avail and has_skills
            fac_progress["account"] += 1 if has_profile else 0
            fac_progress["availability"] += 1 if has_avail else 0
            fac_progress["skills"] += 1 if has_skills else 0
            fac_progress["ready"] += 1 if is_ready else 0

            # Get facilitator skills for THIS UNIT specifically
            facilitator_skills = (
                db.session.query(FacilitatorSkill, Module)
                .join(Module, FacilitatorSkill.module_id == Module.id)
                .filter(
                    FacilitatorSkill.facilitator_id == f.id,
                    Module.unit_id == current_unit.id
                )
                .all()
            )
            
            # Format skills for template
            skills_list = []
            for skill, module in facilitator_skills:
                experience_text = skill.experience_description or "No additional details provided"
                experience_full = experience_text
                if len(experience_text) > 200:
                    experience_text = experience_text[:200] + "..."
                
                skills_list.append({
                    "module": module.module_name,
                    "level": skill.skill_level.value,
                    "experience": experience_text,
                    "experience_full": experience_full
                })

            facilitators.append(
                {
                    "id": f.id,
                    "name": getattr(f, "full_name", None) or f.email,
                    "email": f.email,
                    "phone": getattr(f, "phone_number", None),
                    "staff_number": getattr(f, "staff_number", None),
                    "experience_years": None,         # TODO wire real data later
                    "has_profile": has_profile,
                    "has_availability": has_avail,
                    "has_skills": has_skills,
                    "is_ready": is_ready,
                    "skills": skills_list,
                }
            )

    # ----- Swap & Approvals counts -----
    approvals = {"pending": 0, "approved_this_week": 0, "total": 0}
    approvals_count = 0

    if current_unit:
        RA = aliased(Assignment)
        TA = aliased(Assignment)
        RS = aliased(Session)
        TS = aliased(Session)
        RM = aliased(Module)
        TM = aliased(Module)

        base_q = (
            db.session.query(SwapRequest)
            .join(RA, RA.id == SwapRequest.requester_assignment_id)
            .join(RS, RS.id == RA.session_id)
            .join(RM, RM.id == RS.module_id)
            .join(TA, TA.id == SwapRequest.target_assignment_id)
            .join(TS, TS.id == TA.session_id)
            .join(TM, TM.id == TS.module_id)
            .filter(or_(RM.unit_id == current_unit.id, TM.unit_id == current_unit.id))
        )

        approvals["total"] = base_q.count()
        approvals["pending"] = base_q.filter(SwapRequest.status == SwapStatus.PENDING).count()
        approvals_count = approvals["pending"]

        week_ago = datetime.utcnow() - timedelta(days=7)
        approvals["approved_this_week"] = (
            base_q.filter(
                SwapRequest.status == SwapStatus.APPROVED,
                SwapRequest.reviewed_at != None,
                SwapRequest.reviewed_at >= week_ago,
            ).count()
        )
    pending_requests = []
    if current_unit:
        pending_requests = _pending_swaps_for_unit(current_unit.id)

    # ---- Render ----
    return render_template(
        "unitcoordinator_dashboard.html",
        user=user,
        units=units,
        current_unit=current_unit,
        today=date.today(),
        stats=stats,
        fac_progress=fac_progress,
        facilitators=facilitators,
        fac_stats=fac_stats,
        approvals=approvals,
        approvals_count=approvals_count,
        pending_requests=pending_requests,
    )

@unitcoordinator_bp.route("/admin-dashboard")
@login_required
@role_required(UserRole.ADMIN)
def admin_dashboard():
    """Admin view of Unit Coordinator dashboard - shows all units"""
    from sqlalchemy import func, or_
    from sqlalchemy.orm import aliased
    from datetime import datetime, timedelta, date

    user = get_current_user()

    # Build list of ALL units + session counts (admin can see all units)
    rows = (
        db.session.query(Unit, func.count(Session.id))
        .outerjoin(Module, Module.unit_id == Unit.id)
        .outerjoin(Session, Session.module_id == Module.id)
        .group_by(Unit.id)
        .order_by(Unit.unit_code.asc())
        .all()
    )
    units = []
    for u, cnt in rows:
        setattr(u, "session_count", int(cnt or 0))
        units.append(u)

    # Which unit is selected (via ?unit=) — otherwise first
    selected_id = request.args.get("unit", type=int)
    current_unit = (
        next((u for u in units if u.id == selected_id), None)
        if selected_id
        else (units[0] if units else None)
    )

    # ----- Staffing tiles (safe if no current_unit) -----
    stats = {"total": 0, "fully": 0, "needs_lead": 0, "unstaffed": 0}
    if current_unit:
        session_rows = (
            db.session.query(
                Session.id.label("sid"),
                func.coalesce(Session.max_facilitators, 1).label("maxf"),
                func.count(Assignment.id).label("assigned"),
            )
            .join(Module, Module.id == Session.module_id)
            .outerjoin(Assignment, Assignment.session_id == Session.id)
            .filter(Module.unit_id == current_unit.id)
            .group_by(Session.id, Session.max_facilitators)
            .all()
        )

        # Get sessions that need a lead facilitator specifically
        sessions_with_lead = (
            db.session.query(Session.id)
            .join(Module, Module.id == Session.module_id)
            .join(Assignment, Assignment.session_id == Session.id)
            .filter(Module.unit_id == current_unit.id)
            .filter(Assignment.role == 'lead')
            .distinct()
            .all()
        )
        
        sessions_with_lead_ids = {s.id for s in sessions_with_lead}

        total_sessions = len(session_rows)
        fully_staffed  = sum(1 for r in session_rows if r.assigned >= r.maxf and r.maxf > 0)
        unstaffed      = sum(1 for r in session_rows if r.assigned == 0)
        needs_lead     = sum(1 for r in session_rows if r.assigned > 0 and r.sid not in sessions_with_lead_ids)

        stats = {
            "total": total_sessions,
            "fully": fully_staffed,
            "needs_lead": needs_lead,
            "unstaffed": unstaffed,
        }

    # ----- NEW: Facilitator stats -----
    fac_stats = {
        "total_schedule": 0,
        "schedule_assigned": 0, 
        "schedule_conflicts": 0,
        "total_facilitators": 0
    }

    if current_unit:
        # Total facilitators associated with this unit
        total_facilitators = (
            db.session.query(func.count(UnitFacilitator.user_id.distinct()))
            .filter(UnitFacilitator.unit_id == current_unit.id)
            .scalar() or 0
        )
        fac_stats["total_facilitators"] = total_facilitators

        # Total schedule slots (sessions * max_facilitators)
        total_schedule_slots = (
            db.session.query(func.sum(func.coalesce(Session.max_facilitators, 1)))
            .join(Module, Module.id == Session.module_id)
            .filter(Module.unit_id == current_unit.id)
            .scalar() or 0
        )
        fac_stats["total_schedule"] = total_schedule_slots

        # Assigned schedule slots (total assignments)
        assigned_slots = (
            db.session.query(func.count(Assignment.id))
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .filter(Module.unit_id == current_unit.id)
            .scalar() or 0
        )
        fac_stats["schedule_assigned"] = assigned_slots

        # Schedule conflicts: Check for assignment conflicts
        conflicts_count = 0
        
        # Get all assignments for this unit
        assignments_query = (
            db.session.query(Assignment, Session, User)
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .join(User, User.id == Assignment.facilitator_id)
            .filter(Module.unit_id == current_unit.id)
            .all()
        )
        
        # Check for facilitator double-booking conflicts
        facilitator_sessions = {}
        for assignment, session, facilitator in assignments_query:
            facilitator_id = facilitator.id
            if facilitator_id not in facilitator_sessions:
                facilitator_sessions[facilitator_id] = []
            
            facilitator_sessions[facilitator_id].append({
                'assignment_id': assignment.id,
                'session_id': session.id,
                'start_time': session.start_time,
                'end_time': session.end_time,
                'facilitator_name': f"{facilitator.first_name} {facilitator.last_name}".strip()
            })
        
        # Detect overlapping sessions for each facilitator
        for facilitator_id, sessions in facilitator_sessions.items():
            sessions.sort(key=lambda x: x['start_time'])
            
            for i in range(len(sessions)):
                current_session = sessions[i]
                current_start = current_session['start_time']
                current_end = current_session['end_time']
                
                # Check for overlaps with subsequent sessions
                for j in range(i + 1, len(sessions)):
                    next_session = sessions[j]
                    next_start = next_session['start_time']
                    next_end = next_session['end_time']
                    
                    # Check if sessions overlap
                    if current_end > next_start:
                        conflicts_count += 1
                        
        # Check for unavailability conflicts
        unavailability_conflicts = (
            db.session.query(Assignment, Unavailability, Session, User)
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .join(User, User.id == Assignment.facilitator_id)
            .join(Unavailability, 
                  db.and_(
                      Unavailability.user_id == Assignment.facilitator_id,
                      Unavailability.unit_id.is_(None),  # Check GLOBAL unavailability only
                      db.func.date(Session.start_time) == Unavailability.date
                  )
            )
            .filter(
                Module.unit_id == current_unit.id,
                db.or_(
                    Unavailability.is_full_day == True,
                    db.and_(
                        Unavailability.start_time <= db.func.time(Session.start_time),
                        Unavailability.end_time >= db.func.time(Session.end_time)
                    )
                )
            )
            .count()
        )
        
        conflicts_count += unavailability_conflicts
        
        fac_stats["schedule_conflicts"] = conflicts_count

    # ----- Facilitator Setup Progress + Details -----
    fac_progress = {"total": 0, "account": 0, "availability": 0, "skills": 0, "ready": 0}
    facilitators = []

    if current_unit:
        # All facilitator links for this unit
        links = (
            db.session.query(UnitFacilitator, User)
            .join(User, UnitFacilitator.user_id == User.id)
            .filter(UnitFacilitator.unit_id == current_unit.id)
            .order_by(User.last_name.asc().nulls_last(), User.first_name.asc().nulls_last())
            .all()
        )

        fac_progress["total"] = len(links)

        for uf, f in links:
            has_profile = bool(
                (getattr(f, "first_name", None) or getattr(f, "last_name", None))
                or getattr(f, "phone", None)
                or getattr(f, "staff_number", None)
                or getattr(f, "avatar_url", None)
            )

            # Check if facilitator has availability configured
            # A facilitator is considered to have "availability set" if they either:
            # 1. Have unavailability entries (specific unavailable days), OR
            # 2. Have marked themselves as "Available All Days" for this unit
            has_unavailability = (
                db.session.query(Unavailability.id)
                .filter(Unavailability.user_id == f.id, Unavailability.unit_id.is_(None))  # Global unavailability
                .limit(1)
                .first()
                is not None
            )
            
            # Check if user has marked themselves as "Available All Days" for this unit
            has_available_all_days = False
            if f.preferences:
                try:
                    import json
                    preferences = json.loads(f.preferences)
                    availability_status = preferences.get('availability_status', {})
                    has_available_all_days = availability_status.get(str(current_unit.id)) == 'available_all_days'
                except:
                    pass
            
            has_avail = has_unavailability or has_available_all_days

            # Check if facilitator has skills configured for THIS UNIT specifically
            has_skills = (
                db.session.query(FacilitatorSkill.id)
                .join(Module, FacilitatorSkill.module_id == Module.id)
                .filter(
                    FacilitatorSkill.facilitator_id == f.id,
                    Module.unit_id == current_unit.id
                )
                .limit(1)
                .first()
                is not None
            )

            is_ready = has_profile and has_avail and has_skills
            fac_progress["account"] += 1 if has_profile else 0
            fac_progress["availability"] += 1 if has_avail else 0
            fac_progress["skills"] += 1 if has_skills else 0
            fac_progress["ready"] += 1 if is_ready else 0

            # Get facilitator skills for THIS UNIT specifically
            facilitator_skills = (
                db.session.query(FacilitatorSkill, Module)
                .join(Module, FacilitatorSkill.module_id == Module.id)
                .filter(
                    FacilitatorSkill.facilitator_id == f.id,
                    Module.unit_id == current_unit.id
                )
                .all()
            )
            
            # Format skills for template
            skills_list = []
            for skill, module in facilitator_skills:
                experience_text = skill.experience_description or "No additional details provided"
                experience_full = experience_text
                if len(experience_text) > 200:
                    experience_text = experience_text[:200] + "..."
                
                skills_list.append({
                    "module": module.module_name,
                    "level": skill.skill_level.value,
                    "experience": experience_text,
                    "experience_full": experience_full
                })

            facilitators.append(
                {
                    "id": f.id,
                    "name": getattr(f, "full_name", None) or f.email,
                    "email": f.email,
                    "phone": getattr(f, "phone", None),
                    "staff_number": getattr(f, "staff_number", None),
                    "experience_years": None,         # TODO wire real data later
                    "has_profile": has_profile,
                    "has_availability": has_avail,
                    "has_skills": has_skills,
                    "is_ready": is_ready,
                    "skills": skills_list,
                }
            )

    # ----- Swap & Approvals counts -----
    approvals = {"pending": 0, "approved_this_week": 0, "total": 0}
    approvals_count = 0

    if current_unit:
        RA = aliased(Assignment)
        TA = aliased(Assignment)
        RS = aliased(Session)
        TS = aliased(Session)
        RM = aliased(Module)
        TM = aliased(Module)

        base_q = (
            db.session.query(SwapRequest)
            .join(RA, RA.id == SwapRequest.requester_assignment_id)
            .join(RS, RS.id == RA.session_id)
            .join(RM, RM.id == RS.module_id)
            .join(TA, TA.id == SwapRequest.target_assignment_id)
            .join(TS, TS.id == TA.session_id)
            .join(TM, TM.id == TS.module_id)
            .filter(or_(RM.unit_id == current_unit.id, TM.unit_id == current_unit.id))
        )

        approvals["total"] = base_q.count()
        approvals["pending"] = base_q.filter(SwapRequest.status == SwapStatus.PENDING).count()
        approvals_count = approvals["pending"]

        week_ago = datetime.utcnow() - timedelta(days=7)
        approvals["approved_this_week"] = (
            base_q.filter(
                SwapRequest.status == SwapStatus.APPROVED,
                SwapRequest.reviewed_at != None,
                SwapRequest.reviewed_at >= week_ago,
            ).count()
        )
    pending_requests = []
    if current_unit:
        pending_requests = _pending_swaps_for_unit(current_unit.id)

    # ---- Render ----
    return render_template(
        "unitcoordinator_dashboard.html",
        user=user,
        units=units,
        current_unit=current_unit,
        today=date.today(),
        stats=stats,
        fac_progress=fac_progress,
        facilitators=facilitators,
        fac_stats=fac_stats,
        approvals=approvals,
        approvals_count=approvals_count,
        pending_requests=pending_requests,
        is_admin_view=True,  # Flag to indicate this is admin view
    )

@unitcoordinator_bp.post("/swap_requests/<int:swap_id>/approve")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def approve_swap(swap_id):
    user = get_current_user()
    sr = SwapRequest.query.get_or_404(swap_id)
    if sr.status != SwapStatus.PENDING:
        flash("Request is no longer pending.", "warning")
        unit_id = request.args.get("unit", type=int)
        if user.role == UserRole.ADMIN:
            return redirect(url_for("unitcoordinator.admin_dashboard", unit=unit_id, _anchor="tab-team"))
        else:
            return redirect(url_for("unitcoordinator.dashboard", unit=unit_id, _anchor="tab-team"))
    sr.status = SwapStatus.APPROVED
    sr.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash("Swap approved.", "success")
    unit_id = request.args.get("unit", type=int)
    if user.role == UserRole.ADMIN:
        return redirect(url_for("unitcoordinator.admin_dashboard", unit=unit_id, _anchor="tab-team"))
    else:
        return redirect(url_for("unitcoordinator.dashboard", unit=unit_id, _anchor="tab-team"))

@unitcoordinator_bp.get("/units/<int:unit_id>/unavailability")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def unit_unavailability(unit_id):
    """List all unavailability entries for a unit (UC-owned), optional filters: user_id, start, end (YYYY-MM-DD)."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or access denied"}), 404

    user_id = request.args.get("user_id", type=int)
    start = request.args.get("start")
    end = request.args.get("end")

    q = Unavailability.query.filter(Unavailability.unit_id == unit.id)
    if user_id:
        q = q.filter(Unavailability.user_id == user_id)
    try:
        if start:
            start_d = datetime.strptime(start, "%Y-%m-%d").date()
            q = q.filter(Unavailability.date >= start_d)
        if end:
            end_d = datetime.strptime(end, "%Y-%m-%d").date()
            q = q.filter(Unavailability.date <= end_d)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid date format; use YYYY-MM-DD"}), 400

    rows = (
        q.order_by(Unavailability.date.asc(), Unavailability.start_time.asc().nulls_first()).all()
    )

    def serialize(u):
        owner = User.query.get(u.user_id)
        return {
            "id": u.id,
            "user_id": u.user_id,
            "user": owner.full_name if owner else None,
            "unit_id": u.unit_id,
            "date": u.date.isoformat(),
            "is_full_day": bool(u.is_full_day),
            "start_time": u.start_time.isoformat() if u.start_time else None,
            "end_time": u.end_time.isoformat() if u.end_time else None,
            "recurring_pattern": u.recurring_pattern.value if u.recurring_pattern else None,
            "recurring_interval": u.recurring_interval,
            "recurring_end_date": u.recurring_end_date.isoformat() if u.recurring_end_date else None,
            "reason": u.reason or "",
        }

    return jsonify({"ok": True, "items": [serialize(r) for r in rows]})



@unitcoordinator_bp.post("/swap_requests/<int:swap_id>/reject")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def reject_swap(swap_id):
    user = get_current_user()
    sr = SwapRequest.query.get_or_404(swap_id)
    if sr.status != SwapStatus.PENDING:
        flash("Request is no longer pending.", "warning")
        unit_id = request.args.get("unit", type=int)
        if user.role == UserRole.ADMIN:
            return redirect(url_for("unitcoordinator.admin_dashboard", unit=unit_id, _anchor="tab-team"))
        else:
            return redirect(url_for("unitcoordinator.dashboard", unit=unit_id, _anchor="tab-team"))

    sr.status = SwapStatus.REJECTED
    sr.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash("Swap rejected.", "success")
    unit_id = request.args.get("unit", type=int)
    if user.role == UserRole.ADMIN:
        return redirect(url_for("unitcoordinator.admin_dashboard", unit=unit_id, _anchor="tab-team"))
    else:
        return redirect(url_for("unitcoordinator.dashboard", unit=unit_id, _anchor="tab-team"))


@unitcoordinator_bp.route("/create_unit", methods=["POST"])
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def create_unit():
    user = get_current_user()
    """
    Create OR update a Unit.
    - If unit_id is present and belongs to the current UC -> update
    - Else -> create (guarding duplicates per UC: unit_code+year+semester)
    Accepts dates in either YYYY-MM-DD or DD/MM/YYYY.
    """
    user = get_current_user()

    unit_id = (request.form.get("unit_id") or "").strip()
    unit_code = (request.form.get("unit_code") or "").strip()
    unit_name = (request.form.get("unit_name") or "").strip()
    year_raw = (request.form.get("year") or "").strip()
    semester = (request.form.get("semester") or "").strip()
    description = (request.form.get("description") or "").strip()
    start_raw = (request.form.get("start_date") or "").strip()
    end_raw = (request.form.get("end_date") or "").strip()

    # Basic validation (Step 1 core)
    if not (unit_code and unit_name and year_raw and semester):
        flash("Please complete Unit Information.", "error")
        if user.role == UserRole.ADMIN:
            return redirect(url_for("unitcoordinator.admin_dashboard"))
        else:
            return redirect(url_for("unitcoordinator.dashboard"))

    try:
        year = int(year_raw)
    except ValueError:
        flash("Year must be a number.", "error")
        if user.role == UserRole.ADMIN:
            return redirect(url_for("unitcoordinator.admin_dashboard"))
        else:
            return redirect(url_for("unitcoordinator.dashboard"))

    # Dates (Step 2) – optional but validated if present
    start_date = _parse_date_multi(start_raw)
    end_date = _parse_date_multi(end_raw)
    if start_raw and not start_date:
        flash("Invalid Start Date format.", "error")
        if user.role == UserRole.ADMIN:
            return redirect(url_for("unitcoordinator.admin_dashboard"))
        else:
            return redirect(url_for("unitcoordinator.dashboard"))
    if end_raw and not end_date:
        flash("Invalid End Date format.", "error")
        if user.role == UserRole.ADMIN:
            return redirect(url_for("unitcoordinator.admin_dashboard"))
        else:
            return redirect(url_for("unitcoordinator.dashboard"))
    if start_date and end_date and start_date > end_date:
        flash("Start Date must be before End Date.", "error")
        if user.role == UserRole.ADMIN:
            return redirect(url_for("unitcoordinator.admin_dashboard"))
        else:
            return redirect(url_for("unitcoordinator.dashboard"))

    # UPDATE path when unit_id exists
    if unit_id:
        unit = _get_user_unit_or_404(user, unit_id)
        if not unit:
            flash("Unit not found or you do not have access.", "error")
            if user.role == UserRole.ADMIN:
                return redirect(url_for("unitcoordinator.admin_dashboard"))
            else:
                return redirect(url_for("unitcoordinator.dashboard"))

        # If identity (code/year/semester) changes, guard duplicates
        if (unit.unit_code != unit_code or unit.year != year or unit.semester != semester):
            # Check if user is already a coordinator for another unit with this code/year/semester
            dup = (
                db.session.query(Unit)
                .join(UnitCoordinator, UnitCoordinator.unit_id == Unit.id)
                .filter(
                    Unit.unit_code == unit_code,
                    Unit.year == year,
                    Unit.semester == semester,
                    UnitCoordinator.user_id == user.id,
                    Unit.id != unit.id
                )
                .first()
            )
            if dup:
                flash("Another unit with that code/year/semester already exists.", "error")
                if user.role == UserRole.ADMIN:
                    return redirect(url_for("unitcoordinator.admin_dashboard"))
                else:
                    return redirect(url_for("unitcoordinator.dashboard"))

        # Apply updates
        unit.unit_code = unit_code
        unit.unit_name = unit_name
        unit.year = year
        unit.semester = semester
        unit.description = description or None
        unit.start_date = start_date
        unit.end_date = end_date
        db.session.commit()
        
        # Send setup emails to newly created facilitators (if any were added during edit)
        from flask import session as flask_session
        from email_service import send_welcome_email
        
        print(f"DEBUG (UPDATE): Checking for pending facilitator emails...")
        print(f"DEBUG (UPDATE): Session keys: {list(flask_session.keys())}")
        
        pending_emails = flask_session.pop('pending_facilitator_emails', [])
        print(f"DEBUG (UPDATE): Found {len(pending_emails)} pending emails: {pending_emails}")
        
        if pending_emails:
            for email in pending_emails:
                try:
                    print(f"DEBUG (UPDATE): Attempting to send email to {email}")
                    send_welcome_email(email, user_role=UserRole.FACILITATOR)
                    print(f"✅ Setup email sent to {email}")
                except Exception as e:
                    print(f"❌ Failed to send setup email to {email}: {e}")
        else:
            print(f"DEBUG (UPDATE): No pending emails found in session")

        flash("Unit updated successfully!", "success")
        if user.role == UserRole.ADMIN:
            return redirect(url_for("unitcoordinator.admin_dashboard"))
        else:
            return redirect(url_for("unitcoordinator.dashboard"))

    # CREATE path (no unit_id)
    # Per-UC uniqueness - check if user is already a coordinator for a unit with this code/year/semester
    existing = (
        db.session.query(Unit)
        .join(UnitCoordinator, UnitCoordinator.unit_id == Unit.id)
        .filter(
            Unit.unit_code == unit_code,
            Unit.year == year,
            Unit.semester == semester,
            UnitCoordinator.user_id == user.id
        )
        .first()
    )
    if existing:
        flash("You already coordinate a unit with that code/year/semester.", "error")
        if user.role == UserRole.ADMIN:
            return redirect(url_for("unitcoordinator.admin_dashboard"))
        else:
            return redirect(url_for("unitcoordinator.dashboard"))

    new_unit = Unit(
        unit_code=unit_code,
        unit_name=unit_name,
        year=year,
        semester=semester,
        description=description or None,
        start_date=start_date,
        end_date=end_date,
        created_by=user.id,
    )
    db.session.add(new_unit)
    db.session.flush()  # Flush to get the unit ID
    
    # Create UnitCoordinator entry for the creator
    unit_coordinator = UnitCoordinator(
        unit_id=new_unit.id,
        user_id=user.id
    )
    db.session.add(unit_coordinator)
    
    # Handle additional coordinators
    additional_coordinators_str = request.form.get("additional_coordinators", "").strip()
    additional_coordinators_to_notify = []
    if additional_coordinators_str:
        try:
            import json
            coordinator_ids = json.loads(additional_coordinators_str)
            if isinstance(coordinator_ids, list):
                for coordinator_id in coordinator_ids:
                    try:
                        coordinator_id = int(coordinator_id)
                        # Verify the user exists and has appropriate role
                        coordinator_user = User.query.filter_by(id=coordinator_id).first()
                        if coordinator_user and coordinator_user.role in [UserRole.UNIT_COORDINATOR, UserRole.ADMIN]:
                            # Check if already added (shouldn't happen, but safety check)
                            existing = UnitCoordinator.query.filter_by(
                                unit_id=new_unit.id,
                                user_id=coordinator_id
                            ).first()
                            if not existing:
                                additional_uc = UnitCoordinator(
                                    unit_id=new_unit.id,
                                    user_id=coordinator_id
                                )
                                additional_coordinators_to_notify.append(coordinator_user)
                                db.session.add(additional_uc)
                    except (ValueError, TypeError):
                        continue  # Skip invalid IDs
        except (json.JSONDecodeError, TypeError):
            pass  # If JSON parsing fails, just continue without additional coordinators
    
    db.session.commit()

    # Create default module for new unit
    # Send email notifications to additional coordinators
    from email_service import send_coordinator_added_email
    base_url = os.environ.get('BASE_URL', 'http://localhost:5000')
    for coordinator_user in additional_coordinators_to_notify:
        send_coordinator_added_email(
            recipient_email=coordinator_user.email,
            recipient_name=coordinator_user.full_name,
            unit_code=new_unit.unit_code,
            unit_name=new_unit.unit_name,
            base_url=base_url
        )
    _get_or_create_default_module(new_unit)
    
    # Send setup emails to newly created facilitators
    from flask import session as flask_session
    from email_service import send_welcome_email
    
    print(f"DEBUG: Checking for pending facilitator emails...")
    print(f"DEBUG: Session keys: {list(flask_session.keys())}")
    
    pending_emails = flask_session.pop('pending_facilitator_emails', [])
    print(f"DEBUG: Found {len(pending_emails)} pending emails: {pending_emails}")
    
    if pending_emails:
        for email in pending_emails:
            try:
                print(f"DEBUG: Attempting to send email to {email}")
                send_welcome_email(email, user_role=UserRole.FACILITATOR)
                print(f"✅ Setup email sent to {email}")
            except Exception as e:
                print(f"❌ Failed to send setup email to {email}: {e}")
    else:
        print(f"DEBUG: No pending emails found in session")

    flash("Unit created successfully!", "success")
    if user.role == UserRole.ADMIN:
        return redirect(url_for("unitcoordinator.admin_dashboard"))
    else:
        return redirect(url_for("unitcoordinator.dashboard"))


@unitcoordinator_bp.route('/facilitators/<int:facilitator_id>/profile')
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def facilitator_profile(facilitator_id):
    """View a specific facilitator's profile"""
    from datetime import date, datetime
    
    current_user = get_current_user()
    
    # Get facilitator user by ID (facilitator_id is actually a User ID)
    facilitator_user = User.query.get_or_404(facilitator_id)
    
    # Get all units this facilitator is assigned to
    # (Check if they have UnitFacilitator records instead of checking role,
    # since users can have dual roles like ADMIN+facilitator or UC+facilitator)
    unit_facilitator_records = (
        db.session.query(Unit, UnitFacilitator)
        .join(UnitFacilitator, UnitFacilitator.unit_id == Unit.id)
        .filter(UnitFacilitator.user_id == facilitator_user.id)
        .order_by(Unit.start_date.desc().nulls_last())
        .all()
    )
    
    today = date.today()
    current_units = []
    past_units = []
    
    total_sessions = 0
    total_hours = 0.0
    
    for unit, _ in unit_facilitator_records:
        # Get assignments for this facilitator in this unit
        assignments = (
            db.session.query(Assignment, Session)
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .filter(
                Module.unit_id == unit.id,
                Assignment.facilitator_id == facilitator_user.id
            )
            .all()
        )
        
        # Calculate unit stats
        completed_sessions = sum(1 for _, s in assignments if s.start_time < datetime.now())
        unit_total_hours = sum(
            (s.end_time - s.start_time).total_seconds() / 3600.0
            for _, s in assignments
        )
        
        # Get unique session types
        session_types = list(set(s.session_type for _, s in assignments if s.session_type))
        
        # Calculate average hours per week
        avg_hours_per_week = 0.0
        if unit.start_date and unit.end_date:
            weeks = max(1, (unit.end_date - unit.start_date).days / 7)
            avg_hours_per_week = round(unit_total_hours / weeks, 1) if weeks > 0 else 0.0
        
        unit_data = {
            'id': unit.id,
            'code': unit.unit_code,
            'name': unit.unit_name,
            'start_date': unit.start_date,
            'end_date': unit.end_date,
            'semester': unit.semester,
            'year': unit.year,
            'completed_sessions': completed_sessions,
            'total_hours': round(unit_total_hours, 1),
            'avg_hours_per_week': avg_hours_per_week,
            'session_types': session_types
        }
        
        # Determine if unit is current or past
        is_current = False
        if unit.end_date:
            is_current = today <= unit.end_date
        elif unit.start_date:
            is_current = unit.start_date <= today
        else:
            is_current = len(assignments) > 0
        
        if is_current:
            current_units.append(unit_data)
        else:
            past_units.append(unit_data)
        
        total_sessions += len(assignments)
        total_hours += unit_total_hours
    
    # Calculate years of experience (based on earliest unit start date)
    years_experience = 0
    if unit_facilitator_records:
        earliest_start = min(
            (u.start_date for u, _ in unit_facilitator_records if u.start_date),
            default=None
        )
        if earliest_start:
            years_experience = (today - earliest_start).days / 365.25
            years_experience = round(years_experience, 1)
    
    # Build facilitator_info object for template
    facilitator_info = {
        'current_units': current_units,
        'past_units': past_units,
        'career_summary': {
            'total_units': len(unit_facilitator_records),
            'sessions_facilitated': total_sessions,
            'total_hours': round(total_hours, 1),
            'years_experience': years_experience
        }
    }
    
    return render_template('facilitator_profile.html', 
                         user=facilitator_user,
                         facilitator_info=facilitator_info,
                         current_user=current_user)

@unitcoordinator_bp.route('/units/<int:unit_id>/facilitators/<email>/edit-view')
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def edit_facilitator_view(unit_id: int, email: str):
    """
    UC can edit facilitator's availability and skills using the facilitator's own interface.
    This renders the facilitator dashboard but with UC context.
    """
    current_user = get_current_user()
    unit = _get_user_unit_or_404(current_user, unit_id)
    
    if not unit:
        flash('Unit not found or unauthorized', 'error')
        return redirect(url_for('unitcoordinator.dashboard'))
    
    # Find the facilitator by email
    facilitator_user = User.query.filter_by(email=email).first()
    if not facilitator_user:
        flash('Facilitator not found', 'error')
        return redirect(url_for('unitcoordinator.manage_facilitators', unit_id=unit_id))
    
    # Verify facilitator is linked to this unit
    link = UnitFacilitator.query.filter_by(unit_id=unit.id, user_id=facilitator_user.id).first()
    if not link:
        flash('Facilitator not linked to this unit', 'error')
        return redirect(url_for('unitcoordinator.manage_facilitators', unit_id=unit_id))
    
    # Get facilitator's data for this specific unit
    from models import FacilitatorSkill, Unavailability
    
    # Get skills for this unit's modules
    skills = (
        db.session.query(FacilitatorSkill, Module)
        .join(Module, FacilitatorSkill.module_id == Module.id)
        .filter(
            Module.unit_id == unit.id,
            FacilitatorSkill.facilitator_id == facilitator_user.id
        )
        .all()
    )
    
    skills_count = len(skills)
    availability_configured = link.availability_configured
    
    # Get ALL units this facilitator is assigned to (for unit switcher)
    all_facilitator_units = (
        db.session.query(Unit)
        .join(UnitFacilitator, UnitFacilitator.unit_id == Unit.id)
        .filter(UnitFacilitator.user_id == facilitator_user.id)
        .order_by(Unit.start_date.desc().nulls_last())
        .all()
    )
    
    # Build units_data for ALL facilitator's units (for unit switcher dropdown)
    from datetime import date
    today = date.today()
    units_data = []
    
    for u in all_facilitator_units:
        # Determine if unit is active or completed
        is_active = False
        if u.end_date:
            is_active = today <= u.end_date
        elif u.start_date:
            is_active = u.start_date <= today
        else:
            is_active = True  # Default to active if no dates
        
        # Check availability and skills for this unit
        unit_link = UnitFacilitator.query.filter_by(unit_id=u.id, user_id=facilitator_user.id).first()
        unit_availability_configured = unit_link.availability_configured if unit_link else False
        
        unit_skills_count = (
            db.session.query(FacilitatorSkill)
            .join(Module, FacilitatorSkill.module_id == Module.id)
            .filter(
                Module.unit_id == u.id,
                FacilitatorSkill.facilitator_id == facilitator_user.id
            )
            .count()
        )
        
        unit_data = {
            'id': u.id,
            'code': u.unit_code,
            'name': u.unit_name,
            'semester': u.semester,
            'year': u.year,
            'start_date': u.start_date.isoformat() if u.start_date else None,
            'end_date': u.end_date.isoformat() if u.end_date else None,
            'status': 'active' if is_active else 'completed',  # Required for dropdown filter
            'schedule_status': u.schedule_status.value if u.schedule_status else 'draft',
            'availability_configured': unit_availability_configured,  # For nav tab warning
            'skills_configured': unit_skills_count > 0,  # For nav tab warning
            'kpis': {
                'this_week_hours': 0,
                'active_sessions': 0,
                'remaining_hours': 0,
                'total_hours': 0,
                'upcoming_sessions': 0,
                'total_sessions': 0,
                'completed_sessions': 0
            },
            'upcoming_sessions': [],
            'past_sessions': []
        }
        units_data.append(unit_data)
    
    # Find current unit in units_data or use first one
    current_unit_data = next((u for u in units_data if u['id'] == unit.id), units_data[0] if units_data else None)
    
    # Render the facilitator dashboard template with UC editing context
    return render_template('facilitator_dashboard.html',
                         unit=unit,
                         user=facilitator_user,  # The facilitator being edited
                         units=all_facilitator_units,  # ALL units the facilitator is in (for switcher)
                         units_data=units_data,  # For JavaScript
                         current_unit=unit,  # The current unit being edited
                         current_unit_dict=current_unit_data,  # For template KPIs
                         availability_configured=availability_configured,
                         skills_configured=skills_count > 0,
                         is_uc_editing=True,  # Flag to show "Back to UC View" button
                         uc_user=current_user,  # The actual UC user
                         uc_unit_id=unit_id,  # For back navigation
                         has_no_units=False,  # UC is editing, so there's at least one unit
                         today_sessions_count=0)  # No sessions to show in UC editing mode

@unitcoordinator_bp.route('/facilitators/<int:facilitator_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def edit_facilitator_profile(facilitator_id):
    """Edit a facilitator's profile"""
    current_user = get_current_user()
    
    # Get facilitator user by ID (facilitator_id is actually a User ID)
    facilitator_user = User.query.get_or_404(facilitator_id)
    
    # Verify the user has facilitator assignments (supports dual roles)
    has_facilitator_assignments = UnitFacilitator.query.filter_by(user_id=facilitator_id).first() is not None
    if not has_facilitator_assignments:
        flash('User is not assigned as a facilitator to any units', 'error')
        return redirect(url_for('unitcoordinator.dashboard'))
    
    if request.method == 'POST':
        try:
            # Update user data
            facilitator_user.first_name = request.form.get('first_name', '').strip()
            facilitator_user.last_name = request.form.get('last_name', '').strip()
            facilitator_user.phone_number = request.form.get('phone', '').strip()
            facilitator_user.staff_number = request.form.get('staff_number', '').strip()
            
            db.session.commit()
            flash('Facilitator profile updated successfully!', 'success')
            return redirect(url_for('unitcoordinator.facilitator_profile', facilitator_id=facilitator_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating profile: {str(e)}', 'error')
    
    return render_template('edit_facilitator_profile.html', 
                         facilitator_user=facilitator_user)



@unitcoordinator_bp.post("/create_or_get_draft")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def create_or_get_draft():
    user = get_current_user()
    
    # CHECK FOR CANCEL ACTION FIRST
    action = request.form.get('action', '').strip()
    if action == 'cancel_draft':
        unit_id = request.form.get('unit_id', '').strip()
        if unit_id:
            try:
                unit_id = int(unit_id)
                unit = _get_user_unit_or_404(user, unit_id)
                if unit:
                    # Get all modules for this unit
                    modules = Module.query.filter_by(unit_id=unit.id).all()
                    module_ids = [m.id for m in modules]
                    
                    # Delete all assignments first (foreign key constraint)
                    if module_ids:
                        Assignment.query.filter(
                            Assignment.session_id.in_(
                                db.session.query(Session.id).filter(
                                    Session.module_id.in_(module_ids)
                                )
                            )
                        ).delete(synchronize_session=False)
                    
                    # Delete all sessions for this unit
                    if module_ids:
                        Session.query.filter(
                            Session.module_id.in_(module_ids)
                        ).delete(synchronize_session=False)
                    
                    # Delete all modules for this unit
                    Module.query.filter_by(unit_id=unit.id).delete(synchronize_session=False)
                    
                    # Delete unit facilitator links
                    UnitFacilitator.query.filter_by(unit_id=unit.id).delete(synchronize_session=False)
                    
                    # Delete unit venue links
                    UnitVenue.query.filter_by(unit_id=unit.id).delete(synchronize_session=False)
                    
                    # Delete the unit itself
                    db.session.delete(unit)
                    db.session.commit()
                    
                    logger.info(f"Cancelled and deleted draft unit {unit_id} for user {user.id}")
                    return jsonify({"ok": True, "message": "Draft cancelled successfully"})
                else:
                    return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
            except ValueError:
                return jsonify({"ok": False, "error": "Invalid unit ID"}), 400
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error cancelling draft: {e}")
                return jsonify({"ok": False, "error": "Failed to cancel draft"}), 500
        
        return jsonify({"ok": True, "message": "No unit to cancel"})

    # EXISTING CREATE/GET LOGIC
    unit_code = (request.form.get("unit_code") or "").strip()
    unit_name = (request.form.get("unit_name") or "").strip()
    year_raw = (request.form.get("year") or "").strip()
    semester = (request.form.get("semester") or "").strip()
    start_date = (request.form.get("start_date") or "").strip()
    end_date = (request.form.get("end_date") or "").strip()

    if not (unit_code and unit_name and year_raw and semester):
        return jsonify({"ok": False, "error": "Missing required fields"}), 400

    try:
        year = int(year_raw)
    except ValueError:
        return jsonify({"ok": False, "error": "Year must be an integer"}), 400

    parsed_start = _parse_date_multi(start_date)
    parsed_end = _parse_date_multi(end_date)
    if parsed_start and parsed_end and parsed_start > parsed_end:
        return jsonify({"ok": False, "error": "Start date must be before end date"}), 400

    # Check if user is already a coordinator for a unit with this code/year/semester
    unit = (
        db.session.query(Unit)
        .join(UnitCoordinator, UnitCoordinator.unit_id == Unit.id)
        .filter(
            Unit.unit_code == unit_code,
            Unit.year == year,
            Unit.semester == semester,
            UnitCoordinator.user_id == user.id
        )
        .first()
    )
    if not unit:
        unit = Unit(
            unit_code=unit_code,
            unit_name=unit_name,
            year=year,
            semester=semester,
            start_date=parsed_start,
            end_date=parsed_end,
            created_by=user.id,
        )
        db.session.add(unit)
        db.session.flush()  # Flush to get the unit ID
        
        # Create UnitCoordinator entry for the creator
        unit_coordinator = UnitCoordinator(
            unit_id=unit.id,
            user_id=user.id
        )
        db.session.add(unit_coordinator)
        db.session.commit()
        # Create default module for new unit
        _get_or_create_default_module(unit)

    return jsonify({"ok": True, "unit_id": unit.id})


@unitcoordinator_bp.get("/csv-template")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def download_setup_csv_template():
    """
    Returns a CSV with one column:
      - facilitator_email
    """
    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=CSV_HEADERS, extrasaction="ignore")
    writer.writeheader()

    mem = BytesIO(sio.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name="facilitators_template.csv",
    )


# --------------------------------------------------------------------------
# Upload Facilitators CSV
# --------------------------------------------------------------------------
@unitcoordinator_bp.post("/upload-setup-csv")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def upload_setup_csv():
    """
    Accepts a 1-column CSV:
      - facilitator_email

    For each row:
      - If facilitator_email is present: ensure a User(role=FACILITATOR) exists; link to the Unit
    Returns counts + errors.
    """
    user = get_current_user()

    unit_id = request.form.get("unit_id")
    if not unit_id:
        return jsonify({"ok": False, "error": "Missing unit_id"}), 400

    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found"}), 404

    file = request.files.get("setup_csv")
    if not file:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    try:
        text = file.read().decode("utf-8", errors="replace")
        reader = csv.DictReader(StringIO(text))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed to read CSV: {e}"}), 400

    # Validate headers
    fns = [fn.strip().lower() for fn in (reader.fieldnames or [])]
    required = {"facilitator_email"}
    if not required.issubset(set(fns)):
        return jsonify({
            "ok": False,
            "error": "CSV must include header: facilitator_email"
        }), 400

    # Process CSV rows
    facilitators_data = []
    errors = []

    for idx, row in enumerate(reader, start=2):  # start=2 because header is row 1
        email = (row.get("facilitator_email") or "").strip().lower()
        if not email:
            continue
        if not _valid_email(email):
            errors.append(f"Row {idx}: invalid facilitator_email '{email}'")
            continue
        
        # Check if facilitator user exists
        user_obj = User.query.filter_by(email=email).first()
        
        facilitators_data.append({
            "email": email,
            "exists": user_obj is not None,
            "name": user_obj.full_name if user_obj else "",
            "row": idx
        })

    # Return review data
    return jsonify({
        "ok": True,
        "facilitators": facilitators_data,
        "errors": errors[:20],  # show up to 20 issues
        "unit_id": unit_id
    }), 200


@unitcoordinator_bp.post("/confirm-facilitators")
def confirm_facilitators():
    """
    Confirm and create facilitator accounts from review step
    """
    user = get_current_user()
    
    unit_id = request.form.get("unit_id")
    if not unit_id:
        return jsonify({"ok": False, "error": "Missing unit_id"}), 400

    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found"}), 404

    # Get facilitator emails from form
    facilitator_emails = request.form.getlist("facilitator_emails")
    
    created_users = 0
    linked_facilitators = 0
    errors = []
    new_user_emails = []  # Track new users to send setup emails
    added_to_unit_emails = []  # Track existing users added to this unit
    
    for email in facilitator_emails:
        email = email.strip().lower()
        if not email or not _valid_email(email):
            continue
            
        # Ensure facilitator user exists
        user_obj = User.query.filter_by(email=email).first()
        is_new_user = False
        
        if not user_obj:
            # Create user with only email and role - no password yet
            user_obj = User(email=email, role=UserRole.FACILITATOR)
            db.session.add(user_obj)
            db.session.flush()  # <-- ensure user_obj.id is available
            created_users += 1
            new_user_emails.append(email)  # Track for email sending
            is_new_user = True
        # If user exists with UC or Admin role, keep their role intact
        # They can perform facilitator duties without being downgraded

        # Ensure link to unit exists
        link = UnitFacilitator.query.filter_by(unit_id=unit.id, user_id=user_obj.id).first()
        if not link:
            link = UnitFacilitator(unit_id=unit.id, user_id=user_obj.id)
            db.session.add(link)
            linked_facilitators += 1
            
            # Track existing users being added to this unit
            if not is_new_user:
                # Check if user needs setup
                user_needs_setup = not (user_obj.password_hash and user_obj.first_name and user_obj.last_name)
                added_to_unit_emails.append({
                    'email': email,
                    'name': user_obj.first_name or 'there',
                    'needs_setup': user_needs_setup
                })
    
    try:
        db.session.commit()
        
        # Send setup emails to newly created facilitators immediately
        from email_service import send_welcome_email, send_unit_addition_email
        
        print(f"DEBUG: Created {created_users} new users")
        print(f"DEBUG: New user emails to send to: {new_user_emails}")
        print(f"DEBUG: Existing users added to unit: {added_to_unit_emails}")
        
        emails_sent = 0
        
        # Send welcome emails to new users
        if new_user_emails:
            for email in new_user_emails:
                try:
                    print(f"DEBUG: Attempting to send welcome email to {email}")
                    send_welcome_email(email, user_role=UserRole.FACILITATOR)
                    print(f"✅ Setup email sent to {email}")
                    emails_sent += 1
                except Exception as e:
                    print(f"❌ Failed to send setup email to {email}: {e}")
        
        # Send unit addition emails to existing users
        if added_to_unit_emails:
            for user_info in added_to_unit_emails:
                try:
                    print(f"DEBUG: Attempting to send unit addition email to {user_info['email']} (needs_setup={user_info.get('needs_setup', False)})")
                    send_unit_addition_email(
                        user_info['email'],
                        user_info['name'],
                        unit.unit_code,
                        unit.unit_name,
                        user_needs_setup=user_info.get('needs_setup', False)
                    )
                    print(f"✅ Unit addition email sent to {user_info['email']}")
                    emails_sent += 1
                except Exception as e:
                    print(f"❌ Failed to send unit addition email to {user_info['email']}: {e}")
        
        return jsonify({
            "ok": True,
            "created_users": created_users,
            "linked_facilitators": linked_facilitators,
            "emails_sent": emails_sent,
            "errors": errors[:20],  # show up to 20 issues
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to create facilitators: {e}"}), 500


@unitcoordinator_bp.post("/units/<int:unit_id>/add-facilitator")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def add_single_facilitator(unit_id: int):
    """
    Add a single facilitator to a unit by email address.
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found"}), 403
    
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    
    if not email or not _valid_email(email):
        return jsonify({"ok": False, "error": "Invalid email address"}), 400
    
    # Check if facilitator user exists
    facilitator = User.query.filter_by(email=email).first()
    is_new_user = False
    
    if not facilitator:
        # Create new facilitator user
        facilitator = User(email=email, role=UserRole.FACILITATOR)
        db.session.add(facilitator)
        db.session.flush()
        is_new_user = True
    
    # Check if already linked to this unit
    existing_link = UnitFacilitator.query.filter_by(
        unit_id=unit.id,
        user_id=facilitator.id
    ).first()
    
    if existing_link:
        return jsonify({"ok": False, "error": "This facilitator is already added to this unit"}), 400
    
    # Create link
    link = UnitFacilitator(unit_id=unit.id, user_id=facilitator.id)
    db.session.add(link)
    
    try:
        db.session.commit()
        
        # Send appropriate email
        from email_service import send_welcome_email, send_unit_addition_email
        
        if is_new_user:
            # Send welcome email to new user
            try:
                send_welcome_email(email, user_role=UserRole.FACILITATOR)
                print(f"✅ Welcome email sent to {email}")
            except Exception as e:
                print(f"❌ Failed to send welcome email to {email}: {e}")
        else:
            # Send unit addition email to existing user
            # Check if user has completed setup (has password and name)
            user_needs_setup = not (facilitator.password_hash and facilitator.first_name and facilitator.last_name)
            try:
                send_unit_addition_email(
                    email,
                    facilitator.first_name or 'there',
                    unit.unit_code,
                    unit.unit_name,
                    user_needs_setup=user_needs_setup
                )
                print(f"✅ Unit addition email sent to {email} (needs_setup={user_needs_setup})")
            except Exception as e:
                print(f"❌ Failed to send unit addition email to {email}: {e}")
        
        message = f"Facilitator {email} added successfully and notified via email"
        if is_new_user:
            message += " (new account created)"
        
        # Warn if schedule is already published
        warning = None
        if hasattr(unit, 'schedule_status') and unit.schedule_status and unit.schedule_status.value == 'published':
            warning = "Note: This unit's schedule is already published. You may need to manually assign this facilitator to sessions."
        
        return jsonify({
            "ok": True,
            "message": message,
            "warning": warning,
            "is_new_user": is_new_user
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to add facilitator: {str(e)}"}), 500


@unitcoordinator_bp.post("/units/<int:unit_id>/facilitators/<int:facilitator_id>/resend-setup-email")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def resend_setup_email(unit_id: int, facilitator_id: int):
    """
    Resend the account setup email to a facilitator who hasn't completed setup.
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found"}), 403
    
    # Get the facilitator user
    facilitator = User.query.get(facilitator_id)
    if not facilitator:
        return jsonify({"ok": False, "error": "Facilitator not found"}), 404
    
    # Check if facilitator is linked to this unit
    unit_fac = UnitFacilitator.query.filter_by(unit_id=unit.id, user_id=facilitator_id).first()
    if not unit_fac:
        return jsonify({"ok": False, "error": "Facilitator not linked to this unit"}), 403
    
    # Check if account setup is already complete
    if facilitator.first_name and facilitator.last_name and facilitator.password_hash:
        return jsonify({"ok": False, "error": "This facilitator has already completed account setup"}), 400
    
    # Send the setup email
    from email_service import send_welcome_email
    try:
        send_welcome_email(facilitator.email, user_role=facilitator.role)
        print(f"✅ Resent setup email to {facilitator.email}")
        return jsonify({
            "ok": True,
            "message": f"Setup email resent to {facilitator.email}"
        }), 200
    except Exception as e:
        print(f"❌ Failed to resend setup email to {facilitator.email}: {e}")
        return jsonify({"ok": False, "error": f"Failed to send email: {str(e)}"}), 500


@unitcoordinator_bp.post("/units/<int:unit_id>/facilitators/<int:facilitator_id>/remind-setup")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def remind_setup(unit_id: int, facilitator_id: int):
    """
    Send a reminder email to a facilitator to complete their availability and skills for a unit.
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found"}), 403
    
    # Get the facilitator user
    facilitator = User.query.get(facilitator_id)
    if not facilitator:
        return jsonify({"ok": False, "error": "Facilitator not found"}), 404
    
    # Check if facilitator is linked to this unit
    unit_fac = UnitFacilitator.query.filter_by(unit_id=unit.id, user_id=facilitator_id).first()
    if not unit_fac:
        return jsonify({"ok": False, "error": "Facilitator not linked to this unit"}), 403
    
    # Send reminder email
    from email_service import send_reminder_email
    try:
        send_reminder_email(
            facilitator.email,
            facilitator.first_name or "there",
            unit.unit_code,
            unit.unit_name
        )
        print(f"✅ Sent reminder to {facilitator.email} for unit {unit.unit_code}")
        return jsonify({
            "ok": True,
            "message": f"Reminder sent to {facilitator.email}"
        }), 200
    except Exception as e:
        print(f"❌ Failed to send reminder to {facilitator.email}: {e}")
        return jsonify({"ok": False, "error": f"Failed to send reminder: {str(e)}"}), 500


@unitcoordinator_bp.delete("/units/<int:unit_id>/facilitators")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def remove_unit_facilitators(unit_id: int):
    """
    Remove all facilitator links for a unit.
    This effectively "removes" the CSV data by unlinking all facilitators from the unit.
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found"}), 403

    try:
        # Count facilitators before removal
        facilitator_count = UnitFacilitator.query.filter_by(unit_id=unit.id).count()
        
        # Remove all facilitator links for this unit
        UnitFacilitator.query.filter_by(unit_id=unit.id).delete()
        
        db.session.commit()
        
        return jsonify({
            "ok": True,
            "removed_facilitators": facilitator_count,
            "message": f"Removed {facilitator_count} facilitator(s) from unit"
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to remove facilitators: {str(e)}"}), 500


@unitcoordinator_bp.delete("/units/<int:unit_id>/facilitators/<email>")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def remove_individual_facilitator(unit_id: int, email: str):
    """
    Remove a specific facilitator from a unit by email.
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found"}), 404

    try:
        # Find the user by email (support dual roles)
        facilitator_user = User.query.filter_by(email=email).first()
        if not facilitator_user:
            return jsonify({"ok": False, "error": "Facilitator not found"}), 404

        # Find the facilitator link
        link = UnitFacilitator.query.filter_by(unit_id=unit.id, user_id=facilitator_user.id).first()
        if not link:
            return jsonify({"ok": False, "error": "Facilitator not linked to this unit"}), 404

        # SAFETY CHECK: Prevent removal if schedule is published and unit is still active
        from models import ScheduleStatus
        from datetime import date
        
        if unit.schedule_status == ScheduleStatus.PUBLISHED:
            # Check if unit is still ongoing (not finished yet)
            today = date.today()
            unit_is_active = unit.end_date is None or unit.end_date >= today
            
            if unit_is_active:
                # Check if facilitator has any assignments
                from models import Assignment, Session, Module
                assignments = (
                    db.session.query(Assignment, Session, Module)
                    .join(Session, Assignment.session_id == Session.id)
                    .join(Module, Session.module_id == Module.id)
                    .filter(
                        Module.unit_id == unit.id,
                        Assignment.facilitator_id == facilitator_user.id,
                        Session.date >= today  # Only future/today sessions
                    )
                    .order_by(Session.date, Session.start_time)
                    .all()
                )
                
                if assignments:
                    # Build list of remaining sessions
                    remaining_sessions = []
                    for assignment, session, module in assignments[:5]:  # Show first 5
                        session_info = f"{module.code} - {session.date.strftime('%d/%m/%Y')} {session.start_time.strftime('%H:%M')}"
                        remaining_sessions.append(session_info)
                    
                    more_count = len(assignments) - 5
                    sessions_list = "\n".join(remaining_sessions)
                    if more_count > 0:
                        sessions_list += f"\n... and {more_count} more"
                    
                    return jsonify({
                        "ok": False, 
                        "error": f"Cannot remove facilitator: Schedule is published and unit is still active.\n\nThey have {len(assignments)} upcoming session(s):\n{sessions_list}\n\nYou can only remove facilitators after all their sessions have finished (after {unit.end_date.strftime('%d/%m/%Y') if unit.end_date else 'the unit ends'}).",
                        "remaining_sessions": len(assignments)
                    }), 400

        # Clean up all related data for this facilitator in this unit
        # IMPORTANT: Delete in correct order to avoid foreign key constraint errors
        
        # 1. First, get assignment IDs (we'll need these for swap requests)
        from models import Assignment, Session, Module
        assignment_ids = [
            a.id for a in db.session.query(Assignment)
            .join(Session, Assignment.session_id == Session.id)
            .join(Module, Session.module_id == Module.id)
            .filter(
                Module.unit_id == unit.id,
                Assignment.facilitator_id == facilitator_user.id
            )
            .all()
        ]
        
        # 2. Delete swap requests FIRST (they reference assignments)
        from models import SwapRequest
        # Note: This will cancel any pending swaps involving this facilitator
        # Use a more efficient join query to find swap requests for this unit
        swap_ids_requester = [
            sr.id for sr in db.session.query(SwapRequest)
            .join(Assignment, SwapRequest.requester_assignment_id == Assignment.id)
            .join(Session, Assignment.session_id == Session.id)
            .join(Module, Session.module_id == Module.id)
            .filter(
                Module.unit_id == unit.id,
                db.or_(
                    SwapRequest.requester_id == facilitator_user.id,
                    SwapRequest.target_id == facilitator_user.id
                )
            )
            .all()
        ]
        
        swap_ids_target = [
            sr.id for sr in db.session.query(SwapRequest)
            .join(Assignment, SwapRequest.target_assignment_id == Assignment.id)
            .join(Session, Assignment.session_id == Session.id)
            .join(Module, Session.module_id == Module.id)
            .filter(
                Module.unit_id == unit.id,
                db.or_(
                    SwapRequest.requester_id == facilitator_user.id,
                    SwapRequest.target_id == facilitator_user.id
                )
            )
            .all()
        ]
        
        # Combine and deduplicate
        swap_ids = list(set(swap_ids_requester + swap_ids_target))
        swap_count = len(swap_ids)
        
        if swap_ids:
            SwapRequest.query.filter(SwapRequest.id.in_(swap_ids)).delete(synchronize_session='fetch')
        
        # 3. Now delete session assignments (safe now that swap requests are gone)
        if assignment_ids:
            Assignment.query.filter(Assignment.id.in_(assignment_ids)).delete(synchronize_session='fetch')
        
        # 4. Notifications are user-level (not unit-specific), so we don't delete them here
        # The facilitator keeps their general notifications
        
        # 5. Delete unavailability records
        from models import Unavailability
        # Use raw SQL to avoid ORM relationship issues
        db.session.execute(
            db.text("DELETE FROM unavailability WHERE user_id = :user_id AND unit_id = :unit_id"),
            {"user_id": facilitator_user.id, "unit_id": unit.id}
        )
        
        # 6. Delete skills
        from models import FacilitatorSkill
        skill_ids = [
            s.id for s in db.session.query(FacilitatorSkill)
            .join(Module, FacilitatorSkill.module_id == Module.id)
            .filter(
                Module.unit_id == unit.id,
                FacilitatorSkill.facilitator_id == facilitator_user.id
            )
            .all()
        ]
        
        if skill_ids:
            FacilitatorSkill.query.filter(FacilitatorSkill.id.in_(skill_ids)).delete(synchronize_session='fetch')
        
        # 7. Finally, delete the facilitator link
        db.session.delete(link)
        db.session.commit()
        
        # Build informative message
        message_parts = [f"Removed {email} from unit"]
        if swap_count > 0:
            message_parts.append(f"cancelled {swap_count} swap request(s)")
        
        return jsonify({
            "ok": True,
            "message": ". ".join(message_parts).capitalize(),
            "removed_email": email,
            "warning": "All assignments, skills, and unavailability for this facilitator in this unit have been deleted." if swap_count > 0 else None
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to remove facilitator: {str(e)}"}), 500

# ---------- Step 3B: Calendar / Sessions ----------
@unitcoordinator_bp.get("/search-coordinators")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def search_coordinators():
    """Search for users with UNIT_COORDINATOR or ADMIN role by email."""
    email_query = request.args.get('email', '').strip().lower()
    
    if not email_query or len(email_query) < 3:
        return jsonify({
            "ok": True,
            "coordinators": []
        })
    
    # Search for users with UNIT_COORDINATOR or ADMIN role
    # Only return users with role >= UNIT_COORDINATOR (i.e., UNIT_COORDINATOR or ADMIN)
    coordinators = (
        db.session.query(User)
        .filter(
            User.email.ilike(f'%{email_query}%'),
            User.role.in_([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
        )
        .limit(10)
        .all()
    )
    
    coordinators_data = []
    for coordinator in coordinators:
        coordinators_data.append({
            "id": coordinator.id,
            "email": coordinator.email,
            "full_name": coordinator.full_name,
            "role": coordinator.role.value
        })
    
    return jsonify({
        "ok": True,
        "coordinators": coordinators_data
    })


@unitcoordinator_bp.get("/units/<int:unit_id>/coordinators")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def get_unit_coordinators(unit_id: int):
    """Get all coordinators for a unit."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 403
    
    coordinators = (
        db.session.query(User, UnitCoordinator)
        .join(UnitCoordinator, UnitCoordinator.user_id == User.id)
        .filter(UnitCoordinator.unit_id == unit_id)
        .all()
    )
    
    coordinators_data = []
    for coordinator_user, uc_link in coordinators:
        coordinators_data.append({
            "id": coordinator_user.id,
            "email": coordinator_user.email,
            "first_name": coordinator_user.first_name,
            "last_name": coordinator_user.last_name,
            "full_name": coordinator_user.full_name,
            "is_creator": unit.created_by == coordinator_user.id,
            "added_at": uc_link.created_at.isoformat() if uc_link.created_at else None
        })
    
    return jsonify({
        "ok": True,
        "coordinators": coordinators_data
    })


@unitcoordinator_bp.post("/units/<int:unit_id>/add-coordinator")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def add_unit_coordinator(unit_id: int):
    """Add a coordinator to a unit by email address."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 403
    
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    
    if not email or not _valid_email(email):
        return jsonify({"ok": False, "error": "Invalid email address"}), 400
    
    # Check if user exists and is a unit coordinator
    coordinator_user = User.query.filter_by(email=email).first()
    
    if not coordinator_user:
        return jsonify({"ok": False, "error": "User not found. User must exist and have a unit coordinator role."}), 404
    
    if coordinator_user.role != UserRole.UNIT_COORDINATOR:
        return jsonify({"ok": False, "error": "User is not a unit coordinator"}), 400
    
    # Check if already a coordinator for this unit
    existing_link = UnitCoordinator.query.filter_by(
        unit_id=unit.id,
        user_id=coordinator_user.id
    ).first()
    
    if existing_link:
        return jsonify({"ok": False, "error": "This user is already a coordinator for this unit"}), 400
    
    # Create link
    uc_link = UnitCoordinator(unit_id=unit.id, user_id=coordinator_user.id)
    db.session.add(uc_link)
    
    try:
        db.session.commit()
        
        # Send email notification to the coordinator
        from email_service import send_coordinator_added_email
        base_url = os.environ.get('BASE_URL', 'http://localhost:5000')
        send_coordinator_added_email(
            recipient_email=coordinator_user.email,
            recipient_name=coordinator_user.full_name,
            unit_code=unit.unit_code,
            unit_name=unit.unit_name,
            base_url=base_url
        )
        return jsonify({
            "ok": True,
            "message": f"Coordinator {email} added successfully and notified via email",
            "coordinator": {
                "id": coordinator_user.id,
                "email": coordinator_user.email,
                "full_name": coordinator_user.full_name
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to add coordinator: {str(e)}"}), 500


@unitcoordinator_bp.delete("/units/<int:unit_id>/coordinators/<int:coordinator_id>")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def remove_unit_coordinator(unit_id: int, coordinator_id: int):
    """Remove a coordinator from a unit."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 403
    
    
    # Prevent removing the last coordinator
    total_coordinators = UnitCoordinator.query.filter(
        UnitCoordinator.unit_id == unit.id
    ).count()
    
    if total_coordinators <= 1:
        return jsonify({
            "ok": False,
            "error": "Cannot remove the last coordinator. Please add another coordinator first."
        }), 400
    
    # Find and remove the coordinator link
    uc_link = UnitCoordinator.query.filter_by(
        unit_id=unit.id,
        user_id=coordinator_id
    ).first()
    
    if not uc_link:
        return jsonify({"ok": False, "error": "Coordinator not found for this unit"}), 404
    
    coordinator_user = User.query.get(coordinator_id)
    coordinator_email = coordinator_user.email if coordinator_user else "Unknown"
    
    try:
        db.session.delete(uc_link)
        db.session.commit()
        return jsonify({
            "ok": True,
            "message": f"Coordinator {coordinator_email} removed successfully"
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to remove coordinator: {str(e)}"}), 500


@unitcoordinator_bp.get("/units/<int:unit_id>/calendar")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def calendar_week(unit_id: int):
    """Return sessions that intersect the visible week."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404

    week_start_raw = (request.args.get("week_start") or "").strip()  # YYYY-MM-DD
    try:
        week_start = datetime.strptime(week_start_raw, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"ok": False, "error": "Invalid week_start format (use YYYY-MM-DD)"}), 400

    week_end = week_start + timedelta(days=7)  # exclusive
    sessions = (
        Session.query.join(Module)
        .filter(
            Module.unit_id == unit.id,
            Session.start_time < datetime.combine(week_end, datetime.min.time()),
            Session.end_time >= datetime.combine(week_start, datetime.min.time()),
        )
        .order_by(Session.start_time.asc())
        .all()
    )

    # Build name->id map for this unit's venues
    unit_venues = (
        db.session.query(Venue.id, Venue.name)
        .join(UnitVenue, UnitVenue.venue_id == Venue.id)
        .filter(UnitVenue.unit_id == unit.id)
        .all()
    )
    venues_by_name = { (name or "").strip().lower(): vid for vid, name in unit_venues }

    return jsonify({
        "ok": True,
        "unit_range": {
            "start": unit.start_date.isoformat() if unit.start_date else None,
            "end": unit.end_date.isoformat() if unit.end_date else None,
        },
        "sessions": [_serialize_session(s, venues_by_name) for s in sessions],
    })
    
@unitcoordinator_bp.post("/units/<int:unit_id>/sessions")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def create_session(unit_id: int):
    """Create a session or a weekly series (based on 'recurrence')."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"ok": False, "error": "Invalid or missing JSON data"}), 400

    # name coming from inspector / calendar
    name_in = (data.get("session_name") or data.get("module_name") or data.get("title") or "").strip()

    start_raw = (data.get("start") or "").strip()
    end_raw = (data.get("end") or "").strip()
    venue_name_in = (data.get("venue") or "").strip()
    venue_id_in = data.get("venue_id")

    # Optional recurrence
    rec = _parse_recurrence(data.get("recurrence"))
    
    # Staffing requirements
    lead_staff_required = data.get("lead_staff_required", 1)
    support_staff_required = data.get("support_staff_required", 0)

    # Validate datetime inputs
    start_dt = _parse_dt(start_raw)
    end_dt = _parse_dt(end_raw)
    if not start_dt or not end_dt:
        return jsonify({"ok": False, "error": "Invalid datetime format (use YYYY-MM-DDTHH:MM)"}), 400
    if end_dt <= start_dt:
        return jsonify({"ok": False, "error": "End time must be after start time"}), 400

    # Range guard for the first
    if not _within_unit_range(unit, start_dt) or not _within_unit_range(unit, end_dt):
        return jsonify({"ok": False, "error": "Session outside unit date range"}), 400

    # Determine/validate venue; we store the venue NAME in `location`
    chosen_name = None
    if venue_id_in:
        link = (
            db.session.query(UnitVenue)
            .join(Venue, Venue.id == UnitVenue.venue_id)
            .filter(UnitVenue.unit_id == unit.id, UnitVenue.venue_id == venue_id_in)
            .first()
        )
        if not link:
            return jsonify({"ok": False, "error": "Invalid venue_id for this unit"}), 400
        chosen_name = Venue.query.get(venue_id_in).name
    elif venue_name_in:
        venue_rec = db.session.query(Venue).filter(func.lower(Venue.name) == venue_name_in.lower()).first()
        if not venue_rec:
            return jsonify({"ok": False, "error": f"Venue '{venue_name_in}' not found"}), 404
        unit_venue = UnitVenue.query.filter_by(unit_id=unit.id, venue_id=venue_rec.id).first()
        if not unit_venue:
            return jsonify({"ok": False, "error": f"Venue '{venue_name_in}' not linked to this unit"}), 400
        chosen_name = venue_rec.name  # normalize

    # Pick/create module by name (falls back to 'General' if empty)
    mod = _get_or_create_module_by_name(unit, name_in)

    created_ids = []
    try:
        if rec.get("occurs") == "weekly":
            # Fan out occurrences
            for s_dt, e_dt in _iter_weekly_occurrences(unit, start_dt, end_dt, rec):
                # Skip exact duplicates (same module + start_time)
                exists = (
                    Session.query
                    .join(Module)
                    .filter(
                        Module.unit_id == unit.id,
                        Session.start_time == s_dt,
                        Session.end_time == e_dt,
                        Session.module_id == mod.id,
                    )
                    .first()
                )
                if exists:
                    continue

                sess = Session(
                    module_id=mod.id,
                    session_type="general",
                    start_time=s_dt,
                    end_time=e_dt,
                    day_of_week=s_dt.weekday(),
                    location=chosen_name,
                    required_skills=None,
                    max_facilitators=1,
                    lead_staff_required=lead_staff_required,
                    support_staff_required=support_staff_required,
                )
                db.session.add(sess)
                db.session.flush()
                created_ids.append(sess.id)
        else:
            # Single
            session = Session(
                module_id=mod.id,
                session_type="general",
                start_time=start_dt,
                end_time=end_dt,
                day_of_week=start_dt.weekday(),
                location=chosen_name,
                required_skills=None,
                max_facilitators=1,
                lead_staff_required=lead_staff_required,
                support_staff_required=support_staff_required,
            )
            db.session.add(session)
            db.session.flush()
            created_ids.append(session.id)

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Database error: {str(e)}"}), 500

    # Build mapping for serializer (venue_id resolution)
    venues_by_name = {}
    if chosen_name:
        v_id = db.session.query(Venue.id).filter(func.lower(Venue.name) == chosen_name.lower()).scalar()
        if v_id:
            venues_by_name[chosen_name.lower()] = v_id

    # Serialize the first + include all IDs
    first = Session.query.get(created_ids[0])
    return jsonify({
        "ok": True,
        "session_id": created_ids[0],
        "created_session_ids": created_ids,
        "session": _serialize_session(first, venues_by_name),
    }), 201



@unitcoordinator_bp.get("/units/<int:unit_id>/auto_assign/validation")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def check_auto_assign_validation(unit_id: int):
    """
    Check if auto-assignment can be run (all facilitators have skills declared)
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    try:
        # Get facilitators assigned to this unit
        # Include all users linked to unit (including UCs and Admins who can also facilitate)
        facilitators_from_db = (
            db.session.query(User)
            .join(UnitFacilitator, User.id == UnitFacilitator.user_id)
            .filter(UnitFacilitator.unit_id == unit_id)
            .all()
        )
        
        if not facilitators_from_db:
            return jsonify({
                "ok": False, 
                "can_run": False,
                "error": "No facilitators assigned to this unit"
            }), 400
        
        # Get all modules for this unit (excluding the default "General" module)
        unit_modules = Module.query.filter_by(unit_id=unit_id).filter(Module.module_name != "General").all()
        if not unit_modules:
            return jsonify({
                "ok": False,
                "can_run": False,
                "error": "No modules found for this unit. Please create modules first."
            }), 400
        
        # Check skills declarations
        facilitators_missing_skills = []
        for facilitator in facilitators_from_db:
            facilitator_skills = FacilitatorSkill.query.filter_by(facilitator_id=facilitator.id).all()
            declared_module_ids = {skill.module_id for skill in facilitator_skills}
            unit_module_ids = {module.id for module in unit_modules}
            
            # Check if facilitator has declared skills for all modules in this unit
            missing_modules = unit_module_ids - declared_module_ids
            if missing_modules:
                missing_module_names = [Module.query.get(module_id).module_name for module_id in missing_modules if Module.query.get(module_id).module_name != "General"]
                if missing_module_names:  # Only add if there are actual missing modules (not just General)
                    facilitators_missing_skills.append({
                        'name': facilitator.full_name,
                        'email': facilitator.email,
                        'missing_modules': missing_module_names
                    })
        
        can_run = len(facilitators_missing_skills) == 0
        
        return jsonify({
            "ok": True,
            "can_run": can_run,
            "total_facilitators": len(facilitators_from_db),
            "total_modules": len(unit_modules),
            "facilitators_missing_skills": facilitators_missing_skills,
            "message": "Auto-assignment ready" if can_run else f"{len(facilitators_missing_skills)} facilitators need to declare their skills"
        })
        
    except Exception as e:
        print(f"Error checking validation: {e}")
        return jsonify({
            "ok": False,
            "can_run": False,
            "error": "Error checking validation status"
        }), 500

@unitcoordinator_bp.post("/units/<int:unit_id>/auto_assign")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def auto_assign_facilitators(unit_id: int):
    """
    Auto-assign facilitators to sessions using the optimization algorithm
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    try:
        # Import the optimization engine
        from optimization_engine import (
            generate_optimal_assignments, 
            calculate_metrics, 
            format_session_time, 
            prepare_facilitator_data,
            generate_schedule_report_csv
        )
        from flask import session as flask_session
        
        # Get weight parameters and included facilitators from request
        request_data = request.get_json() or {}
        included_facilitator_ids = request_data.get('included_facilitators', None)
        
        # Get facilitators assigned to this unit
        # Include all users linked to unit (including UCs and Admins who can also facilitate)
        facilitators_query = (
            db.session.query(User)
            .join(UnitFacilitator, User.id == UnitFacilitator.user_id)
            .filter(UnitFacilitator.unit_id == unit_id)
        )
        
        # Filter by included facilitators if specified
        # None = never saved (include all), [] = explicitly deselected all, [1,2,3] = specific IDs
        if included_facilitator_ids is not None:
            if len(included_facilitator_ids) == 0:
                # User explicitly deselected all facilitators
                return jsonify({
                    "ok": False, 
                    "error": "No facilitators selected for auto-assignment. Please open Settings (⚙️) and select at least one facilitator."
                }), 400
            facilitators_query = facilitators_query.filter(User.id.in_(included_facilitator_ids))
        
        facilitators_from_db = facilitators_query.all()
        
        if not facilitators_from_db:
            return jsonify({
                "ok": False, 
                "error": "No facilitators found for this unit. Please add facilitators first."
            }), 400
        
        # Validate that all facilitators have declared their skills and unavailability
        validation_errors = []
        
        # Get all modules for this unit (excluding the default "General" module)
        unit_modules = Module.query.filter_by(unit_id=unit_id).filter(Module.module_name != "General").all()
        if not unit_modules:
            return jsonify({
                "ok": False,
                "error": "No modules found for this unit. Please create modules first."
            }), 400
        
        # Check skills declarations
        facilitators_missing_skills = []
        for facilitator in facilitators_from_db:
            facilitator_skills = FacilitatorSkill.query.filter_by(facilitator_id=facilitator.id).all()
            declared_module_ids = {skill.module_id for skill in facilitator_skills}
            unit_module_ids = {module.id for module in unit_modules}
            
            # Check if facilitator has declared skills for all modules in this unit
            missing_modules = unit_module_ids - declared_module_ids
            if missing_modules:
                missing_module_names = [Module.query.get(module_id).module_name for module_id in missing_modules if Module.query.get(module_id).module_name != "General"]
                if missing_module_names:  # Only add if there are actual missing modules (not just General)
                    facilitators_missing_skills.append({
                    'name': facilitator.full_name,
                    'email': facilitator.email,
                    'missing_modules': missing_module_names
                })
        
        if facilitators_missing_skills:
            validation_errors.append({
                'type': 'skills',
                'message': 'Some facilitators have not declared their skills for all modules',
                'facilitators': facilitators_missing_skills
            })
        
        # Check unavailability declarations (optional - facilitators might not have any unavailability)
        # We'll just log this for now but not block auto-assignment
        facilitators_without_unavailability = []
        for facilitator in facilitators_from_db:
            unavailability_count = Unavailability.query.filter_by(user_id=facilitator.id, unit_id=unit_id).count()
            if unavailability_count == 0:
                facilitators_without_unavailability.append(facilitator.full_name)
        
        # Note: We don't block auto-assignment for missing unavailability since facilitators might be fully available
        
        if validation_errors:
            return jsonify({
                "ok": False,
                "error": "Cannot run auto-assignment: Prerequisites not met",
                "validation_errors": validation_errors,
                "unavailability_note": f"Note: {len(facilitators_without_unavailability)} facilitators have not declared any unavailability (this is optional)"
            }), 400
        
        # Prepare facilitator data for optimization
        facilitators = prepare_facilitator_data(facilitators_from_db)
        
        # Get weight parameters from request (already loaded above)
        # Note: Only skill and fairness are weighted (sum = 100%)
        # Availability is a hard constraint (always checked, not weighted)
        w_skill = request_data.get('w_skill', 0.50)  # Default: 50%
        w_fairness = request_data.get('w_fairness', 0.50)  # Default: 50%
        
        # Generate assignments using the optimization algorithm (filtered to this unit only)
        assignments, conflicts = generate_optimal_assignments(
            facilitators, 
            unit_id,
            w_skill=w_skill,
            w_fairness=w_fairness
        )
        
        if not assignments:
            return jsonify({
                "ok": False,
                "error": "No assignments could be generated. Check facilitator availability and skills.",
                "conflicts": conflicts
            }), 400
        
        # Clean up existing assignments for this unit before creating new ones
        # Get all sessions for this unit
        unit_sessions = (
            db.session.query(Session)
            .join(Module)
            .filter(Module.unit_id == unit_id)
            .all()
        )
        
        deleted_count = 0
        if unit_sessions:
            # Get session IDs for this unit
            unit_session_ids = [session.id for session in unit_sessions]
            
            # Delete all existing assignments for sessions in this unit
            existing_assignments = Assignment.query.filter(
                Assignment.session_id.in_(unit_session_ids)
            ).all()
            
            deleted_count = len(existing_assignments)
            if deleted_count > 0:
                logger.info(f"Removing {deleted_count} existing assignments for unit {unit_id}")
                for assignment in existing_assignments:
                    db.session.delete(assignment)
        
        # Create actual Assignment records in the database
        created_assignments = []
        for assignment in assignments:
            new_assignment = Assignment(
                session_id=assignment['session']['id'],
                facilitator_id=assignment['facilitator']['id'],
                is_confirmed=True,  # Auto-confirm assignments
                role=assignment.get('role', 'lead')  # Track lead vs support role
            )
            db.session.add(new_assignment)
            created_assignments.append({
                'facilitator_name': assignment['facilitator']['name'],
                'session_name': assignment['session']['module_name'],
                'time': format_session_time(assignment['session']),
                'score': round(assignment['score'], 2),
                'role': assignment.get('role', 'lead')
            })
        
        db.session.commit()
        
        # Calculate metrics
        metrics = calculate_metrics(assignments)
        
        # Generate CSV report and cache it in the session
        unit_display_name = f"{unit.unit_code} - {unit.unit_name}" if unit else "Unit"
        csv_report = generate_schedule_report_csv(
            assignments, 
            unit_display_name,
            total_facilitators_in_pool=len(facilitators_from_db),
            unit_id=unit_id,
            all_facilitators=facilitators_from_db
        )
        
        # Store CSV in a temporary file instead of session to avoid cookie size issues
        import tempfile
        import os
        
        # Create a temporary file for the CSV report
        temp_dir = tempfile.gettempdir()
        csv_filename = f"schedule_report_{unit_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_filepath = os.path.join(temp_dir, csv_filename)
        
        # Write CSV to temporary file
        with open(csv_filepath, 'w', encoding='utf-8') as f:
            f.write(csv_report)
        
        # Clean up old temporary files to prevent disk space issues
        _cleanup_old_temp_files(temp_dir, f"schedule_report_{unit_id}_")
        
        # Store filename in database for persistence (survives cookie/session resets)
        unit.csv_report_filename = csv_filename
        unit.csv_report_generated_at = datetime.now()
        db.session.commit()
        
        # Prepare success message
        message = f"Successfully created {len(created_assignments)} assignments"
        if deleted_count > 0:
            message += f" (removed {deleted_count} previous assignments)"
        
        return jsonify({
            "ok": True,
            "message": message,
            "assignments": created_assignments,
            "conflicts": conflicts,
            "metrics": metrics,
            "csv_available": True,
            "csv_download_url": f"/unitcoordinator/units/{unit_id}/download_schedule_report"
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Auto-assign error: {str(e)}")
        return jsonify({
            "ok": False, 
            "error": f"Auto-assignment failed: {str(e)}"
        }), 500


@unitcoordinator_bp.get("/units/<int:unit_id>/check_csv_availability")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def check_csv_availability(unit_id: int):
    """
    Check if a CSV report is available for download
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    # Check if report exists in database
    if unit.csv_report_filename:
        # Verify the file still exists
        import tempfile
        import os
        
        temp_dir = tempfile.gettempdir()
        csv_filepath = os.path.join(temp_dir, unit.csv_report_filename)
        
        # Check if file exists
        if os.path.exists(csv_filepath):
            return jsonify({
                "ok": True,
                "csv_available": True,
                "csv_download_url": f"/unitcoordinator/units/{unit_id}/download_schedule_report"
            })
        else:
            # File was cleaned up, clear from database
            unit.csv_report_filename = None
            unit.csv_report_generated_at = None
            db.session.commit()
    
    return jsonify({
        "ok": True,
        "csv_available": False
    })


@unitcoordinator_bp.get("/units/<int:unit_id>/download_schedule_report")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def download_schedule_report(unit_id: int):
    """
    Download the CSV report from the last auto-assignment run
    """
    from flask import Response
    from datetime import datetime
    
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    # Check if report exists in database
    if not unit.csv_report_filename:
        return jsonify({
            "ok": False, 
            "error": "No report available. Please run auto-assignment first."
        }), 404
    
    # Read CSV content from temporary file
    import tempfile
    import os
    
    temp_dir = tempfile.gettempdir()
    csv_filepath = os.path.join(temp_dir, unit.csv_report_filename)
    
    try:
        with open(csv_filepath, 'r', encoding='utf-8') as f:
            csv_content = f.read()
    except FileNotFoundError:
        # File was cleaned up, clear from database
        unit.csv_report_filename = None
        unit.csv_report_generated_at = None
        db.session.commit()
        return jsonify({
            "ok": False, 
            "error": "Report file not found. Please run auto-assignment again."
        }), 404
    
    # Generate filename with timestamp
    timestamp_str = unit.csv_report_generated_at.strftime('%Y%m%d_%H%M%S') if unit.csv_report_generated_at else datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"schedule_report_{unit.unit_code}_{timestamp_str}.csv"
    
    # Return as downloadable file
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
    )


@unitcoordinator_bp.post("/units/<int:unit_id>/upload_sessions_csv")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def upload_sessions_csv(unit_id: int):
    """
    Accept CSV with headers: Venue, Activity, Session, Date, Time
      - Activity: workshop|tutorial|lab|other (case-insensitive; others→'other')
      - Date: DD/MM/YYYY or YYYY-MM-DD
      - Time: 'HH:MM-HH:MM' (accepts '.' as separator and en-dash)
    Creates sessions inside the unit's date range. Dedupes within-file and against existing.
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404

    file = request.files.get("sessions_csv")
    if not file:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    try:
        text = file.read().decode("utf-8", errors="replace")
        reader = csv.DictReader(StringIO(text))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed to read CSV: {e}"}), 400

    # Header check
    fns = [fn.strip().lower() for fn in (reader.fieldnames or [])]
    needed = {"venue", "activity", "session", "date", "time"}
    if not needed.issubset(set(fns)):
        return jsonify({"ok": False, "error": "CSV must include headers: Venue, Activity, Session, Date, Time"}), 400

    created = 0
    skipped = 0
    errors = []
    seen = set()   # within-file dedupe key
    created_ids = []

    # Preload/collect existing venues for fast lookup
    name_to_venue = {v.name.strip().lower(): v for v in Venue.query.all()}

    # Helper to get or create venue + link to unit
    def ensure_unit_venue(venue_name: str) -> Venue:
        vkey = (venue_name or "").strip().lower()
        if not vkey:
            return None
        venue = name_to_venue.get(vkey)
        if not venue:
            venue = Venue(name=venue_name.strip())
            db.session.add(venue)
            db.session.flush()
            name_to_venue[vkey] = venue
        # ensure UnitVenue link
        if not UnitVenue.query.filter_by(unit_id=unit.id, venue_id=venue.id).first():
            db.session.add(UnitVenue(unit_id=unit.id, venue_id=venue.id))
        return venue

    # Process rows
    MAX_ROWS = 2000
    for idx, row in enumerate(reader, start=2):
        if idx - 1 > MAX_ROWS:
            errors.append(f"Row {idx}: skipped due to row limit ({MAX_ROWS}).")
            skipped += 1
            continue

        venue_in   = (row.get("venue") or "").strip()
        activity_in= _coerce_activity_type(row.get("activity"))
        session_in = (row.get("session") or "").strip()
        date_in    = (row.get("date") or "").strip()
        time_in    = (row.get("time") or "").strip()

        if not (venue_in and activity_in and session_in and date_in and time_in):
            skipped += 1
            errors.append(f"Row {idx}: missing required fields.")
            continue

        d = _parse_date_multi(date_in)
        tr = _parse_time_range(time_in)
        if not d:
            skipped += 1
            errors.append(f"Row {idx}: invalid date '{date_in}'.")
            continue
        if not tr:
            skipped += 1
            errors.append(f"Row {idx}: invalid time range '{time_in}'.")
            continue

        h1, m1, h2, m2 = tr
        start_dt = datetime(d.year, d.month, d.day, h1, m1)
        end_dt   = datetime(d.year, d.month, d.day, h2, m2)
        if end_dt <= start_dt:
            skipped += 1
            errors.append(f"Row {idx}: end time must be after start time.")
            continue

        # Range guard
        if not _within_unit_range(unit, start_dt) or not _within_unit_range(unit, end_dt):
            skipped += 1
            errors.append(f"Row {idx}: outside unit date range.")
            continue

        # File-level dedupe
        dedupe_key = (venue_in.strip().lower(), activity_in, session_in.strip().lower(), start_dt, end_dt)
        if dedupe_key in seen:
            skipped += 1
            continue
        seen.add(dedupe_key)

        # Ensure venue + link to unit
        venue_obj = ensure_unit_venue(venue_in)

        # Module: name = Session (title), type = Activity
        mod = _get_or_create_module_by_name(unit, session_in)
        mod.module_type = activity_in  # set/update to activity type

        # DB-level dedupe: same module + start + end
        exists = (
            Session.query
            .filter(
                Session.module_id == mod.id,
                Session.start_time == start_dt,
                Session.end_time == end_dt,
            )
            .first()
        )
        if exists:
            skipped += 1
            continue

        try:
            s = Session(
                module_id=mod.id,
                session_type="general",
                start_time=start_dt,
                end_time=end_dt,
                day_of_week=start_dt.weekday(),
                location=venue_obj.name if venue_obj else None,
                required_skills=None,
                max_facilitators=1,
            )
            db.session.add(s)
            db.session.flush()
            created_ids.append(s.id)
            created += 1
        except Exception as e:
            db.session.rollback()
            errors.append(f"Row {idx}: database error: {e}")
            continue

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Commit failed: {e}"}), 500

    return jsonify({
        "ok": True,
        "created": created,
        "skipped": skipped,
        "errors": errors[:30],
        "created_session_ids": created_ids,
    })



@unitcoordinator_bp.put("/sessions/<int:session_id>")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def update_session(session_id: int):
    """Move/resize, update venue, or rename session; optional weekly fan-out when apply_to='series'."""
    user = get_current_user()
    session = Session.query.get(session_id)
    if not session:
        return jsonify({"ok": False, "error": "Session not found"}), 404
    
    unit = _get_user_unit_or_404(user, session.module.unit.id)
    if not unit:
        return jsonify({"ok": False, "error": "Unauthorized"}), 403
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"ok": False, "error": "Invalid or missing JSON data"}), 400

    # --- Rename session by switching its module ---
    name_in = (data.get("session_name") or data.get("module_name") or data.get("title") or "").strip()
    if name_in:
        new_mod = _get_or_create_module_by_name(unit, name_in)
        session.module_id = new_mod.id
    else:
        new_mod = session.module  # use current for fan-out below

    # --- Validate and update start/end times ---
    if "start" in data:
        start_time = _parse_dt(str(data["start"]))
        if not start_time:
            return jsonify({"ok": False, "error": "Invalid start time format (use YYYY-MM-DDTHH:MM)"}), 400
        session.start_time = start_time
        session.day_of_week = start_time.weekday()

    if "end" in data:
        end_time = _parse_dt(str(data["end"]))
        if not end_time:
            return jsonify({"ok": False, "error": "Invalid end time format (use YYYY-MM-DDTHH:MM)"}), 400
        session.end_time = end_time

    # --- Update staffing requirements ---
    if "lead_staff_required" in data:
        session.lead_staff_required = data.get("lead_staff_required", 1)
    if "support_staff_required" in data:
        session.support_staff_required = data.get("support_staff_required", 0)

    # --- Validate and update venue ---
    venue_set = False
    if "venue_id" in data:
        venue_id = data["venue_id"]
        if venue_id:
            link = (
                db.session.query(UnitVenue)
                .join(Venue, Venue.id == UnitVenue.venue_id)
                .filter(UnitVenue.unit_id == unit.id, UnitVenue.venue_id == venue_id)
                .first()
            )
            if not link:
                return jsonify({"ok": False, "error": "Invalid venue_id for this unit"}), 400
            session.location = Venue.query.get(venue_id).name
        else:
            session.location = None
        venue_set = True

    if not venue_set and "venue" in data:
        venue_name = (data["venue"] or "").strip()
        if venue_name:
            venue = db.session.query(Venue).filter(func.lower(Venue.name) == venue_name.lower()).first()
            if not venue:
                return jsonify({"ok": False, "error": f"Venue '{venue_name}' not found"}), 404
            unit_venue = UnitVenue.query.filter_by(unit_id=unit.id, venue_id=venue.id).first()
            if not unit_venue:
                return jsonify({"ok": False, "error": f"Venue '{venue_name}' not linked to this unit"}), 400
            session.location = venue.name
        else:
            session.location = None

    # --- Range and sanity checks ---
    if unit.start_date and session.start_time.date() < unit.start_date:
        return jsonify({"ok": False, "error": "Session start date is before unit start date"}), 400
    if unit.end_date and session.end_time.date() > unit.end_date:
        return jsonify({"ok": False, "error": "Session end date is after unit end date"}), 400
    if session.end_time <= session.start_time:
        return jsonify({"ok": False, "error": "End time must be after start time"}), 400

    created_ids = []

    # --- NEW: recurrence fan-out when saving with apply_to='series' ---
    rec = _parse_recurrence(data.get("recurrence"))
    apply_to = (data.get("apply_to") or "").lower()
    if rec.get("occurs") == "weekly" and apply_to == "series":
        # Use the *current* (possibly edited) times as the pattern seed
        seed_s = session.start_time
        seed_e = session.end_time
        chosen_name = session.location  # normalized earlier if set
        mod_for_series = new_mod

        try:
            for s_dt, e_dt in _iter_weekly_occurrences(unit, seed_s, seed_e, rec):
                # Skip the seed itself (already updated above)
                if s_dt == seed_s and e_dt == seed_e:
                    continue
                # Avoid exact duplicates for this module
                exists = (
                    Session.query
                    .join(Module)
                    .filter(
                        Module.unit_id == unit.id,
                        Session.start_time == s_dt,
                        Session.end_time == e_dt,
                        Session.module_id == mod_for_series.id,
                    )
                    .first()
                )
                if exists:
                    continue
                new_sess = Session(
                    module_id=mod_for_series.id,
                    session_type="general",
                    start_time=s_dt,
                    end_time=e_dt,
                    day_of_week=s_dt.weekday(),
                    location=chosen_name,
                    required_skills=None,
                    max_facilitators=1,
                )
                db.session.add(new_sess)
                db.session.flush()
                created_ids.append(new_sess.id)
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "error": f"Database error while expanding series: {str(e)}"}), 500

    # --- Commit changes ---
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Database error: {str(e)}"}), 500

    # --- Include venue_id in response (when resolvable) ---
    venues_by_name = {}
    if session.location:
        v_id = db.session.query(Venue.id).filter(func.lower(Venue.name) == session.location.lower()).scalar()
        if v_id:
            venues_by_name[session.location.lower()] = v_id

    resp = {
        "ok": True,
        "session": _serialize_session(session, venues_by_name)
    }
    if created_ids:
        resp["created_session_ids"] = created_ids
    return jsonify(resp)


@unitcoordinator_bp.delete("/sessions/<int:session_id>")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def delete_session(session_id: int):
    """Delete a session."""
    user = get_current_user()
    session = Session.query.get(session_id)
    if not session:
        return jsonify({"ok": False, "error": "Session not found"}), 404
    
    unit = _get_user_unit_or_404(user, session.module.unit.id)
    if not unit:
        return jsonify({"ok": False, "error": "Unauthorized"}), 403

    try:
        db.session.delete(session)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Database error: {str(e)}"}), 500

    return jsonify({"ok": True})


@unitcoordinator_bp.get("/units/<int:unit_id>/venues")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def list_venues(unit_id: int):
    """Return venues linked to this unit (id + name)."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404

    venues = (
        db.session.query(Venue.id, Venue.name)
        .join(UnitVenue, UnitVenue.venue_id == Venue.id)
        .filter(UnitVenue.unit_id == unit.id)
        .order_by(Venue.name.asc())
        .all()
    )
    return jsonify({
        "ok": True,
        "venues": [{"id": v.id, "name": v.name} for v in venues]
    })


@unitcoordinator_bp.get("/units/<int:unit_id>/publish_preview")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def publish_preview(unit_id: int):
    """Get a preview of what will be published (session and facilitator counts)"""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    try:
        # Get all sessions for this unit
        all_sessions = (
            db.session.query(Session)
            .join(Module, Session.module_id == Module.id)
            .filter(Module.unit_id == unit_id)
            .all()
        )
        
        # Get sessions that have facilitators assigned
        assigned_sessions = (
            db.session.query(Session)
            .join(Module, Session.module_id == Module.id)
            .join(Assignment, Session.id == Assignment.session_id)
            .filter(Module.unit_id == unit_id)
            .distinct()
            .all()
        )
        
        # Build facilitator info with session counts and track current assignments
        facilitator_sessions = {}  # {facilitator_id: {user, sessions: [], session_ids: set()}}
        for session in assigned_sessions:
            assignments = Assignment.query.filter_by(session_id=session.id).all()
            for assignment in assignments:
                fid = assignment.facilitator_id
                if fid not in facilitator_sessions:
                    facilitator = User.query.get(fid)
                    if facilitator:
                        facilitator_sessions[fid] = {
                            'user': facilitator,
                            'session_count': 0,
                            'session_ids': set()
                        }
                if fid in facilitator_sessions:
                    facilitator_sessions[fid]['session_count'] += 1
                    facilitator_sessions[fid]['session_ids'].add(session.id)
        
        # Check if schedule was previously published and get snapshot of old assignments
        previously_published_sessions = {}  # {facilitator_id: set(session_ids)}
        if unit.schedule_status and unit.schedule_status.value == 'published' and unit.published_assignments_snapshot:
            # Load the snapshot from when schedule was last published
            import json
            try:
                snapshot = json.loads(unit.published_assignments_snapshot)
                # Convert lists back to sets for comparison
                previously_published_sessions = {
                    int(fid): set(session_ids) 
                    for fid, session_ids in snapshot.items()
                }
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error loading published assignments snapshot: {e}")
                previously_published_sessions = {}
        
        # Build facilitators list for frontend
        facilitators_list = []
        for fid, data in facilitator_sessions.items():
            # Check if this facilitator's assignments have changed
            has_changes = False
            if unit.schedule_status and unit.schedule_status.value == 'published':
                current_sessions = data['session_ids']
                old_sessions = previously_published_sessions.get(fid, set())
                # Check if sessions added, removed, or facilitator is new
                has_changes = (current_sessions != old_sessions)
                
                # Debug logging
                if has_changes:
                    logger.info(f"Facilitator {fid} has changes: current={current_sessions}, old={old_sessions}")
            else:
                # First publish - all facilitators are "changed"
                has_changes = True
            
            facilitators_list.append({
                'id': fid,
                'name': data['user'].full_name,
                'email': data['user'].email,
                'session_count': data['session_count'],
                'has_changes': has_changes
            })
        
        # Sort by name
        facilitators_list.sort(key=lambda x: x['name'].lower())
        
        # Calculate unassigned count
        unassigned_count = len(all_sessions) - len(assigned_sessions)
        
        return jsonify({
            "ok": True,
            "session_count": len(all_sessions),
            "facilitator_count": len(facilitator_sessions),
            "unassigned_count": unassigned_count,
            "facilitators": facilitators_list
        })
    except Exception as e:
        print(f"Error getting publish preview: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@unitcoordinator_bp.post("/units/<int:unit_id>/sessions/<int:session_id>/assign")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def assign_facilitators_to_session(unit_id: int, session_id: int):
    """Assign facilitators to a session."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    try:
        data = request.get_json()
        facilitator_ids = data.get('facilitator_ids', [])
        
        # Allow empty list to unassign all facilitators
        # if not facilitator_ids:
        #     return jsonify({"ok": False, "error": "No facilitators provided"}), 400
        
        # Verify session belongs to this unit
        session = (
            db.session.query(Session)
            .join(Module, Session.module_id == Module.id)
            .filter(Session.id == session_id)
            .filter(Module.unit_id == unit_id)
            .first()
        )
        
        if not session:
            return jsonify({"ok": False, "error": "Session not found"}), 404
        
        # Check for scheduling conflicts before creating assignments
        conflicts = []
        for facilitator_id in facilitator_ids:
            # Get all existing assignments for this facilitator
            existing_assignments = (
                db.session.query(Assignment, Session)
                .join(Session, Session.id == Assignment.session_id)
                .join(Module, Module.id == Session.module_id)
                .filter(
                    Assignment.facilitator_id == facilitator_id,
                    Module.unit_id == unit_id,
                    Session.id != session_id  # Exclude current session
                )
                .all()
            )
            
            # Check for time overlaps with current session
            for assignment, existing_session in existing_assignments:
                # Check if sessions overlap
                if (session.start_time < existing_session.end_time and 
                    session.end_time > existing_session.start_time):
                    
                    facilitator = User.query.get(facilitator_id)
                    facilitator_name = facilitator.full_name if facilitator else f"Facilitator {facilitator_id}"
                    
                    conflicts.append({
                        'facilitator_id': facilitator_id,
                        'facilitator_name': facilitator_name,
                        'conflicting_session': {
                            'id': existing_session.id,
                            'name': existing_session.module.module_name,
                            'start_time': existing_session.start_time.isoformat(),
                            'end_time': existing_session.end_time.isoformat()
                        },
                        'current_session': {
                            'id': session.id,
                            'name': session.module.module_name,
                            'start_time': session.start_time.isoformat(),
                            'end_time': session.end_time.isoformat()
                        }
                    })
        
        # If there are conflicts, return error with details
        if conflicts:
            conflict_messages = []
            for conflict in conflicts:
                msg = (f"{conflict['facilitator_name']} is already assigned to "
                      f"'{conflict['conflicting_session']['name']}' "
                      f"({conflict['conflicting_session']['start_time'][:16]} - "
                      f"{conflict['conflicting_session']['end_time'][:16]}) "
                      f"which overlaps with this session.")
                conflict_messages.append(msg)
            
            return jsonify({
                "ok": False, 
                "error": "Scheduling conflicts detected",
                "conflicts": conflicts,
                "message": "The following scheduling conflicts were detected:\n\n" + "\n".join(conflict_messages)
            }), 400
        
        # Remove existing assignments for this session
        Assignment.query.filter_by(session_id=session_id).delete()
        
        # Create new assignments
        for facilitator_id in facilitator_ids:
            # Verify facilitator exists (allow any role - UC/Admin can also facilitate)
            facilitator = User.query.get(facilitator_id)
            
            if not facilitator:
                continue
                
            # Check if facilitator is assigned to this unit
            unit_facilitator = UnitFacilitator.query.filter_by(
                unit_id=unit_id, 
                user_id=facilitator_id
            ).first()
            
            if not unit_facilitator:
                continue
            
            # Create assignment
            assignment = Assignment(
                session_id=session_id,
                facilitator_id=facilitator_id,
                is_confirmed=False,  # Default to unconfirmed
                role='lead'  # Default role
            )
            db.session.add(assignment)
        
        # Update session status
        if len(facilitator_ids) > 0:
            session.status = 'assigned'
        else:
            session.status = 'unassigned'
        
        db.session.commit()
        
        # Return appropriate message
        if len(facilitator_ids) == 0:
            message = "All facilitators unassigned from session"
        else:
            message = f"Assigned {len(facilitator_ids)} facilitator{'s' if len(facilitator_ids) != 1 else ''} to session"
        
        return jsonify({
            "ok": True,
            "message": message,
            "session_id": session_id
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to assign facilitators: {str(e)}"}), 500


@unitcoordinator_bp.delete("/units/<int:unit_id>/sessions/<int:session_id>")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def delete_unit_session(unit_id: int, session_id: int):
    """Delete a session and unassign all facilitators."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    try:
        # Verify session belongs to this unit
        session = (
            db.session.query(Session)
            .join(Module, Session.module_id == Module.id)
            .filter(Session.id == session_id)
            .filter(Module.unit_id == unit_id)
            .first()
        )
        
        if not session:
            return jsonify({"ok": False, "error": "Session not found"}), 404
        
        # Store module_id before deleting session
        module_id = session.module_id
        
        # Delete all assignments for this session (cascade will handle this, but explicit is better)
        Assignment.query.filter_by(session_id=session_id).delete()
        
        # Delete the session
        db.session.delete(session)
        db.session.flush()
        
        # Check if module has any remaining sessions
        remaining_sessions = Session.query.filter_by(module_id=module_id).count()
        
        message = "Session deleted successfully"
        
        if remaining_sessions == 0:
            # No more sessions for this module - delete the module and its skills
            module = Module.query.get(module_id)
            if module:
                # Delete all skill declarations for this module
                from models import FacilitatorSkill
                FacilitatorSkill.query.filter_by(module_id=module_id).delete()
                
                # Delete the module
                db.session.delete(module)
                message = "Session deleted successfully. Module had no remaining sessions and was also deleted (including skill declarations)."
        
        db.session.commit()
        
        return jsonify({
            "ok": True,
            "message": message
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to delete session: {str(e)}"}), 500


@unitcoordinator_bp.post("/units/<int:unit_id>/publish")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def publish_schedule(unit_id: int):
    """Publish the schedule and notify facilitators."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    # Get optional list of facilitator IDs to notify (if not provided, notify all)
    data = request.get_json() or {}
    notify_facilitator_ids = data.get('notify_facilitator_ids', None)  # None means notify all
    
    # Check for new unavailability added during unpublish window
    unpublish_conflicts = []
    if unit.unpublished_at:
        # Get all facilitators assigned to sessions in this unit
        facilitator_ids = set()
        for module in unit.modules:
            for session in module.sessions:
                for assignment in session.assignments:
                    facilitator_ids.add(assignment.facilitator_id)
        
        # Check for new unavailability created since unpublish
        new_unavailability = (
            db.session.query(Unavailability, User, Session, Assignment)
            .join(User, User.id == Unavailability.user_id)
            .join(Assignment, Assignment.facilitator_id == User.id)
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .filter(
                Module.unit_id == unit_id,
                Unavailability.user_id.in_(facilitator_ids),
                Unavailability.created_at > unit.unpublished_at,
                Unavailability.unit_id.is_(None),  # Global unavailability only
                db.func.date(Session.start_time) == Unavailability.date
            )
            .all()
        )
        
        for unavail, facilitator, session, assignment in new_unavailability:
            unpublish_conflicts.append({
                'facilitator_id': facilitator.id,
                'facilitator_name': f"{facilitator.first_name} {facilitator.last_name}".strip(),
                'session': {
                    'id': session.id,
                    'module': session.module.module_name,
                    'start_time': session.start_time.isoformat(),
                    'end_time': session.end_time.isoformat()
                },
                'unavailability': {
                    'date': unavail.date.isoformat(),
                    'created_at': unavail.created_at.isoformat(),
                    'reason': unavail.reason
                }
            })
        
        # If conflicts found, return warning (don't block, just warn)
        if unpublish_conflicts:
            logger.warning(f"Found {len(unpublish_conflicts)} new unavailability conflicts since unpublish for unit {unit_id}")
    
    try:
        # Get all sessions for this unit that have facilitators assigned
        # Check for sessions with any assignments, regardless of status
        sessions = (
            db.session.query(Session)
            .join(Module, Session.module_id == Module.id)
            .join(Assignment, Session.id == Assignment.session_id)
            .filter(Module.unit_id == unit_id)
            .distinct()
            .all()
        )
        
        print(f"DEBUG: Found {len(sessions)} sessions with assignments for unit {unit_id}")
        
        if not sessions:
            return jsonify({"ok": False, "error": "No sessions with facilitator assignments found to publish"}), 400
        
        # Collect facilitator assignments - group sessions by facilitator
        from datetime import datetime
        facilitator_sessions = {}  # {facilitator_id: [session_data, ...]}
        
        try:
            for session in sessions:
                # Get facilitators assigned to this session
                assignments = Assignment.query.filter_by(session_id=session.id).all()
                
                # Track which facilitators we've already added this session for (prevent duplicates)
                processed_facilitators = set()
                
                for assignment in assignments:
                    facilitator_id = assignment.facilitator_id
                    
                    # Skip if we've already added this session for this facilitator
                    if facilitator_id in processed_facilitators:
                        print(f"⚠️ Skipping duplicate assignment: facilitator {facilitator_id} already has session {session.id}")
                        continue
                    
                    processed_facilitators.add(facilitator_id)
                    
                    if facilitator_id not in facilitator_sessions:
                        facilitator_sessions[facilitator_id] = []
                    
                    # Get module info
                    module = Module.query.get(session.module_id)
                    
                    # Format date and time with error handling
                    try:
                        if session.start_time:
                            session_date = session.start_time.strftime('%A, %d %b %Y')
                            session_time_start = session.start_time.strftime('%I:%M %p')
                        else:
                            session_date = 'TBA'
                            session_time_start = 'TBA'
                        
                        if session.end_time:
                            session_time_end = session.end_time.strftime('%I:%M %p')
                            session_time = f"{session_time_start} - {session_time_end}" if session_time_start != 'TBA' else 'TBA'
                        else:
                            session_time = session_time_start if session_time_start != 'TBA' else 'TBA'
                    except Exception as e:
                        print(f"Error formatting date/time for session {session.id}: {e}")
                        session_date = 'TBA'
                        session_time = 'TBA'
                    
                    facilitator_sessions[facilitator_id].append({
                        'module': module.module_name if module else 'N/A',
                        'type': session.session_type or 'Session',
                        'date': session_date,
                        'time': session_time,
                        'location': session.location or 'TBA'
                    })
        except Exception as e:
            print(f"❌ ERROR collecting facilitator sessions: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"ok": False, "error": f"Error collecting session data: {str(e)}"}), 500
        
        # Create notifications and send emails to facilitators
        notifications_created = 0
        emails_sent = 0
        from email_service import send_schedule_published_email
        from datetime import datetime
        from models import ScheduleStatus
        
        print(f"DEBUG: Collected sessions for {len(facilitator_sessions)} facilitators")
        
        for facilitator_id, sessions_list in facilitator_sessions.items():
            try:
                # Get facilitator user
                facilitator = User.query.get(facilitator_id)
                if not facilitator:
                    print(f"⚠️ Facilitator {facilitator_id} not found, skipping")
                    continue
                
                print(f"Processing facilitator: {facilitator.email} with {len(sessions_list)} sessions")
                
                # Create in-app notification (always created for all facilitators)
                notification = Notification(
                    user_id=facilitator_id,
                    message=f"Your schedule for {unit.unit_code} has been published. Please review your assigned sessions.",
                    is_read=False
                )
                db.session.add(notification)
                notifications_created += 1
                
                # Check if we should send email to this facilitator
                # If notify_facilitator_ids is None, send to all; otherwise only send to selected
                should_send_email = (notify_facilitator_ids is None) or (facilitator_id in notify_facilitator_ids)
                
                if not should_send_email:
                    print(f"⏭️ Skipping email for {facilitator.email} (not selected)")
                    continue
                
                # Send email with session details
                try:
                    email_sent = send_schedule_published_email(
                        recipient_email=facilitator.email,
                        recipient_name=facilitator.full_name or facilitator.email,
                        unit_code=unit.unit_code,
                        sessions_list=sessions_list
                    )
                    if email_sent:
                        emails_sent += 1
                        print(f"✅ Schedule email sent to {facilitator.email} ({len(sessions_list)} sessions)")
                    else:
                        print(f"⚠️ Email function returned False for {facilitator.email}")
                except Exception as e:
                    print(f"❌ Failed to send schedule email to {facilitator.email}: {e}")
                    import traceback
                    traceback.print_exc()
            except Exception as e:
                print(f"❌ Error processing facilitator {facilitator_id}: {e}")
                import traceback
                traceback.print_exc()
        
        # Update session statuses to 'published'
        for session in sessions:
            session.status = 'published'
        
        # Mark the unit as published (used by facilitator portal to lock edits)
        try:
            unit.schedule_status = ScheduleStatus.PUBLISHED
            unit.published_at = datetime.utcnow()
            
            # Save snapshot of current assignments for change detection on next publish
            import json
            assignments_snapshot = {}  # {facilitator_id: [session_ids]}
            all_current_assignments = (
                db.session.query(Assignment)
                .join(Session, Assignment.session_id == Session.id)
                .join(Module, Session.module_id == Module.id)
                .filter(Module.unit_id == unit_id)
                .all()
            )
            for assignment in all_current_assignments:
                fid = str(assignment.facilitator_id)  # JSON keys must be strings
                if fid not in assignments_snapshot:
                    assignments_snapshot[fid] = []
                assignments_snapshot[fid].append(assignment.session_id)
            
            unit.published_assignments_snapshot = json.dumps(assignments_snapshot)
        except Exception as e:
            print(f"Warning: Could not save assignments snapshot: {e}")
            # Continue anyway - this is not critical
        
        db.session.commit()
        
        # Generate auto-unavailability for facilitators in other units
        auto_unavail_count = generate_unavailability_from_schedule(unit_id)
        
        # Generate CSV report for download
        # NOTE: CSV generation temporarily disabled due to data format mismatch
        # The generate_schedule_report_csv expects dict assignments from auto-assign,
        # but we're passing Assignment model objects. This needs refactoring.
        csv_download_url = None
        print("Note: CSV report generation skipped (needs refactoring to work with Assignment objects)")
        
        response_data = {
            "ok": True,
            "message": f"Schedule published successfully. {emails_sent} facilitators notified via email.",
            "sessions_published": len(sessions),
            "facilitators_notified": emails_sent,
            "notifications_created": notifications_created,
            "auto_unavailability_created": auto_unavail_count,
            "csv_download_url": csv_download_url
        }
        
        # Add unpublish conflicts if any were found
        if unpublish_conflicts:
            response_data["unpublish_conflicts"] = unpublish_conflicts
            response_data["warning"] = f"{len(unpublish_conflicts)} facilitator(s) added unavailability since unpublish"
        
        return jsonify(response_data)
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to publish schedule: {str(e)}"}), 500


@unitcoordinator_bp.post("/units/<int:unit_id>/unpublish")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def unpublish_schedule(unit_id: int):
    """Unpublish a schedule and revert to draft state."""
    from models import ScheduleStatus, SwapStatus
    from datetime import date, timedelta
    
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    # Get optional send_notifications parameter (default True)
    data = request.get_json() or {}
    send_notifications = data.get('send_notifications', True)
    
    # 1. Check if unit is published
    if unit.schedule_status != ScheduleStatus.PUBLISHED:
        return jsonify({"ok": False, "error": "Unit is not published"}), 400
    
    try:
        # 4. Remove auto-generated unavailability
        deleted_unavail = remove_unavailability_from_schedule(unit_id)
        
        # 5. Reject pending swap requests
        # Get all assignment IDs for this unit through modules and sessions
        assignment_ids = []
        for module in unit.modules:
            for session in module.sessions:
                for assignment in session.assignments:
                    assignment_ids.append(assignment.id)
        
        # Find swap requests involving these assignments
        swap_requests = SwapRequest.query.filter(
            db.or_(
                SwapRequest.requester_assignment_id.in_(assignment_ids),
                SwapRequest.target_assignment_id.in_(assignment_ids)
            ),
            SwapRequest.status.in_([
                SwapStatus.PENDING,
                SwapStatus.FACILITATOR_PENDING,
                SwapStatus.COORDINATOR_PENDING
            ])
        ).all()
        
        rejected_swaps = 0
        for swap in swap_requests:
            swap.status = SwapStatus.REJECTED
            swap.rejection_reason = "Schedule unpublished by coordinator"
            rejected_swaps += 1
            
            # Create notification for requesting facilitator
            try:
                from models import Notification
                notification = Notification(
                    user_id=swap.requester_id,
                    message=f"Your swap request for {unit.unit_code} was rejected because the schedule was unpublished.",
                    notification_type="swap_rejected"
                )
                db.session.add(notification)
            except Exception as notif_error:
                logger.warning(f"Failed to create notification for swap rejection: {notif_error}")
        
        # 6. Update unit status
        unit.schedule_status = ScheduleStatus.DRAFT
        unit.unpublished_at = datetime.utcnow()
        unit.unpublished_by = user.id
        
        db.session.commit()
        
        # 7. Send notifications to facilitators (if enabled)
        notifications_sent = 0
        emails_sent = 0
        if send_notifications:
            try:
                from models import Notification
                from email_service import send_schedule_unpublished_email
                
                facilitator_ids = set()
                # Get all sessions through modules
                for module in unit.modules:
                    for session in module.sessions:
                        for assignment in session.assignments:
                            facilitator_ids.add(assignment.facilitator_id)
                
                logger.info(f"Found {len(facilitator_ids)} facilitators to notify")
                
                for facilitator_id in facilitator_ids:
                    facilitator = User.query.get(facilitator_id)
                    if not facilitator:
                        logger.warning(f"Facilitator {facilitator_id} not found")
                        continue
                    
                    logger.info(f"Processing facilitator: {facilitator.email}")
                    
                    # Create in-app notification
                    notification = Notification(
                        user_id=facilitator_id,
                        message=f"The schedule for {unit.unit_code} - {unit.unit_name} has been unpublished. You will be notified when it is republished."
                    )
                    db.session.add(notification)
                    notifications_sent += 1
                    
                    # Send email
                    try:
                        logger.info(f"Attempting to send unpublish email to {facilitator.email}")
                        email_sent = send_schedule_unpublished_email(
                            recipient_email=facilitator.email,
                            recipient_name=facilitator.full_name or facilitator.email,
                            unit_code=unit.unit_code,
                            unit_name=unit.unit_name
                        )
                        if email_sent:
                            emails_sent += 1
                            logger.info(f"✅ Unpublish email sent successfully to {facilitator.email}")
                        else:
                            logger.warning(f"❌ Email function returned False for {facilitator.email}")
                    except Exception as email_error:
                        logger.error(f"❌ Exception sending unpublish email to {facilitator.email}: {email_error}")
                        import traceback
                        traceback.print_exc()
                
                db.session.commit()
            except Exception as notif_error:
                logger.warning(f"Failed to create facilitator notifications: {notif_error}")
        
        logger.info(f"Unit {unit.unit_code} unpublished by {user.email}. Removed {deleted_unavail} auto-unavailability entries, rejected {rejected_swaps} swaps.")
        
        return jsonify({
            "ok": True,
            "message": "Schedule unpublished successfully",
            "deleted_unavailability": deleted_unavail,
            "rejected_swaps": rejected_swaps,
            "notifications_sent": notifications_sent,
            "emails_sent": emails_sent
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to unpublish unit {unit_id}: {str(e)}")
        return jsonify({"ok": False, "error": f"Failed to unpublish schedule: {str(e)}"}), 500


@unitcoordinator_bp.get("/units/<int:unit_id>/modules")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def get_unit_modules(unit_id: int):
    """Get all modules for a unit."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    try:
        modules = Module.query.filter_by(unit_id=unit_id).all()
        
        return jsonify({
            "ok": True,
            "modules": [{
                "id": m.id,
                "name": m.module_name,
                "session_type": m.module_type
            } for m in modules]
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed to fetch modules: {str(e)}"}), 500


@unitcoordinator_bp.post("/units/<int:unit_id>/sessions/manual")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def create_manual_session(unit_id: int):
    """Create a new session manually for a unit."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    try:
        data = request.get_json()
        from datetime import datetime
        
        # Check if using existing module or creating new
        if data.get('existing_module_id'):
            # Use existing module
            module = Module.query.get(data['existing_module_id'])
            if not module or module.unit_id != unit_id:
                return jsonify({"ok": False, "error": "Invalid module selected"}), 400
            
            # Validate required fields for existing module
            required_fields = ['date', 'start_time', 'end_time', 'location']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({"ok": False, "error": f"Missing required field: {field}"}), 400
        else:
            # Create new module
            required_fields = ['name', 'date', 'module_type', 'start_time', 'end_time', 'location']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({"ok": False, "error": f"Missing required field: {field}"}), 400
            
            # Create a module with the session name
            module = Module.query.filter_by(unit_id=unit_id, module_name=data['name']).first()
            if not module:
                module = Module(
                    unit_id=unit_id,
                    module_name=data['name'],
                    module_type=data['module_type']
                )
                db.session.add(module)
                db.session.flush()  # Get the ID
        
        # Parse datetime
        session_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        start_time = datetime.strptime(f"{data['date']} {data['start_time']}", '%Y-%m-%d %H:%M')
        end_time = datetime.strptime(f"{data['date']} {data['end_time']}", '%Y-%m-%d %H:%M')
        
        # Validate time range
        if start_time >= end_time:
            return jsonify({"ok": False, "error": "End time must be after start time"}), 400
        
        # Create session
        session = Session(
            module_id=module.id,
            session_type=module.module_type,
            start_time=start_time,
            end_time=end_time,
            location=data['location'],
            max_facilitators=1,  # Default to 1, can be updated later
            lead_staff_required=1,
            support_staff_required=0
        )
        
        db.session.add(session)
        db.session.commit()
        
        return jsonify({
            "ok": True,
            "session": {
                "id": session.id,
                "name": module.module_name,
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat(),
                "location": session.location,
                "module_type": module.module_type
            }
        })
        
    except ValueError as e:
        return jsonify({"ok": False, "error": f"Invalid date/time format: {str(e)}"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to create session: {str(e)}"}), 500


@unitcoordinator_bp.get("/units/<int:unit_id>/facilitators")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def list_facilitators(unit_id: int):
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404

    # Get session date, time, and module if provided
    session_date_str = request.args.get('session_date')
    session_start_time_str = request.args.get('session_start_time')
    session_end_time_str = request.args.get('session_end_time')
    module_id_str = request.args.get('module_id')
    
    session_date = None
    session_start_time = None
    session_end_time = None
    module_id = None
    
    if session_date_str:
        try:
            from datetime import datetime, time as dt_time
            session_date = datetime.strptime(session_date_str, '%Y-%m-%d').date()
            
            # Parse session times if provided
            if session_start_time_str:
                session_start_time = datetime.strptime(session_start_time_str, '%H:%M').time()
            if session_end_time_str:
                session_end_time = datetime.strptime(session_end_time_str, '%H:%M').time()
        except ValueError:
            pass  # Invalid date/time format, ignore
    
    if module_id_str:
        try:
            module_id = int(module_id_str)
        except ValueError:
            pass  # Invalid module ID, ignore

    facs = (
        db.session.query(User)
        .join(UnitFacilitator, UnitFacilitator.user_id == User.id)
        .filter(UnitFacilitator.unit_id == unit.id)
        .order_by(User.first_name.asc(), User.last_name.asc())
        .all()
    )
    
    facilitators = []
    for fac in facs:
        is_unavailable = False
        unavailability_reason = None
        skill_level = None
        skill_label = None
        
        # Check if facilitator is unavailable on this date
        if session_date:
            unavailability = Unavailability.query.filter_by(
                user_id=fac.id,
                unit_id=unit_id,
                date=session_date
            ).first()
            
            if unavailability:
                # Check if it's full day or if times overlap
                if unavailability.is_full_day:
                    is_unavailable = True
                    unavailability_reason = "Full day"
                elif session_start_time and session_end_time and unavailability.start_time and unavailability.end_time:
                    # Check time overlap: session overlaps if it starts before unavailability ends AND ends after unavailability starts
                    if session_start_time < unavailability.end_time and session_end_time > unavailability.start_time:
                        is_unavailable = True
                        unavailability_reason = f"{unavailability.start_time.strftime('%H:%M')} - {unavailability.end_time.strftime('%H:%M')}"
                else:
                    # If no session times provided, assume unavailable for the whole day
                    is_unavailable = True
                    unavailability_reason = f"{unavailability.start_time.strftime('%H:%M')} - {unavailability.end_time.strftime('%H:%M')}"
        
        # Get skill level for this module if provided
        if module_id:
            skill = FacilitatorSkill.query.filter_by(
                facilitator_id=fac.id,
                module_id=module_id
            ).first()
            
            if skill:
                skill_level = skill.skill_level.value
                # Map skill level to display label
                skill_map = {
                    'proficient': '✓ Proficient',
                    'have_run_before': '✓ Have Run Before',
                    'have_some_skill': '✓ Have Some Skill',
                    'no_interest': '✗ No Interest'
                }
                skill_label = skill_map.get(skill_level, skill_level)
        
        facilitators.append({
            "id": fac.id,
            "name": fac.full_name,
            "email": fac.email,
            "first_name": fac.first_name,
            "last_name": fac.last_name,
            "phone_number": fac.phone_number,
            "staff_number": fac.staff_number,
            "is_unavailable": is_unavailable,
            "unavailability_reason": unavailability_reason,
            "skill_level": skill_level,
            "skill_label": skill_label
        })
    
    return jsonify({"ok": True, "facilitators": facilitators})


@unitcoordinator_bp.get("/units/<int:unit_id>/facilitators-with-unavailability")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def list_facilitators_with_unavailability(unit_id: int):
    """Get facilitators for a unit with their global unavailability status"""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404

    # Get all facilitators for this unit
    facs = (
        db.session.query(User)
        .join(UnitFacilitator, User.id == UnitFacilitator.user_id)
        .filter(UnitFacilitator.unit_id == unit_id)
        .all()
    )
    
    facilitators = []
    for fac in facs:
        # Check if facilitator has MANUAL GLOBAL unavailability (not auto-generated)
        has_manual_global = db.session.query(Unavailability).filter(
            Unavailability.user_id == fac.id,
            Unavailability.unit_id == None,  # Global only
            Unavailability.source_session_id == None  # Manual only (not auto-generated)
        ).first() is not None
        
        facilitators.append({
            "id": fac.id,
            "full_name": fac.full_name,
            "email": fac.email,
            "first_name": fac.first_name,
            "last_name": fac.last_name,
            "has_manual_global_unavailability": has_manual_global
        })
    
    return jsonify({"ok": True, "facilitators": facilitators})


# ---------- CAS CSV Upload (auto-generate sessions) ----------
@unitcoordinator_bp.post("/units/<int:unit_id>/upload_cas_csv")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def upload_cas_csv(unit_id: int):
    """
    Accept a CAS-style CSV and create sessions.
    Recognized headers (case-insensitive):
      - activity_group_code (maps to session/module name)
      - day_of_week         (Monday..Sunday)
      - start_time          (HH:MM 24h)
      - duration            (minutes integer)
      - weeks               (e.g. "1-12", "2,4,6-10") relative to unit start week
      - location            (venue name). We'll ensure Venue and UnitVenue link.

    Other columns are ignored.
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404

    file = request.files.get("cas_csv")
    if not file:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    try:
        text = file.read().decode("utf-8", errors="replace")
        reader = csv.DictReader(StringIO(text))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed to read CSV: {e}"}), 400

    # Normalize headers (accept wide variety – we will resolve per-row using aliases)
    fns = [fn.strip().lower() for fn in (reader.fieldnames or [])]
    if not fns:
        return jsonify({"ok": False, "error": "CSV has no headers"}), 400

    # Helpers
    dow_map = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1, "tues": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }

    def parse_weeks(s: str):
        """Return sorted unique week numbers (1-based) from a string like '1-12,14,16-18'."""
        out = set()
        s = (s or "").replace(" ", "")
        if not s:
            return []
        for part in s.split(','):
            if '-' in part:
                a, b = part.split('-', 1)
                try:
                    a, b = int(a), int(b)
                except ValueError:
                    continue
                if a <= 0 or b <= 0:
                    continue
                if a > b:
                    a, b = b, a
                out.update(range(a, b + 1))
            else:
                try:
                    n = int(part)
                    if n > 0:
                        out.add(n)
                except ValueError:
                    continue
        return sorted(out)

    # Also allow 'weeks' to be explicit dates/ranges (e.g., '30/6' or '24/7-28/8, 11/9-16/10')
    def parse_week_dates(s: str):
        """Return a list of date objects expanded weekly when 'weeks' contains explicit
        date tokens or date ranges. For a token like '24/7-28/8' we add dates every 7 days
        from the first to the last date (inclusive). Year is inferred from the unit start.
        """
        s = (s or "").strip()
        if not s or "/" not in s:
            return []
        results = []
        guess_year = unit.start_date.year if unit.start_date else date.today().year
        start_month = unit.start_date.month if unit.start_date else 1

        def parse_one_date(tok: str):
            m = re.match(r"^(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?$", tok)
            if not m:
                return None
            d_str, m_str, y_str = m.groups()
            day_i = int(d_str)
            mon_i = int(m_str)
            if y_str:
                yr_i = int(y_str)
                if yr_i < 100:
                    yr_i += 2000
            else:
                yr_i = guess_year
                if mon_i < start_month:
                    yr_i += 1
            try:
                return date(yr_i, mon_i, day_i)
            except Exception:
                return None

        for token in [t.strip() for t in s.split(',') if t.strip()]:
            if '-' in token:
                a, b = [p.strip() for p in token.split('-', 1)]
                d1 = parse_one_date(a)
                d2 = parse_one_date(b)
                if not d1 or not d2:
                    continue
                if d1 > d2:
                    d1, d2 = d2, d1
                cur = d1
                while cur <= d2:
                    results.append(cur)
                    cur = cur + timedelta(days=7)
            else:
                d = parse_one_date(token)
                if d:
                    results.append(d)
        return results

    # Find Monday of the unit start week (or just use start_date itself if Monday)
    if not unit.start_date:
        return jsonify({"ok": False, "error": "Unit start_date is required for CAS parsing"}), 400
    unit_start = unit.start_date
    start_monday = unit_start - timedelta(days=((unit_start.weekday() + 7) % 7))

    # Local helpers shared with other endpoints
    name_to_venue = {v.name.strip().lower(): v for v in Venue.query.all()}

    def ensure_unit_venue(venue_name: str) -> Venue:
        key = (venue_name or "").strip().lower()
        if not key:
            return None
        venue = name_to_venue.get(key)
        if not venue:
            venue = Venue(name=venue_name.strip())
            db.session.add(venue)
            db.session.flush()
            name_to_venue[key] = venue
        if not UnitVenue.query.filter_by(unit_id=unit.id, venue_id=venue.id).first():
            db.session.add(UnitVenue(unit_id=unit.id, venue_id=venue.id))
        return venue

    created = 0
    skipped = 0
    errors = []
    created_ids = []

    MAX_ROWS = 5000
    # Column alias helpers
    def first_value(d: dict, keys):
        for k in keys:
            if k in d and (str(d[k]).strip() != ""):
                return str(d[k]).strip()
        return ""

    name_keys = ["activity_group_code", "activity", "session", "module", "module_name", "activity_code", "group", "title"]
    dow_keys = ["day_of_week", "day", "dow"]
    start_keys = ["start_time", "start", "from"]
    time_keys = ["time", "time_range", "session_time"]  # may contain range 'HH:MM-HH:MM'
    duration_keys = ["duration", "minutes", "mins", "length"]
    weeks_keys = ["weeks", "week", "teaching_weeks", "dates", "date_weeks"]
    explicit_date_keys = ["date", "session_date"]  # single date per row (dd/mm or dd/mm/yyyy)
    location_keys = ["location", "venue", "room", "place"]

    for idx, row in enumerate(reader, start=2):
        if idx - 1 > MAX_ROWS:
            skipped += 1
            errors.append(f"Row {idx}: exceeded row limit")
            continue

        # Row values via aliases
        lowered_row = {k.strip().lower(): v for k, v in row.items()}
        name_in = first_value(lowered_row, name_keys)
        dow_in = first_value(lowered_row, dow_keys).lower()
        start_time_in = first_value(lowered_row, start_keys)
        time_range_in = first_value(lowered_row, time_keys)
        duration_in = first_value(lowered_row, duration_keys)
        weeks_in = first_value(lowered_row, weeks_keys)
        explicit_date_in = first_value(lowered_row, explicit_date_keys)
        location_in = first_value(lowered_row, location_keys)

        # We need at minimum: a location AND (either time-range or start+duration) AND (either dates/weeks or a single date)
        if not location_in:
            skipped += 1
            errors.append(f"Row {idx}: missing required fields")
            continue

        # Skip non-physical or unspecified locations per parsing rules
        def _is_physical_location(loc: str) -> bool:
            if not loc:
                return False
            val = loc.strip().lower()
            if val in {"tba", "tbd", "n/a", "na"}:
                return False
            banned_keywords = [
                "online", "virtual", "zoom", "teams", "webex",
                "collaborate", "interactive", "recorded", "recording",
                "stream", "streaming"
            ]
            return not any(k in val for k in banned_keywords)

        if not _is_physical_location(location_in):
            skipped += 1
            # Only log an error message if the row had a location but it's non-physical
            if location_in:
                errors.append(f"Row {idx}: non-physical location '{location_in}' skipped")
            else:
                errors.append(f"Row {idx}: missing/unspecific location skipped")
            continue

        weekday = dow_map.get(dow_in) if dow_in else None

        # Time parsing: allow either explicit range or start+duration
        duration_min = None
        if time_range_in:
            # Accept 'HH:MM-HH:MM' style
            m = TIME_RANGE_RE.match(time_range_in.replace('–', '-').replace('—', '-'))
            if not m:
                skipped += 1
                errors.append(f"Row {idx}: invalid time range '{time_range_in}'")
                continue
            h1, m1, h2, m2 = map(int, m.groups())
            hh, mm = h1, m1
            duration_min = (h2 * 60 + m2) - (h1 * 60 + m1)
            if duration_min <= 0:
                skipped += 1
                errors.append(f"Row {idx}: invalid time range (end before start)")
                continue
        else:
            try:
                hh, mm = [int(x) for x in re.split(r"[:\.]", start_time_in, maxsplit=1)]
                if not (0 <= hh <= 23 and 0 <= mm <= 59):
                    raise ValueError
            except Exception:
                skipped += 1
                errors.append(f"Row {idx}: invalid start_time '{start_time_in}'")
                continue

            if duration_in:
                try:
                    duration_min = int(duration_in)
                    if duration_min <= 0:
                        raise ValueError
                except Exception:
                    skipped += 1
                    errors.append(f"Row {idx}: invalid duration '{duration_in}'")
                    continue
            else:
                skipped += 1
                errors.append(f"Row {idx}: missing duration/time range")
                continue

        # Date targets: explicit date(s) column, or 'weeks' (dates or week numbers)
        week_dates = parse_week_dates(explicit_date_in or weeks_in)
        if week_dates:
            # Use explicit dates; ignore day_of_week field and map each date directly
            targets = []
            for d0 in week_dates:
                targets.append(d0)
        else:
            weeks_list = parse_weeks(weeks_in)
            if not weeks_list:
                skipped += 1
                errors.append(f"Row {idx}: invalid weeks '{weeks_in}'")
                continue
            # Convert week numbers to actual dates by weekday
            targets = []
            for w in weeks_list:
                # If weekday not present, default to unit start weekday
                wd = weekday if weekday is not None else unit_start.weekday()
                d0 = start_monday + timedelta(days=(w - 1) * 7 + wd)
                targets.append(d0)

        # Ensure module and venue (cleanup complex location strings like 'EZONENTH: [ 109] Room (30/6)')
        mod = _get_or_create_module_by_name(unit, name_in)
        clean_location = (location_in or "").strip()
        if clean_location:
            # If there are multiple comma-separated venues, pick the first physical one
            candidates = [t.strip() for t in clean_location.split(',') if t.strip()]
            chosen_token = None
            for tok in candidates:
                # Reject non-physical tokens early
                low = tok.lower()
                if any(k in low for k in [
                    "online", "virtual", "zoom", "teams", "webex",
                    "collaborate", "interactive", "recorded", "recording",
                    "stream", "streaming", "tba", "tbd", "n/a", "na",
                    "lecture recording"
                ]):
                    continue
                chosen_token = tok
                break
            # Fallback to first token if none explicitly chosen (kept for backwards compatibility)
            if not chosen_token and candidates:
                chosen_token = candidates[0]

            clean_location = chosen_token or ''
            # remove campus/prefix codes before colon
            if ':' in clean_location:
                clean_location = clean_location.split(':', 1)[1]
            # strip bracketed codes and parentheses
            clean_location = re.sub(r"\[[^\]]*\]", "", clean_location)
            clean_location = re.sub(r"\([^\)]*\)", "", clean_location)
            clean_location = clean_location.strip()
        # After cleaning, ensure we still have a non-empty physical venue
        if not clean_location:
            skipped += 1
            errors.append(f"Row {idx}: location became empty after normalization, skipped")
            continue
        venue_obj = ensure_unit_venue(clean_location) if clean_location else None

        for day_date in targets:
            # If target date provided doesn't match requested weekday, we will trust the date
            start_dt = datetime(day_date.year, day_date.month, day_date.day, hh, mm)
            end_dt = start_dt + timedelta(minutes=duration_min)

            if not _within_unit_range(unit, start_dt) or not _within_unit_range(unit, end_dt):
                skipped += 1
                continue

            # Avoid duplicates
            exists = (
                Session.query
                .filter(
                    Session.module_id == mod.id,
                    Session.start_time == start_dt,
                    Session.end_time == end_dt,
                )
                .first()
            )
            if exists:
                skipped += 1
                continue

            try:
                s = Session(
                    module_id=mod.id,
                    session_type="general",
                    start_time=start_dt,
                    end_time=end_dt,
                    day_of_week=start_dt.weekday(),
                    location=location_in or None,
                    required_skills=None,
                    max_facilitators=1,
                )
                db.session.add(s)
                db.session.flush()
                created_ids.append(s.id)
                created += 1
            except Exception as e:
                db.session.rollback()
                errors.append(f"Row {idx}: database error: {e}")
                continue

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Commit failed: {e}"}), 500

    return jsonify({
        "ok": True,
        "created": created,
        "skipped": skipped,
        "errors": errors[:30],
        "created_session_ids": created_ids,
    })

@unitcoordinator_bp.delete("/units/<int:unit_id>/clear_csv_sessions")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def clear_csv_sessions(unit_id: int):
    """
    Delete all sessions for a unit. This allows users to remove sessions
    that were created via CSV upload and start fresh.
    """
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404

    try:
        # Get all modules for this unit
        modules = Module.query.filter_by(unit_id=unit.id).all()
        module_ids = [m.id for m in modules]
        
        # Delete all assignments first (foreign key constraint)
        deleted_assignments = Assignment.query.filter(
            Assignment.session_id.in_(
                db.session.query(Session.id).filter(
                    Session.module_id.in_(module_ids)
                )
            )
        ).delete(synchronize_session=False)
        
        # Delete all sessions for this unit's modules
        deleted_sessions = Session.query.filter(
            Session.module_id.in_(module_ids)
        ).delete(synchronize_session=False)
        
        db.session.commit()
        
        return jsonify({
            "ok": True,
            "deleted_sessions": deleted_sessions,
            "deleted_assignments": deleted_assignments
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": f"Failed to delete sessions: {e}"}), 500

@unitcoordinator_bp.get("/units/<int:unit_id>/dashboard-sessions")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def get_dashboard_sessions(unit_id: int):
    """Get session data for dashboard display - today's sessions, upcoming sessions, and statistics"""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404

    from datetime import datetime, timedelta, date
    from flask import request
    
    # Get week parameters from request
    week_start_str = request.args.get('week_start')
    week_end_str = request.args.get('week_end')
    
    today = date.today()
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)
    
    # Parse week dates if provided
    week_start_date = None
    week_end_date = None
    if week_start_str and week_end_str:
        try:
            week_start_date = datetime.strptime(week_start_str, '%Y-%m-%d').date()
            week_end_date = datetime.strptime(week_end_str, '%Y-%m-%d').date()
        except ValueError:
            pass  # Use default dates if parsing fails

    # Get today's sessions
    today_sessions = (
        db.session.query(Session, Module, Assignment, User)
        .join(Module, Module.id == Session.module_id)
        .outerjoin(Assignment, Assignment.session_id == Session.id)
        .outerjoin(User, User.id == Assignment.facilitator_id)
        .filter(
            Module.unit_id == unit.id,
            Session.start_time >= datetime.combine(today, datetime.min.time()),
            Session.start_time < datetime.combine(tomorrow, datetime.min.time())
        )
        .order_by(Session.start_time.asc())
        .all()
    )

    # Get upcoming sessions (next 7 days)
    upcoming_sessions = (
        db.session.query(Session, Module, Assignment, User)
        .join(Module, Module.id == Session.module_id)
        .outerjoin(Assignment, Assignment.session_id == Session.id)
        .outerjoin(User, User.id == Assignment.facilitator_id)
        .filter(
            Module.unit_id == unit.id,
            Session.start_time >= datetime.combine(tomorrow, datetime.min.time()),
            Session.start_time < datetime.combine(week_end, datetime.min.time())
        )
        .order_by(Session.start_time.asc())
        .all()
    )

    # Process today's sessions
    today_data = []
    for session, module, assignment, user in today_sessions:
        # Get all facilitators for this session with roles
        facilitators = []
        if session.assignments:
            for session_assignment in session.assignments:
                if session_assignment.facilitator:
                    facilitators.append({
                        "name": session_assignment.facilitator.full_name,
                        "initials": f"{session_assignment.facilitator.first_name[0] if session_assignment.facilitator.first_name else ''}{session_assignment.facilitator.last_name[0] if session_assignment.facilitator.last_name else ''}".upper() or session_assignment.facilitator.email[0].upper(),
                        "role": getattr(session_assignment, 'role', 'lead'),
                        "is_confirmed": session_assignment.is_confirmed
                    })
        
        # Determine session status
        status = "unassigned"
        if facilitators:
            status = "assigned"  # Any facilitator assigned, regardless of confirmation status
        
        today_data.append({
            "id": session.id,
            "name": module.module_name or "Session",
            "time": f"{session.start_time.strftime('%I:%M %p')} - {session.end_time.strftime('%I:%M %p')}",
            "location": session.location or "TBA",
            "status": status,
            "facilitators": facilitators
        })

    # Process upcoming sessions
    upcoming_data = []
    for session, module, assignment, user in upcoming_sessions:
        # Get all facilitators for this session with roles
        facilitators = []
        if session.assignments:
            for session_assignment in session.assignments:
                if session_assignment.facilitator:
                    facilitators.append({
                        "name": session_assignment.facilitator.full_name,
                        "initials": f"{session_assignment.facilitator.first_name[0] if session_assignment.facilitator.first_name else ''}{session_assignment.facilitator.last_name[0] if session_assignment.facilitator.last_name else ''}".upper() or session_assignment.facilitator.email[0].upper(),
                        "role": getattr(session_assignment, 'role', 'lead'),
                        "is_confirmed": session_assignment.is_confirmed
                    })
        
        # Determine session status
        status = "unassigned"
        if facilitators:
            status = "assigned"  # Any facilitator assigned, regardless of confirmation status
        
        # Determine relative date
        session_date = session.start_time.date()
        if session_date == tomorrow:
            relative_date = "Tomorrow"
        else:
            relative_date = session_date.strftime("%A")
        
        upcoming_data.append({
            "id": session.id,
            "name": module.module_name or "Session",
            "date": relative_date,
            "time": session.start_time.strftime("%I:%M %p"),
            "location": session.location or "TBA",
            "status": status,
            "facilitators": facilitators
        })

    # Get facilitator session counts for bar chart
    facilitator_counts = (
        db.session.query(
            User.first_name,
            User.last_name,
            User.email,
            func.count(Assignment.id).label('session_count')
        )
        .join(Assignment, Assignment.facilitator_id == User.id)
        .join(Session, Session.id == Assignment.session_id)
        .join(Module, Module.id == Session.module_id)
        .filter(Module.unit_id == unit.id)
        .group_by(User.id, User.first_name, User.last_name, User.email)
        .order_by(func.count(Assignment.id).desc())
        .limit(10)
        .all()
    )

    facilitator_data = []
    for first_name, last_name, email, count in facilitator_counts:
        # Use actual database names, don't fall back to email
        name = f"{first_name or ''} {last_name or ''}".strip()
        if not name:
            name = "Unknown"  # Don't use email as name
        
        # Get detailed facilitator info
        facilitator = User.query.filter_by(email=email).first()
        if facilitator:
            # Get all assignments for this facilitator in this unit
            assignments = db.session.query(Assignment).join(Session).join(Module).filter(
                Assignment.facilitator_id == facilitator.id,
                Module.unit_id == unit.id
            ).all()
            
            # Calculate total hours
            total_hours = 0
            for assignment in assignments:
                session = assignment.session
                duration = (session.end_time - session.start_time).total_seconds() / 3600
                total_hours += duration
            
            # Get the most recent session date
            latest_session = db.session.query(Session).join(Assignment).join(Module).filter(
                Assignment.facilitator_id == facilitator.id,
                Module.unit_id == unit.id
            ).order_by(Session.start_time.desc()).first()
            
            latest_date = latest_session.start_time.date().isoformat() if latest_session else None
            
            # Calculate total hours (all assignments across all time)
            total_assigned_hours = sum(
                (a.session.end_time - a.session.start_time).total_seconds() / 3600 
                for a in assignments
            )
            
            # Calculate weekly hours (assignments within the specified week)
            weekly_assigned_hours = 0
            if week_start_date and week_end_date:
                weekly_assignments = [
                    a for a in assignments 
                    if week_start_date <= a.session.start_time.date() <= week_end_date
                ]
                weekly_assigned_hours = sum(
                    (a.session.end_time - a.session.start_time).total_seconds() / 3600 
                    for a in weekly_assignments
                )
            else:
                # If no week specified, use total hours as fallback
                weekly_assigned_hours = total_assigned_hours
            
            facilitator_data.append({
                "name": name,
                "student_number": facilitator.email.split('@')[0] if '@' in facilitator.email else "N/A",
                "session_count": count,
                "assigned_hours": round(weekly_assigned_hours, 2),  # Weekly hours
                "total_hours": round(total_assigned_hours, 2),      # Total hours
                "date": latest_date,
                "email": facilitator.email,
                "phone": "N/A",
                "status": "active" if count > 0 else "inactive"
            })
        else:
            # Fallback for facilitators not found in User table
            # Use actual database names, don't fall back to email
            fallback_name = f"{first_name or ''} {last_name or ''}".strip()
            if not fallback_name:
                fallback_name = "Unknown"  # Don't use email as name
            facilitator_data.append({
                "name": fallback_name,
                "student_number": email.split('@')[0] if '@' in email else "N/A",
                "session_count": count,
                "assigned_hours": 0,  # Weekly hours (0 for fallback)
                "total_hours": 0,      # Total hours (0 for fallback)
                "date": None,
                "email": email,
                "phone": "N/A",
                "status": "active" if count > 0 else "inactive"
            })

    # Get swap requests over time (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    swap_requests = (
        db.session.query(SwapRequest.created_at)
        .join(Assignment, Assignment.id == SwapRequest.requester_assignment_id)
        .join(Session, Session.id == Assignment.session_id)
        .join(Module, Module.id == Session.module_id)
        .filter(
            Module.unit_id == unit.id,
            SwapRequest.created_at >= thirty_days_ago
        )
        .order_by(SwapRequest.created_at.asc())
        .all()
    )

    # Group swap requests by date
    swap_data = {}
    for swap_request, in swap_requests:
        date_key = swap_request.date().isoformat()
        swap_data[date_key] = swap_data.get(date_key, 0) + 1

    # Convert to array format for chart
    swap_chart_data = []
    for i in range(30):
        date_obj = today - timedelta(days=29-i)
        date_str = date_obj.isoformat()
        swap_chart_data.append({
            "date": date_str,
            "count": swap_data.get(date_str, 0)
        })

    return jsonify({
        "ok": True,
        "today_sessions": today_data,
        "upcoming_sessions": upcoming_data,
        "facilitator_counts": facilitator_data,
        "swap_requests": swap_chart_data,
        "week_session_count": len(today_data) + len(upcoming_data)
    })

@unitcoordinator_bp.get("/units/<int:unit_id>/bulk-staffing/filters")

@login_required

@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])

def get_bulk_staffing_filters(unit_id: int):

    """Get filter options for bulk staffing based on existing sessions."""

    user = get_current_user()

    unit = _get_user_unit_or_404(user, unit_id)

    if not unit:

        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404



    filter_type = request.args.get("type", "activity")

    

    try:

        if filter_type == "all_sessions":

            # For all sessions, we don't need to return any options
            options = []

        elif filter_type == "activity":

            # Get unique session types

            session_types = (

                db.session.query(Session.session_type)

                .join(Module)

                .filter(Module.unit_id == unit.id, Session.session_type.isnot(None))

                .distinct()

                .all()

            )

            options = [{"value": st[0], "label": st[0]} for st in session_types if st[0]]

            

        elif filter_type == "session_name":

            # Get unique session names (using session_type as name for now)

            session_names = (

                db.session.query(Session.session_type)

                .join(Module)

                .filter(Module.unit_id == unit.id, Session.session_type.isnot(None))

                .distinct()

                .all()

            )

            options = [{"value": sn[0], "label": sn[0]} for sn in session_names if sn[0]]

            

        elif filter_type == "module":

            # Get modules for this unit (excluding the default "General" module)

            modules = (

                db.session.query(Module.id, Module.module_name)

                .filter(Module.unit_id == unit.id, Module.module_name != "General")

                .all()

            )

            options = [{"value": str(m[0]), "label": m[1]} for m in modules]

            

        else:

            return jsonify({"ok": False, "error": "Invalid filter type"}), 400



        return jsonify({"ok": True, "options": options})

        

    except Exception as e:

        return jsonify({"ok": False, "error": str(e)}), 500





@unitcoordinator_bp.get("/units/<int:unit_id>/bulk-staffing/sessions")

@login_required

@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])

def get_bulk_staffing_sessions(unit_id: int):

    """Get sessions that match the bulk staffing filter criteria."""

    user = get_current_user()

    unit = _get_user_unit_or_404(user, unit_id)

    if not unit:

        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404



    filter_type = request.args.get("type", "activity")

    filter_value = request.args.get("value", "")

    

    # For all_sessions, we don't need a filter value
    if filter_type != "all_sessions" and not filter_value:

        return jsonify({"ok": False, "error": "Filter value required"}), 400

    

    try:

        query = Session.query.join(Module).filter(Module.unit_id == unit.id)

        

        if filter_type == "all_sessions":

            # No additional filtering - get all sessions

            pass

        elif filter_type == "activity":

            query = query.filter(Session.session_type == filter_value)

        elif filter_type == "session_name":

            query = query.filter(Session.session_type == filter_value)

        elif filter_type == "module":

            query = query.filter(Module.id == int(filter_value))

        else:

            return jsonify({"ok": False, "error": "Invalid filter type"}), 400



        sessions = query.all()

        

        # Serialize sessions for display

        session_data = []

        for session in sessions:

            session_data.append({

                "id": session.id,

                "name": session.session_type or "Unnamed Session",

                "start_time": session.start_time.isoformat(),

                "end_time": session.end_time.isoformat(),

                "location": session.location or "TBA",

                "lead_staff_required": session.lead_staff_required or 1,

                "support_staff_required": session.support_staff_required or 0,

                "module_name": session.module.module_name

            })



        return jsonify({"ok": True, "sessions": session_data})

        

    except Exception as e:

        return jsonify({"ok": False, "error": str(e)}), 500





@unitcoordinator_bp.get("/units/<int:unit_id>/conflicts")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def get_schedule_conflicts(unit_id: int):
    """Get detailed information about schedule conflicts."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
  
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    try:
        conflicts = []
        
        # Get all assignments for this unit
        assignments_query = (
            db.session.query(Assignment, Session, User)
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .join(User, User.id == Assignment.facilitator_id)
            .filter(Module.unit_id == unit.id)
            .all()
        )
        
        # Group assignments by facilitator
        facilitator_sessions = {}
        for assignment, session, facilitator in assignments_query:
            facilitator_id = facilitator.id
            if facilitator_id not in facilitator_sessions:
                facilitator_sessions[facilitator_id] = []
            
            facilitator_sessions[facilitator_id].append({
                'assignment_id': assignment.id,
                'session_id': session.id,
                'start_time': session.start_time,
                'end_time': session.end_time,
                'module_name': session.module.module_name,
                'facilitator_name': f"{facilitator.first_name} {facilitator.last_name}".strip()
            })
        
        # Detect overlapping sessions
        for facilitator_id, sessions in facilitator_sessions.items():
            sessions.sort(key=lambda x: x['start_time'])
            facilitator_name = sessions[0]['facilitator_name']
            
            for i in range(len(sessions)):
                current_session = sessions[i]
                
                for j in range(i + 1, len(sessions)):
                    next_session = sessions[j]
                    
                    # Check for time overlap
                    if current_session['end_time'] > next_session['start_time']:
                        conflict = {
                            'type': 'schedule_overlap',
                            'facilitator_id': facilitator_id,
                            'facilitator_name': facilitator_name,
                            'session1': {
                                'id': current_session['session_id'],
                                'module': current_session['module_name'],
                                'start_time': current_session['start_time'].isoformat(),
                                'end_time': current_session['end_time'].isoformat()
                            },
                            'session2': {
                                'id': next_session['session_id'],
                                'module': next_session['module_name'],
                                'start_time': next_session['start_time'].isoformat(),
                                'end_time': next_session['end_time'].isoformat()
                            }
                        }
                        conflicts.append(conflict)
        
        # Check for unavailability conflicts
        unavailability_conflicts_query = (
            db.session.query(Assignment, Unavailability, Session, User)
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .join(User, User.id == Assignment.facilitator_id)
            .join(Unavailability, 
                  db.and_(
                      Unavailability.user_id == Assignment.facilitator_id,
                      Unavailability.unit_id.is_(None),  # Check GLOBAL unavailability only
                      db.func.date(Session.start_time) == Unavailability.date
                  )
            )
            .filter(
                Module.unit_id == unit.id,
                db.or_(
                    Unavailability.is_full_day == True,
                    db.and_(
                        Unavailability.start_time <= db.func.time(Session.start_time),
                        Unavailability.end_time >= db.func.time(Session.end_time)
                    )
                )
            )
            .all()
        )
        
        for assignment, unavailability, session, facilitator in unavailability_conflicts_query:
            conflict = {
                'type': 'unavailability_conflict',
                'facilitator_id': facilitator.id,
                'facilitator_name': f"{facilitator.first_name} {facilitator.last_name}".strip(),
                'session': {
                    'id': session.id,
                    'module': session.module.module_name,
                    'start_time': session.start_time.isoformat(),
                    'end_time': session.end_time.isoformat()
                },
                'unavailability': {
                    'date': unavailability.date.isoformat(),
                    'start_time': unavailability.start_time.isoformat() if unavailability.start_time else None,
                    'end_time': unavailability.end_time.isoformat() if unavailability.end_time else None,
                    'is_full_day': unavailability.is_full_day,
                    'reason': unavailability.reason
                }
            }
            conflicts.append(conflict)
        
        # Check for skill conflicts (facilitators marked as "no_interest" but assigned)
        skill_conflicts_query = (
            db.session.query(Assignment, Session, User, FacilitatorSkill)
            .join(Session, Session.id == Assignment.session_id)
            .join(Module, Module.id == Session.module_id)
            .join(User, User.id == Assignment.facilitator_id)
            .join(FacilitatorSkill, 
                  db.and_(
                      FacilitatorSkill.facilitator_id == Assignment.facilitator_id,
                      FacilitatorSkill.module_id == Session.module_id
                  )
            )
            .filter(
                Module.unit_id == unit.id,
                FacilitatorSkill.skill_level == SkillLevel.NO_INTEREST
            )
            .all()
        )
        
        for assignment, session, facilitator, skill in skill_conflicts_query:
            conflict = {
                'type': 'skill_conflict',
                'facilitator_id': facilitator.id,
                'facilitator_name': f"{facilitator.first_name} {facilitator.last_name}".strip(),
                'session': {
                    'id': session.id,
                    'module': session.module.module_name,
                    'start_time': session.start_time.isoformat(),
                    'end_time': session.end_time.isoformat()
                },
                'skill_level': 'no_interest',
                'message': f"{facilitator.first_name} {facilitator.last_name} is marked as 'No Interest' for {session.module.module_name}"
            }
            conflicts.append(conflict)
        
        return jsonify({
            "ok": True,
            "conflicts": conflicts,
            "total_conflicts": len(conflicts),
            "unit_name": unit.unit_name
        })
        
    except Exception as e:
        logging.error(f"Error fetching schedule conflicts: {str(e)}")
        return jsonify({"ok": False, "error": str(e)}), 500


@unitcoordinator_bp.get("/units/<int:unit_id>/attendance-summary")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def get_attendance_summary(unit_id: int):
    """Get attendance summary data for facilitators in a unit."""
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    
    if not unit:
        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404
    
    try:
        # Get all facilitators assigned to sessions in this unit
        facilitators_query = db.session.query(User).join(Assignment).join(Session).join(Module).filter(
            Module.unit_id == unit.id,
            User.role == UserRole.FACILITATOR
        ).distinct()
        
        facilitators_data = []
        
        for facilitator in facilitators_query:
            # Get all assignments for this facilitator in this unit
            assignments = db.session.query(Assignment).join(Session).join(Module).filter(
                Assignment.facilitator_id == facilitator.id,
                Module.unit_id == unit.id
            ).all()
            
            # Calculate total hours and session count
            total_hours = 0
            session_count = len(assignments)
            
            for assignment in assignments:
                session = assignment.session
                duration = (session.end_time - session.start_time).total_seconds() / 3600  # Convert to hours
                total_hours += duration
            
            # Get the most recent session date
            latest_session = db.session.query(Session).join(Assignment).join(Module).filter(
                Assignment.facilitator_id == facilitator.id,
                Module.unit_id == unit.id
            ).order_by(Session.start_time.desc()).first()
            
            latest_date = latest_session.start_time.date().isoformat() if latest_session else None
            
            # Calculate assigned hours (all assignments, not just confirmed)
            assigned_hours = sum(
                (a.session.end_time - a.session.start_time).total_seconds() / 3600 
                for a in assignments
            )
            
            facilitator_data = {
                "name": facilitator.full_name,
                "student_number": facilitator.email.split('@')[0] if '@' in facilitator.email else "N/A",
                "session_count": session_count,
                "assigned_hours": round(assigned_hours, 2),
                "total_hours": round(total_hours, 2),
                "date": latest_date,
                "email": facilitator.email,
                "phone": "N/A",  # Phone not stored in User model
                "status": "active" if session_count > 0 else "inactive"
            }
            
            facilitators_data.append(facilitator_data)
        
        # Sort by total hours descending
        facilitators_data.sort(key=lambda x: x['total_hours'], reverse=True)
        
        return jsonify({
            "ok": True,
            "facilitators": facilitators_data,
            "unit_name": unit.unit_name,
            "total_facilitators": len(facilitators_data)
        })
        
    except Exception as e:
        logging.error(f"Error fetching attendance summary: {str(e)}")
        return jsonify({"ok": False, "error": str(e)}), 500


@unitcoordinator_bp.post("/units/<int:unit_id>/bulk-staffing/apply")

@login_required

@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])

def apply_bulk_staffing(unit_id: int):

    """Apply bulk staffing requirements to filtered sessions."""

    user = get_current_user()

    unit = _get_user_unit_or_404(user, unit_id)

    if not unit:

        return jsonify({"ok": False, "error": "Unit not found or unauthorized"}), 404



    data = request.get_json()

    filter_type = data.get("type", "activity")

    filter_value = data.get("value", "")

    lead_staff_required = data.get("lead_staff_required", 1)

    support_staff_required = data.get("support_staff_required", 0)

    respect_overrides = data.get("respect_overrides", True)



    # For all_sessions, we don't need a filter value
    if filter_type != "all_sessions" and not filter_value:

        return jsonify({"ok": False, "error": "Filter value required"}), 400

    

    try:

        query = Session.query.join(Module).filter(Module.unit_id == unit.id)

        

        if filter_type == "all_sessions":

            # No additional filtering - apply to all sessions

            pass

        elif filter_type == "activity":

            query = query.filter(Session.session_type == filter_value)

        elif filter_type == "session_name":

            query = query.filter(Session.session_type == filter_value)

        elif filter_type == "module":

            query = query.filter(Module.id == int(filter_value))

        else:

            return jsonify({"ok": False, "error": "Invalid filter type"}), 400



        sessions = query.all()

        updated_count = 0



        for session in sessions:

            # Update logic:
            # - If respect_overrides is FALSE: Always update (force update all sessions)
            # - If respect_overrides is TRUE: Only skip if values are already what we want
            #   (this prevents redundant updates but allows changing values)
            
            should_update = True
            
            if respect_overrides:
                # Skip only if the session already has the exact values we're trying to set
                # This prevents redundant updates but allows changing to new values
                if (session.lead_staff_required == lead_staff_required and 
                    session.support_staff_required == support_staff_required):
                    should_update = False  # Already set to target values, skip
                # Otherwise, update (even if different from defaults)
            
            if should_update:
                session.lead_staff_required = lead_staff_required

                session.support_staff_required = support_staff_required

                updated_count += 1



        db.session.commit()



        return jsonify({

            "ok": True, 

            "updated_sessions": updated_count,

            "total_sessions": len(sessions)

        })

        

    except Exception as e:

        db.session.rollback()

        return jsonify({"ok": False, "error": str(e)}), 500

