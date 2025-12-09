# Auto-Generated Unavailability Feature

## Overview
When a unit coordinator publishes a schedule, the system automatically creates unavailability entries for facilitators in their OTHER units. This prevents double-booking across units.

## How It Works

### 1. **Publishing a Schedule**
When UC publishes Unit A's schedule:
- System finds all sessions with assigned facilitators
- For each facilitator, finds all OTHER units they're assigned to
- Creates unavailability entries in those other units
- Entries are marked as "auto-generated" with `source_session_id`

### 2. **Visual Display**
Facilitators see three types of unavailability on their calendar:

| Type | Color | Icon | Can Edit? |
|------|-------|------|-----------|
| **Manual Unavailability** | Red (`#fee2e2`) | `event_busy` | ✅ Yes |
| **Scheduled Commitment** | Blue (`#dbeafe`) | `lock` | ❌ No |
| **Both (Mixed)** | Red/Blue gradient | - | Partial |

### 3. **Legend**
A color legend appears above the calendar explaining:
- 🔴 Your Unavailability (manual)
- 🔵 🔒 Scheduled Commitment (auto-generated)
- 🟣 Both (mixed)

### 4. **Details Panel**
When clicking a date with unavailability:
- **Manual entries**: Show edit/delete buttons
- **Auto-generated entries**: Show lock icon + reason (e.g., "Scheduled: CITS3200 - Lab Session (Lab)")
- Cannot edit or delete auto-generated entries

## Database Changes

### New Column: `unavailability.source_session_id`
- Type: `INTEGER` (nullable)
- Foreign Key: References `session.id`
- Purpose: Links auto-generated unavailability to source session

### Migration
Run the migration:
```bash
flask shell
>>> exec(open('migrations/add_source_session_to_unavailability.py').read())
```

Or manually:
```sql
ALTER TABLE unavailability ADD COLUMN source_session_id INTEGER;
```

## Backend Implementation

### Key Functions

#### `generate_unavailability_from_schedule(unit_id)`
**Location**: `unitcoordinator_routes.py`
**Called**: When schedule is published
**Logic**:
1. Get all sessions with facilitators in published unit
2. For each session, find facilitator's other units
3. Check if unavailability already exists (prevent duplicates)
4. Create unavailability with reason: "Scheduled: {unit_code} - {module} ({type})"
5. Set `source_session_id` to link back to session

#### `remove_unavailability_from_schedule(unit_id)`
**Location**: `unitcoordinator_routes.py`
**Called**: When schedule is unpublished (if implemented)
**Logic**:
1. Find all sessions from unpublished unit
2. Delete unavailability entries where `source_session_id` matches

### API Changes

#### GET `/facilitator/unavailability`
**Added field**: `is_auto_generated` (boolean)
- `true` if `source_session_id` is not null
- `false` otherwise

#### DELETE `/facilitator/unavailability/<id>`
**New validation**: Blocks deletion if `source_session_id` is not null
**Error message**: "Cannot delete auto-generated unavailability from published schedules."

## Frontend Implementation

### JavaScript Changes (`facilitator.js`)

#### `getUnavailabilityType(dateString)`
Enhanced to return:
- `'full'` - Full day manual unavailability
- `'partial'` - Partial day manual unavailability
- `'auto'` - Only auto-generated unavailability
- `'mixed'` - Both manual and auto-generated on same day

#### Calendar Rendering
Applies CSS classes based on type:
- `.unavailable-full` - Red (manual full day)
- `.unavailable-partial` - Red (manual partial)
- `.auto-unavailable` - Blue (auto-generated)
- `.mixed-unavailable` - Red/Blue gradient (both)

#### Recent Unavailability List
- Auto-generated entries show lock icon (blue)
- Display reason text instead of edit/delete buttons
- Manual entries show normal edit/delete buttons

### CSS Styles (`facilitator.css`)

```css
/* Auto-generated unavailability */
.auto-unavailable {
  background-color: #dbeafe !important;
  border-color: #3b82f6 !important;
  color: #1e40af !important;
}

/* Mixed unavailability */
.mixed-unavailable {
  background: linear-gradient(135deg, #fee2e2 50%, #dbeafe 50%) !important;
  border-color: #7c3aed !important;
  color: #6b21a8 !important;
}
```

## Edge Cases Handled

### ✅ Duplicate Prevention
- Checks if unavailability already exists before creating
- Uses: `user_id`, `unit_id`, `date`, `start_time`, `end_time`, `source_session_id`

### ✅ Date Range Validation
- Only creates unavailability within target unit's date range
- Skips dates before `start_date` or after `end_date`

### ✅ Deletion Protection
- Cannot delete auto-generated unavailability
- Clear error message guides user to contact UC

### ✅ Schedule Status Check
- Only generates when schedule status is `PUBLISHED`
- Validates unit status before processing

### ✅ Cross-Unit Coordination
- Automatically updates all units facilitator is assigned to
- No manual intervention needed

## User Experience

### For Facilitators
1. **Visibility**: Clearly see scheduled commitments in other units
2. **Prevention**: Cannot accidentally set unavailability during scheduled times
3. **Clarity**: Lock icon and blue color indicate read-only status
4. **Information**: Reason shows which unit/module/session type

### For Unit Coordinators
1. **Automatic**: No manual work needed
2. **Accurate**: Always reflects current published schedules
3. **Reliable**: Prevents double-booking across units
4. **Transparent**: Facilitators see why they're unavailable

## Testing Checklist

- [ ] Publish schedule in Unit A with assigned facilitators
- [ ] Check facilitator's Unit B shows blue unavailability
- [ ] Verify lock icon appears in recent unavailability list
- [ ] Confirm cannot edit/delete auto-generated entries
- [ ] Test mixed day (manual + auto) shows gradient
- [ ] Verify legend displays correctly
- [ ] Check dates outside unit range are skipped
- [ ] Test duplicate prevention works
- [ ] Verify UC sees auto_unavailability_created count in publish response

## Future Enhancements

### Potential Improvements
1. **Unpublish Handler**: Remove auto-unavailability when schedule is unpublished
2. **Session Updates**: Update unavailability when session times change
3. **Facilitator Reassignment**: Update unavailability when facilitator is reassigned
4. **Notification**: Notify facilitators when auto-unavailability is created
5. **View Source**: Link to view the source session/schedule

## Files Modified

### Backend
- `models.py` - Added `source_session_id` column
- `unitcoordinator_routes.py` - Added generation/removal functions
- `facilitator_routes.py` - Added `is_auto_generated` flag, deletion protection

### Frontend
- `facilitator.js` - Enhanced calendar rendering, unavailability type detection
- `facilitator.css` - Added styles for auto-generated and mixed types
- `facilitator_dashboard.html` - Added color legend

### Database
- `migrations/add_source_session_to_unavailability.py` - Migration script

## Summary

This feature provides **automatic cross-unit conflict prevention** by:
- ✅ Auto-generating unavailability from published schedules
- ✅ Clear visual distinction (blue vs red)
- ✅ Protection against accidental deletion
- ✅ Seamless integration with existing unavailability system
- ✅ Zero manual work for UCs or facilitators

**Result**: Facilitators cannot be double-booked across units! 🎯
