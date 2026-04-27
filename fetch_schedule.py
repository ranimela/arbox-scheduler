import os
import json
import requests
import sys
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Force UTF-8 for Windows terminal support
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

GYM_ID = os.getenv('ARBOX_BOX_ID', '80')
LOCATION_ID = os.getenv('ARBOX_LOCATION_ID', '70')
EMAIL = os.getenv('ARBOX_EMAIL')
PASSWORD = os.getenv('ARBOX_PASSWORD')
USER_ID = os.getenv('ARBOX_USER_ID')
MEMBERSHIP_USER_ID = os.getenv('ARBOX_MEMBERSHIP_USER_ID', '12165397')

# NTFY Settings
# Using a specific variable name to avoid collision with other projects
# Falls back to default if the env var is missing or empty
NTFY_TOPIC = os.getenv('ARBOX_NTFY_TOPIC') or 'arbox-scheduler-ranimela'

IDENTIFIER = "f1UhUDad1588686203"

# TARGET CONFIGURATION (Custom Per-Day Schedule)
TARGET_CONFIG = {
    'Sunday':   {'time': '08:30', 'coach': 'בר טנג\'י'},
    'Tuesday':  {'time': '18:30', 'coach': ''}, 
    'Thursday': {'time': '08:30', 'coach': 'שיראל ריצמן'},
    'Friday':   {'time': '08:30', 'coach': 'דניאל טנג\'י'}
}

# ONE-TIME OVERRIDES (Date-specific exceptions)
DATE_OVERRIDES = {}

# SET TO False TO ACTUALLY BOOK CLASSES
DRY_RUN = False

def send_ntfy(title, message, priority="default", tags=""):
    """Send push notification via ntfy.sh"""
    print(f"Sending ntfy notification: {title}")
    try:
        headers = {
            "Title": title.encode('utf-8'),
            "Priority": priority,
            "Tags": tags
        }
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode('utf-8'),
            headers=headers,
            timeout=10
        ).raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send ntfy: {e}")
        return False

def wait_for_precision_window(target_hour_utc=18, target_minute_utc=0, expected_wake_hour_utc=16, expected_wake_minute_utc=0, pre_notify_msg=None):
    """
    If the script starts early, it will wait until exactly the target time.
    Sends a status update at 20:59 (1 minute before launch).
    """
    now_utc = datetime.now(timezone.utc)
    target_time = now_utc.replace(hour=target_hour_utc, minute=target_minute_utc, second=0, microsecond=0)
    
    # Calculate the expected wake-up time to report delays
    expected_wake = now_utc.replace(hour=expected_wake_hour_utc, minute=expected_wake_minute_utc, second=0, microsecond=0)
    delay_delta = now_utc - expected_wake
    delay_mins = int(delay_delta.total_seconds() / 60)
    
    # Only wait if we are within the window
    if (target_time - now_utc).total_seconds() > 9000 or (target_time - now_utc).total_seconds() < 0:
        print(f"Skipping wait: Not in the precision window. Current UTC: {now_utc.strftime('%H:%M:%S')}")
        return

    print(f"--- PRECISION COUNTDOWN ENGAGED ---")
    print(f"Target Time: {target_time.strftime('%H:%M:%S')} UTC (21:00:00 Israel)")
    
    # Initial "I am here" notification
    send_ntfy(
        title="Arbox Agent Active",
        message=f"Standing by for 21:00:00 registration.\nExpected wake-up: {expected_wake.strftime('%H:%M')} UTC\nGitHub Delay: {delay_mins}m"
    )
    
    has_sent_pre_notification = False
    
    while True:
        now = datetime.now(timezone.utc)
        remaining = (target_time - now).total_seconds()
        
        # 20:59 Notification (60 seconds before target)
        if 59 <= remaining <= 61 and not has_sent_pre_notification:
            print("\n[20:59] Sending T-minus 1 minute status update...")
            send_ntfy(
                title="T-minus 1 Minute",
                message=f"Targeting: {pre_notify_msg or 'No specific target found.'}",
                priority="high"
            )
            has_sent_pre_notification = True

        if remaining <= 0:
            print(f"\nBEEP BEEP BEEP! 21:00:00 REACHED! GO GO GO! (Actual: {now.strftime('%H:%M:%S.%f')})")
            break
            
        if remaining > 1:
            print(f"T-minus {int(remaining)} seconds...", end='\r')
            time.sleep(0.5)
        else:
            time.sleep(0.001)

