# Facilitators Tab Redesign - Step-by-Step Implementation Guide

## Overview
This guide will walk you through redesigning the Facilitators tab to be modern, clean, and useful.

**Estimated Time:** 4-6 hours  
**Difficulty:** Medium  
**Files to Modify:** 2-3 files

---

## Step 1: Update Backend Endpoint (30 minutes)

### 1.1 Find the Current Endpoint

**File:** `unitcoordinator_routes.py`

Search for the endpoint that returns facilitator data for the dashboard. Look for something like:
```python
@unitcoordinator_bp.get("/units/<int:unit_id>/dashboard-sessions")
```

### 1.2 Add Unavailability Check

Add this helper function near the top of `unitcoordinator_routes.py`:

```python
def get_facilitator_unavailability_status(facilitator_id):
    """Check if facilitator has manual global unavailability set"""
    has_manual_global = db.session.query(Unavailability).filter(
        Unavailability.user_id == facilitator_id,
        Unavailability.unit_id == None,  # Global only
        Unavailability.source_session_id == None  # Manual only
    ).first() is not None
    
    return has_manual_global
```

### 1.3 Add Skill Summary Function

Add this helper function:

```python
def get_facilitator_skill_summary(facilitator_id, unit_id):
    """Get skill counts by level for a facilitator"""
    from models import FacilitatorSkill, SkillLevel, Module
    
    # Get all modules for this unit
    unit_modules = Module.query.filter_by(unit_id=unit_id).all()
    module_ids = [m.id for m in unit_modules]
    
    # Get facilitator's skills for these modules
    skills = FacilitatorSkill.query.filter(
        FacilitatorSkill.facilitator_id == facilitator_id,
        FacilitatorSkill.module_id.in_(module_ids)
    ).all()
    
    # Count by level
    summary = {
        'proficient': 0,
        'have_run_before': 0,
        'have_some_skill': 0,
        'no_interest': 0,
        'total_modules': len(module_ids),
        'declared_modules': len(skills)
    }
    
    for skill in skills:
        if skill.skill_level == SkillLevel.PROFICIENT:
            summary['proficient'] += 1
        elif skill.skill_level == SkillLevel.HAVE_RUN_BEFORE:
            summary['have_run_before'] += 1
        elif skill.skill_level == SkillLevel.HAVE_SOME_SKILL:
            summary['have_some_skill'] += 1
        elif skill.skill_level == SkillLevel.NO_INTEREST:
            summary['no_interest'] += 1
    
    return summary
```

### 1.4 Update Dashboard Endpoint

Find where `facilitator_counts` is built and add the new data:

```python
# In the dashboard-sessions endpoint, update facilitator_counts:
facilitator_counts = []
for facilitator in facilitators:
    # Existing code...
    
    # ADD THESE NEW FIELDS:
    has_unavailability = get_facilitator_unavailability_status(facilitator.id)
    skill_summary = get_facilitator_skill_summary(facilitator.id, unit_id)
    
    facilitator_counts.append({
        'id': facilitator.id,
        'name': facilitator.full_name or facilitator.email,
        'email': facilitator.email,
        'session_count': session_count,
        'status': status,  # existing
        'has_manual_unavailability': has_unavailability,  # NEW
        'skill_summary': skill_summary,  # NEW
        # ... other existing fields
    })
```

---

## Step 2: Update Frontend Rendering (2-3 hours)

### 2.1 Find the Rendering Function

**File:** `static/js/uc.js`

Search for `renderActivityLog` function (around line 4121).

### 2.2 Create Helper Functions

Add these helper functions BEFORE `renderActivityLog`:

