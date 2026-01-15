from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from models import db, User, Session, Assignment, SwapRequest, Unavailability, SwapStatus, FacilitatorSkill, SkillLevel, Unit, Module, UnitFacilitator, UnitCoordinator, RecurringPattern, ScheduleStatus
from auth import facilitator_required, get_current_user, login_required
from datetime import datetime, time, date, timedelta
from utils import role_required
from models import UserRole
import json

facilitator_bp = Blueprint('facilitator', __name__, url_prefix='/facilitator')


def validate_password_requirements(password):
    """Validate password meets requirements and return list of errors"""
    errors = []
    
    if len(password) < 8:
        errors.append("minimum 8 characters")
    
    if not any(c.isupper() for c in password):
        errors.append("at least 1 capital letter")
    
    special_chars = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
    if not any(c in special_chars for c in password):
        errors.append("at least 1 special character")
    
    if not any(c.isdigit() for c in password):
        errors.append("at least 1 number")
    
    return errors


def format_session_date(dt):
    """Format session date with custom day abbreviations"""
    day_mapping = {
        'Mon': 'Mon',
        'Tue': 'Tues', 
        'Wed': 'Wed',
        'Thu': 'Thurs',
        'Fri': 'Fri',
        'Sat': 'Sat',
        'Sun': 'Sun'
    }
    day_abbr = dt.strftime('%a')
    custom_day = day_mapping.get(day_abbr, day_abbr)
    return f"{custom_day}, {dt.strftime('%d/%m/%Y')}"


def get_greeting():
    """Return time-based greeting"""
    hour = datetime.now().hour
    if hour < 12:
        return "Good Morning"
    elif hour < 17:
        return "Good Afternoon"
    else:
        return "Good Evening"


@facilitator_bp.route("/units", methods=["GET"])
@login_required
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def list_units_grouped():
    """Return current user's units grouped into active and past.

    Active definition:
    - today between start_date and end_date (inclusive), OR
    - start_date set and today >= start_date with no end_date, OR
    - no dates but user has future assigned sessions in this unit.
    Past definition:
    - otherwise (typically end_date < today or no future sessions)
    """
    user = get_current_user()
    today = date.today()

    # Fetch units this facilitator is assigned to
    units = (
        Unit.query
        .join(UnitFacilitator, Unit.id == UnitFacilitator.unit_id)
        .filter(UnitFacilitator.user_id == user.id)
        .all()
    )

    # Pre-compute whether a unit has any future sessions assigned to the user
    future_assignments_by_unit = {
        row[0]: row[1]
        for row in (
            db.session.query(Module.unit_id, db.func.count(Session.id))
            .join(Session, Session.module_id == Module.id)
            .join(Assignment, Assignment.session_id == Session.id)
            .filter(
                Assignment.facilitator_id == user.id,
                Session.start_time > datetime.utcnow()
            )
            .group_by(Module.unit_id)
            .all()
        )
    }

    def serialize_unit(u: Unit):
        return {
            "id": u.id,
            "code": u.unit_code,
            "name": u.unit_name,
            "year": u.year,
            "semester": u.semester,
            "start_date": u.start_date.isoformat() if u.start_date else None,
            "end_date": u.end_date.isoformat() if u.end_date else None,
        }

    active_units = []
    past_units = []

    for u in units:
        has_future = future_assignments_by_unit.get(u.id, 0) > 0
        is_active = False

        if u.start_date and u.end_date:
            is_active = (u.start_date <= today <= u.end_date)
        elif u.start_date and not u.end_date:
            is_active = (u.start_date <= today)
        elif not u.start_date and u.end_date:
            is_active = (today <= u.end_date) or has_future
        else:
            is_active = has_future

        (active_units if is_active else past_units).append(serialize_unit(u))

    # Sort: active by start_date desc, then code; past by end_date desc, then code
    def date_key(value):
        return value or "0000-00-00"

    active_units.sort(key=lambda x: (date_key(x["start_date"]), x["code"]), reverse=True)
    past_units.sort(key=lambda x: (date_key(x["end_date"]), x["code"]), reverse=True)

    return jsonify({
        "active_units": active_units,
        "past_units": past_units
    })


@facilitator_bp.route("/dashboard")
@login_required
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def dashboard():
    user = get_current_user()

    # JSON unit-scoped dashboard API: /facilitator/dashboard?unit_id=...
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        try:
            unit_id_int = int(unit_id)
        except ValueError:
            return jsonify({"error": "invalid unit_id"}), 400

        # Authorization: ensure the user is assigned to this unit
        access = (
            db.session.query(Unit)
            .join(UnitFacilitator, Unit.id == UnitFacilitator.unit_id)
            .filter(Unit.id == unit_id_int, UnitFacilitator.user_id == user.id)
            .first()
        )
        if not access:
            return jsonify({"error": "forbidden"}), 403

        # Time windows
        now = datetime.utcnow()
        start_of_week = (now.replace(hour=0, minute=0, second=0, microsecond=0)
                         - timedelta(days=now.weekday()))
        end_of_week = start_of_week + timedelta(days=6, hours=23, minutes=59, seconds=59)

        # Base query for user's assignments within this unit
        # Only show published sessions to facilitators
        base_q = (
            db.session.query(Assignment, Session, Module)
            .join(Session, Assignment.session_id == Session.id)
            .join(Module, Session.module_id == Module.id)
            .filter(
                Assignment.facilitator_id == user.id, 
                Module.unit_id == unit_id_int,
                Session.status == 'published'  # Only show published sessions
            )
        )

        # Total hours for the unit
        all_rows = base_q.all()
        def duration_hours(row):
            return max(0.0, (row[1].end_time - row[1].start_time).total_seconds() / 3600.0)
        total_hours = sum(duration_hours(r) for r in all_rows)

        # This week hours and active sessions count
        week_rows = [r for r in all_rows if start_of_week <= r[1].start_time < end_of_week]
        this_week_hours = sum(duration_hours(r) for r in week_rows)
        active_sessions = len(week_rows)

        # Upcoming sessions (next 10)
        upcoming_rows = (
            base_q.filter(Session.start_time >= now)
            .order_by(Session.start_time.asc())
            .limit(10)
            .all()
        )

        # Recent past sessions (last 10)
        past_rows = (
            base_q.filter(Session.start_time < now)
            .order_by(Session.start_time.desc())
            .limit(10)
            .all()
        )

        def serialize_session(r):
            a, s, m = r
            return {
                "assignment_id": a.id,
                "session_id": s.id,
                "module": m.module_name,
                "session_type": s.session_type,
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat(),
                "location": s.location,
                "is_confirmed": bool(a.is_confirmed),
            }

        payload = {
            "unit": {
                "id": access.id,
                "code": access.unit_code,
                "name": access.unit_name,
                "year": access.year,
                "semester": access.semester,
            },
            "kpis": {
                "this_week_hours": round(this_week_hours, 2),
                "total_hours": round(total_hours, 2),
                "active_sessions": active_sessions,
            },
            "sessions": {
                "upcoming": [serialize_session(r) for r in upcoming_rows],
                "recent_past": [serialize_session(r) for r in past_rows],
            }
        }
        return jsonify(payload)

    # Fallback to HTML dashboard when no unit_id is provided
    greeting = get_greeting()
    
    # Get user's units for the dashboard
    units = (
        Unit.query
        .join(UnitFacilitator, Unit.id == UnitFacilitator.unit_id)
        .filter(UnitFacilitator.user_id == user.id)
        .order_by(Unit.start_date.desc())
        .all()
    )
    
    # Check if facilitator has no units assigned
    has_no_units = len(units) == 0
    
    # Get current active unit (most recent with future sessions or current date range)
    current_unit = None
    today = date.today()
    
    for unit in units:
        # Check if unit is currently active
        if (unit.start_date and unit.end_date and 
            unit.start_date <= today <= unit.end_date):
            current_unit = unit
            break
        elif (unit.start_date and not unit.end_date and 
              unit.start_date <= today):
            current_unit = unit
            break
    
    # If no active unit found, use the most recent unit
    if not current_unit and units:
        current_unit = units[0]
    
    # Convert current_unit to dictionary for JSON serialization
    current_unit_dict = None
    if current_unit:
        current_unit_dict = {
            'id': current_unit.id,
            'unit_code': current_unit.unit_code,
            'unit_name': current_unit.unit_name,
            'year': current_unit.year,
            'semester': current_unit.semester,
            'start_date': current_unit.start_date.isoformat() if current_unit.start_date else None,
            'end_date': current_unit.end_date.isoformat() if current_unit.end_date else None,
            'schedule_status': getattr(current_unit, 'schedule_status', None).value if getattr(current_unit, 'schedule_status', None) else 'draft',
            'description': current_unit.description
        }
    
    # Get units data for JavaScript
    units_data = []
    for unit in units:
        # Get assignments for this unit (only published sessions)
        print(f"DEBUG: Fetching assignments for user {user.id}, unit {unit.id}")
        
        # First check: How many assignments exist for this user in this unit (regardless of status)?
        all_assignments = (
            db.session.query(Assignment, Session, Module)
            .join(Session, Assignment.session_id == Session.id)
            .join(Module, Session.module_id == Module.id)
            .filter(
                Assignment.facilitator_id == user.id, 
                Module.unit_id == unit.id
            )
            .all()
        )
        print(f"DEBUG: Found {len(all_assignments)} total assignments for user in unit")
        
        # Check session statuses
        for a, s, m in all_assignments:
            print(f"DEBUG: Session {s.id} status = '{s.status}', module = {m.module_name}")
        
        # Now filter for published sessions only
        assignments = (
            db.session.query(Assignment, Session, Module)
            .join(Session, Assignment.session_id == Session.id)
            .join(Module, Session.module_id == Module.id)
            .filter(
                Assignment.facilitator_id == user.id, 
                Module.unit_id == unit.id,
                Session.status == 'published'  # Only show published sessions
            )
            .all()
        )
        print(f"DEBUG: Found {len(assignments)} published assignments")
        
        # Get session count for this unit (sessions assigned to this facilitator)
        session_count = len(assignments)
        
        # Calculate KPIs
        total_hours = sum((s.end_time - s.start_time).total_seconds() / 3600.0 for _, s, _ in assignments)
        
        # This week hours
        now = datetime.utcnow()
        start_of_week = (now.replace(hour=0, minute=0, second=0, microsecond=0)
                         - timedelta(days=now.weekday()))
        end_of_week = start_of_week + timedelta(days=6, hours=23, minutes=59, seconds=59)
        
        this_week_hours = sum(
            (s.end_time - s.start_time).total_seconds() / 3600.0 
            for _, s, _ in assignments 
            if start_of_week <= s.start_time < end_of_week
        )
        
        # Active sessions this week
        active_sessions = len([
            s for _, s, _ in assignments 
            if start_of_week <= s.start_time < end_of_week
        ])
        
        # Upcoming sessions
        upcoming_sessions = [
            {
                'id': a.id,
                'session_id': s.id,
                'module': m.module_name or 'Unknown Module',  # Handle null module names
                'session_type': s.session_type or 'Session',  # Better default for session type
                'start_time': s.start_time.isoformat(),
                'end_time': s.end_time.isoformat(),
                'location': s.location or 'TBA',  # Handle null locations
                'is_confirmed': bool(a.is_confirmed),
                'date': format_session_date(s.start_time),
                'time': f"{s.start_time.strftime('%I:%M %p')} - {s.end_time.strftime('%I:%M %p')}",
                'topic': m.module_name or 'Unknown Module',
                'status': 'confirmed' if a.is_confirmed else 'pending',
                'role': getattr(a, 'role', 'lead')  # Include role information
            }
            for a, s, m in assignments
            if s.start_time >= now
        ]
        
        # Past sessions
        past_sessions = [
            {
                'id': a.id,
                'session_id': s.id,
                'module': m.module_name or 'Unknown Module',  # Handle null module names
                'session_type': s.session_type or 'Session',  # Better default for session type
                'start_time': s.start_time.isoformat(),
                'end_time': s.end_time.isoformat(),
                'location': s.location or 'TBA',  # Handle null locations
                'is_confirmed': bool(a.is_confirmed),
                'date': format_session_date(s.start_time),
                'time': f"{s.start_time.strftime('%I:%M %p')} - {s.end_time.strftime('%I:%M %p')}",
                'topic': m.module_name or 'Unknown Module',
                'status': 'completed'
            }
            for a, s, m in assignments
            if s.start_time < now
        ]
        
        # Determine if unit is active
        today = date.today()
        is_active = False
        if unit.start_date and unit.end_date:
            is_active = (today <= unit.end_date)
        elif unit.start_date and not unit.end_date:
            is_active = (unit.start_date <= today)
        elif not unit.start_date and unit.end_date:
            is_active = (today <= unit.end_date)
        else:
            is_active = len(upcoming_sessions) > 0
        
        unit_data = {
            'id': unit.id,
            'code': unit.unit_code,
            'name': unit.unit_name,
            'year': unit.year,
            'semester': unit.semester,
            'start_date': unit.start_date.isoformat() if unit.start_date else None,
            'end_date': unit.end_date.isoformat() if unit.end_date else None,
            'schedule_status': getattr(unit, 'schedule_status', None).value if getattr(unit, 'schedule_status', None) else 'draft',
            'status': 'active' if is_active else 'completed',
            'sessions': session_count,
            'date_range': f"{unit.start_date.strftime('%d/%m/%Y')} - {unit.end_date.strftime('%d/%m/%Y')}" if unit.start_date and unit.end_date else 'No date range',
            'kpis': {
                'this_week_hours': round(this_week_hours, 1),
                'total_hours': round(total_hours, 1),
                'active_sessions': active_sessions,
                'remaining_hours': round(total_hours - this_week_hours, 1),
                'total_sessions': session_count
            },
            'upcoming_sessions': upcoming_sessions,  # Show all upcoming sessions
            'past_sessions': past_sessions  # Show all past sessions
        }
        units_data.append(unit_data)
    
    # Count today's sessions for the facilitator (only published sessions)
    today = date.today()
    today_sessions_count = (
        db.session.query(Assignment, Session, Module)
        .join(Session, Assignment.session_id == Session.id)
        .join(Module, Session.module_id == Module.id)
        .filter(
            Assignment.facilitator_id == user.id,
            db.func.date(Session.start_time) == today,
            Session.status == 'published'  # Only show published sessions
        )
        .count()
    )
    
    # Check if facilitator has configured availability for current unit
    availability_configured = False
    skills_configured = False
    
    if current_unit:
        unit_facilitator = UnitFacilitator.query.filter_by(
            user_id=user.id,
            unit_id=current_unit.id
        ).first()
        
        if unit_facilitator:
            availability_configured = unit_facilitator.availability_configured
        
        # Check if facilitator has set skills for any modules in this unit
        skills_count = (
            db.session.query(FacilitatorSkill)
            .join(Module, FacilitatorSkill.module_id == Module.id)
            .filter(
                FacilitatorSkill.facilitator_id == user.id,
                Module.unit_id == current_unit.id
            )
            .count()
        )
        skills_configured = skills_count > 0
    
    return render_template("facilitator_dashboard.html", 
                         user=user, 
                         greeting=greeting,
                         units=units,
                         current_unit=current_unit,
                         current_unit_dict=current_unit_dict,
                         units_data=units_data,
                         has_no_units=has_no_units,
                         today_sessions_count=today_sessions_count,
                         availability_configured=availability_configured,
                         skills_configured=skills_configured)


