# Session Swap Workflow - Current Implementation

## Overview
The session swap system allows facilitators to request swaps when they cannot attend scheduled sessions. The workflow is **auto-approved** (no UC approval needed) and immediately transfers the assignment.

---

## User Roles

### **Facilitators**
- Request swaps for their assigned sessions
- View incoming swap requests
- View their swap history

### **Unit Coordinators**
- View all swap requests for their unit
- Monitor swap activity (read-only)
- No approval required (auto-approved system)

---

## Current Workflow

### **Step 1: Facilitator Requests Swap**

**Location:** Facilitator Dashboard → "Session Swaps" tab

**Process:**
1. Facilitator clicks "Request Swap" button
2. Modal opens with:
   - Dropdown to select their assigned session
   - Dropdown to select target facilitator
   - Checkbox: "I have discussed this swap with the suggested facilitator" (required)
3. Facilitator submits request

**Frontend:** `facilitator_dashboard.html` (lines 784-1008)
**Backend:** `POST /facilitator/swap-requests` (lines 1742-1860)

---

### **Step 2: Validation**

**Backend checks:**
1. ✅ Requester owns the assignment
2. ✅ Target facilitator exists
3. ✅ Target facilitator is assigned to the same unit
4. ✅ Target facilitator has required skills for the module
5. ✅ Target facilitator is available at the session time
6. ✅ No duplicate swap request exists

**If validation fails:** Returns error message

---

### **Step 3: Auto-Approval & Execution**

**If validation passes:**
1. Creates `SwapRequest` with:
   - `status = APPROVED` (immediately)
   - `facilitator_confirmed = True`
   - `reason = "Session swap request (auto-approved)"`

2. **Transfers assignment:**
   ```python
   requester_assignment.facilitator_id = target_facilitator_id
   db.session.commit()
   ```

3. Returns success message

**Result:** Session is immediately transferred to target facilitator!

---

### **Step 4: View Swap History**

**Facilitators can view:**
- **My Requests:** Swaps they initiated
- **Incoming Requests:** Swaps where they're the target

**Unit Coordinators can view:**
- All swap requests for their unit
- Read-only monitoring

**Frontend:** `facilitator_dashboard.html` (lines 812-846)
**Backend:** `GET /facilitator/swap-requests` (lines 1863-1889)

---

## Database Model

### **SwapRequest Table**

```python
class SwapRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'))  # Who wants to swap
    target_id = db.Column(db.Integer, db.ForeignKey('user.id'))     # Who will take over
    requester_assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'))
    target_assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'))
    reason = db.Column(db.String(500))
    status = db.Column(db.Enum(SwapStatus))  # APPROVED (auto)
    facilitator_confirmed = db.Column(db.Boolean, default=False)
    facilitator_confirmed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

### **SwapStatus Enum**
```python
class SwapStatus(enum.Enum):
    FACILITATOR_PENDING = 'facilitator_pending'  # Not used (auto-approved)
    APPROVED = 'approved'                        # Used immediately
    DECLINED = 'declined'                        # Not used
    UC_PENDING = 'uc_pending'                    # Not used
