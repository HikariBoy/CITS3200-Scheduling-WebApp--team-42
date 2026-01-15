# Session Swap System - Missing Features & Improvements

## ✅ COMPLETED

### 1. Auto-Unavailability Handling
- **Status:** FIXED
- **Issue:** Swaps didn't update global unavailability
- **Solution:** Added logic to remove old facilitator's unavailability and create new one for target
- **Commit:** acc4a9c

### 2. UI Accuracy
- **Status:** FIXED  
- **Issue:** UI described two-step approval but system does instant transfer
- **Solution:** Updated all text to reflect instant transfer workflow
- **Commit:** baca00c

### 3. False Conflict Detection
- **Status:** FIXED
- **Issue:** Facilitators shown as "conflicting" when assigned to the session being swapped
- **Solution:** Added `exclude_session_id` parameter to availability check
- **Commit:** cf1317d, 68231df

---

## ❌ MISSING / TO DO

### 4. Email Notifications
- **Status:** NOT IMPLEMENTED
- **Issue:** No one gets notified when a swap happens
- **Impact:** 
  - Target facilitator doesn't know they got a new session
  - Unit coordinator doesn't know about the swap
  - Old facilitator has no confirmation
- **Solution Needed:**
  - Send email to target facilitator: "You've been assigned to [session]"
  - Send email to requester: "Swap confirmed for [session]"
  - Optional: Notify UC of the swap

### 5. Swap History / Audit Trail
- **Status:** PARTIAL
- **Issue:** SwapRequest records exist but no easy way to view swap history
- **Impact:** Hard to track who swapped what and when
- **Solution Needed:**
  - Add "Swap History" view for UCs
  - Show original facilitator in swap records
  - Add filters by date, facilitator, session

### 6. Undo/Reverse Swap
- **Status:** NOT IMPLEMENTED
- **Issue:** No way to undo an accidental swap
- **Impact:** If someone clicks wrong button, permanent
- **Solution Needed:**
  - Add "Reverse Swap" button for recent swaps (within 24h?)
  - Or allow UC to manually reassign
  - Or add confirmation dialog before transfer

### 7. Swap Validation Edge Cases
- **Status:** PARTIAL
- **Current checks:**
  - ✅ Target has required skills
  - ✅ Target is available (no conflicts)
  - ✅ Target is in the unit
  - ✅ User confirmed discussion
- **Missing checks:**
  - ❌ Session hasn't already been swapped recently
  - ❌ Target facilitator hasn't exceeded max hours
  - ❌ Session isn't in the past
  - ❌ Session is actually assigned to requester

### 8. Swap Limits / Abuse Prevention
- **Status:** NOT IMPLEMENTED
- **Issue:** No limits on how many swaps a facilitator can do
- **Impact:** Could abuse system, swap all sessions away
- **Solution Needed:**
  - Max swaps per week/month?
  - Require UC approval after X swaps?
  - Flag excessive swapping

### 9. Bulk Swap Support
- **Status:** NOT IMPLEMENTED
- **Issue:** Can only swap one session at a time
- **Impact:** If someone needs to swap multiple sessions, tedious
- **Solution Needed:**
  - "Swap All My Sessions" feature
  - Select multiple sessions to swap to same person
  - Batch validation

### 10. Swap Suggestions
- **Status:** NOT IMPLEMENTED
- **Issue:** User has to manually find available facilitators
- **Impact:** Might not know who's available
- **Solution Needed:**
  - Auto-suggest facilitators who are:
    - Available at that time
    - Have required skills
    - Haven't been swapped with recently
  - Show their current workload

### 11. In-App Notifications
- **Status:** NOT IMPLEMENTED
- **Issue:** Only email notifications (which don't exist yet)
- **Impact:** Facilitators might miss important swap info
- **Solution Needed:**
  - Create Notification record when swap happens
  - Show notification badge
  - Link to session details

### 12. Calendar Integration
- **Status:** NOT IMPLEMENTED
- **Issue:** Swapped sessions don't immediately update in calendar view
- **Impact:** User sees stale data until page refresh
- **Solution Needed:**
  - Reload calendar after successful swap
  - Or use WebSocket for real-time updates
  - Or at minimum show success message with "Refresh to see changes"

### 13. Swap Analytics
- **Status:** NOT IMPLEMENTED
- **Issue:** No visibility into swap patterns
- **Impact:** Can't identify problem areas
- **Solution Needed:**
  - UC dashboard showing:
    - Most swapped sessions
    - Facilitators who swap most often
    - Peak swap times
  - Help identify scheduling issues

### 14. Swap Request Expiry
- **Status:** NOT APPLICABLE (instant approval)
- **Note:** If we ever add approval workflow, need expiry

### 15. Conflict Resolution
- **Status:** PARTIAL
- **Issue:** What if target facilitator later becomes unavailable?
- **Impact:** Swap might create future conflict
- **Solution Needed:**
  - Check for future unavailability
  - Warn if target has marked unavailability after swap date
  - Allow UC to override

---

## 🎯 PRIORITY RECOMMENDATIONS

### High Priority (Do Now)
1. **Email Notifications** - Critical for communication
2. **Session Validation** - Prevent swapping past sessions
3. **Calendar Refresh** - UX issue, confusing users

### Medium Priority (Do Soon)
4. **Swap History** - Useful for UCs
5. **Undo Swap** - Safety net
6. **In-App Notifications** - Better UX

### Low Priority (Nice to Have)
7. **Swap Suggestions** - Convenience feature
8. **Bulk Swap** - Edge case
9. **Analytics** - Long-term improvement
10. **Abuse Prevention** - Only if becomes a problem

---

## 📝 NOTES

- Current system assumes facilitators are responsible and honest
- "I have discussed this" checkbox is honor system only
- No approval = fast but risky
- Consider adding UC notification at minimum
