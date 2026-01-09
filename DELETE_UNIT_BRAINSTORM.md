# DELETE UNIT - Complete Brainstorm

## Current State
- Admin dashboard has "Delete Unit" button
- Currently shows: `alert('Delete unit functionality coming soon')`
- No implementation yet

---

## What Should Happen When Admin Deletes a Unit?

### 🔴 **CRITICAL CONSIDERATIONS**

#### **1. Published vs Draft Status**
- **DRAFT Unit**: Safer to delete (no facilitators assigned yet)
- **PUBLISHED Unit**: High risk! Facilitators have been assigned, may have set availability, schedule is live

**Recommendation:**
- ✅ Allow deleting DRAFT units easily
- ⚠️ Require extra confirmation for PUBLISHED units
- 🛑 Consider BLOCKING deletion of published units (force unpublish first)

---

### 📋 **DATABASE CASCADE - What Gets Deleted?**

When deleting a unit, we need to delete (in order):

#### **1. Auto-Generated Unavailability** ⭐ CRITICAL!
```python
# Delete all auto-generated unavailability from this unit's published schedules
Unavailability.query.filter(
    Unavailability.source_session_id.in_(
        # All session IDs from this unit
    )
).delete()
```
**Why:** These were created when UC published schedule. Must be removed!

#### **2. Assignments**
```python
# Delete all facilitator assignments to sessions in this unit
Assignment.query.filter(
    Assignment.session_id.in_(unit_session_ids)
).delete()
```

#### **3. Swap Requests**
```python
# Delete all swap requests for sessions in this unit
SwapRequest.query.filter(
    SwapRequest.session_id.in_(unit_session_ids)
).delete()
```
**Why:** Swap requests reference sessions that will be deleted

#### **4. Sessions**
```python
# Delete all sessions for all modules in this unit
Session.query.filter(
    Session.module_id.in_(module_ids)
).delete()
```

#### **5. Modules**
```python
# Delete all modules for this unit
Module.query.filter_by(unit_id=unit.id).delete()
```

#### **6. Facilitator Skills**
```python
# Delete all skill declarations for this unit's modules
FacilitatorSkill.query.filter(
    FacilitatorSkill.module_id.in_(module_ids)
).delete()
```

#### **7. Unit-Facilitator Links**
```python
# Delete all facilitator associations with this unit
UnitFacilitator.query.filter_by(unit_id=unit.id).delete()
```
**Important:** This does NOT delete the User accounts, just the link!

#### **8. Unit-Coordinator Links**
```python
# Delete all coordinator associations with this unit
UnitCoordinator.query.filter_by(unit_id=unit.id).delete()
```

#### **9. Unit-Venue Links**
```python
# Delete all venue associations with this unit
UnitVenue.query.filter_by(unit_id=unit.id).delete()
```

#### **10. The Unit Itself**
```python
# Finally, delete the unit
db.session.delete(unit)
```

---

### 🔔 **NOTIFICATIONS**

Who should be notified when a unit is deleted?

#### **Option 1: Email Everyone**
- ✅ All facilitators in the unit
- ✅ All coordinators in the unit
- ✅ Admin who deleted it (confirmation)

**Email Template:**
```
Subject: Unit Deleted - [UNIT_CODE] [UNIT_NAME]

Dear [NAME],

The unit [UNIT_CODE] - [UNIT_NAME] (Semester [X], [YEAR]) has been deleted by an administrator.

All associated data has been removed:
- Sessions and assignments
- Unavailability generated from published schedules
- Swap requests

If you believe this was done in error, please contact your administrator.

Best regards,
ScheduleME Team
```

#### **Option 2: In-App Notifications Only**
- Faster, less intrusive
- Users see notification next time they log in

#### **Option 3: No Notifications**
- ❌ Bad UX! Users will be confused

**Recommendation:** Option 1 (Email) for published units, Option 2 (In-app) for draft units

---

### ⚠️ **SAFETY CHECKS**

Before allowing deletion:

#### **1. Confirmation Dialog**
```javascript
if (!confirm(`⚠️ WARNING: You are about to DELETE unit ${unitCode}.

This will permanently remove:
- ${sessionCount} sessions
- ${assignmentCount} facilitator assignments
- ${swapCount} pending swap requests
- All auto-generated unavailability

