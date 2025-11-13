# utils.py
from functools import wraps
from flask import redirect, url_for, flash
from auth import get_current_user
from models import UserRole

# Role hierarchy: ADMIN > UNIT_COORDINATOR > FACILITATOR
ROLE_HIERARCHY = {
    UserRole.ADMIN: [UserRole.ADMIN, UserRole.UNIT_COORDINATOR, UserRole.FACILITATOR],
    UserRole.UNIT_COORDINATOR: [UserRole.UNIT_COORDINATOR, UserRole.FACILITATOR],
    UserRole.FACILITATOR: [UserRole.FACILITATOR]
}

def has_role_access(user_role, required_role):
    """
    Check if a user with user_role has access to a feature requiring required_role.
    Higher roles inherit permissions from lower roles.
    
    Args:
        user_role: The actual role of the user (UserRole enum)
        required_role: The role required for access (UserRole enum)
    
    Returns:
        bool: True if user has access, False otherwise
    """
    if user_role not in ROLE_HIERARCHY:
        return False
    return required_role in ROLE_HIERARCHY[user_role]

def can_access_as_role(user_role, selected_role):
    """
    Check if a user can log in or access features as a specific role.
    
    Args:
        user_role: The actual role of the user (UserRole enum)
        selected_role: The role they want to access as (UserRole enum or string)
    
    Returns:
        bool: True if user can access as the selected role, False otherwise
    """
    # Convert string to UserRole if needed
    if isinstance(selected_role, str):
        role_map = {
            "admin": UserRole.ADMIN,
            "unit_coordinator": UserRole.UNIT_COORDINATOR,
            "facilitator": UserRole.FACILITATOR
        }
        selected_role = role_map.get(selected_role)
        if not selected_role:
            return False
    
    return has_role_access(user_role, selected_role)

def get_available_roles(user_role):
    """
    Get list of roles that a user can access based on their actual role.
    
    Args:
        user_role: The actual role of the user (UserRole enum)
    
    Returns:
        list: List of role strings that the user can access
    """
    if user_role not in ROLE_HIERARCHY:
        return []
    
    role_map = {
        UserRole.ADMIN: "admin",
        UserRole.UNIT_COORDINATOR: "unit_coordinator",
        UserRole.FACILITATOR: "facilitator"
    }
    
    available_roles = []
    for role_enum in ROLE_HIERARCHY[user_role]:
        role_string = role_map.get(role_enum)
        if role_string:
            available_roles.append(role_string)
    
    return available_roles

def role_required(required_roles):
    """
    Decorator to enforce hierarchical role-based access control.
    Higher roles can access features of lower roles.
    
    Args:
        required_roles: Single UserRole or list of UserRole enums
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                flash("Please log in.")
                return redirect(url_for("login"))
            
            # Handle both single role and list of roles
            roles_to_check = required_roles if isinstance(required_roles, list) else [required_roles]
            
            # Check if user has access to any of the required roles (hierarchically)
            has_access = any(has_role_access(user.role, role) for role in roles_to_check)
            
            if not has_access:
                flash("Unauthorized for this area.")
                return redirect(url_for("login"))
            
            return fn(*args, **kwargs)
        return wrapper
    return decorator