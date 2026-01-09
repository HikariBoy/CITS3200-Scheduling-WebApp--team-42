# Facilitators Tab Redesign Plan

## Current Problems

The Facilitators tab is outdated and clunky:
- ❌ Doesn't show manual unavailability status
- ❌ Skills are just listed as text (not color-coded)
- ❌ "Next steps" section is clunky and not useful
- ❌ Status indicators are unclear
- ❌ Too much vertical space per facilitator
- ❌ Hard to scan quickly

## What We Keep

✅ **Remind Setup button** - User likes this feature!
✅ **Search and filter functionality**
✅ **View Profile button**

## Proposed Improvements

### 1. **Add Manual Unavailability Indicator**
```
John Doe                    ✓ Unavail. Set
john@example.com
```
- Green checkmark if manual global unavailability set
- Red X if not set
- Same as auto-assign settings

### 2. **Color-Coded Skill Badges**
Instead of plain text list, show color-coded badges:

```
Skills:
[Proficient] [Have Run Before] [Have Some Skill] [No Interest]
```

**Colors:**
- **Proficient**: Green (#10b981)
- **Have Run Before**: Blue (#3b82f6)
- **Have Some Skill**: Yellow (#f59e0b)
- **No Interest**: Red (#ef4444)

### 3. **Cleaner Card Layout**
```
┌─────────────────────────────────────────────────┐
│ John Doe                    ✓ Unavail. Set      │
│ john@example.com            ✅ Ready             │
│                                                  │
│ Skills: [5 Proficient] [2 Have Run] [1 Some]    │
│                                                  │
│ [View Profile] [Remind Setup]                   │
└─────────────────────────────────────────────────┘
```

### 4. **Better Status Badges**
- **Ready**: Green with checkmark
- **Needs Skills**: Red with warning
- **Needs Availability**: Yellow with clock
- **Pending Setup**: Gray with hourglass

### 5. **Remove Clunky Sections**
- ❌ Remove "Next steps" section
- ❌ Remove individual skill listings (replace with summary)
- ❌ Remove "All setup steps complete" text

### 6. **Skill Summary**
Instead of listing every skill, show summary:
```
Skills: 5 Proficient, 2 Have Run Before, 1 Have Some Skill, 2 No Interest
```

Click to expand for full list.

## Implementation Steps

### Backend Changes

1. **Update facilitators endpoint** to include:
   - `has_manual_global_unavailability` flag
   - Skill counts by level
   - Overall status

2. **New endpoint**: `/units/{id}/facilitators-detailed`
   ```json
   {
     "id": 1,
     "name": "John Doe",
     "email": "john@example.com",
     "status": "ready",
     "has_manual_unavailability": true,
     "skill_summary": {
       "proficient": 5,
       "have_run_before": 2,
       "have_some_skill": 1,
       "no_interest": 2
     },
     "skills": [...]
   }
   ```

### Frontend Changes

1. **Update `renderActivityLog()` function**
   - New card design
   - Color-coded skill badges
   - Unavailability indicator
   - Cleaner layout

2. **Add skill badge component**
   ```javascript
   function renderSkillBadge(level, count) {
     const colors = {
       'proficient': '#10b981',
       'have_run_before': '#3b82f6',
       'have_some_skill': '#f59e0b',
       'no_interest': '#ef4444'
     };
     return `<span style="background: ${colors[level]}; ...">${count} ${label}</span>`;
   }
   ```

3. **Add unavailability indicator**
   ```javascript
   function renderUnavailabilityStatus(hasUnavail) {
     return hasUnavail 
       ? '<span style="color: #10b981;">✓ Unavail. Set</span>'
       : '<span style="color: #ef4444;">✗ No Unavail.</span>';
   }
   ```

## Mockup

```
┌───────────────────────────────────────────────────────────┐
│ Facilitator Details                          4 of 4       │
│ [search] [All Status ▼]                                   │
├───────────────────────────────────────────────────────────┤
│                                                            │
│ ┌─────────────────────────────────────────────────────┐  │
│ │ John Doe                    ✓ Unavail. Set  ✅ Ready│  │
│ │ john@example.com                                     │  │
│ │                                                       │  │
│ │ Skills: [5 Proficient] [2 Have Run] [1 Some] [2 No] │  │
│ │                                                       │  │
│ │ [View Profile] [Remind Setup]                        │  │
│ └─────────────────────────────────────────────────────┘  │
│                                                            │
│ ┌─────────────────────────────────────────────────────┐  │
│ │ Jane Smith                  ✗ No Unavail.  ⚠️ Needs │  │
│ │ jane@example.com                          Skills     │  │
│ │                                                       │  │
│ │ Skills: [0 Proficient] [0 Have Run] [0 Some] [0 No] │  │
│ │                                                       │  │
│ │ [View Profile] [Remind Setup]                        │  │
│ └─────────────────────────────────────────────────────┘  │
│                                                            │
└───────────────────────────────────────────────────────────┘
```

## Priority

**HIGH** - This is a major UX improvement that will make the Facilitators tab actually useful!

## Estimated Time

- Backend: 1-2 hours
- Frontend: 2-3 hours
- Testing: 1 hour
- **Total: 4-6 hours**

## Next Steps

1. Create backend endpoint with unavailability status
2. Update frontend rendering function
3. Add color-coded skill badges
4. Test with real data
5. Get user feedback
6. Iterate

---

**Note**: This is a comprehensive redesign. Should be done in a separate session when we have dedicated time for it.