```javascript
// Helper: Render unavailability status
function renderUnavailabilityBadge(hasUnavail) {
  if (hasUnavail) {
    return `
      <span style="display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: #10b981; font-weight: 500;">
        <span class="material-icons" style="font-size: 14px;">check_circle</span>
        Unavail. Set
      </span>
    `;
  } else {
    return `
      <span style="display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: #ef4444; font-weight: 500;">
        <span class="material-icons" style="font-size: 14px;">cancel</span>
        No Unavail.
      </span>
    `;
  }
}

// Helper: Render skill summary badges
function renderSkillSummary(skillSummary) {
  if (!skillSummary) return '<span style="color: #9ca3af;">No skills declared</span>';
  
  const badges = [];
  
  if (skillSummary.proficient > 0) {
    badges.push(`<span style="background: #10b981; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">${skillSummary.proficient} Proficient</span>`);
  }
  
  if (skillSummary.have_run_before > 0) {
    badges.push(`<span style="background: #3b82f6; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">${skillSummary.have_run_before} Have Run</span>`);
  }
  
  if (skillSummary.have_some_skill > 0) {
    badges.push(`<span style="background: #f59e0b; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">${skillSummary.have_some_skill} Some Skill</span>`);
  }
  
  if (skillSummary.no_interest > 0) {
    badges.push(`<span style="background: #ef4444; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">${skillSummary.no_interest} No Interest</span>`);
  }
  
  if (badges.length === 0) {
    return '<span style="color: #9ca3af;">No skills declared</span>';
  }
  
  return badges.join(' ');
}

// Helper: Render status badge
function renderStatusBadge(status) {
  const statusConfig = {
    'ready': {
      icon: 'check_circle',
      color: '#10b981',
      bg: '#d1fae5',
      text: 'Ready'
    },
    'needs_skills': {
      icon: 'priority_high',
      color: '#ef4444',
      bg: '#fee2e2',
      text: 'Needs Skills'
    },
    'needs_availability': {
      icon: 'schedule',
      color: '#f59e0b',
      bg: '#fef3c7',
      text: 'Needs Availability'
    },
    'pending': {
      icon: 'hourglass_bottom',
      color: '#6b7280',
      bg: '#f3f4f6',
      text: 'Pending Setup'
    }
  };
  
  const config = statusConfig[status] || statusConfig['pending'];
  
  return `
    <span style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 6px; background: ${config.bg}; color: ${config.color}; font-size: 12px; font-weight: 600;">
      <span class="material-icons" style="font-size: 14px;">${config.icon}</span>
      ${config.text}
    </span>
  `;
}
```

### 2.3 Rewrite renderActivityLog Function

Replace the entire `renderActivityLog` function with this new version:

