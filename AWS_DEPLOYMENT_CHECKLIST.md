# AWS Deployment Checklist - Global Unavailability Migration

## ⚠️ IMPORTANT: DO NOT DEPLOY TO AWS UNTIL ALL STEPS ARE COMPLETE!

---

## 🏠 LOCAL DEVELOPMENT (Complete These First)

### ✅ Completed:
- [x] Updated `models.py` - unit_id now nullable
- [x] Created `migrate_global_unavailability.py` migration script
- [x] Tested migration on local database
- [x] Committed schema changes to GitHub

### 🔄 In Progress:
- [ ] Update all backend queries (optimization_engine.py, facilitator_routes.py, unitcoordinator_routes.py)
- [ ] Update facilitator routes to create global unavailability
- [ ] Update publish schedule to create global blocks
- [ ] Update frontend UI (remove unit selection)
- [ ] Test all features thoroughly on localhost
- [ ] Commit all code changes

### ✅ Ready for AWS When:
- [ ] All checkboxes above are complete
- [ ] App works perfectly on localhost
- [ ] No errors in Flask console
- [ ] All tests pass

---

## ☁️ AWS DEPLOYMENT (Do These Steps IN ORDER)

### Step 1: Backup AWS Database
```bash
# SSH into EC2
ssh -i your-key.pem ec2-user@your-ec2-ip

# Navigate to app directory
cd /path/to/scheduleME

# Create backup
cp instance/dev.db instance/dev.db.backup_BEFORE_GLOBAL_UNAVAIL_$(date +%Y%m%d_%H%M%S)

# Verify backup exists
ls -lh instance/dev.db*
```

**✅ Checkpoint:** Backup file exists and has reasonable size

---

### Step 2: Pull Latest Code
```bash
# Still on EC2
git fetch origin
git checkout fixes
git pull origin fixes
```

**✅ Checkpoint:** No merge conflicts, code pulled successfully

---

### Step 3: Verify Migration Script Exists
```bash
# Check migration script is present
ls -lh migrate_global_unavailability.py
```

**✅ Checkpoint:** File exists

---

### Step 4: Run Migration
```bash
# Run the migration (this will create another backup automatically)
python3 migrate_global_unavailability.py
```

**Expected Output:**
```
============================================================
🚀 GLOBAL UNAVAILABILITY MIGRATION
============================================================
📦 Creating backup: instance/dev.db.backup_before_global_unavail_XXXXXX
✅ Backup created successfully!
🔧 Starting database migration...
📝 Creating new unavailability table with nullable unit_id...
📋 Copying existing data...
🗑️  Dropping old table...
✏️  Renaming new table...
✅ Migration completed successfully!
📊 Verified: XXX unavailability records preserved
============================================================
✅ MIGRATION SUCCESSFUL!
============================================================
```

**✅ Checkpoint:** Migration successful, all records preserved

---

### Step 5: Restart Application
```bash
# Restart Gunicorn (adjust command based on your setup)
sudo systemctl restart gunicorn

# OR if using supervisor:
sudo supervisorctl restart scheduleme

# Check status
sudo systemctl status gunicorn
# OR
sudo supervisorctl status scheduleme
```

**✅ Checkpoint:** App restarted without errors

---

### Step 6: Test on AWS
1. Visit your AWS URL in browser
2. Log in as facilitator
3. Try adding unavailability
4. Check it appears correctly
5. Log in as UC
6. Try publishing a schedule
7. Verify no errors in browser console

**✅ Checkpoint:** All features work correctly

---

### Step 7: Monitor Logs
```bash
# Check for errors
sudo journalctl -u gunicorn -n 100 --no-pager
# OR
tail -f /var/log/scheduleme/error.log
```

**✅ Checkpoint:** No errors in logs

---

## 🚨 ROLLBACK PROCEDURE (If Something Goes Wrong)

### Option 1: Restore from Backup
```bash
# Stop the app
sudo systemctl stop gunicorn

# Restore database
cp instance/dev.db.backup_BEFORE_GLOBAL_UNAVAIL_XXXXXX instance/dev.db

# Revert code
git checkout main  # or your previous working branch

# Restart app
sudo systemctl start gunicorn
```

### Option 2: Use Migration's Auto-Backup
```bash
# The migration script creates its own backup
# Find it:
ls -lh instance/dev.db.backup_before_global_unavail_*

# Restore:
cp instance/dev.db.backup_before_global_unavail_XXXXXX instance/dev.db
```

---

## 📞 TROUBLESHOOTING

### Migration Fails
- **Error:** "unable to open database file"
  - **Fix:** Check file permissions: `ls -l instance/dev.db`
  - **Fix:** Ensure you're in the right directory

### App Won't Start After Migration
- **Check:** Gunicorn logs for errors
- **Check:** Database file permissions
- **Fix:** Restore from backup and investigate

### Unavailability Not Showing
- **Check:** Browser console for JavaScript errors
- **Check:** Network tab - are API calls succeeding?
- **Fix:** Clear browser cache, hard refresh

---

## ✅ POST-DEPLOYMENT VERIFICATION

After successful deployment:
- [ ] Facilitators can add global unavailability
- [ ] UCs can view unavailability across all units
- [ ] Publishing schedules creates global blocks
- [ ] No errors in logs
- [ ] All users can access the app
- [ ] Database backup exists and is valid

---

## 📝 NOTES

- **Migration is SAFE:** It only adds flexibility, doesn't delete data
- **Rollback is EASY:** Just restore from backup
- **Test First:** Always test on localhost before AWS
- **Backup Everything:** Multiple backups = peace of mind
- **Take Your Time:** No rush, do it when ready

---

## 🎯 CURRENT STATUS

**Last Updated:** 2026-01-03
**Status:** ⚠️ NOT READY FOR AWS - Code changes incomplete
**Next Step:** Finish updating backend queries locally