This action CANNOT be undone!

Type "${unitCode}" to confirm:`)) {
    return;
}
```

#### **2. Published Unit Extra Warning**
```javascript
if (unit.schedule_status === 'PUBLISHED') {
    alert(`⛔ This unit has a PUBLISHED schedule!
    
    ${facilitatorCount} facilitators have been assigned.
    
    Consider UNPUBLISHING first instead of deleting.
    
    Are you ABSOLUTELY sure you want to delete?`);
}
```

#### **3. Admin Permission Check**
- Only ADMIN role can delete units
- Not even UNIT_COORDINATOR can delete their own units
- Prevents accidental deletion

---

### 🎯 **ALTERNATIVE: SOFT DELETE**

Instead of permanently deleting, consider:

#### **Soft Delete (Archive)**
```python
unit.is_archived = True
unit.archived_at = datetime.now()
unit.archived_by = admin_user_id
```

**Benefits:**
- ✅ Can be restored if mistake
- ✅ Keeps historical data
- ✅ Safer for auditing
- ✅ Can still view old schedules

**Drawbacks:**
- ❌ Database grows larger
- ❌ More complex queries (need to filter archived)

**Recommendation:** Implement soft delete for published units, hard delete for drafts

---

### 📊 **WHAT IF UNIT HAS...**

#### **Active Swap Requests?**
- ❌ Block deletion
- Show message: "Cannot delete unit with pending swap requests. Resolve or reject them first."
- OR: Auto-reject all swap requests with notification

#### **Upcoming Sessions (within 7 days)?**
- ⚠️ Extra warning
- "This unit has sessions scheduled within the next 7 days!"
- Force admin to type unit code to confirm

#### **Historical Data (past semester)?**
- ✅ Allow deletion
- OR: Suggest archiving instead

---

### 🔄 **ROLLBACK PLAN**

What if deletion fails halfway?

```python
try:
    # Delete in transaction
    db.session.begin_nested()
    
    # 1. Delete auto-unavailability
    # 2. Delete assignments
    # 3. Delete swap requests
    # ... etc
    
    db.session.commit()
    
except Exception as e:
    db.session.rollback()
    logger.error(f"Failed to delete unit {unit_id}: {str(e)}")
    return jsonify({"error": "Failed to delete unit. No changes made."}), 500
```

**Important:** Use database transaction to ensure all-or-nothing deletion!

---

### 📝 **LOGGING & AUDIT TRAIL**

What should be logged?

```python
logger.info(f"""
UNIT DELETED:
- Unit ID: {unit.id}
- Unit Code: {unit.unit_code}
- Unit Name: {unit.unit_name}
- Deleted By: {admin_user.email}
- Deleted At: {datetime.now()}
- Status: {unit.schedule_status}
- Sessions Deleted: {session_count}
- Facilitators Affected: {facilitator_count}
- Assignments Deleted: {assignment_count}
- Swap Requests Deleted: {swap_count}
- Auto-Unavailability Deleted: {auto_unavail_count}
""")
```

**Consider:** Save to separate audit log table for compliance

---

### 🎨 **UI/UX FLOW**

#### **Step 1: Click Delete**
- Show loading spinner
- Fetch unit details (session count, facilitator count, etc.)

#### **Step 2: Show Warning Dialog**
```
⚠️ Delete Unit: CITS3200 - Professional Computing

This will permanently delete:
✗ 24 sessions
✗ 8 facilitator assignments
✗ 2 pending swap requests
✗ Auto-generated unavailability for 5 facilitators

Status: PUBLISHED
Facilitators will be notified by email.

This action CANNOT be undone!

Type "CITS3200" to confirm: [_______]

[Cancel] [Delete Unit]
```

#### **Step 3: Deletion Progress**
```
Deleting unit...
✓ Removed auto-generated unavailability
✓ Deleted swap requests
✓ Deleted assignments
✓ Deleted sessions
✓ Deleted modules
✓ Removed facilitator links
✓ Sending notifications...
✓ Unit deleted successfully!
```

#### **Step 4: Confirmation**
```
✅ Unit CITS3200 has been deleted.

8 facilitators have been notified by email.

[Return to Dashboard]
```

