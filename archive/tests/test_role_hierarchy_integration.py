#!/usr/bin/env python3
"""
Integration test for hierarchical role access system with session management.
Tests the complete flow from login to accessing different portals.
"""

import sys
import os

# Setup Flask app context
sys.path.insert(0, os.path.dirname(__file__))

from application import app
from models import db, User, UserRole
from werkzeug.security import generate_password_hash

def setup_test_users():
    """Create test users with different roles"""
    with app.app_context():
        # Clear existing test users
        User.query.filter(User.email.like('test_%@example.com')).delete()
        
        # Create test users
        facilitator = User(
            email='test_facilitator@example.com',
            first_name='Test',
            last_name='Facilitator',
            role=UserRole.FACILITATOR,
            password_hash=generate_password_hash('Password123!')
        )
        
        unit_coordinator = User(
            email='test_uc@example.com',
            first_name='Test',
            last_name='UC',
            role=UserRole.UNIT_COORDINATOR,
            password_hash=generate_password_hash('Password123!')
        )
        
        admin = User(
            email='test_admin@example.com',
            first_name='Test',
            last_name='Admin',
            role=UserRole.ADMIN,
            password_hash=generate_password_hash('Password123!')
        )
        
        db.session.add_all([facilitator, unit_coordinator, admin])
        db.session.commit()
        
        return {
            'facilitator': facilitator,
            'unit_coordinator': unit_coordinator,
            'admin': admin
        }

def test_login_with_role_selection():
    """Test that users can log in with different role selections"""
    print("\n" + "="*60)
    print("Testing Login with Role Selection")
    print("="*60)
    
    # Temporarily disable CSRF for testing
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.app_context():
        test_users = setup_test_users()
        
        # Test 1: Facilitator can only log in as facilitator
        print("\n--- Test 1: Facilitator login ---")
        with app.test_client() as client:
            # Try to log in as admin (should fail)
            response = client.post('/login', data={
                'email': 'test_facilitator@example.com',
                'password': 'Password123!',
                'user_role': 'admin'
            }, follow_redirects=False)
            # Debug: print response
            if response.status_code != 200 and response.status_code != 302:
                print(f"DEBUG: Status code: {response.status_code}")
                print(f"DEBUG: Response data: {response.data[:500]}")
            # Should stay on login page with error message
            assert b"You don't have permission" in response.data or b"permission" in response.data
            print("✓ Facilitator cannot log in as admin")
            
            # Try to log in as UC (should fail)
            response = client.post('/login', data={
                'email': 'test_facilitator@example.com',
                'password': 'Password123!',
                'user_role': 'unit_coordinator'
            }, follow_redirects=False)
            assert b"You don't have permission" in response.data or b"permission" in response.data
            print("✓ Facilitator cannot log in as unit coordinator")
            
            # Log in as facilitator (should succeed)
            response = client.post('/login', data={
                'email': 'test_facilitator@example.com',
                'password': 'Password123!',
                'user_role': 'facilitator'
            }, follow_redirects=False)
            assert response.status_code == 302
            assert '/facilitator' in response.location
            print("✓ Facilitator can log in as facilitator")
        
        # Test 2: Unit Coordinator can log in as UC or facilitator
        print("\n--- Test 2: Unit Coordinator login ---")
        with app.test_client() as client:
            # Try to log in as admin (should fail)
            response = client.post('/login', data={
                'email': 'test_uc@example.com',
                'password': 'Password123!',
                'user_role': 'admin'
            }, follow_redirects=False)
            assert b"You don't have permission" in response.data or b"permission" in response.data
            print("✓ Unit Coordinator cannot log in as admin")
            
            # Log in as UC (should succeed)
            response = client.post('/login', data={
                'email': 'test_uc@example.com',
                'password': 'Password123!',
                'user_role': 'unit_coordinator'
            }, follow_redirects=False)
            assert response.status_code == 302
            assert '/unitcoordinator' in response.location or response.location.endswith('/')
            print("✓ Unit Coordinator can log in as unit coordinator")
            
        with app.test_client() as client:
            # Log in as facilitator (should succeed) - THIS IS THE KEY TEST
            response = client.post('/login', data={
                'email': 'test_uc@example.com',
                'password': 'Password123!',
                'user_role': 'facilitator'
            }, follow_redirects=False)
            assert response.status_code == 302
            assert '/facilitator' in response.location
            
            # Check that selected_role is stored in session
            with client.session_transaction() as sess:
                assert sess.get('selected_role') == 'facilitator'
                assert sess.get('user_id') is not None
            
            print("✓ Unit Coordinator can log in as facilitator")
            print("✓ selected_role is stored in session")
        
        # Test 3: Admin can log in as any role
        print("\n--- Test 3: Admin login ---")
        with app.test_client() as client:
            # Log in as admin
            response = client.post('/login', data={
                'email': 'test_admin@example.com',
                'password': 'Password123!',
                'user_role': 'admin'
            }, follow_redirects=False)
            assert response.status_code == 302
            assert '/admin' in response.location or response.location.endswith('/')
            print("✓ Admin can log in as admin")
            
        with app.test_client() as client:
            # Log in as UC
            response = client.post('/login', data={
                'email': 'test_admin@example.com',
                'password': 'Password123!',
                'user_role': 'unit_coordinator'
            }, follow_redirects=False)
            assert response.status_code == 302
            assert '/unitcoordinator' in response.location or response.location.endswith('/')
            print("✓ Admin can log in as unit coordinator")
            
        with app.test_client() as client:
            # Log in as facilitator
            response = client.post('/login', data={
                'email': 'test_admin@example.com',
                'password': 'Password123!',
                'user_role': 'facilitator'
            }, follow_redirects=False)
            assert response.status_code == 302
            assert '/facilitator' in response.location
            print("✓ Admin can log in as facilitator")

