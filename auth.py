from functools import wraps
from flask import session, redirect, url_for, request, flash
from urllib.parse import urlparse, urljoin
from models import User, UserRole
from flask import Blueprint

auth_bp = Blueprint("auth", __name__)

def set_user_session(user, selected_role=None):
    """
    Set user session data with authentication flag.
    
    Args:
        user: The User object
        selected_role: Optional selected role string ('admin', 'unit_coordinator', 'facilitator')
                      If not provided, defaults to user's actual role
    """
    if user:
        session['user_id'] = user.id
        session['role'] = user.role.value
        session['authenticated'] = True
        
        # Set selected_role for hierarchical role system
        if selected_role:
            session['selected_role'] = selected_role
        else:
            # Default to user's actual role
            role_map = {
                UserRole.ADMIN: 'admin',
                UserRole.UNIT_COORDINATOR: 'unit_coordinator',
                UserRole.FACILITATOR: 'facilitator'
            }
            session['selected_role'] = role_map.get(user.role, 'facilitator')
        
        return True
    return False

def test_session_creation(self):
    """Test session creation"""
    with self.app.test_request_context():
        # Set session
        set_user_session(self.test_user)
        
        # Verify all session data
        expected_session = {
            'user_id': self.test_user.id,
            'role': self.test_user.role.value,
            'authenticated': True
        }
        
        for key, value in expected_session.items():
            self.assertIn(key, session)
            self.assertEqual(session[key], value)

def clear_user_session():
    """Clear user session data"""
    session.clear()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        # Verify user exists in database
        user = User.query.get(session['user_id'])
        if not user:
            session.clear()  # Clear invalid session
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """
    Decorator requiring admin role (only exact admin role, no hierarchy).
    For hierarchical access, use @role_required from utils.py
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        
        user = User.query.get(session['user_id'])
        if not user or user.role != UserRole.ADMIN:
            flash("Access denied. Admin privileges required.")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper

def facilitator_required(f):
    """
    Decorator requiring facilitator access (allows FACILITATOR, UNIT_COORDINATOR, and ADMIN roles).
    This implements hierarchical role access.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        
        user = User.query.get(session['user_id'])
        if not user:
            flash("Access denied. Please log in.")
            return redirect(url_for("index"))
        
        # Allow FACILITATOR, UNIT_COORDINATOR, and ADMIN to access facilitator routes
        allowed_roles = [UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR, UserRole.ADMIN]
        if user.role not in allowed_roles:
            flash("Access denied. Facilitator privileges required.")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper

def is_safe_url(target):
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc

def get_current_user():
    if "user_id" in session:
        user = User.query.get(session['user_id'])
        if user is None:
            session.pop("user_id", None)
        return user
    return None

@auth_bp.route("/logout", methods=["POST"])
def logout():
    from flask import session, redirect, url_for, request, flash
    session.clear()
    flash("You have been logged out.", "info")

    # Optional: support safe redirect if "next" param is present
    next_url = request.args.get("next")
    if next_url and is_safe_url(next_url):
        return redirect(next_url)

    # Default: back to login page
    return redirect(url_for("login"))