```

---

## API Endpoints

### **POST /facilitator/swap-requests**
**Purpose:** Create and auto-approve swap request

**Request Body:**
```json
{
  "requester_assignment_id": 123,
  "target_assignment_id": 123,
  "target_facilitator_id": 456,
  "has_discussed": true,
  "unit_id": 789
}
```

**Response (Success):**
```json
{
  "success": true,
  "message": "Swap request approved and session transferred successfully!",
  "swap_request_id": 999
}
```

**Response (Error):**
```json
{
  "error": "Target facilitator is not available: Has unavailability on this date"
}
```

---

### **GET /facilitator/swap-requests?unit_id=X**
**Purpose:** Get swap requests for a facilitator

**Response:**
```json
{
  "my_requests": [
    {
      "id": 1,
      "requester_assignment": {...},
      "target_assignment": {...},
      "status": "approved",
      "created_at": "2026-01-14T14:00:00"
    }
  ],
  "requests_for_me": [...]
}
```

---

## UI Components

### **Facilitator Dashboard - Session Swaps Tab**

**Location:** `facilitator_dashboard.html` (lines 784-1008)

**Components:**
1. **Header:** "Session Swaps" with subtitle
2. **Unit Info Card:** Shows current unit and session count
3. **Request Swap Button:** Opens modal
4. **Incoming Requests Section:** Shows swaps where user is target
5. **My Requests Section:** Shows swaps user initiated
6. **How Swaps Work:** Educational section

**Modal:**
- Session dropdown (populated with user's assignments)
- Target facilitator dropdown (populated with unit facilitators)
- Discussion checkbox (required)
- Submit/Cancel buttons

---

### **Unit Coordinator Dashboard - Swap & Approvals Tab**

**Location:** `unitcoordinator_dashboard.html` (lines 1363-1453)

**Components:**
1. **Header:** "Session Swap Management"
2. **Swap requests list:** Read-only view of all swaps
3. **Badge:** Shows pending count (though all are auto-approved)

---

## Key Features

### ✅ **Auto-Approval**
- No UC approval needed
- Instant transfer of assignment
- Reduces administrative overhead

### ✅ **Validation**
- Skills check
- Availability check
- Unit membership check
- Duplicate prevention

### ✅ **Discussion Requirement**
- Checkbox forces facilitators to discuss first
- Reduces conflicts

### ✅ **Unit Filtering**
- Swaps filtered by unit
- Multi-unit support

---

## Current Issues / Limitations

### 🔴 **No Approval Workflow**
- All swaps are auto-approved
- No way to require UC approval
- Status enum has unused states (UC_PENDING, DECLINED)

### 🔴 **No Notifications**
- Target facilitator not notified
- UC not notified
- No email alerts

### 🔴 **No Undo/Revert**
- Once swapped, cannot be undone
- No rollback mechanism

### 🔴 **Limited History**
- No detailed audit trail
- No reason tracking (always "auto-approved")

### 🔴 **Same Assignment ID**
- Uses `target_assignment_id = requester_assignment_id`
- Simplified approach, not true swap

### 🔴 **No Bulk Operations**
- Can only swap one session at a time
- No multi-session swaps

---

## Potential Improvements

### **1. Add Approval Workflow**
- Make UC approval optional (configurable)
- Use `UC_PENDING` status
- Add approve/decline endpoints

### **2. Add Notifications**
- Email target facilitator
- Email UC for monitoring
- In-app notifications

### **3. Add Undo/Revert**
- Allow UC to revert swaps
- Add `REVERTED` status
- Track original assignment

### **4. Improve History**
- Add reason field (user input)
- Add audit trail
- Track all state changes

### **5. Add Bulk Operations**
- Swap multiple sessions at once
- Recurring swap requests

### **6. Add Swap Offers**
- Facilitators can offer to take sessions
- Reverse workflow (target initiates)

---

## Files to Review

### **Backend:**
- `facilitator_routes.py` (lines 1740-2100)
- `models.py` (SwapRequest model, lines 319-346)

### **Frontend:**
- `facilitator_dashboard.html` (lines 784-1008)
- `unitcoordinator_dashboard.html` (lines 1363-1453)
- `static/js/facilitator.js` (swap handling)

### **Database:**
- `swap_request` table
- `assignment` table (modified by swaps)

---

## Summary

**Current State:**
- ✅ Basic swap functionality works
- ✅ Auto-approval system
- ✅ Validation checks
- ✅ Unit filtering

**Missing:**
- ❌ Approval workflow
- ❌ Notifications
- ❌ Undo/revert
- ❌ Detailed history
- ❌ Bulk operations

**Next Steps:**
- Decide if UC approval is needed
- Add notifications
- Improve history tracking
- Add undo functionality