---

### 🚀 **IMPLEMENTATION PRIORITY**

#### **Phase 1: Basic Hard Delete (Draft Only)**
- Only allow deleting DRAFT units
- Simple cascade delete
- No emails
- Admin confirmation only

#### **Phase 2: Published Unit Delete**
- Extra warnings
- Email notifications
- Detailed logging
- Type-to-confirm

#### **Phase 3: Soft Delete / Archive**
- Add `is_archived` flag
- Archive UI
- Restore functionality

---

### 💡 **RECOMMENDATION**

**For MVP:**
1. ✅ Allow deleting DRAFT units easily
2. ⚠️ BLOCK deleting PUBLISHED units (show message: "Unpublish first")
3. ✅ Cascade delete all related data
4. ✅ Send email to affected facilitators
5. ✅ Require admin confirmation
6. ✅ Log to audit trail

**For Future:**
- Soft delete / archive system
- Restore deleted units
- More granular permissions
- Bulk delete

---

### 🔧 **CODE STRUCTURE**

```python
@admin_bp.delete("/units/<int:unit_id>")
@login_required
@role_required([UserRole.ADMIN])
def delete_unit(unit_id: int):
    """
    Delete a unit and all associated data.
    Only ADMIN can delete units.
    """
    user = get_current_user()
    unit = Unit.query.get_or_404(unit_id)
    
    # 1. Check if published
    if unit.schedule_status == ScheduleStatus.PUBLISHED:
        return jsonify({
            "error": "Cannot delete published unit. Unpublish first."
        }), 403
    
    # 2. Get counts for logging
    session_ids = [s.id for s in unit.sessions]
    assignment_count = Assignment.query.filter(
        Assignment.session_id.in_(session_ids)
    ).count()
    
    # 3. Get affected facilitators for notifications
    facilitators = [uf.user for uf in unit.unit_facilitators]
    
    try:
        # 4. Delete in transaction
        db.session.begin_nested()
        
        # Delete auto-unavailability
        Unavailability.query.filter(
            Unavailability.source_session_id.in_(session_ids)
        ).delete(synchronize_session=False)
        
        # Delete assignments
        Assignment.query.filter(
            Assignment.session_id.in_(session_ids)
        ).delete(synchronize_session=False)
        
        # Delete swap requests
        SwapRequest.query.filter(
            SwapRequest.session_id.in_(session_ids)
        ).delete(synchronize_session=False)
        
        # Delete sessions
        Session.query.filter(
            Session.module_id.in_([m.id for m in unit.modules])
        ).delete(synchronize_session=False)
        
        # Delete modules
        Module.query.filter_by(unit_id=unit.id).delete()
        
        # Delete skills
        FacilitatorSkill.query.filter(
            FacilitatorSkill.module_id.in_([m.id for m in unit.modules])
        ).delete(synchronize_session=False)
        
        # Delete links
        UnitFacilitator.query.filter_by(unit_id=unit.id).delete()
        UnitCoordinator.query.filter_by(unit_id=unit.id).delete()
        UnitVenue.query.filter_by(unit_id=unit.id).delete()
        
        # Delete unit
        db.session.delete(unit)
        db.session.commit()
        
        # 5. Send notifications
        for facilitator in facilitators:
            send_unit_deleted_email(facilitator, unit)
        
        # 6. Log
        logger.info(f"Unit {unit.unit_code} deleted by {user.email}")
        
        return jsonify({
            "message": f"Unit {unit.unit_code} deleted successfully",
            "facilitators_notified": len(facilitators)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete unit {unit_id}: {str(e)}")
        return jsonify({"error": "Failed to delete unit"}), 500
```

---

## Summary

**Key Points:**
1. ⚠️ **High-risk operation** - affects many users and data
2. 🔒 **Admin-only** - strong permission check
3. 📧 **Notify everyone** - facilitators, coordinators
4. 🗑️ **Cascade delete** - 10+ related tables
5. ✅ **Transaction safety** - all-or-nothing
6. 📝 **Audit logging** - who, what, when
7. 🛡️ **Extra warnings** for published units
8. 💾 **Consider soft delete** for published units

**Recommendation:** Start with blocking published unit deletion, only allow draft deletion!