def book_class(session, schedule_id):
    """
    Attempts to book a class using the V2 Arbox API.
    """
    url = f'https://apiappv2.arboxapp.com/api/v2/scheduleUser/insert?XDEBUG_SESSION_START=PHPSTORM'
    payload = {
        "extras": None,
        "membership_user_id": int(MEMBERSHIP_USER_ID),
        "schedule_id": int(schedule_id)
    }
    
    if DRY_RUN:
        print(f"[DRY RUN] Would book class with Schedule ID: {schedule_id}")
        return True, "Dry run success"

    try:
        resp = session.post(url, json=payload)
        resp_json = resp.json()
        
        # Check for success or already registered
        is_already_in = "alreadyRegistered" in str(resp_json)
        
        if resp.status_code == 200 or is_already_in:
            status = "Confirmed" if resp.status_code == 200 else "Already Registered"
            msg = f"Successfully secured spot! ({status})"
            print(msg)
            return True, msg
        else:
            msg = f"Failed to book: {resp.status_code} {resp.text}"
            print(msg)
            return False, msg
    except Exception as e:
        msg = f"Error during booking: {e}"
        print(msg)
        return False, msg

def generate_html_table(classes_info, date_range_str, status_html=""):
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {{
            --bg-color: #f8fafc;
            --text-color: #1e293b;
            --card-bg: #ffffff;
            --accent: #3b82f6;
            --table-border: #e2e8f0;
            --target-row: #f0fdf4;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 20px;
        }}
        .container {{
            background: var(--card-bg);
            border: 1px solid var(--table-border);
            border-radius: 12px;
            padding: 24px;
            max-width: 600px;
            margin: 0 auto;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        .status-header {{
            text-align: center;
            padding: 16px;
            margin-bottom: 24px;
            border-radius: 8px;
            font-weight: 600;
        }}
        .status-success {{ background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }}
        .status-failure {{ background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid var(--table-border);
        }}
        th {{
            color: #64748b;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        tr.target {{ background-color: var(--target-row); }}
        .badge {{
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 11px;
            font-weight: 600;
        }}
        .booked {{ background: #22c55e; color: white; }}
        .missed {{ background: #ef4444; color: white; }}
    </style>
</head>
<body>
    <div class="container">
        <h2 style="text-align:center; margin-top:0;">Gorillot Booking Report</h2>
        {status_html}
        <p style="text-align:center; font-size:14px; color:#64748b;">Schedule for {date_range_str}</p>
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Training</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
"""
    for cls in classes_info:
        is_target = cls['best_match']
        row_class = "target" if is_target else ""
        
        if is_target:
            status_badge = '<span class="badge booked">SECURED</span>' if cls.get('was_booked') else '<span class="badge missed" style="background:#ef4444">MISSED</span>'
        else:
            status_badge = '<span style="color:#cbd5e1">-</span>'
            
        html_content += f"""
                <tr class="{row_class}">
                    <td><strong>{cls['hour']}</strong></td>
                    <td>{cls['training']}</td>
                    <td>{status_badge}</td>
                </tr>"""

    html_content += """
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    with open('schedule.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    return html_content

def main():
    if not EMAIL or not PASSWORD:
        print("Please ensure ARBOX_EMAIL and ARBOX_PASSWORD are set in the .env file.")
        return

    base_headers = {
        'Content-Type': 'application/json',
        'identifier': IDENTIFIER,
        'boxfk': GYM_ID,
        'whitelabel': 'Arbox',
        'newsite': '1',
        'referername': 'site',
        'version': '10',
        'lang': 'en',
        'User-Agent': 'Mozilla/5.0'
    }

    session = requests.Session()
    session.headers.update(base_headers)
    
    # 1. Login Immediately (Don't wait for 21:00)
    login_url = 'https://apiappv2.arboxapp.com/api/v2/user/siteLogin'
    try:
        resp = session.post(login_url, json={"email": EMAIL, "password": PASSWORD, "phone": ""})
        data = resp.json().get("data", resp.json())
        token = data.get("token") or resp.headers.get("token")
        if not token:
            print("Login failed, no token returned.")
            return
        session.headers.update({'accesstoken': token})
        print(f"Logged in as {EMAIL}.")
    except Exception as e:
        print(f"Login error: {e}")
        return

    # 2. Fetch schedule for tomorrow immediately to find the target ID
    today = datetime.now()
    tomorrow_obj = today + timedelta(days=1)
    tomorrow = tomorrow_obj.strftime("%Y-%m-%d")
    tomorrow_day = tomorrow_obj.strftime("%A")
    
    day_config = DATE_OVERRIDES.get(tomorrow, TARGET_CONFIG.get(tomorrow_day))
    
    target_class_id = None
    target_summary = "Searching..."
    target_summary_with_spots = "Searching..."
    
    print(f"Pre-scanning schedule for {tomorrow}...")
    schedule_url = 'https://apiappv2.arboxapp.com/api/v2/site/schedule/betweenDates'
    payload = {"from": tomorrow, "to": tomorrow, "locations_box_id": int(LOCATION_ID)}
    
    try:
        resp = session.post(schedule_url, json=payload)
        events = resp.json().get("data", [])
        
        if day_config:
            target_time = day_config['time']
            preferred_coach = day_config['coach']
            matches = [e for e in events if e.get('time') == target_time]
            
            if matches:
                best_match = None
                if preferred_coach:
                    for m in matches:
                        coach_dict = m.get('coach') or {}
                        if preferred_coach in coach_dict.get('full_name', ''):
                            best_match = m
                            break
                if not best_match:
                    best_match = matches[0]
                
                target_class_id = best_match.get('id')
                coach_name = best_match.get('coach', {}).get('full_name', 'Unknown')
                free_spots = best_match.get('free', 0)
                total_spots = best_match.get('max_users', 0)
                target_summary = f"{tomorrow_day} {tomorrow} at {target_time} (Coach: {coach_name})"
                target_summary_with_spots = f"{target_summary}\nSpots: {free_spots}/{total_spots}"
                print(f"TARGET ACQUIRED: {target_summary_with_spots}")
            else:
                target_summary_with_spots = f"No class found at {target_time} for {tomorrow_day}."
                print(f"WARNING: {target_summary_with_spots}")
    except Exception as e:
        print(f"Pre-scan error: {e}")

    # 3. Start Precision Timer with target info for the 20:59 notification
    wait_for_precision_window(pre_notify_msg=target_summary_with_spots)

    # 4. EXECUTION (Fire immediately at 21:00:00)
    classes_info = []
    booking_summaries = []
    
    if target_class_id:
        success, log_msg = book_class(session, target_class_id)
        # Clean the log message of any success/fail emojis
        clean_log_msg = log_msg.replace("✅", "").replace("❌", "").strip()
        booking_summaries.append(f"{target_summary}: {clean_log_msg}")
        
        # We still fetch the full list for the final report table
        resp = session.post(schedule_url, json=payload)
        events = resp.json().get("data", [])
        
        for entry in events:
            schedule_id = entry.get('id')
            is_best_match = (schedule_id == target_class_id)
            
            # Extract basic info for table
            hour = entry.get('time', '')
            box_cats = entry.get('box_categories') or {}
            training = box_cats.get('name') or entry.get('series', {}).get('series_name') or 'WOD'
            
            classes_info.append({
                'day': tomorrow_day,
                'date': tomorrow,
                'hour': hour,
                'training': training,
                'was_booked': True if (is_best_match and success) else False,
                'best_match': is_best_match
            })
    else:
        print("No target ID found. Skipping booking attempt.")

    # 5. Final Processing & Notification Report
    if classes_info:
        classes_info.sort(key=lambda x: (x['date'], x['hour']))
        any_booked = any(cls['was_booked'] for cls in classes_info if cls['best_match'])
        
        if any_booked:
            status_html = '<div class="status-header status-success">MISSION SUCCESS: Booking Secured</div>'
            ntfy_title = "✅ Booking Confirmed"
        else:
            status_html = '<div class="status-header status-failure">FAILURE: Class was likely full</div>'
            ntfy_title = "❌ Booking Failed"

        generate_html_table(classes_info, tomorrow, status_html)
        
        ntfy_msg = "\n".join(booking_summaries)
        send_ntfy(ntfy_title, ntfy_msg, priority="high")

if __name__ == '__main__':
    main()
