#!/usr/bin/env python3
"""Verify that uc2 has full access to units they coordinate"""

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from application import app, db
from models import User, Unit, UnitCoordinator, Module, Session
from unitcoordinator_routes import _get_user_unit_or_404

def verify_uc2_access():
    with app.app_context():
        uc2 = User.query.filter_by(email='uc2@example.com').first()
        if not uc2:
            print("❌ uc2 not found")
            return
        
        print(f"✅ Found uc2: {uc2.email} (ID: {uc2.id})")
        
        # Get all units uc2 coordinates
        coord_links = UnitCoordinator.query.filter_by(user_id=uc2.id).all()
        print(f"\n📋 uc2 coordinates {len(coord_links)} unit(s):")
        
        for link in coord_links:
            unit = Unit.query.get(link.unit_id)
            if not unit:
                continue
            
            print(f"\n  Unit: {unit.unit_code} ({unit.unit_name})")
            
            # Test access
            result = _get_user_unit_or_404(uc2, unit.id)
            if result:
                print(f"    ✅ Can access unit")
            else:
                print(f"    ❌ CANNOT access unit - THIS IS A PROBLEM!")
            
            # Check modules
            modules = Module.query.filter_by(unit_id=unit.id).all()
            print(f"    ✅ Can see {len(modules)} module(s)")
            
            # Check sessions
            sessions = db.session.query(Session).join(Module).filter(Module.unit_id == unit.id).all()
            print(f"    ✅ Can see {len(sessions)} session(s)")
            
            # Check if creator
            is_creator = unit.created_by == uc2.id
            print(f"    ℹ️  Is creator: {is_creator}")
            print(f"    ℹ️  Created by user ID: {unit.created_by}")
        
        if len(coord_links) == 0:
            print("\n⚠️  WARNING: uc2 is not assigned to any units!")
            print("   They need to be added as a coordinator to see units.")
            print("   Use the 'Add Coordinator' feature or run:")
            print("   python3 -c \"from application import app, db; from models import User, Unit, UnitCoordinator; app.app_context().push(); uc2 = User.query.filter_by(email='uc2@example.com').first(); unit = Unit.query.first(); UnitCoordinator(unit_id=unit.id, user_id=uc2.id); db.session.add(_); db.session.commit()\"")

if __name__ == "__main__":
    verify_uc2_access()

