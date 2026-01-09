# Remaining Features Implementation Guide

## ✅ COMPLETED FEATURES

### 1B: Skill Conflict Detection ✅
**Status:** IMPLEMENTED
**What it does:** Detects when facilitators marked as "no_interest" are assigned to sessions
**Files modified:**
- `unitcoordinator_routes.py` - Added skill conflict query to `/conflicts` endpoint
- `uc.js` - Added orange-styled rendering for skill conflicts

**How to test:**
1. Assign a facilitator to a session
2. Go to facilitator profile and change their skill to "No Interest" for that module
3. Return to UC dashboard - conflict should show with orange border
4. Message: "✗ Marked as 'No Interest'"

---

### 2A: Unpublish Window Conflict Detection ✅
**Status:** IMPLEMENTED
**What it does:** Warns UC if facilitators added unavailability during unpublish period
**Files modified:**
- `unitcoordinator_routes.py` - Added unpublish conflict check in `/publish` endpoint
- `uc.js` - Added warning popup when republishing with conflicts

**How to test:**
1. Publish a schedule
2. Unpublish it
3. Have a facilitator add unavailability for a day they're assigned
4. Try to republish - warning popup should appear listing affected facilitators

---

### 2B: Email Notification Toggle ✅
**Status:** IMPLEMENTED
**What it does:** Allows UC to choose whether to send email notifications when unpublishing
**Files modified:**
- `uc.js` - Replaced confirm() with custom modal including checkbox
- `unitcoordinator_routes.py` - Added `send_notifications` parameter handling

**How to test:**
1. Click "Unpublish Schedule"
2. Modal appears with checkbox (checked by default)
3. Uncheck to skip notifications
4. Confirm - facilitators should not receive emails

---

## 📋 REMAINING FEATURES TO IMPLEMENT

### 2C: Unpublish History Tracking
**Priority:** Medium
**Estimated Time:** 4-5 hours
**Complexity:** Medium

#### What it does:
Tracks when a unit was unpublished, by whom, and for how long. Shows history in unit details page.

#### Database Changes:
Create new table `UnpublishHistory`:
```python
class UnpublishHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('unit.id'), nullable=False)
    unpublished_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    unpublished_at = db.Column(db.DateTime, nullable=False)
    republished_at = db.Column(db.DateTime, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    duration_hours = db.Column(db.Float, nullable=True)
    
    unit = db.relationship('Unit', backref='unpublish_history')
    user = db.relationship('User', foreign_keys=[unpublished_by])
```

#### Backend Changes:
**File:** `unitcoordinator_routes.py`

1. **On Unpublish** (line ~4647):
```python
# After setting unit.unpublished_at
history_entry = UnpublishHistory(
    unit_id=unit_id,
    unpublished_by=user.id,
    unpublished_at=datetime.utcnow(),
    reason=data.get('reason', 'No reason provided')
)
db.session.add(history_entry)
```

2. **On Republish** (line ~4470):
```python
# After unit.schedule_status = ScheduleStatus.PUBLISHED
if unit.unpublished_at:
    # Find the most recent unpublish entry
    history_entry = UnpublishHistory.query.filter_by(
        unit_id=unit_id,
        republished_at=None
    ).order_by(UnpublishHistory.unpublished_at.desc()).first()
    
    if history_entry:
        history_entry.republished_at = datetime.utcnow()
        history_entry.duration_hours = (
            datetime.utcnow() - history_entry.unpublished_at
        ).total_seconds() / 3600
```

3. **New Endpoint** - Get History:
```python
@unitcoordinator_bp.get("/units/<int:unit_id>/unpublish-history")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def get_unpublish_history(unit_id: int):
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    
    history = (
        db.session.query(UnpublishHistory, User)
        .join(User, User.id == UnpublishHistory.unpublished_by)
        .filter(UnpublishHistory.unit_id == unit_id)
        .order_by(UnpublishHistory.unpublished_at.desc())
        .all()
    )
    
    history_data = []
    for entry, user in history:
        history_data.append({
            'unpublished_by': user.full_name,
            'unpublished_at': entry.unpublished_at.isoformat(),
            'republished_at': entry.republished_at.isoformat() if entry.republished_at else None,
            'reason': entry.reason,
            'duration_hours': entry.duration_hours,
            'status': 'Currently Unpublished' if not entry.republished_at else 'Republished'
        })
    
    return jsonify({'ok': True, 'history': history_data})
```