@facilitator_bp.route("/")
@login_required
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def root():
    return redirect(url_for(".dashboard"))


@facilitator_bp.route("/profile")
@login_required
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def profile():
    user = get_current_user()
    today = date.today()
    
    # Get facilitator's current units and stats
    units = (
        Unit.query
        .join(UnitFacilitator, Unit.id == UnitFacilitator.unit_id)
        .filter(UnitFacilitator.user_id == user.id)
        .all()
    )
    
    # Facilitator Information Calculations
    facilitator_info = calculate_facilitator_info(user, today)
    
    return render_template("facilitator_profile.html",
                         user=user,
                         units=units,
                         facilitator_info=facilitator_info,
                         current_user=user)


def calculate_facilitator_info(user, today):
    """Calculate comprehensive facilitator information including units, sessions, and career metrics."""
    
    # Get all units the facilitator has been assigned to
    all_units = (
        Unit.query
        .join(UnitFacilitator, Unit.id == UnitFacilitator.unit_id)
        .filter(UnitFacilitator.user_id == user.id)
        .all()
    )
    
    current_units = []
    past_units = []
    
    for unit in all_units:
        # Determine if unit is current or past
        is_current = False
        
        if unit.start_date and unit.end_date:
            is_current = unit.start_date <= today <= unit.end_date
        elif unit.start_date and not unit.end_date:
            is_current = unit.start_date <= today
        elif not unit.start_date and unit.end_date:
            is_current = today <= unit.end_date
        else:
            # Check if there are future assignments for this unit (only published sessions)
            has_future_sessions = (
                db.session.query(Assignment)
                .join(Session, Assignment.session_id == Session.id)
                .join(Module, Session.module_id == Module.id)
                .filter(
                    Assignment.facilitator_id == user.id,
                    Module.unit_id == unit.id,
                    Session.start_time > datetime.utcnow(),
                    Session.status == 'published'  # Only show published sessions
                )
                .count() > 0
            )
            is_current = has_future_sessions
        
        # Get sessions for this unit (only published sessions)
        sessions_query = (
            db.session.query(Assignment, Session, Module)
            .join(Session, Assignment.session_id == Session.id)
            .join(Module, Session.module_id == Module.id)
            .filter(
                Assignment.facilitator_id == user.id,
                Module.unit_id == unit.id,
                Session.status == 'published'  # Only show published sessions
            )
        ).all()
        
        # Separate current and past sessions
        current_sessions = [(a, s, m) for a, s, m in sessions_query if s.start_time >= datetime.utcnow()]
        past_sessions = [(a, s, m) for a, s, m in sessions_query if s.start_time < datetime.utcnow()]
        
        # Calculate metrics for this unit
        completed_sessions = len(past_sessions)
        total_hours = sum((s.end_time - s.start_time).total_seconds() / 3600.0 for _, s, _ in past_sessions)
        
        # Calculate average hours per week based on weeks with sessions assigned (completed only)
        avg_hours_per_week = 0
        if completed_sessions > 0:
            week_keys = set()
            for _, s, _ in past_sessions:
                iso = s.start_time.isocalendar()
                # Python's isocalendar may return a namedtuple (year, week, weekday)
                try:
                    week_key = (iso.year, iso.week)
                except AttributeError:
                    week_key = (iso[0], iso[1])
                week_keys.add(week_key)
            weeks_count = max(1, len(week_keys))
            avg_hours_per_week = total_hours / weeks_count
        
        # Get session types (module names)
        session_types = list(set(m.module_name for _, _, m in past_sessions if m.module_name))
        
        unit_info = {
            'id': unit.id,
            'code': unit.unit_code,
            'name': unit.unit_name,
            'year': unit.year,
            'semester': unit.semester,
            'start_date': unit.start_date,
            'end_date': unit.end_date,
            'completed_sessions': completed_sessions,
            'total_hours': round(total_hours, 1),
            'avg_hours_per_week': round(avg_hours_per_week, 1),
            'session_types': session_types,
            'sessions': past_sessions
        }
        
        if is_current:
            current_units.append(unit_info)
        else:
            past_units.append(unit_info)
    
    # Calculate career summary metrics
    # Total Units
    total_units = len(all_units)
    
    # Sessions Facilitated (completed sessions across all units, only published)
    all_completed_sessions = (
        db.session.query(Assignment, Session)
        .join(Session, Assignment.session_id == Session.id)
        .join(Module, Session.module_id == Module.id)
        .join(UnitFacilitator, Module.unit_id == UnitFacilitator.unit_id)
        .filter(
            Assignment.facilitator_id == user.id,
            UnitFacilitator.user_id == user.id,
            Session.end_time < datetime.utcnow(),
            Session.status == 'published'  # Only show published sessions
        )
        .all()
    )
    
    sessions_facilitated = len(all_completed_sessions)
    
    # Total Hours (across all units)
    total_hours = sum((s.end_time - s.start_time).total_seconds() / 3600.0 for _, s in all_completed_sessions)
    
    # Years Experience (from earliest unit start date)
    years_experience = 0
    if all_units:
        earliest_start = min(unit.start_date for unit in all_units if unit.start_date)
        if earliest_start:
            years_experience = (today - earliest_start).days / 365.25
    
    # Sort past units by end date (most recent first)
    past_units.sort(key=lambda x: x['end_date'] or date.min, reverse=True)
    
    return {
        'current_units': current_units,
        'past_units': past_units,
        'career_summary': {
            'total_units': total_units,
            'sessions_facilitated': sessions_facilitated,
            'total_hours': round(total_hours, 1),
            'years_experience': round(years_experience, 1)
        }
    }