```javascript
function renderActivityLog(facilitatorData = []) {
  console.log('renderActivityLog called with:', facilitatorData);
  
  const tableBody = document.querySelector('#activity-log-table tbody');
  if (!tableBody) {
    console.error('Activity log table body not found');
    return;
  }
  
  console.log('Table body found:', true);
  
  if (!facilitatorData || facilitatorData.length === 0) {
    tableBody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; padding: 40px; color: #9ca3af;">
          <span class="material-icons" style="font-size: 48px; opacity: 0.3;">people_outline</span>
          <p style="margin-top: 16px;">No facilitators found for this unit</p>
        </td>
      </tr>
    `;
    return;
  }
  
  console.log('Rendering', facilitatorData.length, 'facilitators');
  
  // Build new table rows
  let html = '';
  
  facilitatorData.forEach(facilitator => {
    const name = facilitator.name || facilitator.email;
    const email = facilitator.email || '';
    const sessionCount = facilitator.session_count || 0;
    const status = facilitator.status || 'pending';
    const hasUnavail = facilitator.has_manual_unavailability || false;
    const skillSummary = facilitator.skill_summary || null;
    
    html += `
      <tr style="border-bottom: 1px solid #e5e7eb;">
        <td style="padding: 16px;">
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <div style="font-weight: 600; font-size: 14px; color: #1f2937;">${name}</div>
            <div style="font-size: 12px; color: #6b7280;">${email}</div>
          </div>
        </td>
        
        <td style="padding: 16px;">
          ${renderUnavailabilityBadge(hasUnavail)}
        </td>
        
        <td style="padding: 16px;">
          ${renderStatusBadge(status)}
        </td>
        
        <td style="padding: 16px;">
          <div style="display: flex; flex-wrap: wrap; gap: 4px;">
            ${renderSkillSummary(skillSummary)}
          </div>
        </td>
        
        <td style="padding: 16px; text-align: center;">
          <span style="font-weight: 600; color: #1f2937;">${sessionCount}</span>
        </td>
        
        <td style="padding: 16px;">
          <div style="display: flex; gap: 8px;">
            <button class="btn-sm btn-secondary" onclick="viewFacilitatorProfile(${facilitator.id})" style="font-size: 11px; padding: 6px 12px;">
              <span class="material-icons" style="font-size: 14px;">visibility</span>
              View
            </button>
            ${status !== 'ready' ? `
              <button class="btn-sm btn-primary" onclick="remindFacilitatorSetup(${facilitator.id})" style="font-size: 11px; padding: 6px 12px;">
                <span class="material-icons" style="font-size: 14px;">notifications_active</span>
                Remind
              </button>
            ` : ''}
          </div>
        </td>
      </tr>
    `;
  });
  
  tableBody.innerHTML = html;
}
```

---

## Step 3: Update Table Header (15 minutes)

### 3.1 Find the Table HTML

**File:** `templates/unitcoordinator_dashboard.html`

Search for the facilitators table (look for "activity-log-table" or "Facilitator Details").

### 3.2 Update Table Header

Replace the `<thead>` section with:

```html
<thead style="background: #f9fafb; border-bottom: 2px solid #e5e7eb;">
  <tr>
    <th style="padding: 12px 16px; text-align: left; font-weight: 600; color: #374151; font-size: 12px; text-transform: uppercase;">
      Facilitator
    </th>
    <th style="padding: 12px 16px; text-align: left; font-weight: 600; color: #374151; font-size: 12px; text-transform: uppercase;">
      Availability
    </th>
    <th style="padding: 12px 16px; text-align: left; font-weight: 600; color: #374151; font-size: 12px; text-transform: uppercase;">
      Status
    </th>
    <th style="padding: 12px 16px; text-align: left; font-weight: 600; color: #374151; font-size: 12px; text-transform: uppercase;">
      Skills
    </th>
    <th style="padding: 12px 16px; text-align: center; font-weight: 600; color: #374151; font-size: 12px; text-transform: uppercase;">
      Sessions
    </th>
    <th style="padding: 12px 16px; text-align: left; font-weight: 600; color: #374151; font-size: 12px; text-transform: uppercase;">
      Actions
    </th>
  </tr>
</thead>
```

---

## Step 4: Test (1 hour)

### 4.1 Restart Server

```bash
# Stop server (Ctrl+C)
cd /Users/aj/Desktop/scheduleME/CITS3200-Scheduling-WebApp--team-42
python3 application.py
```

### 4.2 Test Checklist

- [ ] Navigate to UC Dashboard
- [ ] Click on Facilitators tab
- [ ] Verify table shows:
  - [ ] Facilitator name and email
  - [ ] Unavailability status (green ✓ or red ✗)
  - [ ] Status badge (Ready, Needs Skills, etc.)
  - [ ] Color-coded skill badges
  - [ ] Session count
  - [ ] View and Remind buttons
- [ ] Test with facilitators who:
  - [ ] Have skills declared
  - [ ] Don't have skills declared
  - [ ] Have manual unavailability
  - [ ] Don't have manual unavailability
- [ ] Verify "Remind" button only shows for non-ready facilitators
- [ ] Click "View Profile" button - should work
- [ ] Click "Remind Setup" button - should work

### 4.3 Browser Console Check

Open browser console (F12) and check for:
- No JavaScript errors
- `renderActivityLog called with:` log shows correct data
- All facilitators render correctly

---

## Step 5: Polish & Refinements (30 minutes)

### 5.1 Add Hover Effects

Update the table row style to include hover:

```javascript
html += `
  <tr style="border-bottom: 1px solid #e5e7eb; transition: background 0.2s;" 
      onmouseover="this.style.background='#f9fafb'" 
      onmouseout="this.style.background='white'">
```

### 5.2 Add Loading State

At the start of `renderActivityLog`, add:

```javascript
if (facilitatorData === null || facilitatorData === undefined) {
  tableBody.innerHTML = `
    <tr>
      <td colspan="6" style="text-align: center; padding: 40px;">
        <span class="material-icons rotating" style="font-size: 48px; color: #3b82f6;">hourglass_empty</span>
        <p style="margin-top: 16px; color: #6b7280;">Loading facilitators...</p>
      </td>
    </tr>
  `;
  return;
}
```