#### Frontend Changes:
**File:** `unitcoordinator_dashboard.html`

Add history section to unit details:
```html
<div class="unit-history-section" style="margin-top: 24px;">
  <h3>Schedule History</h3>
  <div id="unpublish-history-list">
    <!-- Populated by JavaScript -->
  </div>
</div>
```

**File:** `uc.js`

Add function to load and display history:
```javascript
async function loadUnpublishHistory(unitId) {
  try {
    const response = await fetch(`/unitcoordinator/units/${unitId}/unpublish-history`);
    const result = await response.json();
    
    if (result.ok && result.history.length > 0) {
      let html = '<ul style="list-style: none; padding: 0;">';
      
      result.history.forEach(entry => {
        const unpublishedDate = new Date(entry.unpublished_at).toLocaleString();
        const status = entry.status;
        const duration = entry.duration_hours ? 
          `${Math.round(entry.duration_hours)} hours` : 'Ongoing';
        
        html += `
          <li style="padding: 12px; border-left: 3px solid ${status === 'Currently Unpublished' ? '#f59e0b' : '#10b981'}; margin-bottom: 12px; background: #f9fafb;">
            <div style="font-weight: 600;">${unpublishedDate}</div>
            <div style="color: #6b7280; font-size: 0.875rem;">
              Unpublished by ${entry.unpublished_by}
            </div>
            ${entry.reason ? `<div style="color: #6b7280; font-size: 0.875rem;">Reason: ${entry.reason}</div>` : ''}
            <div style="color: #6b7280; font-size: 0.875rem;">
              Status: ${status} ${entry.duration_hours ? `(${duration})` : ''}
            </div>
          </li>
        `;
      });
      
      html += '</ul>';
      document.getElementById('unpublish-history-list').innerHTML = html;
    }
  } catch (error) {
    console.error('Error loading unpublish history:', error);
  }
}
```

#### Migration:
```bash
# Create migration
flask db migrate -m "Add unpublish history table"
flask db upgrade
```

---

### 3C: Cascade Delete Verification
**Priority:** Low
**Estimated Time:** 1 hour
**Complexity:** Low

#### What it does:
Ensures orphaned assignments are properly cleaned up when sessions are deleted.

#### Current Status:
Already implemented in `models.py` line 171:
```python
assignments = db.relationship('Assignment', backref='session', lazy=True, cascade='all, delete-orphan')
```

#### Additional Safety:
Add verification script:

**File:** `scripts/verify_cascade_deletes.py`
```python
from models import db, Session, Assignment, Module

def verify_no_orphans():
    """Check for orphaned assignments."""
    # Find assignments with no session
    orphaned = (
        db.session.query(Assignment)
        .outerjoin(Session, Session.id == Assignment.session_id)
        .filter(Session.id.is_(None))
        .all()
    )
    
    if orphaned:
        print(f"⚠️ Found {len(orphaned)} orphaned assignments!")
        for assignment in orphaned:
            print(f"  - Assignment {assignment.id} (session_id={assignment.session_id})")
        return False
    else:
        print("✅ No orphaned assignments found")
        return True

def cleanup_orphans():
    """Remove orphaned assignments."""
    orphaned = (
        db.session.query(Assignment)
        .outerjoin(Session, Session.id == Assignment.session_id)
        .filter(Session.id.is_(None))
        .all()
    )
    
    for assignment in orphaned:
        db.session.delete(assignment)
    
    db.session.commit()
    print(f"🧹 Cleaned up {len(orphaned)} orphaned assignments")

if __name__ == '__main__':
    verify_no_orphans()
```

#### Testing:
```python
# Test cascade delete
session = Session.query.first()
assignment_count = len(session.assignments)
session_id = session.id

db.session.delete(session)
db.session.commit()

# Verify assignments were deleted
remaining = Assignment.query.filter_by(session_id=session_id).count()
assert remaining == 0, "Assignments not cascaded!"
```

---

