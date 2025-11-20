# Hierarchical Role System Implementation

## Overview

This document describes the hierarchical role-based access control system that allows users with higher roles to access functionality of lower roles without losing their original permissions.

## Role Hierarchy

The system implements a three-tier role hierarchy:

```
ADMIN (highest)
  ├─ Can access: Admin, Unit Coordinator, and Facilitator portals
  └─ Full system access

UNIT_COORDINATOR (middle)
  ├─ Can access: Unit Coordinator and Facilitator portals
  └─ Cannot access: Admin portal

FACILITATOR (lowest)
  ├─ Can access: Facilitator portal only
  └─ Cannot access: Unit Coordinator or Admin portals
```

## Key Features

### 1. Role Selection at Login

Users can select which role they want to log in as from the login page:
- **Facilitators**: Can only select "Facilitator"
- **Unit Coordinators**: Can select "Facilitator" or "Unit Coordinator"
- **Admins**: Can select "Facilitator", "Unit Coordinator", or "Admin"

The selected role is stored in the session and respected throughout the application.

### 2. Session Management

When a user logs in:
- `session['user_id']` stores the user's ID
- `session['selected_role']` stores the role they selected (e.g., 'facilitator', 'unit_coordinator', 'admin')

This allows the system to distinguish between:
- What role the user actually has (stored in database)
- What role they're currently using (stored in session)

### 3. Role Switching

Users can switch between roles they have access to without logging out:

**Route**: `POST /switch-role`
**Parameters**: `new_role` (string: 'facilitator', 'unit_coordinator', or 'admin')

Example:
```javascript
fetch('/switch-role', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
    'X-CSRFToken': getCsrfToken()
  },
  body: 'new_role=facilitator'
});
```

### 4. Index Page Redirect

The index page (`/`) automatically redirects users to the appropriate dashboard based on their `selected_role`:
- `selected_role='admin'` → `/admin/dashboard`
- `selected_role='unit_coordinator'` → `/unitcoordinator/dashboard`
- `selected_role='facilitator'` → `/facilitator/dashboard`

This ensures that users stay in their selected role context even when navigating to the home page.

## Implementation Details

### Files Modified

1. **`utils.py`**
   - Added `ROLE_HIERARCHY` dictionary defining role permissions
   - Added `has_role_access(user_role, required_role)` function
   - Added `can_access_as_role(user_role, selected_role)` function
   - Added `get_available_roles(user_role)` function
   - Updated `role_required` decorator to support hierarchical access

2. **`application.py`**
   - Updated login route to store `selected_role` in session
   - Updated index route to use `selected_role` for redirects
   - Updated Google OAuth callback to set `selected_role`
   - Added `/switch-role` route for role switching
   - Updated context processor to inject role information into templates

3. **`auth.py`**
   - Updated `set_user_session()` to accept optional `selected_role` parameter
   - Updated `facilitator_required` decorator to allow hierarchical access

### Decorators

#### `@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])`

This decorator implements hierarchical role checking. It checks if the user has access to ANY of the specified roles.

**Examples:**
```python
# Facilitator routes - accessible by FACILITATOR, UNIT_COORDINATOR, and ADMIN
@facilitator_bp.route("/dashboard")
@role_required([UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR])
def dashboard():
    pass

# UC routes - accessible by UNIT_COORDINATOR and ADMIN  
@unitcoordinator_bp.route("/dashboard")
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def dashboard():
    pass

# Admin-only routes - accessible by ADMIN only
@admin_bp.route("/dashboard")
@role_required(UserRole.ADMIN)
def dashboard():
    pass
```

Note: The decorator automatically handles the hierarchy. If a route requires `FACILITATOR` role, it will automatically allow `UNIT_COORDINATOR` and `ADMIN` users as well, because they have hierarchical access.

### Template Context Variables

The following variables are available in all templates:

- `user` - The current User object
- `available_roles` - List of role strings the user can access (e.g., ['facilitator', 'unit_coordinator'])
- `selected_role` - The role the user is currently using (e.g., 'facilitator')
- `actual_role` - The user's actual role from the database (e.g., 'Unit_Coordinator')

**Example usage in templates:**
```html
{% if 'admin' in available_roles %}
  <a href="#" onclick="switchRole('admin')">Switch to Admin</a>
{% endif %}

{% if selected_role == 'facilitator' %}
  <p>You are viewing as a Facilitator</p>
{% endif %}
```

## Use Cases

### Use Case 1: Unit Coordinator Needs to View Their Own Schedule

**Scenario**: A Unit Coordinator wants to see their own schedule as a facilitator.

**Solution**:
1. Log in and select "Facilitator" role
2. OR log in as "Unit Coordinator" and then click "Switch to Facilitator"
3. Access the facilitator dashboard to view their schedule

### Use Case 2: Admin Wants to Test Facilitator View

**Scenario**: An admin wants to test how the system looks from a facilitator's perspective.

**Solution**:
1. Log in and select "Facilitator" role
2. The admin will see exactly what facilitators see
3. Switch back to admin role when needed

### Use Case 3: Unit Coordinator Promoted from Facilitator

**Scenario**: A facilitator is promoted to Unit Coordinator role.

**Before (Problem)**: They lose access to the facilitator portal.

**After (Solution)**: They can:
- Log in as "Unit Coordinator" to manage their units
- Log in as "Facilitator" to view their own schedule and swap requests
- Switch between roles without logging out

## Testing

Two test files verify the system works correctly:

1. **`test_role_hierarchy.py`** - Unit tests for utility functions
   ```bash
   python test_role_hierarchy.py
   ```

2. **`test_role_hierarchy_integration.py`** - Integration tests for full system
   ```bash
   python test_role_hierarchy_integration.py
   ```

Both test files should pass with all checks showing ✅.

## Upgrading Existing Users

If you have existing users in the database who have been upgraded from facilitator to unit coordinator:

1. **No action needed!** The system will automatically work.
2. When they log in, they can select which role they want to use.
3. If they select "facilitator", they will have access to the facilitator portal.
4. If they select "unit_coordinator", they will have access to the UC portal.

## Future Enhancements

Potential improvements to consider:

1. **Role Switching UI Component**: Add a dropdown in the header to easily switch roles
2. **Remember Last Selected Role**: Store the user's preferred role in the database
3. **Role-Specific Customizations**: Show different sidebar menus based on selected role
4. **Audit Logging**: Track when users switch roles for security purposes

## Security Considerations

- Users can only access roles they have hierarchical permission for
- The `selected_role` in session is validated against the user's actual role
- All route decorators still enforce proper permissions
- OAuth login automatically sets the selected role based on user's actual role
- Session data is server-side and cannot be tampered with by clients

## Troubleshooting

### Issue: User cannot access facilitator portal after promotion to UC

**Check**:
1. Verify the user's role in the database is `Unit_Coordinator`
2. Ensure they select "Facilitator" at login or use role switching
3. Check that `session['selected_role']` is set to 'facilitator'

### Issue: User sees wrong dashboard after login

**Check**:
1. Verify the `selected_role` was stored correctly in session
2. Check the index route is using `session.get('selected_role')`
3. Ensure the login form is sending the `user_role` parameter

### Issue: Role switching doesn't work

**Check**:
1. Verify CSRF token is included in the POST request
2. Check that `/switch-role` route is handling the request
3. Verify the user has hierarchical access to the target role
4. Check for flash messages indicating permission errors

## Summary

The hierarchical role system allows users with higher roles to seamlessly access functionality of lower roles, solving the problem where promoted users lose access to their original functionality. The system is secure, well-tested, and easy to extend.

