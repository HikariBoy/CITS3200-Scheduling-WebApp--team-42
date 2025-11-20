#!/usr/bin/env python3
"""
Test script to verify hierarchical role access system.
This script tests that:
1. ADMIN can access admin, unit coordinator, and facilitator routes
2. UNIT_COORDINATOR can access unit coordinator and facilitator routes
3. FACILITATOR can only access facilitator routes
"""

from models import UserRole
from utils import has_role_access, can_access_as_role, ROLE_HIERARCHY

def test_role_hierarchy():
    """Test the role hierarchy configuration"""
    print("=" * 60)
    print("Testing Role Hierarchy Configuration")
    print("=" * 60)
    
    # Verify hierarchy structure
    assert UserRole.ADMIN in ROLE_HIERARCHY
    assert UserRole.UNIT_COORDINATOR in ROLE_HIERARCHY
    assert UserRole.FACILITATOR in ROLE_HIERARCHY
    
    print("\n✓ All roles are defined in hierarchy")
    
    # Test ADMIN role access
    print("\n--- Testing ADMIN role access ---")
    assert UserRole.ADMIN in ROLE_HIERARCHY[UserRole.ADMIN]
    assert UserRole.UNIT_COORDINATOR in ROLE_HIERARCHY[UserRole.ADMIN]
    assert UserRole.FACILITATOR in ROLE_HIERARCHY[UserRole.ADMIN]
    print("✓ ADMIN can access: ADMIN, UNIT_COORDINATOR, FACILITATOR")
    
    # Test UNIT_COORDINATOR role access
    print("\n--- Testing UNIT_COORDINATOR role access ---")
    assert UserRole.UNIT_COORDINATOR in ROLE_HIERARCHY[UserRole.UNIT_COORDINATOR]
    assert UserRole.FACILITATOR in ROLE_HIERARCHY[UserRole.UNIT_COORDINATOR]
    assert UserRole.ADMIN not in ROLE_HIERARCHY[UserRole.UNIT_COORDINATOR]
    print("✓ UNIT_COORDINATOR can access: UNIT_COORDINATOR, FACILITATOR")
    print("✓ UNIT_COORDINATOR cannot access: ADMIN")
    
    # Test FACILITATOR role access
    print("\n--- Testing FACILITATOR role access ---")
    assert UserRole.FACILITATOR in ROLE_HIERARCHY[UserRole.FACILITATOR]
    assert UserRole.UNIT_COORDINATOR not in ROLE_HIERARCHY[UserRole.FACILITATOR]
    assert UserRole.ADMIN not in ROLE_HIERARCHY[UserRole.FACILITATOR]
    print("✓ FACILITATOR can access: FACILITATOR only")
    print("✓ FACILITATOR cannot access: UNIT_COORDINATOR, ADMIN")

def test_has_role_access():
    """Test the has_role_access function"""
    print("\n" + "=" * 60)
    print("Testing has_role_access() Function")
    print("=" * 60)
    
    # Test ADMIN access
    print("\n--- ADMIN user accessing different roles ---")
    assert has_role_access(UserRole.ADMIN, UserRole.ADMIN) == True
    print("✓ ADMIN -> ADMIN: True")
    assert has_role_access(UserRole.ADMIN, UserRole.UNIT_COORDINATOR) == True
    print("✓ ADMIN -> UNIT_COORDINATOR: True")
    assert has_role_access(UserRole.ADMIN, UserRole.FACILITATOR) == True
    print("✓ ADMIN -> FACILITATOR: True")
    
    # Test UNIT_COORDINATOR access
    print("\n--- UNIT_COORDINATOR user accessing different roles ---")
    assert has_role_access(UserRole.UNIT_COORDINATOR, UserRole.ADMIN) == False
    print("✓ UNIT_COORDINATOR -> ADMIN: False")
    assert has_role_access(UserRole.UNIT_COORDINATOR, UserRole.UNIT_COORDINATOR) == True
    print("✓ UNIT_COORDINATOR -> UNIT_COORDINATOR: True")
    assert has_role_access(UserRole.UNIT_COORDINATOR, UserRole.FACILITATOR) == True
    print("✓ UNIT_COORDINATOR -> FACILITATOR: True")
    
    # Test FACILITATOR access
    print("\n--- FACILITATOR user accessing different roles ---")
    assert has_role_access(UserRole.FACILITATOR, UserRole.ADMIN) == False
    print("✓ FACILITATOR -> ADMIN: False")
    assert has_role_access(UserRole.FACILITATOR, UserRole.UNIT_COORDINATOR) == False
    print("✓ FACILITATOR -> UNIT_COORDINATOR: False")
    assert has_role_access(UserRole.FACILITATOR, UserRole.FACILITATOR) == True
    print("✓ FACILITATOR -> FACILITATOR: True")

