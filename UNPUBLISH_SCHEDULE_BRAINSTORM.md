# UNPUBLISH SCHEDULE - Complete Brainstorm

## Current State
- ✅ **Publish Schedule** button exists (sends emails, creates auto-unavailability)
- ✅ **Republish Schedule** button exists (for updates after initial publish)
- ❌ **NO Unpublish button** in UI
- ✅ Backend function `remove_unavailability_from_schedule()` exists but unused
- ✅ Database has `schedule_status` enum: DRAFT, PUBLISHED, UNPUBLISHED
- ✅ Database has `unpublished_at` and `unpublished_by` fields

---

## What Should UNPUBLISH Do?

### 🎯 **Core Purpose**
**Revert a published schedule back to draft state, removing all published artifacts while preserving the schedule structure.**

Think of it as: "Oops, I published too early / published the wrong schedule / need to make major changes"

---

## 📋 **What Should Happen When UC Clicks UNPUBLISH?**

### **1. Remove Auto-Generated Unavailability** ⭐ CRITICAL!
```python
# Delete all auto-generated unavailability from this unit's sessions
# This is what prevents facilitators from being double-booked
session_ids = [s.id for s in unit.sessions]
Unavailability.query.filter(
    Unavailability.source_session_id.in_(session_ids)
).delete()
```

**Why:** These orange unavailability entries were created when schedule was published. They block facilitators from being available in other units. Must be removed!

**Impact:** Facilitators become available again in other units for those time slots.

---

### **2. Update Unit Status**
```python
unit.schedule_status = ScheduleStatus.UNPUBLISHED  # or back to DRAFT?
unit.unpublished_at = datetime.utcnow()
unit.unpublished_by = current_user.id
```

**Question:** Should status be `UNPUBLISHED` or `DRAFT`?

**Option A: Set to UNPUBLISHED**
- ✅ Tracks that it was published before
- ✅ Can show "Previously published" badge
- ✅ Better audit trail
- ❌ Need to handle 3 states everywhere

**Option B: Set back to DRAFT**
- ✅ Simpler - only 2 states (draft/published)
- ✅ Behaves like it was never published
- ✅ Can republish normally
- ❌ Loses history that it was published

**Recommendation:** Use `DRAFT` for simplicity. Keep `unpublished_at` for audit trail.

---

### **3. Keep or Remove Assignments?**

**Option A: KEEP Assignments** ✅ RECOMMENDED
```python
# Don't touch assignments
# Facilitators remain assigned to sessions
```

**Why:**
- ✅ UC probably wants to keep the schedule structure
- ✅ Can make small edits and republish
- ✅ Facilitators don't lose their assignments
- ✅ Less destructive

**Option B: REMOVE Assignments** ❌ Too Destructive
```python
# Delete all assignments
Assignment.query.filter(
    Assignment.session_id.in_(session_ids)
).delete()
```

**Why NOT:**
- ❌ Loses all the work UC did assigning facilitators
- ❌ Would need to reassign everyone
- ❌ Too destructive for "unpublish"

**Recommendation:** KEEP assignments! Only remove auto-unavailability.

---

### **4. Handle Pending Swap Requests**

**Question:** What if facilitators have pending swap requests?

**Option A: Auto-Reject All Swaps** ✅ RECOMMENDED
```python
# Reject all pending swap requests for this unit
swap_requests = SwapRequest.query.filter(
    SwapRequest.session_id.in_(session_ids),
    SwapRequest.status.in_([SwapStatus.PENDING, SwapStatus.FACILITATOR_PENDING, SwapStatus.COORDINATOR_PENDING])
).all()

for swap in swap_requests:
    swap.status = SwapStatus.REJECTED
    swap.rejection_reason = "Schedule unpublished by coordinator"
    # Send notification to facilitators
```

**Why:**
- ✅ Swaps don't make sense if schedule is unpublished
- ✅ Clear communication
- ✅ Prevents confusion

**Option B: Keep Swaps Pending**
- ❌ Confusing - schedule is unpublished but swaps are pending?
- ❌ What if schedule changes before republish?