@facilitator_bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def edit_profile():
    user = get_current_user()
    
    if request.method == "POST":
        try:
            # Update user information
            user.first_name = request.form.get("first_name", user.first_name)
            user.last_name = request.form.get("last_name", user.last_name)
            # Email is read-only and cannot be changed
            user.phone_number = request.form.get("phone_number", user.phone_number)
            user.staff_number = request.form.get("staff_number", user.staff_number)
            
            # Also update the Facilitator table if it exists
            from models import Facilitator
            facilitator = Facilitator.query.filter_by(email=user.email).first()
            if facilitator:
                facilitator.first_name = user.first_name
                facilitator.last_name = user.last_name
                facilitator.phone = user.phone_number
                facilitator.staff_number = user.staff_number
            
            # Handle password update if provided
            current_password = request.form.get("current_password")
            new_password = request.form.get("new_password")
            confirm_password = request.form.get("confirm_password")
            
            if new_password and new_password.strip():
                # Verify current password if provided
                if current_password and not user.check_password(current_password):
                    flash("Current password is incorrect.", "error")
                    return render_template("edit_facilitator_profile.html", user=user)
                
                # Validate new passwords match
                if new_password != confirm_password:
                    flash("New passwords do not match.", "error")
                    return render_template("edit_facilitator_profile.html", user=user)
                
                # Validate password requirements
                password_errors = validate_password_requirements(new_password)
                if password_errors:
                    flash("Password does not meet requirements: " + ", ".join(password_errors), "error")
                    return render_template("edit_facilitator_profile.html", user=user)
                
                # Set new password
                user.set_password(new_password)
            
            db.session.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for("facilitator.profile"))
            
        except Exception as e:
            db.session.rollback()
            flash("Error updating profile. Please try again.", "error")
    
    return render_template("edit_facilitator_profile.html", user=user)

@facilitator_bp.route('/schedule')
@facilitator_required
def view_schedule():
    user = get_current_user()
    # Only show published sessions
    assignments = (
        Assignment.query
        .filter_by(facilitator_id=user.id)
        .join(Session)
        .filter(Session.status == 'published')
        .order_by(Session.start_time)
        .all()
    )
    return render_template('view_schedule.html', user=user, assignments=assignments)

@facilitator_bp.route('/unit-info', methods=['GET'])
@facilitator_required
def get_unit_info():
    """Get unit information for unavailability system"""
    user = get_current_user()
    unit_id = request.args.get('unit_id', type=int)
    
    if not unit_id:
        return jsonify({"error": "unit_id is required"}), 400
    
    # Verify user has access to this unit
    unit = (
        db.session.query(Unit)
        .join(UnitFacilitator, Unit.id == UnitFacilitator.unit_id)
        .filter(Unit.id == unit_id, UnitFacilitator.user_id == user.id)
        .first()
    )
    
    if not unit:
        return jsonify({"error": "forbidden"}), 403
    
    # Serialize unit data
    unit_data = {
        "id": unit.id,
        "code": unit.unit_code,
        "name": unit.unit_name,
        "start_date": unit.start_date.isoformat() if unit.start_date else None,
        "end_date": unit.end_date.isoformat() if unit.end_date else None,
        "year": unit.year,
        "semester": unit.semester
    }
    
    return jsonify({"unit": unit_data})

@facilitator_bp.route('/unavailability', methods=['GET'])
@facilitator_required
def get_unavailability():
    """Get GLOBAL unavailability (unit_id optional for backwards compatibility)"""
    current_user = get_current_user()
    unit_id = request.args.get('unit_id', type=int)  # Optional now
    
    # Get the target user (facilitator being viewed)
    # If 'user_id' is provided, UC/admin is viewing on behalf of facilitator
    target_user_id = request.args.get('user_id', type=int, default=current_user.id)
    
    # Check permission: either viewing own data or UC/admin viewing facilitator's data
    if target_user_id != current_user.id:
        if current_user.role not in [UserRole.ADMIN, UserRole.UNIT_COORDINATOR]:
            return jsonify({"error": "forbidden"}), 403
    
    # Get GLOBAL unavailability records for this user
    unavailabilities = Unavailability.query.filter_by(
        user_id=target_user_id, 
        unit_id=None  # Global unavailability
    ).all()
    
    print(f"[DEBUG] GET unavailability - user_id={target_user_id}, found {len(unavailabilities)} records")
    for u in unavailabilities:
        print(f"[DEBUG]   - ID={u.id}, date={u.date}, recurring_pattern={u.recurring_pattern}")
    
    # Serialize unavailability data
    unavailability_data = []
    for unav in unavailabilities:
        unavailability_data.append({
            'id': unav.id,
            'date': unav.date.isoformat(),
            'start_time': unav.start_time.isoformat() if unav.start_time else None,
            'end_time': unav.end_time.isoformat() if unav.end_time else None,
            'is_full_day': unav.is_full_day,
            'recurring_pattern': unav.recurring_pattern.value if unav.recurring_pattern else None,
            'recurring_end_date': unav.recurring_end_date.isoformat() if unav.recurring_end_date else None,
            'recurring_interval': unav.recurring_interval,
            'reason': unav.reason,
            'is_auto_generated': unav.source_session_id is not None
        })
    
    return jsonify({
        'unavailabilities': unavailability_data
    })