def test_can_access_as_role():
    """Test the can_access_as_role function with string inputs"""
    print("\n" + "=" * 60)
    print("Testing can_access_as_role() Function (Login Simulation)")
    print("=" * 60)
    
    # Test ADMIN login as different roles
    print("\n--- ADMIN user logging in as different roles ---")
    assert can_access_as_role(UserRole.ADMIN, "admin") == True
    print("✓ ADMIN can log in as 'admin'")
    assert can_access_as_role(UserRole.ADMIN, "unit_coordinator") == True
    print("✓ ADMIN can log in as 'unit_coordinator'")
    assert can_access_as_role(UserRole.ADMIN, "facilitator") == True
    print("✓ ADMIN can log in as 'facilitator'")
    
    # Test UNIT_COORDINATOR login as different roles
    print("\n--- UNIT_COORDINATOR user logging in as different roles ---")
    assert can_access_as_role(UserRole.UNIT_COORDINATOR, "admin") == False
    print("✓ UNIT_COORDINATOR cannot log in as 'admin'")
    assert can_access_as_role(UserRole.UNIT_COORDINATOR, "unit_coordinator") == True
    print("✓ UNIT_COORDINATOR can log in as 'unit_coordinator'")
    assert can_access_as_role(UserRole.UNIT_COORDINATOR, "facilitator") == True
    print("✓ UNIT_COORDINATOR can log in as 'facilitator'")
    
    # Test FACILITATOR login as different roles
    print("\n--- FACILITATOR user logging in as different roles ---")
    assert can_access_as_role(UserRole.FACILITATOR, "admin") == False
    print("✓ FACILITATOR cannot log in as 'admin'")
    assert can_access_as_role(UserRole.FACILITATOR, "unit_coordinator") == False
    print("✓ FACILITATOR cannot log in as 'unit_coordinator'")
    assert can_access_as_role(UserRole.FACILITATOR, "facilitator") == True
    print("✓ FACILITATOR can log in as 'facilitator'")

def test_use_case_scenarios():
    """Test real-world use case scenarios"""
    print("\n" + "=" * 60)
    print("Testing Real-World Use Case Scenarios")
    print("=" * 60)
    
    print("\nScenario 1: Unit Coordinator promoted from Facilitator")
    print("A facilitator is promoted to unit coordinator.")
    print("They should be able to access both UC and facilitator portals.")
    assert can_access_as_role(UserRole.UNIT_COORDINATOR, "facilitator") == True
    assert can_access_as_role(UserRole.UNIT_COORDINATOR, "unit_coordinator") == True
    print("✓ Unit coordinator can access facilitator portal")
    print("✓ Unit coordinator can access their UC portal")
    
    print("\nScenario 2: Unit Coordinator accessing facilitator routes")
    print("A unit coordinator wants to view their own schedule as a facilitator.")
    assert has_role_access(UserRole.UNIT_COORDINATOR, UserRole.FACILITATOR) == True
    print("✓ Unit coordinator has access to facilitator routes")
    
    print("\nScenario 3: Admin accessing any portal")
    print("An admin wants to test the system from different user perspectives.")
    assert can_access_as_role(UserRole.ADMIN, "admin") == True
    assert can_access_as_role(UserRole.ADMIN, "unit_coordinator") == True
    assert can_access_as_role(UserRole.ADMIN, "facilitator") == True
    print("✓ Admin can access admin portal")
    print("✓ Admin can access unit coordinator portal")
    print("✓ Admin can access facilitator portal")
    
    print("\nScenario 4: Facilitator trying to access higher role")
    print("A facilitator should not be able to access UC or admin portals.")
    assert can_access_as_role(UserRole.FACILITATOR, "unit_coordinator") == False
    assert can_access_as_role(UserRole.FACILITATOR, "admin") == False
    print("✓ Facilitator cannot access unit coordinator portal")
    print("✓ Facilitator cannot access admin portal")

def main():
    """Run all tests"""
    try:
        test_role_hierarchy()
        test_has_role_access()
        test_can_access_as_role()
        test_use_case_scenarios()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        print("\nThe hierarchical role system is working correctly:")
        print("• ADMIN can access all portals (admin, UC, facilitator)")
        print("• UNIT_COORDINATOR can access UC and facilitator portals")
        print("• FACILITATOR can only access facilitator portal")
        print("\nUsers with higher roles can now log in as lower roles")
        print("without losing access to their original functionality.")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())