**Recommendation:** Auto-reject all pending swaps with notification.

---

### **5. Notifications** 📧

**Who should be notified?**

#### **Option A: Email ALL Facilitators** ⚠️ Might be too much
```
Subject: Schedule Unpublished - [UNIT_CODE] [UNIT_NAME]

Dear [NAME],

The schedule for [UNIT_CODE] - [UNIT_NAME] has been unpublished by the unit coordinator.

What this means:
- Your assignments are still saved
- You are now available for other units during these times
- You will be notified when the schedule is republished

If you have questions, contact your unit coordinator.

Best regards,
ScheduleME Team
```

**Pros:**
- ✅ Transparent
- ✅ Facilitators know what's happening
- ✅ Explains they're available again

**Cons:**
- ❌ Might cause confusion
- ❌ Extra emails
- ❌ Might not be necessary if republishing soon

#### **Option B: Email Only Coordinators** ✅ RECOMMENDED
```
Subject: Schedule Unpublished - [UNIT_CODE]

You have unpublished the schedule for [UNIT_CODE].

Changes made:
- Status changed to DRAFT
- Auto-generated unavailability removed (${count} entries)
- Pending swap requests rejected (${swap_count})
- Facilitator assignments preserved

You can now make changes and republish when ready.
```

**Pros:**
- ✅ Less noise for facilitators
- ✅ Coordinator gets confirmation
- ✅ Simpler

**Cons:**
- ❌ Facilitators don't know schedule was unpublished

#### **Option C: In-App Notification Only**
- Show notification to facilitators next time they log in
- "The schedule for [UNIT] has been unpublished"
- Less intrusive than email

**Recommendation:** Option B (coordinator email) + Option C (facilitator in-app notification)

---

### **6. UI/UX Flow**

#### **Where Should the Button Be?**

**Location 1: Unit Dashboard** (next to Publish/Republish)
```
[Unit: CITS3200]
Status: PUBLISHED ✓

[View Schedule] [Edit Schedule] [Unpublish Schedule]
```

**Location 2: Schedule View** (top bar)
```
CITS3200 Schedule - Published

[Back] [Export CSV] [Republish] [Unpublish]
```

**Recommendation:** Both locations!

---

#### **Confirmation Dialog**
```javascript
⚠️ Unpublish Schedule?

This will:
✓ Remove auto-generated unavailability (facilitators become available again)
✓ Reject all pending swap requests
✓ Change status back to DRAFT
✓ Keep all facilitator assignments

You can make changes and republish when ready.

Are you sure?

[Cancel] [Unpublish Schedule]
```

**Important:** Clear explanation of what happens!

---

#### **Success Message**
```
✅ Schedule unpublished successfully

Changes made:
- Removed 47 auto-generated unavailability entries
- Rejected 2 pending swap requests
- Status changed to DRAFT

You can now edit the schedule and republish when ready.

[Edit Schedule] [Close]
```

---

### **7. When Should Unpublish Be Allowed?**

#### **Scenario A: Unit is Active (sessions happening now)**
**Should unpublish be allowed?** ⚠️ RISKY

**Option 1: Block unpublish**
```
❌ Cannot unpublish schedule

This unit has sessions scheduled within the next 7 days.
Unpublishing would disrupt active schedules.

If you need to make changes, use Republish instead.
```

**Option 2: Allow with extra warning**
```
⚠️ WARNING: Active Sessions!

This unit has 5 sessions scheduled within the next 7 days.

Unpublishing will:
- Remove facilitator unavailability
- May cause double-booking issues
- Disrupt active schedules

Are you ABSOLUTELY sure?

Type "UNPUBLISH" to confirm: [_______]
```

**Recommendation:** Option 1 (block) for sessions within 7 days. Too risky!

---

#### **Scenario B: Unit is in the Past (semester ended)**
**Should unpublish be allowed?** ❌ NO

```
❌ Cannot unpublish schedule

This unit ended on [END_DATE].
Historical schedules cannot be unpublished.
```

**Why:** Historical data should be preserved!

---