@facilitator_bp.route('/unavailability', methods=['POST'])
@login_required
def create_unavailability():
    """Create GLOBAL unavailability (unit_id is optional for backwards compatibility)"""
    current_user = get_current_user()
    data = request.get_json()
    
    # unit_id is now OPTIONAL - unavailability is global!
    # If provided (for backwards compatibility), we ignore it
    unit_id = data.get('unit_id')
    
    # Get the target user (facilitator being edited)
    # If 'user_id' is provided, UC is editing on behalf of facilitator
    target_user_id = data.get('user_id', current_user.id)
    
    # Permission check: user can edit their own data, or UC/admin can edit facilitator's data
    if target_user_id != current_user.id:
        # Someone else is editing - must be UC or admin
        if current_user.role not in [UserRole.ADMIN, UserRole.UNIT_COORDINATOR]:
            return jsonify({"error": "forbidden"}), 403
    
    # For global unavailability, we don't need to verify unit access
    # Just check that the user exists and is a facilitator
    target_user = User.query.get(target_user_id)
    if not target_user:
        return jsonify({"error": "user not found"}), 404
    
    # Get ANY unit the facilitator is in (for date range validation)
    access = (
        db.session.query(Unit)
        .join(UnitFacilitator, Unit.id == UnitFacilitator.unit_id)
        .filter(UnitFacilitator.user_id == target_user_id)
        .first()
    )
    if not access:
        return jsonify({"error": "facilitator not linked to any unit"}), 403
    
    # Note: We allow editing unavailability even if schedule is published
    # Auto-generated unavailability from published schedules is protected separately
    
    # Validate date format and range
    try:
        unavailability_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
    
    # Skip date range validation for global unavailability
    # Users can set unavailability for any future date
    
    # Parse time data
    start_time = None
    end_time = None
    is_full_day = data.get('is_full_day', False)
    
    if not is_full_day:
        start_time_str = data.get('start_time')
        end_time_str = data.get('end_time')
        
        if not start_time_str or not end_time_str:
            return jsonify({"error": "Start time and end time are required for partial day unavailability"}), 400
        
        # Strip whitespace and validate format
        start_time_str = str(start_time_str).strip()
        end_time_str = str(end_time_str).strip()
        
        # Validate format is HH:MM (24-hour format)
        import re
        time_pattern = re.compile(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$')
        
        if not time_pattern.match(start_time_str) or not time_pattern.match(end_time_str):
            return jsonify({"error": f"Invalid time format. Use HH:MM (24-hour format). Received: start={start_time_str}, end={end_time_str}"}), 400
        
        try:
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            end_time = datetime.strptime(end_time_str, '%H:%M').time()
        except ValueError as e:
            return jsonify({"error": f"Invalid time format. Use HH:MM. Error: {str(e)}"}), 400
        
        if start_time >= end_time:
            return jsonify({"error": "End time must be after start time"}), 400
    
    # Parse recurring pattern
    recurring_pattern = None
    recurring_end_date = None
    recurring_interval = 1
    
    if data.get('recurring_pattern'):
        recurring_pattern_str = data.get('recurring_pattern')
        if recurring_pattern_str not in [pattern.value for pattern in RecurringPattern]:
            return jsonify({"error": "Invalid recurring pattern"}), 400
        
        recurring_pattern = RecurringPattern(recurring_pattern_str)
        
        if not data.get('recurring_end_date'):
            return jsonify({"error": "Recurring end date is required for recurring unavailability"}), 400
        
        try:
            recurring_end_date = datetime.strptime(data.get('recurring_end_date'), '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"error": "Invalid recurring end date format. Use YYYY-MM-DD"}), 400
        
        if recurring_end_date <= unavailability_date:
            return jsonify({"error": "Recurring end date must be after the start date"}), 400
        
        recurring_interval = data.get('recurring_interval', 1)
        if not isinstance(recurring_interval, int) or recurring_interval < 1 or recurring_interval > 52:
            return jsonify({"error": "Recurring interval must be between 1 and 52"}), 400
    
    # Validate reason length
    reason = data.get('reason', '')
    if len(reason) > 500:
        return jsonify({"error": "Reason must be 500 characters or less"}), 400
    
    # Check for existing GLOBAL unavailability on the same date and time
    # (Skip this check when creating multiple time ranges OR when delete_existing_for_date is set)
    if not data.get('time_ranges') and not data.get('delete_existing_for_date'):
        existing = Unavailability.query.filter_by(
            user_id=target_user_id,
            unit_id=None,  # Global unavailability
            date=unavailability_date,
            start_time=start_time,
            end_time=end_time
        ).first()
        
        if existing:
            return jsonify({"error": "Unavailability already exists for this date and time"}), 409
    
    # Check for conflicts with existing assignments across ALL units
    conflicts = []
    assignments = (
        db.session.query(Assignment)
        .join(Session, Assignment.session_id == Session.id)
        .filter(
            Assignment.facilitator_id == target_user_id,
            db.func.date(Session.start_time) == unavailability_date
        )
        .all()
    )
    
    for assignment in assignments:
        session = assignment.session
        # Check if the unavailability time overlaps with the session time
        if is_full_day or (start_time and end_time and session.start_time and session.end_time):
            if is_full_day:
                conflicts.append({
                    'session_id': session.id,
                    'module_name': session.module.module_name,
                    'session_type': session.session_type,
                    'start_time': session.start_time.strftime('%I:%M %p') if session.start_time else 'N/A',
                    'end_time': session.end_time.strftime('%I:%M %p') if session.end_time else 'N/A',
                    'location': session.location or 'TBA'
                })
            elif start_time and end_time and session.start_time and session.end_time:
                # Check time overlap
                session_start = session.start_time.time()
                session_end = session.end_time.time()
                if not (end_time <= session_start or start_time >= session_end):
                    conflicts.append({
                        'session_id': session.id,
                        'module_name': session.module.module_name,
                        'session_type': session.session_type,
                        'start_time': session.start_time.strftime('%I:%M %p'),
                        'end_time': session.end_time.strftime('%I:%M %p'),
                        'location': session.location or 'TBA'
                    })
    
    # Check if we need to delete existing records for this date first (when editing multiple)
    if data.get('delete_existing_for_date'):
        # Delete all manual unavailability for this user on this date
        deleted_count = Unavailability.query.filter(
            Unavailability.user_id == target_user_id,
            Unavailability.unit_id.is_(None),
            Unavailability.date == unavailability_date,
            Unavailability.source_session_id.is_(None)  # Only manual
        ).delete(synchronize_session=False)
        
        # If no time ranges provided, user is clearing unavailability - just delete and return
        if not data.get('time_ranges') and not data.get('is_full_day'):
            db.session.commit()
            return jsonify({
                "message": f"Deleted {deleted_count} unavailability record(s)",
                "deleted_count": deleted_count
            }), 200
    
    # Check if multiple time ranges were provided
    time_ranges = data.get('time_ranges')
    unavailabilities_created = []
    
    if time_ranges and len(time_ranges) > 1:
        # Multiple time ranges - create separate record for each
        for time_range in time_ranges:
            try:
                range_start = datetime.strptime(time_range['start_time'], '%H:%M').time()
                range_end = datetime.strptime(time_range['end_time'], '%H:%M').time()
            except (ValueError, KeyError) as e:
                return jsonify({"error": f"Invalid time range format: {str(e)}"}), 400
            
            # Check for existing record with same time
            existing = Unavailability.query.filter_by(
                user_id=target_user_id,
                unit_id=None,
                date=unavailability_date,
                start_time=range_start,
                end_time=range_end
            ).first()
            
            if not existing:
                unavailability = Unavailability(
                    user_id=target_user_id,
                    unit_id=None,
                    date=unavailability_date,
                    start_time=range_start,
                    end_time=range_end,
                    is_full_day=False,  # Multiple ranges = not full day
                    recurring_pattern=recurring_pattern,
                    recurring_end_date=recurring_end_date,
                    recurring_interval=recurring_interval,
                    reason=reason if reason else None
                )
                db.session.add(unavailability)
                unavailabilities_created.append(unavailability)
    else:
        # Single time range or full day - create one record
        unavailability = Unavailability(
            user_id=target_user_id,
            unit_id=None,  # Global unavailability
            date=unavailability_date,
            start_time=start_time,
            end_time=end_time,
            is_full_day=is_full_day,
            recurring_pattern=recurring_pattern,
            recurring_end_date=recurring_end_date,
            recurring_interval=recurring_interval,
            reason=reason if reason else None
        )
        db.session.add(unavailability)
        unavailabilities_created.append(unavailability)
    
    try:
        
        # Get target user object for preferences
        target_user = User.query.get(target_user_id)
        
        # Clear "Available All Days" status when unavailability is added
        import json
        preferences = {}
        if target_user.preferences:
            try:
                preferences = json.loads(target_user.preferences)
            except:
                preferences = {}
        
        # Mark availability as configured for ALL units the facilitator is in
        unit_facilitators = UnitFacilitator.query.filter_by(
            user_id=target_user_id
        ).all()
        
        for unit_facilitator in unit_facilitators:
            unit_facilitator.availability_configured = True
        
        db.session.commit()
        
        # Build response with all created unavailabilities
        unavailability_list = []
        for unav in unavailabilities_created:
            unavailability_list.append({
                "id": unav.id,
                "date": unav.date.isoformat(),
                "is_full_day": unav.is_full_day,
                "start_time": unav.start_time.isoformat() if unav.start_time else None,
                "end_time": unav.end_time.isoformat() if unav.end_time else None,
                "recurring_pattern": unav.recurring_pattern.value if unav.recurring_pattern else None,
                "reason": unav.reason
            })
        
        count_msg = f"{len(unavailabilities_created)} unavailability record(s)" if len(unavailabilities_created) > 1 else "Unavailability"
        
        response_data = {
            "message": f"{count_msg} created successfully",
            "availability_configured": True,
            "unavailability": unavailability_list[0] if len(unavailability_list) == 1 else unavailability_list,
            "count": len(unavailabilities_created)
        }
        
        # Include conflicts if any exist
        if conflicts:
            response_data["conflicts"] = conflicts
            response_data["warning"] = f"Warning: You have {len(conflicts)} assignment(s) on this date. Please contact your Unit Coordinator to resolve this conflict."
        
        return jsonify(response_data), 201
    except Exception as e:
        import traceback
        db.session.rollback()
        print(f"Error creating unavailability: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Failed to create unavailability: {str(e)}"}), 500

@facilitator_bp.route('/unavailability/<int:unavailability_id>', methods=['PUT'])
@facilitator_required
def update_unavailability(unavailability_id):
    """Update an existing GLOBAL unavailability record"""
    current_user = get_current_user()
    data = request.get_json()
    
    # Get the unavailability record
    unavailability = Unavailability.query.filter_by(id=unavailability_id).first()
    
    if not unavailability:
        return jsonify({"error": "Unavailability not found"}), 404
    
    # Check permission: either owner or UC/admin editing on behalf of facilitator
    if unavailability.user_id != current_user.id:
        # For global unavailability, just check role (no unit needed)
        if current_user.role not in [UserRole.ADMIN, UserRole.UNIT_COORDINATOR]:
            return jsonify({"error": "forbidden"}), 403
    
    # Prevent editing auto-generated unavailability
    if unavailability.source_session_id is not None:
        return jsonify({"error": "Cannot edit auto-generated unavailability from published schedules."}), 403
    
    # Update fields - always update is_full_day first to handle time clearing
    if 'is_full_day' in data:
        unavailability.is_full_day = data['is_full_day']
        # If switching to full day, clear times
        if data['is_full_day']:
            unavailability.start_time = None
            unavailability.end_time = None
    
    if 'date' in data:
        unavailability.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    
    # Only update times if not full day
    if not unavailability.is_full_day:
        if 'start_time' in data:
            start_time_str = data['start_time']
            if start_time_str:
                start_time_str = str(start_time_str).strip()
                import re
                time_pattern = re.compile(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$')
                if not time_pattern.match(start_time_str):
                    return jsonify({"error": f"Invalid start time format. Use HH:MM (24-hour format). Received: {start_time_str}"}), 400
                unavailability.start_time = datetime.strptime(start_time_str, '%H:%M').time()
            else:
                unavailability.start_time = None
        
        if 'end_time' in data:
            end_time_str = data['end_time']
            if end_time_str:
                end_time_str = str(end_time_str).strip()
                import re
                time_pattern = re.compile(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$')
                if not time_pattern.match(end_time_str):
                    return jsonify({"error": f"Invalid end time format. Use HH:MM (24-hour format). Received: {end_time_str}"}), 400
                unavailability.end_time = datetime.strptime(end_time_str, '%H:%M').time()
            else:
                unavailability.end_time = None
    elif 'start_time' in data or 'end_time' in data:
        # If full day but times are provided, clear them
        unavailability.start_time = None
        unavailability.end_time = None
    
    if 'recurring_pattern' in data:
        unavailability.recurring_pattern = RecurringPattern(data['recurring_pattern']) if data['recurring_pattern'] else None
    
    if 'recurring_end_date' in data:
        unavailability.recurring_end_date = datetime.strptime(data['recurring_end_date'], '%Y-%m-%d').date() if data['recurring_end_date'] else None
    
    if 'recurring_interval' in data:
        unavailability.recurring_interval = data['recurring_interval']
    
    if 'reason' in data:
        unavailability.reason = data['reason']
    
    try:
        db.session.commit()
        return jsonify({
            "message": "Unavailability updated successfully",
            "unavailability": {
                "id": unavailability.id,
                "date": unavailability.date.isoformat(),
                "is_full_day": unavailability.is_full_day,
                "start_time": unavailability.start_time.isoformat() if unavailability.start_time else None,
                "end_time": unavailability.end_time.isoformat() if unavailability.end_time else None
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to update unavailability"}), 500

@facilitator_bp.route('/unavailability/<int:unavailability_id>', methods=['DELETE'])
@login_required
def delete_unavailability(unavailability_id):
    """Delete a GLOBAL unavailability record"""
    current_user = get_current_user()
    
    # Get the unavailability record
    unavailability = Unavailability.query.get(unavailability_id)
    
    if not unavailability:
        return jsonify({"error": "Unavailability not found"}), 404
    
    # Check permission: either owner or UC/admin
    if unavailability.user_id != current_user.id:
        if current_user.role not in [UserRole.ADMIN, UserRole.UNIT_COORDINATOR]:
            return jsonify({"error": "forbidden"}), 403
    
    # Prevent deletion of auto-generated unavailability
    if unavailability.source_session_id is not None:
        return jsonify({"error": "Cannot delete auto-generated unavailability from published schedules. Contact your unit coordinator if this needs to be changed."}), 403
    
    db.session.delete(unavailability)
    db.session.commit()
    
    return jsonify({"message": "Unavailability deleted successfully"})

@facilitator_bp.route('/unavailability/clear-all', methods=['POST'])
@login_required
def clear_all_unavailability():
    """Clear all unavailability for a specific unit"""
    current_user = get_current_user()
    data = request.get_json()
    
    unit_id = data.get('unit_id')
    if not unit_id:
        return jsonify({"error": "unit_id is required"}), 400
    
    # Get the target user (facilitator being edited)
    target_user_id = data.get('user_id', current_user.id)
    
    # Check permission
    if not can_edit_facilitator_data(current_user, target_user_id, unit_id):
        return jsonify({"error": "forbidden"}), 403
    
    # Verify target user has access to this unit
    access = (
        db.session.query(Unit)
        .join(UnitFacilitator, Unit.id == UnitFacilitator.unit_id)
        .filter(Unit.id == unit_id, UnitFacilitator.user_id == target_user_id)
        .first()
    )
    if not access:
        return jsonify({"error": "facilitator not linked to this unit"}), 403
    
    # Note: We allow clearing unavailability even if schedule is published
    # Auto-generated unavailability from published schedules is protected separately
    
    try:
        # Delete all MANUAL global unavailability (NOT auto-generated from schedules)
        deleted_count = Unavailability.query.filter(
            Unavailability.user_id == target_user_id,
            Unavailability.unit_id.is_(None),  # Global unavailability
            Unavailability.source_session_id.is_(None)  # Only manual (not auto-generated)
        ).delete(synchronize_session=False)
        
        # Get target user object
        target_user = User.query.get(target_user_id)
        
        # Mark user as "Available All Days" for this unit in preferences
        import json
        preferences = {}
        if target_user.preferences:
            try:
                preferences = json.loads(target_user.preferences)
            except:
                preferences = {}
        
        # Store availability status per unit
        if 'availability_status' not in preferences:
            preferences['availability_status'] = {}
        
        preferences['availability_status'][str(unit_id)] = 'available_all_days'
        target_user.preferences = json.dumps(preferences)
        
        # Mark availability as configured in UnitFacilitator
        unit_facilitator = UnitFacilitator.query.filter_by(
            user_id=target_user_id,
            unit_id=unit_id
        ).first()
        
        if unit_facilitator:
            unit_facilitator.availability_configured = True
        
        db.session.commit()
        
        return jsonify({
            "message": f"Cleared {deleted_count} unavailability entries",
            "deleted_count": deleted_count
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to clear unavailability"}), 500

@facilitator_bp.route('/unavailability/generate-recurring', methods=['POST'])
@facilitator_required
def generate_recurring_unavailability():
    """Generate recurring GLOBAL unavailability entries based on pattern"""
    current_user = get_current_user()
    data = request.get_json()
    
    # unit_id is now optional - unavailability is global
    unit_id = data.get('unit_id')  # Ignored, kept for backwards compatibility
    
    # Get the target user (facilitator being edited)
    # If 'user_id' is provided, UC is editing on behalf of facilitator
    target_user_id = data.get('user_id', current_user.id)
    
    # Permission check: user can edit their own data, or UC/admin can edit facilitator's data
    if target_user_id != current_user.id:
        # Someone else is editing - must be UC or admin
        if current_user.role not in [UserRole.ADMIN, UserRole.UNIT_COORDINATOR]:
            return jsonify({"error": "forbidden"}), 403
    
    # Get the target user object
    user = User.query.get(target_user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Check if user is a facilitator in at least one unit
    has_units = UnitFacilitator.query.filter_by(user_id=user.id).first()
    if not has_units:
        return jsonify({"error": "You must be assigned to at least one unit to set unavailability"}), 403
    
    # Parse the base unavailability data
    base_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date()
    recurring_pattern = RecurringPattern(data.get('recurring_pattern'))
    recurring_end_date = datetime.strptime(data.get('recurring_end_date'), '%Y-%m-%d').date()
    recurring_interval = data.get('recurring_interval', 1)
    
    # Generate all dates for the recurring pattern
    # For global unavailability, use the user-specified end date
    effective_end_date = recurring_end_date
    message = None
    
    dates = []
    current_date = base_date
    
    while current_date <= effective_end_date:
        dates.append(current_date)
        
        if recurring_pattern == RecurringPattern.DAILY:
            current_date += timedelta(days=recurring_interval)
        elif recurring_pattern == RecurringPattern.WEEKLY or recurring_pattern == RecurringPattern.CUSTOM:
            # CUSTOM is treated as weekly with custom interval
            current_date += timedelta(weeks=recurring_interval)
        elif recurring_pattern == RecurringPattern.MONTHLY:
            # Simple monthly increment
            year = current_date.year
            month = current_date.month + recurring_interval
            if month > 12:
                year += 1
                month -= 12
            try:
                current_date = current_date.replace(year=year, month=month)
            except ValueError:
                current_date = current_date.replace(year=year, month=month, day=1) - timedelta(days=1)
    
    # Check if multiple time ranges provided
    time_ranges = data.get('time_ranges')
    time_ranges_to_create = []
    
    if time_ranges and len(time_ranges) > 1:
        # Multiple time ranges - validate and prepare them
        for time_range in time_ranges:
            try:
                range_start = datetime.strptime(time_range['start_time'], '%H:%M').time()
                range_end = datetime.strptime(time_range['end_time'], '%H:%M').time()
                time_ranges_to_create.append((range_start, range_end))
            except (ValueError, KeyError) as e:
                return jsonify({"error": f"Invalid time range format: {str(e)}"}), 400
    else:
        # Single time range - parse as before
        start_time = None
        end_time = None
        if not data.get('is_full_day', False):
            start_time_str = data.get('start_time')
            end_time_str = data.get('end_time')
            
            if start_time_str:
                start_time_str = str(start_time_str).strip()
                import re
                time_pattern = re.compile(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$')
                if not time_pattern.match(start_time_str):
                    return jsonify({"error": f"Invalid start time format. Use HH:MM (24-hour format). Received: {start_time_str}"}), 400
                start_time = datetime.strptime(start_time_str, '%H:%M').time()
            else:
                start_time = None
                
            if end_time_str:
                end_time_str = str(end_time_str).strip()
                import re
                time_pattern = re.compile(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$')
                if not time_pattern.match(end_time_str):
                    return jsonify({"error": f"Invalid end time format. Use HH:MM (24-hour format). Received: {end_time_str}"}), 400
                end_time = datetime.strptime(end_time_str, '%H:%M').time()
            else:
                end_time = None
        
        time_ranges_to_create.append((start_time, end_time))
    
    # Create unavailability records for each date and each time range
    created_count = 0
    skipped_count = 0
    skipped_dates = []
    
    for date in dates:
        for start_time, end_time in time_ranges_to_create:
            # Check if GLOBAL unavailability already exists for this date and time combination
            existing = Unavailability.query.filter_by(
                user_id=user.id,
                unit_id=None,  # Global unavailability
                date=date,
                start_time=start_time,
                end_time=end_time
            ).first()
            
            if existing:
                print(f"[DEBUG] RECURRING - Skipping duplicate: date={date}, start={start_time}, end={end_time}")
                continue
            
            # Check for conflicts with auto-generated (scheduled) unavailability
            # Skip creating unavailability if it would conflict with a scheduled session
            auto_generated_on_date = Unavailability.query.filter(
                Unavailability.user_id == user.id,
                Unavailability.unit_id.is_(None),
                Unavailability.date == date,
                Unavailability.source_session_id.isnot(None)  # Auto-generated
            ).all()
            
            has_conflict = False
            if not data.get('is_full_day') and start_time and end_time:
                # Check for time overlap with scheduled sessions
                for auto_unav in auto_generated_on_date:
                    if auto_unav.start_time and auto_unav.end_time:
                        # Check overlap
                        if (start_time < auto_unav.end_time and end_time > auto_unav.start_time):
                            has_conflict = True
                            if date not in skipped_dates:
                                skipped_dates.append(date)
                            print(f"[DEBUG] RECURRING - Skipping {date} due to conflict with scheduled session")
                            break
            
            if has_conflict:
                skipped_count += 1
                continue
            
            # Create the unavailability record
            unavailability = Unavailability(
                user_id=user.id,
                unit_id=None,  # Global unavailability
                date=date,
                start_time=start_time,
                end_time=end_time,
                is_full_day=data.get('is_full_day', False),
                recurring_pattern=recurring_pattern,
                recurring_end_date=recurring_end_date,
                recurring_interval=recurring_interval,
                reason=data.get('reason')
            )
            db.session.add(unavailability)
            print(f"[DEBUG] RECURRING - Creating record: user_id={user.id}, unit_id=None, date={date}, recurring_pattern={recurring_pattern}")
            created_count += 1
    
    # Mark availability as configured for ALL units the facilitator is in
    # (Since unavailability is now global, mark all units)
    unit_facilitators = UnitFacilitator.query.filter_by(
        user_id=user.id
    ).all()
    
    for unit_facilitator in unit_facilitators:
        unit_facilitator.availability_configured = True
    
    db.session.commit()
    
    # Build message
    total_expected = len(dates) * len(time_ranges_to_create)
    duplicates = total_expected - created_count - skipped_count
    
    if skipped_count > 0:
        skipped_dates_str = ', '.join([d.strftime('%b %d') for d in sorted(skipped_dates)])
        message = f"Created {created_count} recurring unavailability entries. Skipped {skipped_count} date(s) due to scheduled commitments ({skipped_dates_str})"
    elif created_count == total_expected:
        message = f"Created {created_count} recurring unavailability entries"
    else:
        message = f"Created {created_count} recurring unavailability entries ({duplicates} already existed)"
    
    response_data = {
        "message": message,
        "total_dates": len(dates),
        "total_time_ranges": len(time_ranges_to_create),
        "created_count": created_count,
        "skipped_count": skipped_count,
        "skipped_dates": [d.isoformat() for d in skipped_dates],
        "availability_configured": True
    }
    
    return jsonify(response_data), 201

@facilitator_bp.post("/copy-unavailability")
@login_required
def copy_unavailability():
    """
    DEPRECATED: This endpoint is no longer needed with global unavailability.
    Unavailability is now global across all units, so there's nothing to copy.
    """
    return jsonify({
        "ok": True,
        "message": "Unavailability is now global across all units. No copying needed.",
        "copied_count": 0,
        "skipped_count": 0
    }), 200

@facilitator_bp.route('/skills', methods=['GET', 'POST'])
@login_required
def manage_skills():
    current_user = get_current_user()
    
    # Handle JSON API requests (for dashboard)
    if request.method == 'GET' and request.args.get('unit_id'):
        unit_id = request.args.get('unit_id')
        target_user_id = request.args.get('user_id', current_user.id)
        
        # Check permission
        if not can_edit_facilitator_data(current_user, int(target_user_id), int(unit_id)):
            return jsonify({"error": "forbidden"}), 403
        
        # Get ALL modules for the unit, excluding "General" module
        all_modules = Module.query.filter_by(unit_id=unit_id).filter(Module.module_name != 'General').all()
        
        # Get facilitator's skills for this unit
        facilitator_skills = db.session.query(FacilitatorSkill, Module).join(
            Module, FacilitatorSkill.module_id == Module.id
        ).filter(
            FacilitatorSkill.facilitator_id == target_user_id,
            Module.unit_id == unit_id
        ).all()
        
        # Create a dictionary of module_id -> skill_level for quick lookup
        skill_lookup = {module.id: skill.skill_level.value for skill, module in facilitator_skills}
        
        # Build skills data with all modules, showing skill level if assigned
        skills_data = []
        for module in all_modules:
            skill_level = skill_lookup.get(module.id, 'no_interest')  # Default to 'no_interest' instead of 'unassigned'
            experience_description = ''
            
            # Get experience description if skill exists
            for skill, skill_module in facilitator_skills:
                if skill_module.id == module.id:
                    experience_description = skill.experience_description or ''
                    break
            
            skills_data.append({
                'module_name': module.module_name,
                'module_type': module.module_type,
                'skill_level': skill_level,
                'module_id': module.id,
                'experience_description': experience_description
            })
        
        return jsonify({
            'success': True,
            'skills': skills_data
        })
    
    # Handle form-based requests (existing functionality)
    # Get all modules
    modules = Module.query.all()
    
    if request.method == 'POST':
        # Handle JSON API requests (for dashboard)
        if request.is_json:
            data = request.get_json()
            unit_id = data.get('unit_id')
            target_user_id = data.get('user_id', current_user.id)
            skills = data.get('skills', {})
            experience_descriptions = data.get('experience_descriptions', {})
            
            if not unit_id:
                return jsonify({"error": "Unit ID is required"}), 400
            
            # Check permission
            if not can_edit_facilitator_data(current_user, int(target_user_id), int(unit_id)):
                return jsonify({"error": "forbidden"}), 403
            
            # Get the unit to check schedule status
            unit = Unit.query.get(unit_id)
            if not unit:
                return jsonify({"error": "Unit not found"}), 404
            
            # Note: We allow editing skills even if schedule is published
            # Existing assignments remain valid, skill changes only affect future auto-assignments
            
            # Use upsert logic: update existing skills or create new ones
            for module_id, skill_level in skills.items():
                try:
                    experience_description = experience_descriptions.get(module_id, '')
                    
                    # Check if skill already exists for this facilitator and module
                    existing_skill = FacilitatorSkill.query.filter_by(
                        facilitator_id=target_user_id,
                        module_id=int(module_id)
                    ).first()
                    
                    if existing_skill:
                        # Update existing skill
                        existing_skill.skill_level = SkillLevel(skill_level)
                        existing_skill.experience_description = experience_description
                        existing_skill.updated_at = datetime.utcnow()
                    else:
                        # Create new skill
                        facilitator_skill = FacilitatorSkill(
                            facilitator_id=target_user_id,
                            module_id=int(module_id),
                            skill_level=SkillLevel(skill_level),
                            experience_description=experience_description
                        )
                        db.session.add(facilitator_skill)
                        
                except ValueError:
                    return jsonify({"error": f"Invalid skill level: {skill_level}"}), 400
            
            # Remove skills that are no longer selected (set to 'unassigned' or not in the skills dict)
            existing_skills = db.session.query(FacilitatorSkill).join(
                Module, FacilitatorSkill.module_id == Module.id
            ).filter(
                FacilitatorSkill.facilitator_id == target_user_id,
                Module.unit_id == unit_id
            ).all()
            
            for skill in existing_skills:
                if str(skill.module_id) not in skills:
                    db.session.delete(skill)
            
            db.session.commit()
            return jsonify({
                "success": True,
                "message": "Skills updated successfully!"
            })
        
        # Handle form-based requests (legacy functionality)
        preferences = request.form.get('preferences', '')
        
        # Update preferences
        current_user.preferences = preferences
        
        # Clear existing skills
        FacilitatorSkill.query.filter_by(facilitator_id=current_user.id).delete()
        
        # Add new skills with levels based on module IDs
        for module in modules:
            skill_level = request.form.get(f'skill_level_{module.id}')
            if skill_level and skill_level != 'uninterested':
                facilitator_skill = FacilitatorSkill(
                    facilitator_id=current_user.id,
                    module_id=module.id,
                    skill_level=SkillLevel(skill_level)
                )
                db.session.add(facilitator_skill)
        
        db.session.commit()
        flash('Skills and preferences updated successfully!')
        return redirect(url_for('facilitator.manage_skills'))
    
    # Get current skills for this facilitator
    current_skills = {}
    facilitator_skills = FacilitatorSkill.query.filter_by(facilitator_id=current_user.id).all()
    for skill in facilitator_skills:
        current_skills[skill.module_id] = skill.skill_level.value
    
    return render_template('manage_skills.html', 
                         user=current_user,
                         modules=modules,
                         current_skills=current_skills,
                         current_preferences=current_user.preferences)

@facilitator_bp.route('/swaps')
@facilitator_required
def view_swaps():
    user = get_current_user()
    my_requests = SwapRequest.query.filter_by(requester_id=user.id).all()
    
    # Fix: Specify the join condition explicitly
    # Get swap requests where the target assignment belongs to the current user
    requests_for_me = SwapRequest.query.join(
        Assignment, 
        SwapRequest.target_assignment_id == Assignment.id
    ).filter(Assignment.facilitator_id == user.id).all()
    
    return render_template('view_swaps.html', 
                         user=user,
                         my_requests=my_requests, 
                         requests_for_me=requests_for_me)

@facilitator_bp.route('/swaps/request', methods=['GET', 'POST'])
@facilitator_required
def request_swap():
    user = get_current_user()
    
    if request.method == 'POST':
        my_assignment_id = request.form.get('my_assignment_id')
        target_assignment_id = request.form.get('target_assignment_id')
        reason = request.form.get('reason', '')
        
        # Validate assignments
        my_assignment = Assignment.query.filter_by(id=my_assignment_id, facilitator_id=user.id).first()
        target_assignment = Assignment.query.get(target_assignment_id)
        
        if not my_assignment or not target_assignment:
            flash('Invalid assignment selection.')
            return redirect(url_for('facilitator.request_swap'))
        
        # Check if swap request already exists
        existing_request = SwapRequest.query.filter_by(
            requester_id=user.id,
            requester_assignment_id=my_assignment_id,
            target_assignment_id=target_assignment_id
        ).first()
        
        if existing_request:
            flash('Swap request already exists for these assignments.')
            return redirect(url_for('facilitator.request_swap'))
        
        # Create swap request
        swap_request = SwapRequest(
            requester_id=user.id,
            target_id=target_assignment.facilitator_id,
            requester_assignment_id=my_assignment_id,
            target_assignment_id=target_assignment_id,
            reason=reason,
            status=SwapStatus.FACILITATOR_PENDING
        )
        
        db.session.add(swap_request)
        db.session.commit()
        
        flash('Swap request submitted successfully!')
        return redirect(url_for('facilitator.view_swaps'))
    
    # Get user's assignments and other available assignments
    my_assignments = Assignment.query.filter_by(facilitator_id=user.id).join(Session).filter(Session.start_time > datetime.utcnow()).all()
    other_assignments = Assignment.query.filter(Assignment.facilitator_id != user.id).join(Session).filter(Session.start_time > datetime.utcnow()).all()
    
    return render_template('request_swap.html', 
                         user=user,
                         my_assignments=my_assignments, 
                         other_assignments=other_assignments)


# New API endpoints for Session Swaps tab

@facilitator_bp.route('/swap-requests', methods=['POST'])
@login_required
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def create_swap_request():
    """Create a new swap request via API."""
    user = get_current_user()
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    requester_assignment_id = data.get('requester_assignment_id')
    target_assignment_id = data.get('target_assignment_id')
    target_facilitator_id = data.get('target_facilitator_id')
    has_discussed = data.get('has_discussed', False)
    unit_id = data.get('unit_id')  # Optional unit context
    
    # Validate required fields
    if not all([requester_assignment_id, target_assignment_id, target_facilitator_id]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    if not has_discussed:
        return jsonify({'error': 'Must confirm discussion with target facilitator'}), 400
    
    # Validate requester assignment
    requester_assignment = Assignment.query.filter_by(
        id=requester_assignment_id, 
        facilitator_id=user.id
    ).first()
    
    if not requester_assignment:
        return jsonify({'error': 'Invalid requester assignment selection'}), 400
    
    # Get the session and module from requester assignment
    session = requester_assignment.session
    module = session.module
    
    # Validate session isn't in the past
    from datetime import datetime
    if session.start_time < datetime.utcnow():
        return jsonify({'error': 'Cannot swap a session that has already occurred'}), 400
    
    # Validate session belongs to requester
    if requester_assignment.facilitator_id != user.id:
        return jsonify({'error': 'You are not assigned to this session'}), 403
    
    # For the target assignment, we'll create a virtual assignment or use the same session
    # Since we're doing a direct notification system, we don't need actual assignment swapping
    # We'll use the same assignment ID for both (simplified approach)
    target_assignment_id = requester_assignment_id
    
    # Check if swap request already exists
    existing_request = SwapRequest.query.filter_by(
        requester_id=user.id,
        requester_assignment_id=requester_assignment_id,
        target_assignment_id=target_assignment_id
    ).first()
    
    if existing_request:
        return jsonify({'error': 'Swap request already exists for these assignments'}), 400
    
    # Verify target facilitator exists and has access to the unit
    target_facilitator = User.query.get(target_facilitator_id)
    if not target_facilitator:
        return jsonify({'error': 'Target facilitator not found'}), 404
    
    # Check if target facilitator is assigned to the same unit
    unit_access = (
        db.session.query(Unit)
        .join(UnitFacilitator, Unit.id == UnitFacilitator.unit_id)
        .filter(Unit.id == module.unit_id, UnitFacilitator.user_id == target_facilitator_id)
        .first()
    )
    
    if not unit_access:
        return jsonify({'error': 'Target facilitator is not assigned to this unit'}), 400
    
    # Check if target facilitator has required skills for this module
    facilitator_skill = FacilitatorSkill.query.filter_by(
        facilitator_id=target_facilitator_id,
        module_id=module.id
    ).first()
    
    if not facilitator_skill or facilitator_skill.skill_level.value == 'no_interest':
        return jsonify({'error': 'Target facilitator does not have required skills for this module'}), 400
    
    # Check availability for the session time
    # Exclude the current session from conflict check (facilitator might already be assigned to it)
    is_available, reason = check_facilitator_availability(
        target_facilitator_id,
        session.start_time.date(),
        session.start_time.time(),
        session.end_time.time(),
        module.unit_id,
        exclude_session_id=session.id
    )
    
    if not is_available:
        return jsonify({'error': f'Target facilitator is not available: {reason}'}), 400
    
    # Create swap request (immediately approved and executed)
    swap_request = SwapRequest(
        requester_id=user.id,
        target_id=target_facilitator_id,
        requester_assignment_id=requester_assignment_id,
        target_assignment_id=target_assignment_id,
        reason="Session swap request (auto-approved)",
        status=SwapStatus.APPROVED,  # Immediately approved
        facilitator_confirmed=True,  # No approval needed
        facilitator_confirmed_at=datetime.utcnow()
    )
    
    try:
        # Add the swap request
        db.session.add(swap_request)
        
        # Get old facilitator ID before transfer
        old_facilitator_id = requester_assignment.facilitator_id
        
        # Transfer the assignment to the target facilitator
        requester_assignment.facilitator_id = target_facilitator_id
        
        # Handle auto-unavailability if the schedule is published
        if session.status == 'published':
            # Remove old facilitator's auto-unavailability for this session
            old_unavail = Unavailability.query.filter_by(
                user_id=old_facilitator_id,
                unit_id=None,  # Global unavailability
                source_session_id=session.id
            ).first()
            
            if old_unavail:
                db.session.delete(old_unavail)
            
            # Create new auto-unavailability for the target facilitator
            session_date = session.start_time.date()
            session_start_time = session.start_time.time()
            session_end_time = session.end_time.time()
            
            # Check if it doesn't already exist
            existing_unavail = Unavailability.query.filter_by(
                user_id=target_facilitator_id,
                unit_id=None,
                date=session_date,
                start_time=session_start_time,
                end_time=session_end_time,
                source_session_id=session.id
            ).first()
            
            if not existing_unavail:
                module_name = module.module_name if module else "Session"
                session_type = session.session_type or "Session"
                unit = Unit.query.get(module.unit_id)
                unit_code = unit.unit_code if unit else "Unknown"
                reason = f"Scheduled: {unit_code} - {module_name} ({session_type})"
                
                new_unavail = Unavailability(
                    user_id=target_facilitator_id,
                    unit_id=None,  # Global unavailability
                    date=session_date,
                    start_time=session_start_time,
                    end_time=session_end_time,
                    is_full_day=False,
                    reason=reason,
                    source_session_id=session.id
                )
                
                db.session.add(new_unavail)
        
        db.session.commit()
        
        # Send email notifications
        try:
            from email_service import send_session_swap_emails
            
            requester = User.query.get(user.id)
            target = User.query.get(target_facilitator_id)
            unit = Unit.query.get(module.unit_id)
            
            session_details = {
                'session_name': f"{module.module_name} - {session.session_type or 'Session'}",
                'date': session.start_time.strftime('%A, %B %d, %Y'),
                'time': f"{session.start_time.strftime('%I:%M %p')} - {session.end_time.strftime('%I:%M %p')}",
                'location': session.location or 'TBA'
            }
            
            send_session_swap_emails(
                requester_email=requester.email,
                requester_name=requester.full_name,
                target_email=target.email,
                target_name=target.full_name,
                session_details=session_details,
                unit_code=unit.unit_code if unit else 'Unknown'
            )
        except Exception as email_error:
            # Don't fail the swap if email fails
            print(f"Warning: Failed to send swap notification emails: {email_error}")
        
        return jsonify({
            'success': True,
            'message': 'Swap request approved and session transferred successfully!',
            'swap_request_id': swap_request.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create and execute swap request: {str(e)}'}), 500


@facilitator_bp.route('/swap-requests', methods=['GET'])
@login_required
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def get_swap_requests():
    """Get user's swap requests grouped by status, filtered by unit."""
    user = get_current_user()
    unit_id = request.args.get('unit_id', type=int)
    
    # Base query for requests made by this user
    my_requests_query = SwapRequest.query.filter_by(requester_id=user.id)
    
    # Base query for requests where this user is the target facilitator
    requests_for_me_query = SwapRequest.query.filter_by(target_id=user.id)
    
    # Filter by unit if provided
    if unit_id:
        # Join with Assignment, Session, and Module to filter by unit
        # Specify the join condition explicitly to avoid ambiguity
        my_requests_query = my_requests_query.join(
            Assignment, SwapRequest.requester_assignment_id == Assignment.id
        ).join(Session).join(Module).filter(Module.unit_id == unit_id)
        
        requests_for_me_query = requests_for_me_query.join(
            Assignment, SwapRequest.target_assignment_id == Assignment.id
        ).join(Session).join(Module).filter(Module.unit_id == unit_id)
    
    my_requests = my_requests_query.all()
    requests_for_me = requests_for_me_query.all()
    
    def serialize_swap_request(req):
        return {
            'id': req.id,
            'requester_name': req.requester.full_name,
            'target_name': req.target.full_name,
            'session_name': req.requester_assignment.session.module.module_name,
            'session_date': req.requester_assignment.session.start_time.strftime('%Y-%m-%d'),
            'session_time': req.requester_assignment.session.start_time.strftime('%H:%M'),
            'session_location': req.requester_assignment.session.location,
            'status': req.status.value,
            'facilitator_confirmed': req.facilitator_confirmed,
            'facilitator_confirmed_at': req.facilitator_confirmed_at.isoformat() if req.facilitator_confirmed_at else None,
            'facilitator_decline_reason': req.facilitator_decline_reason,
            'coordinator_decline_reason': req.coordinator_decline_reason,
            'created_at': req.created_at.isoformat(),
            'is_my_request': req.requester_id == user.id
        }
    
    # Group requests by status
    incoming_requests = []
    approved_requests = []
    declined_requests = []
    
    # Process incoming requests (requests sent TO this user)
    for req in requests_for_me:
        serialized = serialize_swap_request(req)
        serialized['is_incoming'] = True
        incoming_requests.append(serialized)
    
    # Process outgoing requests (requests made BY this user)
    for req in my_requests:
        serialized = serialize_swap_request(req)
        serialized['is_incoming'] = False
        
        # Since we now have immediate approval, all requests go directly to approved
        # Pending status requests are no longer used
        if req.status == SwapStatus.APPROVED:
            approved_requests.append(serialized)
        elif req.status in [SwapStatus.FACILITATOR_DECLINED, SwapStatus.COORDINATOR_DECLINED, SwapStatus.REJECTED]:
            declined_requests.append(serialized)
    
    return jsonify({
        'incoming_requests': incoming_requests,
        'approved_requests': approved_requests,
        'declined_requests': declined_requests
    })


def check_facilitator_availability(facilitator_id, session_date, session_start_time, session_end_time, unit_id, exclude_session_id=None):
    """Check if a facilitator is available for a specific session time.
    
    Args:
        facilitator_id: ID of the facilitator to check
        session_date: Date of the session
        session_start_time: Start time of the session
        session_end_time: End time of the session
        unit_id: ID of the unit
        exclude_session_id: Optional session ID to exclude from conflict check (for swap requests)
    """
    
    # Check for GLOBAL unavailability conflicts
    # Exclude auto-unavailability from the session being checked (for reverse swaps)
    unavailability_query = Unavailability.query.filter(
        Unavailability.user_id == facilitator_id,
        Unavailability.unit_id.is_(None),  # Global unavailability
        Unavailability.date == session_date,
        db.or_(
            Unavailability.is_full_day == True,
            db.and_(
                Unavailability.start_time <= session_start_time,
                Unavailability.end_time >= session_end_time
            )
        )
    )
    
    # Exclude auto-unavailability from the session being swapped
    if exclude_session_id is not None:
        unavailability_query = unavailability_query.filter(
            db.or_(
                Unavailability.source_session_id.is_(None),  # Manual unavailability
                Unavailability.source_session_id != exclude_session_id  # Different session
            )
        )
    
    unavailability_conflict = unavailability_query.first()
    
    if unavailability_conflict:
        return False, "Facilitator has marked unavailability for this time"
    
    # Check for existing session assignments at the same time
    # Exclude the session being swapped (if provided)
    conflict_query = Assignment.query.join(Session).filter(
        Assignment.facilitator_id == facilitator_id,
        db.func.date(Session.start_time) == session_date,
        db.or_(
            db.and_(
                db.func.time(Session.start_time) <= session_start_time,
                db.func.time(Session.end_time) > session_start_time
            ),
            db.and_(
                db.func.time(Session.start_time) < session_end_time,
                db.func.time(Session.end_time) >= session_end_time
            )
        )
    )
    
    # Exclude the session being swapped from conflict check
    if exclude_session_id is not None:
        conflict_query = conflict_query.filter(Session.id != exclude_session_id)
    
    conflicting_assignment = conflict_query.first()
    
    if conflicting_assignment:
        return False, "Facilitator has conflicting session assignment"
    
    return True, "Available"


@facilitator_bp.route('/swap-requests/<int:request_id>/facilitator-response', methods=['POST'])
@login_required
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def facilitator_response_to_swap(request_id):
    """Handle facilitator response to swap request (approve/decline)."""
    user = get_current_user()
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    action = data.get('action')  # 'approve' or 'decline'
    reason = data.get('reason', '')
    
    if action not in ['approve', 'decline']:
        return jsonify({'error': 'Invalid action. Must be approve or decline'}), 400
    
    # Get the swap request
    swap_request = SwapRequest.query.get(request_id)
    if not swap_request:
        return jsonify({'error': 'Swap request not found'}), 404
    
    # Check if user is the target facilitator
    if swap_request.target_id != user.id:
        return jsonify({'error': 'Unauthorized. You are not the target facilitator'}), 403
    
    # Check if request is in correct status
    if swap_request.status != SwapStatus.FACILITATOR_PENDING:
        return jsonify({'error': 'Request is not in facilitator pending status'}), 400
    
    try:
        if action == 'approve':
            # Check availability before approving
            session = swap_request.requester_assignment.session
            session_date = session.start_time.date()
            session_start_time = session.start_time.time()
            session_end_time = session.end_time.time()
            
            is_available, availability_reason = check_facilitator_availability(
                user.id, session_date, session_start_time, session_end_time, session.module.unit_id
            )
            
            if not is_available:
                return jsonify({'error': f'Cannot approve: {availability_reason}'}), 400
            
            # Approve the request
            swap_request.facilitator_confirmed = True
            swap_request.facilitator_confirmed_at = datetime.utcnow()
            swap_request.status = SwapStatus.COORDINATOR_PENDING
            
        else:  # decline
            swap_request.facilitator_confirmed = False
            swap_request.facilitator_confirmed_at = datetime.utcnow()
            swap_request.facilitator_decline_reason = reason
            swap_request.status = SwapStatus.FACILITATOR_DECLINED
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Swap request {action}d successfully',
            'status': swap_request.status.value
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to process response: {str(e)}'}), 500


@facilitator_bp.route('/available-facilitators', methods=['GET'])
@login_required
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def get_available_facilitators():
    """Get available facilitators for a specific session swap."""
    user = get_current_user()
    session_id = request.args.get('session_id', type=int)
    unit_id = request.args.get('unit_id', type=int)
    
    if not session_id:
        return jsonify({'error': 'Session ID is required'}), 400
    
    # Get the session details
    session = Session.query.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    
    # Get the module and unit
    module = Module.query.get(session.module_id)
    if not module:
        return jsonify({'error': 'Module not found'}), 404
    
    unit = Unit.query.get(module.unit_id)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    
    # Verify user has access to this unit
    user_unit_access = (
        db.session.query(Unit)
        .join(UnitFacilitator, Unit.id == UnitFacilitator.unit_id)
        .filter(Unit.id == unit.id, UnitFacilitator.user_id == user.id)
        .first()
    )
    
    if not user_unit_access:
        return jsonify({'error': 'Access denied to this unit'}), 403
    
    # Get all facilitators assigned to this unit (excluding the current user)
    # Include ADMIN role since admins can also be facilitators
    unit_facilitators = (
        db.session.query(User)
        .join(UnitFacilitator, User.id == UnitFacilitator.user_id)
        .filter(
            UnitFacilitator.unit_id == unit.id,
            User.id != user.id,  # Exclude current user
            User.role.in_([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
        )
        .all()
    )
    
    available_facilitators = []
    
    print(f"\n{'='*80}")
    print(f"🔍 DEBUGGING AVAILABLE FACILITATORS FOR SESSION {session.id}")
    print(f"Session: {module.module_name} on {session.start_time}")
    print(f"Checking {len(unit_facilitators)} facilitators in unit {unit.unit_code}")
    print(f"{'='*80}\n")
    
    for facilitator in unit_facilitators:
        print(f"Checking: {facilitator.full_name} ({facilitator.email})")
        
        # Check availability for the session time
        # Exclude the current session from conflict check (facilitator might already be assigned to it)
        is_available, reason = check_facilitator_availability(
            facilitator.id,
            session.start_time.date(),
            session.start_time.time(),
            session.end_time.time(),
            unit.id,
            exclude_session_id=session.id
        )
        
        print(f"  Availability check: {'✅ AVAILABLE' if is_available else '❌ NOT AVAILABLE'}")
        print(f"  Reason: {reason}")
        
        # Check if facilitator has required skills for this module
        has_skills = True
        skill_level = "No skills recorded"
        
        facilitator_skill = FacilitatorSkill.query.filter_by(
            facilitator_id=facilitator.id,
            module_id=module.id
        ).first()
        
        if facilitator_skill:
            skill_level = facilitator_skill.skill_level.value.replace('_', ' ').title()
            print(f"  Skill level: {skill_level}")
            # Only include facilitators with some level of skill (not "no_interest")
            if facilitator_skill.skill_level.value == 'no_interest':
                has_skills = False
                print(f"  ❌ EXCLUDED: No interest in this module")
        else:
            print(f"  ⚠️  No skill record found")
        
        if is_available and has_skills:
            print(f"  ✅ ADDED TO LIST as AVAILABLE")
            available_facilitators.append({
                'id': facilitator.id,
                'name': facilitator.full_name,
                'email': facilitator.email,
                'skill_level': skill_level,
                'reason': 'Available'
            })
        elif not is_available:
            print(f"  ⚠️  ADDED TO LIST as UNAVAILABLE")
            available_facilitators.append({
                'id': facilitator.id,
                'name': facilitator.full_name,
                'email': facilitator.email,
                'skill_level': skill_level,
                'reason': reason,
                'available': False
            })
        else:
            print(f"  ❌ NOT ADDED: Available but no skills")
        
        print()
    
    # Sort by availability status and name
    available_facilitators.sort(key=lambda x: (x.get('available', True), x['name']))
    
    return jsonify({
        'session': {
            'id': session.id,
            'module_name': module.module_name,
            'start_time': session.start_time.isoformat(),
            'end_time': session.end_time.isoformat(),
            'location': session.location
        },
        'facilitators': available_facilitators
    })


# -------------------------- Unavailability (Facilitator) --------------------------
@facilitator_bp.get("/unavailability")
@login_required
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def list_unavailability():
    """List current facilitator's unavailability. Optional filter by unit_id and date range."""
    user = get_current_user()
    unit_id = request.args.get("unit_id", type=int)
    start = request.args.get("start")  # YYYY-MM-DD
    end = request.args.get("end")      # YYYY-MM-DD

    # Query GLOBAL unavailability only (unit_id filter no longer needed)
    q = Unavailability.query.filter_by(user_id=user.id, unit_id=None)
    try:
        if start:
            start_d = datetime.strptime(start, "%Y-%m-%d").date()
            q = q.filter(Unavailability.date >= start_d)
        if end:
            end_d = datetime.strptime(end, "%Y-%m-%d").date()
            q = q.filter(Unavailability.date <= end_d)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid date format; use YYYY-MM-DD"}), 400

    rows = q.order_by(Unavailability.date.asc(), Unavailability.start_time.asc().nulls_first()).all()

    def serialize(u):
        return {
            "id": u.id,
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


def _parse_hhmm(val: str):
    if not val:
        return None
    try:
        hh, mm = map(int, val.split(":", 1))
        return time(hh, mm)
    except Exception:
        return None


def can_edit_facilitator_data(current_user, target_user_id, unit_id=None):
    """
    Check if current_user can edit data for target_user_id.
    For global unavailability (unit_id=None), just checks role.
    For unit-specific data, checks unit permissions.
    
    Returns True if:
    - current_user IS the target user (facilitator editing their own data), OR
    - current_user is a UC/ADMIN
    """
    # Case 1: User editing their own data
    if current_user.id == target_user_id:
        return True
    
    # Case 2: UC or Admin editing facilitator's data
    if current_user.role in [UserRole.UNIT_COORDINATOR, UserRole.ADMIN]:
        # For global unavailability (unit_id=None), any UC/Admin can edit
        if unit_id is None:
            return True
        
        # For unit-specific data, check unit permissions
        # Admins can always edit
        if current_user.role == UserRole.ADMIN:
            # Verify target user is a facilitator in this unit
            link = UnitFacilitator.query.filter_by(unit_id=unit_id, user_id=target_user_id).first()
            return link is not None
        
        # For UNIT_COORDINATOR, check if they're a coordinator for this unit via UnitCoordinator table
        unit = Unit.query.get(unit_id)
        if unit:
            # Check if user is a coordinator for this unit
            is_coordinator = UnitCoordinator.query.filter_by(
                unit_id=unit_id,
                user_id=current_user.id
            ).first() is not None
            
            if is_coordinator:
                # Verify target user is a facilitator in this unit
                link = UnitFacilitator.query.filter_by(unit_id=unit_id, user_id=target_user_id).first()
                return link is not None
    
    return False


@facilitator_bp.route('/swap-requests/<int:request_id>/coordinator-response', methods=['POST'])
@login_required
@role_required(UserRole.UNIT_COORDINATOR)
def coordinator_response_to_swap(request_id):
    """Handle coordinator response to swap request (approve/decline)."""
    user = get_current_user()
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    action = data.get('action')  # 'approve' or 'decline'
    reason = data.get('reason', '')
    
    if action not in ['approve', 'decline']:
        return jsonify({'error': 'Invalid action. Must be approve or decline'}), 400
    
    # Get the swap request
    swap_request = SwapRequest.query.get(request_id)
    if not swap_request:
        return jsonify({'error': 'Swap request not found'}), 404
    
    # Check if request is in correct status
    if swap_request.status != SwapStatus.COORDINATOR_PENDING:
        return jsonify({'error': 'Request is not in coordinator pending status'}), 400
    
    try:
        if action == 'approve':
            # Perform the actual swap
            requester_assignment = swap_request.requester_assignment
            target_assignment = swap_request.target_assignment
            
            # Swap the facilitators
            temp_facilitator_id = requester_assignment.facilitator_id
            requester_assignment.facilitator_id = target_assignment.facilitator_id
            target_assignment.facilitator_id = temp_facilitator_id
            
            swap_request.status = SwapStatus.APPROVED
            swap_request.reviewed_at = datetime.utcnow()
            swap_request.reviewed_by = user.id
            
        else:  # decline
            swap_request.status = SwapStatus.COORDINATOR_DECLINED
            swap_request.coordinator_decline_reason = reason
            swap_request.reviewed_at = datetime.utcnow()
            swap_request.reviewed_by = user.id
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Swap request {action}d successfully',
            'status': swap_request.status.value
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to process response: {str(e)}'}), 500


