# UNPUBLISH EMAIL NOT WORKING - FIX GUIDE

## THE PROBLEM
Unpublish emails are not being sent to facilitators, even though publish emails work fine.

## ROOT CAUSE
The Flask server is running **OLD CODE** that doesn't have the `send_schedule_unpublished_email()` function.

## THE FIX - RESTART THE SERVER

### Step 1: Stop the current server
```bash
# Find the Flask process
ps aux | grep python | grep application.py

# Kill it (replace XXXX with the process ID)
kill XXXX

# OR if running in terminal, press Ctrl+C
```

### Step 2: Restart the server
```bash
cd /Users/aj/Desktop/scheduleME/CITS3200-Scheduling-WebApp--team-42

# Start the server
python3 application.py

# OR if using gunicorn:
gunicorn -w 4 -b 0.0.0.0:7321 application:app

# OR if using nohup:
nohup python3 application.py > nohup.out 2>&1 &
```

### Step 3: Test unpublish
1. Go to UC dashboard
2. Click "Unpublish Schedule"
3. Keep checkbox checked
4. Confirm
5. Check server logs for:
   ```
   ============================================================
   UNPUBLISH EMAIL FUNCTION CALLED
   Recipient: email@example.com
   ============================================================
   ```

## WHAT WAS ADDED

### New Email Function (email_service.py)
```python
def send_schedule_unpublished_email(recipient_email, recipient_name, unit_code, unit_name, base_url=None)
```

This function:
- Sends professional orange-themed email
- Explains schedule is being revised
- Reassures assignments are saved
- Provides dashboard link
- Uses AWS SES (same as publish emails)

### Updated Backend (unitcoordinator_routes.py)
- Imports `send_schedule_unpublished_email`
- Loops through facilitators
- Sends email to each
- Tracks emails_sent count

### Extensive Logging
- Shows each step of email sending
- Displays AWS SES responses
- Shows errors clearly

## VERIFICATION

After restarting, you should see in logs:
```
INFO:unitcoordinator_routes:Found 5 facilitators to notify
INFO:unitcoordinator_routes:Processing facilitator: user@example.com
============================================================
UNPUBLISH EMAIL FUNCTION CALLED
Recipient: user@example.com
Unit: CITS3200 - Professional Computing
============================================================
USE_MOCK_EMAIL: not set (use_mock=False)
SES_SENDER_EMAIL: your-email@example.com
✓ Email validation passed
Creating SES client in region: ap-southeast-1
Sending email via AWS SES...
  From: your-email@example.com
  To: user@example.com
  Subject: Schedule Update: CITS3200 Unpublished
✅ Unpublish email sent successfully to user@example.com
✅ Message ID: 010e019ba128d546-...
============================================================
```

## IF STILL NOT WORKING

### Check 1: Environment Variables
```bash
echo $USE_MOCK_EMAIL
echo $SES_SENDER_EMAIL
echo $SES_REGION
```

Should show:
- `USE_MOCK_EMAIL`: (empty or "false")
- `SES_SENDER_EMAIL`: your-verified-email@example.com
- `SES_REGION`: ap-southeast-1

### Check 2: AWS SES Permissions
- Sender email must be verified in AWS SES
- AWS credentials must be valid
- SES must be out of sandbox mode (or recipient must be verified)

### Check 3: Check Spam Folder
Unpublish emails might be going to spam because:
- New email template
- Different subject line
- AWS SES reputation

## QUICK TEST

Run this to test the email function directly:
```bash
cd /Users/aj/Desktop/scheduleME/CITS3200-Scheduling-WebApp--team-42

python3 << 'EOF'
import os
os.environ['USE_MOCK_EMAIL'] = 'true'  # Test in mock mode first

from email_service import send_schedule_unpublished_email

result = send_schedule_unpublished_email(
    recipient_email="test@example.com",
    recipient_name="Test User",
    unit_code="TEST101",
    unit_name="Test Unit"
)

print(f"\nResult: {result}")
print("If you see '[MOCK MODE]' above, the function works!")
EOF
```

## SUMMARY

**The code is correct. You just need to RESTART THE FLASK SERVER to load the new email function.**

After restart:
✅ Unpublish emails will be sent
✅ Checkbox toggle will work
✅ Success message will show email count
✅ Facilitators will receive professional notifications

**RESTART THE SERVER NOW!** 🚀