#### **Scenario C: Unit is in the Future (hasn't started yet)**
**Should unpublish be allowed?** ✅ YES

This is the main use case - UC published too early or needs to make changes.

---

### **8. Difference: Unpublish vs Republish**

| Action | Purpose | What It Does |
|--------|---------|--------------|
| **Publish** | First time publishing | Creates auto-unavailability, sends emails, marks as PUBLISHED |
| **Republish** | Update published schedule | Sends update emails only to changed facilitators, updates auto-unavailability |
| **Unpublish** | Revert to draft | Removes auto-unavailability, rejects swaps, back to DRAFT |

**Key Difference:**
- **Republish** = "I want to update the published schedule"
- **Unpublish** = "I want to take it back to draft and make major changes"

---

### **9. Edge Cases**

#### **What if facilitator manually added unavailability on those dates?**
**Answer:** Leave it! Only remove AUTO-GENERATED unavailability (where `source_session_id` is not null)

```python
# Only delete auto-generated
Unavailability.query.filter(
    Unavailability.source_session_id.in_(session_ids),
    Unavailability.source_session_id.isnot(None)  # Auto-generated only!
).delete()
```

Manual red unavailability stays untouched! ✅

---

#### **What if UC unpublishes, makes changes, then republishes?**
**Answer:** Works perfectly!
1. Unpublish → removes auto-unavailability, back to DRAFT
2. Edit schedule → change assignments, times, etc.
3. Republish → creates NEW auto-unavailability, sends update emails

---

#### **What if facilitator was assigned to multiple sessions?**
**Answer:** All their auto-unavailability for this unit is removed
- They become available again for ALL sessions in this unit
- Other units are unaffected

---

### **10. Implementation Checklist**

#### **Backend (Python)**
```python
@unitcoordinator_bp.post("/units/<int:unit_id>/unpublish")
@login_required
@role_required([UserRole.UNIT_COORDINATOR, UserRole.ADMIN])
def unpublish_schedule(unit_id: int):
    """Unpublish a schedule and revert to draft state."""
    
    user = get_current_user()
    unit = _get_user_unit_or_404(user, unit_id)
    
    # 1. Check if unit is published
    if unit.schedule_status != ScheduleStatus.PUBLISHED:
        return jsonify({"error": "Unit is not published"}), 400
    
    # 2. Check if unit has active sessions (within 7 days)
    from datetime import date, timedelta
    today = date.today()
    near_future = today + timedelta(days=7)
    
    active_sessions = Session.query.join(Module).filter(
        Module.unit_id == unit.id,
        Session.date >= today,
        Session.date <= near_future
    ).count()
    
    if active_sessions > 0:
        return jsonify({
            "error": f"Cannot unpublish. {active_sessions} sessions scheduled within next 7 days."
        }), 403
    
    # 3. Check if unit is in the past
    if unit.end_date and unit.end_date < today:
        return jsonify({
            "error": "Cannot unpublish historical schedules."
        }), 403
    
    try:
        # 4. Remove auto-generated unavailability
        deleted_unavail = remove_unavailability_from_schedule(unit_id)
        
        # 5. Reject pending swap requests
        session_ids = [s.id for s in unit.sessions]
        swap_requests = SwapRequest.query.filter(
            SwapRequest.session_id.in_(session_ids),
            SwapRequest.status.in_([
                SwapStatus.PENDING,
                SwapStatus.FACILITATOR_PENDING,
                SwapStatus.COORDINATOR_PENDING
            ])
        ).all()
        
        rejected_swaps = 0
        for swap in swap_requests:
            swap.status = SwapStatus.REJECTED
            swap.rejection_reason = "Schedule unpublished by coordinator"
            rejected_swaps += 1
            # TODO: Send notification to facilitators
        
        # 6. Update unit status
        unit.schedule_status = ScheduleStatus.DRAFT
        unit.unpublished_at = datetime.utcnow()
        unit.unpublished_by = user.id
        
        db.session.commit()
        
        # 7. Send confirmation email to coordinator
        # TODO: send_schedule_unpublished_email(user, unit)
        
        # 8. Create in-app notifications for facilitators
        # TODO: notify_facilitators_schedule_unpublished(unit)
        
        logger.info(f"Unit {unit.unit_code} unpublished by {user.email}")
        
        return jsonify({
            "message": "Schedule unpublished successfully",
            "deleted_unavailability": deleted_unavail,
            "rejected_swaps": rejected_swaps
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to unpublish unit {unit_id}: {str(e)}")
        return jsonify({"error": "Failed to unpublish schedule"}), 500
```