### 5.3 Add Empty State

Already included in Step 2.3!

---

## Step 6: Commit Changes (5 minutes)

```bash
cd /Users/aj/Desktop/scheduleME/CITS3200-Scheduling-WebApp--team-42
git add -A
git commit -m "feat: redesign Facilitators tab with modern UI

MAJOR REDESIGN: Facilitators tab

NEW FEATURES:
✅ Manual unavailability indicator (green ✓ / red ✗)
✅ Color-coded skill badges (Proficient/Have Run/Some/No Interest)
✅ Cleaner table layout
✅ Better status badges (Ready, Needs Skills, etc.)
✅ Skill summary instead of long list
✅ Hover effects on rows
✅ Loading and empty states

REMOVED:
❌ Clunky 'Next steps' section
❌ Long skill listings
❌ Confusing status indicators

COLORS:
- Proficient: Green (#10b981)
- Have Run Before: Blue (#3b82f6)
- Have Some Skill: Yellow (#f59e0b)
- No Interest: Red (#ef4444)

BACKEND:
- Added get_facilitator_unavailability_status()
- Added get_facilitator_skill_summary()
- Updated dashboard endpoint with new fields

FRONTEND:
- Rewrote renderActivityLog()
- Added renderUnavailabilityBadge()
- Added renderSkillSummary()
- Added renderStatusBadge()
- Updated table header

TESTED:
✅ Shows correct unavailability status
✅ Color-coded skills display properly
✅ Status badges work
✅ Buttons functional
✅ Responsive and clean

USER FEEDBACK ADDRESSED:
'This is so bad and outdated' → NOW MODERN! ✨
'doesn't check manual unavailability' → NOW SHOWS IT! ✓
'should be colour coded' → NOW COLOR-CODED! 🎨
'just overall should be 10x better' → IT IS! 🚀"

git push
```

---

## Troubleshooting

### Issue: Unavailability always shows "No Unavail."

**Solution:** Check that `get_facilitator_unavailability_status()` is querying correctly:
- Verify `unit_id == None` (not `unit_id == unit.id`)
- Verify `source_session_id == None` (manual only)

### Issue: Skills not showing

**Solution:** Check that `get_facilitator_skill_summary()` is:
- Getting correct module IDs for the unit
- Filtering skills by those module IDs
- Counting correctly by SkillLevel enum

### Issue: Table not rendering

**Solution:** Check browser console for errors:
- Verify `facilitatorData` has the new fields
- Check that helper functions are defined BEFORE `renderActivityLog`
- Verify table body element exists

### Issue: Colors not showing

**Solution:** Inline styles should work, but verify:
- No CSS conflicts
- Material Icons loaded
- Browser supports the styles

---

## Final Checklist

Before marking as complete:

- [ ] Backend functions added and working
- [ ] Frontend rendering updated
- [ ] Table header updated
- [ ] All tests passing
- [ ] No console errors
- [ ] Unavailability indicator works
- [ ] Skill badges color-coded
- [ ] Status badges clear
- [ ] Buttons functional
- [ ] Hover effects smooth
- [ ] Loading state shows
- [ ] Empty state shows
- [ ] Code committed and pushed
- [ ] User tested and approved! ✅

---

## Estimated Timeline

1. **Backend (30 min)** - Add helper functions and update endpoint
2. **Frontend (2-3 hours)** - Rewrite rendering logic
3. **HTML (15 min)** - Update table header
4. **Testing (1 hour)** - Comprehensive testing
5. **Polish (30 min)** - Hover effects, loading states
6. **Commit (5 min)** - Git commit and push

**Total: 4-6 hours**

---

## Success Criteria

✅ Facilitators tab looks modern and professional  
✅ Unavailability status clearly visible  
✅ Skills color-coded and easy to scan  
✅ Status badges intuitive  
✅ No clunky sections  
✅ User says "This is 10x better!" 🎉

---

**Good luck! Take your time and test thoroughly at each step!** 🚀