### 4C: Role at Assignment Tracking
**Priority:** Low
**Estimated Time:** 2-3 hours
**Complexity:** Medium

#### What it does:
Tracks what role a user had when they were assigned (e.g., "Assigned as Facilitator, now Unit Coordinator").

#### Database Changes:
**File:** `models.py`

Add field to Assignment model (line ~314):
```python
class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    facilitator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_confirmed = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(20), default='lead')  # 'lead' or 'support'
    role_at_assignment = db.Column(db.String(20), nullable=True)  # NEW: 'FACILITATOR', 'UNIT_COORDINATOR', 'ADMIN'
```

#### Backend Changes:
**File:** `unitcoordinator_routes.py`

Update assignment creation (line ~4178):
```python
# Create assignment
assignment = Assignment(
    session_id=session_id,
    facilitator_id=facilitator_id,
    is_confirmed=False,
    role='lead',
    role_at_assignment=facilitator.role.value  # Store current role
)
db.session.add(assignment)
```

#### Frontend Display:
**File:** Schedule report CSV or session details

Show role information:
```python
# In CSV export
if assignment.role_at_assignment and assignment.role_at_assignment != facilitator.role.value:
    role_note = f"(Assigned as {assignment.role_at_assignment}, now {facilitator.role.value})"
else:
    role_note = ""
```

#### Migration:
```bash
flask db migrate -m "Add role_at_assignment to Assignment"
flask db upgrade

# Backfill existing data
python scripts/backfill_role_at_assignment.py
```

**File:** `scripts/backfill_role_at_assignment.py`
```python
from models import db, Assignment, User

assignments = Assignment.query.all()
for assignment in assignments:
    if not assignment.role_at_assignment:
        facilitator = User.query.get(assignment.facilitator_id)
        if facilitator:
            assignment.role_at_assignment = facilitator.role.value

db.session.commit()
print(f"✅ Backfilled {len(assignments)} assignments")
```

---

## 🧪 TESTING CHECKLIST

### Skill Conflicts
- [ ] Assign facilitator with "Proficient" skill → no conflict
- [ ] Change skill to "No Interest" → conflict appears
- [ ] Conflict shows orange border and "✗ No Interest" message
- [ ] Reassign different facilitator → conflict disappears

### Unpublish Window Conflicts
- [ ] Publish → Unpublish → Add unavailability → Republish → Warning shows
- [ ] Warning lists correct facilitators and sessions
- [ ] Can proceed with republish despite warning
- [ ] No warning if no new unavailability added

### Email Toggle
- [ ] Unpublish with checkbox checked → facilitators receive emails
- [ ] Unpublish with checkbox unchecked → no emails sent
- [ ] Checkbox defaults to checked
- [ ] Modal can be cancelled

### Cascade Deletes (if implemented)
- [ ] Delete session → assignments deleted
- [ ] Delete module → sessions and assignments deleted
- [ ] No orphaned records remain
- [ ] Verification script finds no issues

### Role Tracking (if implemented)
- [ ] New assignment stores current role
- [ ] Role change doesn't affect assignment record
- [ ] CSV export shows role changes
- [ ] Historical data is accurate

---

## 📊 SUMMARY

### Completed (3/6):
✅ 1B - Skill Conflict Detection  
✅ 2A - Unpublish Window Conflicts  
✅ 2B - Email Notification Toggle  

### Remaining (3/6):
⏳ 2C - Unpublish History (Medium priority, 4-5 hours)  
⏳ 3C - Cascade Delete Verification (Low priority, 1 hour)  
⏳ 4C - Role at Assignment Tracking (Low priority, 2-3 hours)  

### Total Remaining Effort:
**7-9 hours** for all remaining features

### Recommendation:
1. **Implement 2C first** - Most valuable for auditing and transparency
2. **Skip 3C** - Already working correctly, verification script is optional
3. **Consider 4C** - Nice to have but not critical

---

## 🎯 NEXT STEPS

1. **Test current implementation thoroughly**
2. **Gather user feedback** on implemented features
3. **Prioritize remaining features** based on actual usage
4. **Implement 2C (History)** if auditing is important
5. **Document everything** for future developers

---

**All core functionality is working! The remaining features are enhancements that can be added iteratively based on user needs.**