def test_index_redirect():
    """Test that index page redirects based on selected_role in session"""
    print("\n" + "="*60)
    print("Testing Index Page Redirect with selected_role")
    print("="*60)
    
    # Temporarily disable CSRF for testing
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.app_context():
        test_users = setup_test_users()
        
        # Test: UC logs in as facilitator, then accesses index
        print("\n--- Unit Coordinator logged in as facilitator ---")
        with app.test_client() as client:
            # Log in as facilitator
            response = client.post('/login', data={
                'email': 'test_uc@example.com',
                'password': 'Password123!',
                'user_role': 'facilitator'
            }, follow_redirects=False)
            
            # Access index page - should redirect to facilitator dashboard
            response = client.get('/', follow_redirects=False)
            assert response.status_code == 302
            assert '/facilitator' in response.location
            print("✓ Index redirects to facilitator dashboard when UC is logged in as facilitator")
        
        # Test: Admin logs in as facilitator, then accesses index
        print("\n--- Admin logged in as facilitator ---")
        with app.test_client() as client:
            # Log in as facilitator
            response = client.post('/login', data={
                'email': 'test_admin@example.com',
                'password': 'Password123!',
                'user_role': 'facilitator'
            }, follow_redirects=False)
            
            # Access index page - should redirect to facilitator dashboard
            response = client.get('/', follow_redirects=False)
            assert response.status_code == 302
            assert '/facilitator' in response.location
            print("✓ Index redirects to facilitator dashboard when admin is logged in as facilitator")

def test_role_switching():
    """Test the role switching functionality"""
    print("\n" + "="*60)
    print("Testing Role Switching")
    print("="*60)
    
    # Temporarily disable CSRF for testing
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.app_context():
        test_users = setup_test_users()
        
        # Test: UC switches from UC role to facilitator role
        print("\n--- Unit Coordinator switching roles ---")
        with app.test_client() as client:
            # Log in as UC
            client.post('/login', data={
                'email': 'test_uc@example.com',
                'password': 'Password123!',
                'user_role': 'unit_coordinator'
            })
            
            # Switch to facilitator role
            response = client.post('/switch-role', data={
                'new_role': 'facilitator'
            }, follow_redirects=False)
            
            assert response.status_code == 302
            assert '/facilitator' in response.location
            
            # Check session
            with client.session_transaction() as sess:
                assert sess.get('selected_role') == 'facilitator'
            
            print("✓ Unit Coordinator can switch to facilitator role")
            
            # Try to switch to admin (should fail)
            response = client.post('/switch-role', data={
                'new_role': 'admin'
            }, follow_redirects=False)
            
            # Should get a redirect (error handling redirects back)
            assert response.status_code == 302
            
            # Check that session role did NOT change to admin
            with client.session_transaction() as sess:
                current_role = sess.get('selected_role')
                assert current_role == 'facilitator', f"Role should still be facilitator, but got {current_role}"
            
            print("✓ Unit Coordinator cannot switch to admin role")
        
        # Test: Admin can switch to any role
        print("\n--- Admin switching roles ---")
        with app.test_client() as client:
            # Log in as admin
            client.post('/login', data={
                'email': 'test_admin@example.com',
                'password': 'Password123!',
                'user_role': 'admin'
            })
            
            # Switch to facilitator
            response = client.post('/switch-role', data={
                'new_role': 'facilitator'
            }, follow_redirects=False)
            assert '/facilitator' in response.location
            print("✓ Admin can switch to facilitator role")
            
            # Switch to UC
            response = client.post('/switch-role', data={
                'new_role': 'unit_coordinator'
            }, follow_redirects=False)
            assert '/unitcoordinator' in response.location
            print("✓ Admin can switch to unit coordinator role")
            
            # Switch back to admin
            response = client.post('/switch-role', data={
                'new_role': 'admin'
            }, follow_redirects=False)
            assert '/admin' in response.location or response.location.endswith('/')
            print("✓ Admin can switch back to admin role")

def main():
    """Run all integration tests"""
    try:
        test_login_with_role_selection()
        test_index_redirect()
        test_role_switching()
        
        print("\n" + "="*60)
        print("✅ ALL INTEGRATION TESTS PASSED!")
        print("="*60)
        print("\nThe hierarchical role system with session management is working correctly:")
        print("• Users can log in with their selected role")
        print("• selected_role is properly stored in session")
        print("• Index page respects selected_role for redirects")
        print("• Users with higher roles can switch to lower roles")
        print("• Unit Coordinators can access facilitator portal")
        print("• Admins can access all portals")
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())

