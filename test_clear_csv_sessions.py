"""
Test for the clear CSV sessions functionality.
This test verifies that the UC can remove all uploaded CSV sessions.
"""
import unittest
from datetime import datetime, timedelta
from application import app, db
from models import User, UserRole, Unit, Module, Session, Assignment, Facilitator
from auth import hash_password


class TestClearCsvSessions(unittest.TestCase):
    """Test clearing CSV sessions functionality"""

    def setUp(self):
        """Set up test client and test database"""
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        
        with app.app_context():
            db.create_all()
            
            # Create UC user
            uc_user = User(
                email='uc@test.edu',
                password=hash_password('password123'),
                role=UserRole.UNIT_COORDINATOR,
                first_name='Test',
                last_name='Coordinator'
            )
            db.session.add(uc_user)
            db.session.commit()
            
            # Login as UC
            self.client.post('/login', data={
                'email': 'uc@test.edu',
                'password': 'password123'
            })

    def tearDown(self):
        """Clean up after tests"""
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_clear_csv_sessions_success(self):
        """Test successfully clearing all sessions for a unit"""
        with app.app_context():
            # Create a unit
            unit = Unit(
                unit_code='TEST1001',
                unit_name='Test Unit',
                semester='S1',
                year=2024,
                start_date=datetime(2024, 2, 26).date(),
                end_date=datetime(2024, 6, 7).date()
            )
            db.session.add(unit)
            db.session.commit()
            
            # Create a module and sessions
            module = Module(
                unit_id=unit.id,
                module_name='Tutorial A',
                module_type='Tutorial'
            )
            db.session.add(module)
            db.session.commit()
            
            # Create some sessions
            session1 = Session(
                module_id=module.id,
                session_type='general',
                start_time=datetime(2024, 3, 5, 9, 0),
                end_time=datetime(2024, 3, 5, 11, 0),
                day_of_week=1,  # Tuesday
                location='EZONE 1.24',
                max_facilitators=1
            )
            session2 = Session(
                module_id=module.id,
                session_type='general',
                start_time=datetime(2024, 3, 12, 9, 0),
                end_time=datetime(2024, 3, 12, 11, 0),
                day_of_week=1,
                location='EZONE 1.24',
                max_facilitators=1
            )
            db.session.add(session1)
            db.session.add(session2)
            db.session.commit()
            
            # Verify sessions exist
            sessions_before = Session.query.filter_by(module_id=module.id).count()
            self.assertEqual(sessions_before, 2)
            
            # Clear sessions via API
            response = self.client.delete(f'/unitcoordinator/units/{unit.id}/clear_csv_sessions')
            
            # Verify response
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data['ok'])
            self.assertEqual(data['deleted_sessions'], 2)
            
            # Verify sessions are deleted
            sessions_after = Session.query.filter_by(module_id=module.id).count()
            self.assertEqual(sessions_after, 0)

    def test_clear_csv_sessions_with_assignments(self):
        """Test clearing sessions that have facilitator assignments"""
        with app.app_context():
            # Create a unit
            unit = Unit(
                unit_code='TEST1002',
                unit_name='Test Unit 2',
                semester='S1',
                year=2024,
                start_date=datetime(2024, 2, 26).date(),
                end_date=datetime(2024, 6, 7).date()
            )
            db.session.add(unit)
            
            # Create a facilitator
            fac_user = User(
                email='fac@test.edu',
                password=hash_password('password123'),
                role=UserRole.FACILITATOR,
                first_name='Test',
                last_name='Facilitator'
            )
            db.session.add(fac_user)
            db.session.commit()
            
            facilitator = Facilitator(user_id=fac_user.id)
            db.session.add(facilitator)
            db.session.commit()
            
            # Create a module and session
            module = Module(
                unit_id=unit.id,
                module_name='Tutorial B',
                module_type='Tutorial'
            )
            db.session.add(module)
            db.session.commit()
            
            session = Session(
                module_id=module.id,
                session_type='general',
                start_time=datetime(2024, 3, 5, 9, 0),
                end_time=datetime(2024, 3, 5, 11, 0),
                day_of_week=1,
                location='EZONE 1.24',
                max_facilitators=1
            )
            db.session.add(session)
            db.session.commit()
            
            # Create an assignment
            assignment = Assignment(
                facilitator_id=facilitator.id,
                session_id=session.id,
                status='confirmed'
            )
            db.session.add(assignment)
            db.session.commit()
            
            # Verify assignment exists
            assignments_before = Assignment.query.filter_by(session_id=session.id).count()
            self.assertEqual(assignments_before, 1)
            
            # Clear sessions via API
            response = self.client.delete(f'/unitcoordinator/units/{unit.id}/clear_csv_sessions')
            
            # Verify response
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data['ok'])
            self.assertEqual(data['deleted_sessions'], 1)
            self.assertEqual(data['deleted_assignments'], 1)
            
            # Verify both session and assignment are deleted
            sessions_after = Session.query.filter_by(module_id=module.id).count()
            assignments_after = Assignment.query.count()
            self.assertEqual(sessions_after, 0)
            self.assertEqual(assignments_after, 0)

    def test_clear_csv_sessions_unauthorized(self):
        """Test that clearing sessions requires proper authorization"""
        with app.app_context():
            # Create a unit for a different UC
            other_uc = User(
                email='other_uc@test.edu',
                password=hash_password('password123'),
                role=UserRole.UNIT_COORDINATOR,
                first_name='Other',
                last_name='UC'
            )
            db.session.add(other_uc)
            db.session.commit()
            
            unit = Unit(
                unit_code='TEST1003',
                unit_name='Test Unit 3',
                semester='S1',
                year=2024,
                start_date=datetime(2024, 2, 26).date(),
                end_date=datetime(2024, 6, 7).date()
            )
            db.session.add(unit)
            db.session.commit()
            
            # Try to clear sessions for a unit we don't own
            # (assuming the route checks authorization)
            response = self.client.delete(f'/unitcoordinator/units/{unit.id}/clear_csv_sessions')
            
            # This should fail if authorization is properly implemented
            # The exact response depends on the implementation
            # It could be 404 (not found) or 403 (forbidden)
            self.assertIn(response.status_code, [403, 404])


if __name__ == '__main__':
    unittest.main()