---

#### **Frontend (JavaScript)**
```javascript
async function unpublishSchedule(unitId) {
    // 1. Show confirmation dialog
    const confirmed = confirm(`⚠️ Unpublish Schedule?

This will:
✓ Remove auto-generated unavailability (facilitators become available again)
✓ Reject all pending swap requests
✓ Change status back to DRAFT
✓ Keep all facilitator assignments

You can make changes and republish when ready.

Are you sure?`);
    
    if (!confirmed) return;
    
    try {
        // 2. Call backend
        const response = await fetch(`/unitcoordinator/units/${unitId}/unpublish`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            }
        });
        
        const result = await response.json();
        
        if (response.ok) {
            // 3. Show success message
            alert(`✅ Schedule unpublished successfully

Changes made:
- Removed ${result.deleted_unavailability} auto-generated unavailability entries
- Rejected ${result.rejected_swaps} pending swap requests
- Status changed to DRAFT

You can now edit the schedule and republish when ready.`);
            
            // 4. Reload page to show updated status
            location.reload();
        } else {
            alert(`❌ Failed to unpublish: ${result.error}`);
        }
    } catch (error) {
        console.error('Unpublish error:', error);
        alert('❌ Failed to unpublish schedule. Please try again.');
    }
}
```

---

#### **HTML Button**
```html
<!-- Show only when schedule is PUBLISHED -->
{% if unit.schedule_status == ScheduleStatus.PUBLISHED %}
<button class="btn btn-warning" onclick="unpublishSchedule({{ unit.id }})">
    <span class="material-icons">unpublished</span>
    Unpublish Schedule
</button>
{% endif %}
```

---

### **11. Testing Scenarios**

#### **Test 1: Basic Unpublish**
1. Publish a schedule
2. Verify auto-unavailability created
3. Click Unpublish
4. Verify auto-unavailability removed
5. Verify status = DRAFT
6. Verify assignments still exist

#### **Test 2: Unpublish with Pending Swaps**
1. Publish schedule
2. Facilitator requests swap
3. Click Unpublish
4. Verify swap status = REJECTED
5. Verify facilitator gets notification

#### **Test 3: Block Unpublish for Active Sessions**
1. Publish schedule with session tomorrow
2. Try to unpublish
3. Verify error: "Cannot unpublish. X sessions scheduled within next 7 days."

#### **Test 4: Block Unpublish for Past Units**
1. Create unit with end_date in the past
2. Publish schedule
3. Try to unpublish
4. Verify error: "Cannot unpublish historical schedules."

#### **Test 5: Unpublish → Edit → Republish**
1. Publish schedule
2. Unpublish
3. Change assignments
4. Republish
5. Verify new auto-unavailability created
6. Verify update emails sent

---

### **12. Summary**

**What Unpublish Should Do:**
1. ✅ Remove auto-generated unavailability (facilitators available again)
2. ✅ Reject pending swap requests
3. ✅ Change status back to DRAFT
4. ✅ Keep facilitator assignments (not destructive)
5. ✅ Log who unpublished and when
6. ✅ Send confirmation to coordinator
7. ✅ In-app notification to facilitators

**Safety Checks:**
1. ⚠️ Block if sessions within 7 days
2. ⚠️ Block if unit is in the past
3. ⚠️ Require confirmation dialog
4. ⚠️ Only ADMIN or UC can unpublish

**Key Benefits:**
- ✅ Allows UC to fix mistakes
- ✅ Non-destructive (keeps assignments)
- ✅ Clean revert to draft state
- ✅ Can republish after making changes

**Recommendation:** Implement this! It's a useful feature and relatively simple since backend logic already exists.
