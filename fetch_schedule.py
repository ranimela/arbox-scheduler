import os
import json
import requests
import sys
import time
import logging
import random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("arbox_scheduler")

# Load environment variables from .env file
load_dotenv()

# Force UTF-8 for Windows terminal support
if sys.platform == "win32" and "pytest" not in sys.modules:
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

# Default TARGET CONFIGURATION (Custom Per-Day Schedule)
TARGET_CONFIG = {
    'Sunday':   {'time': '08:30', 'coach': 'not דניאל טנג\'י', 'type': 'WOD'},
    'Tuesday':  {'time': '18:30', 'coach': 'not דניאל טנג\'י', 'type': 'WOD'}, 
    'Thursday': {'time': '08:30', 'coach': 'not דניאל טנג\'י', 'type': 'WOD'},
    'Friday':   {'time': '08:30', 'coach': 'not דניאל טנג\'י', 'type': 'WOD'}
}
DATE_OVERRIDES = {}

# Load Configuration from external config.json
config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
if os.path.exists(config_path):
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            TARGET_CONFIG = config_data.get('TARGET_CONFIG', TARGET_CONFIG)
            DATE_OVERRIDES = config_data.get('DATE_OVERRIDES', DATE_OVERRIDES)
            logger.info("Loaded target configuration from config.json.")
    except Exception as e:
        logger.warning(f"Failed to load config.json ({e}). Using default configuration.")
else:
    logger.info("config.json not found. Using default configuration.")

# Purge stale report files at startup
for stale_file in ['schedule.html', 'schedule_output.json']:
    stale_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), stale_file)
    if os.path.exists(stale_path):
        try:
            os.remove(stale_path)
            logger.info(f"Purged stale execution report: {stale_file}")
        except Exception as e:
            logger.warning(f"Could not purge stale file {stale_file}: {e}")

# SET TO False TO ACTUALLY BOOK CLASSES
DRY_RUN = os.getenv('DRY_RUN', 'False').lower() == 'true'

def get_israel_time():
    """Returns the current time in Israel (UTC+2 or UTC+3 depending on DST)"""
    now_utc = datetime.now(timezone.utc)
    month = now_utc.month
    day = now_utc.day
    # Israel DST: Friday before the last Sunday in March to the last Sunday in October
    if 3 < month < 10:
        is_dst = True
    elif month == 3:
        is_dst = (day >= 23)
    elif month == 10:
        is_dst = (day < 25)
    else:
        is_dst = False
    offset = 3 if is_dst else 2
    return now_utc + timedelta(hours=offset)

def send_ntfy(title, message, priority="default", tags=""):
    """Send push notification via ntfy.sh"""
    # Allowed notification window: 8:00 PM (20:00) to 9:30 PM (21:30) Israel Time
    isr_now = get_israel_time()
    isr_minutes = isr_now.hour * 60 + isr_now.minute
    if not (1200 <= isr_minutes <= 1290):
        logger.info(f"Skipping ntfy notification (outside allowed window 20:00 - 21:30 Israel Time): {title}")
        return False

    logger.info(f"Sending ntfy notification: {title}")
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
        logger.error(f"Failed to send ntfy: {e}")
        return False

def wait_for_precision_window(target_hour_utc=18, target_minute_utc=0, expected_wake_hour_utc=13, expected_wake_minute_utc=47, pre_notify_msg=None):
    """
    If the script starts early, it will wait until exactly the target time.
    Sends a status update at 20:59 (1 minute before launch).
    """
    now_utc = datetime.now(timezone.utc)
    target_time = now_utc.replace(hour=target_hour_utc, minute=target_minute_utc, second=0, microsecond=0)
    
    # Calculate the expected wake-up time to report delays
    expected_wake = now_utc.replace(hour=expected_wake_hour_utc, minute=expected_wake_minute_utc, second=0, microsecond=0)
    if now_utc < expected_wake:
        expected_wake -= timedelta(days=1)
    delay_delta = now_utc - expected_wake
    delay_mins = int(delay_delta.total_seconds() / 60)
    
    # Only wait if we are within the window
    if (target_time - now_utc).total_seconds() > 18000 or (target_time - now_utc).total_seconds() < 0:
        logger.info(f"Skipping wait: Not in the precision window. Current UTC: {now_utc.strftime('%H:%M:%S')}")
        return

    logger.info("--- PRECISION COUNTDOWN ENGAGED ---")
    logger.info(f"Target Time: {target_time.strftime('%H:%M:%S')} UTC (21:00:00 Israel)")
    
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
            logger.info("[20:59] Sending T-minus 1 minute status update...")
            send_ntfy(
                title="T-minus 1 Minute",
                message=f"Targeting: {pre_notify_msg or 'No specific target found.'}",
                priority="high"
            )
            has_sent_pre_notification = True

        if remaining <= 0:
            logger.info(f"BEEP BEEP BEEP! 21:00:00 REACHED! GO GO GO! (Actual: {now.strftime('%H:%M:%S.%f')})")
            break
            
        if remaining > 1:
            # We print a periodic progress update for terminal logs
            print(f"T-minus {int(remaining)} seconds...", end='\r')
            time.sleep(0.5)
        elif sys.platform == "win32" and remaining < 0.1:
            # Under Windows, when very close to trigger (< 100ms), use busy-wait for sub-millisecond accuracy
            # due to standard Windows scheduler timer resolution limitations (15.6ms)
            while (target_time - datetime.now(timezone.utc)).total_seconds() > 0:
                pass
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
        logger.info(f"[DRY RUN] Would book class with Schedule ID: {schedule_id}")
        return True, "Dry run success"

    # Rapid-fire retry loop for peak-load connection drops
    for attempt in range(1, 6):
        try:
            resp = session.post(url, json=payload, timeout=10)
            
            # Safely parse JSON without raising a fatal exception
            try:
                resp_json = resp.json()
            except ValueError:
                resp_json = {}
            
            # Check for success or already registered
            is_already_in = "alreadyRegistered" in str(resp_json) or "alreadyRegistered" in resp.text
            
            if resp.status_code == 200 or is_already_in:
                status = "Confirmed" if resp.status_code == 200 else "Already Registered"
                msg = f"Successfully secured spot! ({status}) - Attempt {attempt}"
                logger.info(msg)
                return True, msg
            else:
                # Sanitize response dump
                clean_resp_text = resp.text[:200] + "..." if len(resp.text) > 200 else resp.text
                msg = f"Failed to book: {resp.status_code} {clean_resp_text}"
                logger.error(msg)
                # If it's a specific "full" error or client error (4xx except 429), stop retrying
                if "full" in msg.lower() or "limit" in msg.lower() or (400 <= resp.status_code < 500 and resp.status_code != 429):
                    return False, msg
                
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            logger.warning(f"Attempt {attempt} failed (Connection/Timeout Error): {e}")
            if attempt == 5:
                msg = f"Error during booking after 5 attempts: {e}"
                logger.error(msg)
                return False, msg
            # Exponential backoff with random jitter
            sleep_time = (0.1 * (2 ** (attempt - 1))) + random.uniform(0.01, 0.05)
            logger.info(f"Retrying in {sleep_time:.3f} seconds...")
            time.sleep(sleep_time)
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed with unexpected error: {e}")
            if attempt == 5:
                msg = f"Error during booking after 5 attempts: {e}"
                logger.error(msg)
                return False, msg
            sleep_time = (0.1 * (2 ** (attempt - 1))) + random.uniform(0.01, 0.05)
            logger.info(f"Retrying in {sleep_time:.3f} seconds...")
            time.sleep(sleep_time)
    
    return False, "Max retries reached"

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
            padding: 24px;
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
            font-size: 18px;
        }}
        .status-success {{ background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }}
        .status-failure {{ background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 16px;
            text-align: left;
            border-bottom: 1px solid var(--table-border);
        }}
        th {{
            color: #64748b;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        tr.target {{ background-color: var(--target-row); }}
        .badge {{
            padding: 8px 16px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 600;
        }}
        .booked {{ background: #22c55e; color: white; }}
        .missed {{ background: #ef4444; color: white; }}
    </style>
</head>
<body>
    <div class="container">
        <h2 style="text-align:center; margin-top:0; font-size:24px; font-weight:700;">Gorillot Booking Report</h2>
        {status_html}
        <p style="text-align:center; font-size:18px; font-weight:500; color:#64748b;">Schedule for {date_range_str}</p>
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
        logger.error("Please ensure ARBOX_EMAIL and ARBOX_PASSWORD are set in the .env file.")
        sys.exit(1)

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
    
    # 1. Load cached token or login if missing/invalid
    login_url = 'https://apiappv2.arboxapp.com/api/v2/user/siteLogin'
    session_cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'session.json')
    token = None

    if os.path.exists(session_cache_path):
        try:
            with open(session_cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                token = cache_data.get('token')
                if token:
                    logger.info("Found cached session token.")
        except Exception as e:
            logger.warning(f"Could not load cached session token: {e}")

    parts = EMAIL.split("@")
    masked_email = f"{parts[0][0]}***{parts[0][-1]}@{parts[1]}" if len(parts[0]) > 1 else EMAIL

    if token:
        session.headers.update({'accesstoken': token})
    else:
        logger.info("No cached session token found. Initiating fresh login...")
        try:
            resp = session.post(login_url, json={"email": EMAIL, "password": PASSWORD, "phone": ""}, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("data", resp.json())
            token = data.get("token") or resp.headers.get("token")
            if not token:
                logger.error("Login failed, no token returned.")
                sys.exit(1)
            session.headers.update({'accesstoken': token})
            # Save token to cache
            with open(session_cache_path, 'w', encoding='utf-8') as f:
                json.dump({'token': token, 'created_at': datetime.now(timezone.utc).isoformat()}, f)
            logger.info(f"Logged in fresh as {masked_email} and cached token.")
        except Exception as e:
            logger.exception(f"Login error: {e}")
            sys.exit(1)

    # 2. Fetch schedule for tomorrow immediately to find the target ID
    today = datetime.now()
    tomorrow_obj = today + timedelta(days=1)
    tomorrow = tomorrow_obj.strftime("%Y-%m-%d")
    tomorrow_day = tomorrow_obj.strftime("%A")
    
    day_config = DATE_OVERRIDES.get(tomorrow, TARGET_CONFIG.get(tomorrow_day))
    
    target_class_id = None
    target_summary = "Searching..."
    target_summary_with_spots = "Searching..."
    is_already_booked = False
    
    logger.info(f"Pre-scanning schedule for {tomorrow}...")
    schedule_url = 'https://apiappv2.arboxapp.com/api/v2/site/schedule/betweenDates'
    payload = {"from": tomorrow, "to": tomorrow, "locations_box_id": int(LOCATION_ID)}
    
    try:
        resp = session.post(schedule_url, json=payload, timeout=10)
        # Intercept 401/403 errors for token refresh logic
        if resp.status_code in (401, 403):
            logger.info("Cached token expired/invalid. Re-authenticating...")
            resp_login = session.post(login_url, json={"email": EMAIL, "password": PASSWORD, "phone": ""}, timeout=10)
            resp_login.raise_for_status()
            data = resp_login.json().get("data", resp_login.json())
            token = data.get("token") or resp_login.headers.get("token")
            if token:
                session.headers.update({'accesstoken': token})
                with open(session_cache_path, 'w', encoding='utf-8') as f:
                    json.dump({'token': token, 'created_at': datetime.now(timezone.utc).isoformat()}, f)
                logger.info("Fresh token cached successfully. Retrying pre-scan...")
                resp = session.post(schedule_url, json=payload, timeout=10)
        resp.raise_for_status()
        events = resp.json().get("data", [])
        
        if day_config:
            target_time = day_config['time']
            target_coach = day_config['coach']
            target_type = day_config.get('type')
            
            target_info_list = [entry for entry in events if entry.get('time') == target_time]
            
            # Match by training type if specified (e.g., "WOD")
            if target_type:
                def matches_training_type(entry_item):
                    cat_name = ((entry_item.get('box_categories') or {}).get('name') or '').strip().lower()
                    if cat_name:
                        return target_type.lower() in cat_name
                    ser_name = ((entry_item.get('series') or {}).get('series_name') or '').strip().lower()
                    return target_type.lower() in ser_name

                target_info_list = [entry for entry in target_info_list if matches_training_type(entry)]
            
            # Match by coach name if specified (supports "not Coach Name" syntax and fallback)
            ALWAYS_EXCLUDE_COACH = "דניאל טנג'י"
            target_entry = None
            
            def get_coach_full_name(entry_obj):
                c_data = entry_obj.get('coach') or {}
                if isinstance(c_data, dict):
                    return (c_data.get('full_name') or c_data.get('name') or f"{c_data.get('first_name', '')} {c_data.get('last_name', '')}").strip()
                elif isinstance(c_data, str):
                    return c_data.strip()
                return ''

            if target_coach:
                if target_coach.lower().startswith('not '):
                    exclude_coach = target_coach[4:].strip().lower()
                    for entry in target_info_list:
                        coach_name = get_coach_full_name(entry)
                        if exclude_coach not in coach_name.lower():
                            target_entry = entry
                            break
                else:
                    # First try to find exact preferred coach
                    for entry in target_info_list:
                        coach_name = get_coach_full_name(entry)
                        if target_coach.lower() in coach_name.lower():
                            target_entry = entry
                            break
                    # Fallback: if preferred coach not found, choose any class NOT coached by דניאל טנג'י
                    if not target_entry:
                        for entry in target_info_list:
                            coach_name = get_coach_full_name(entry)
                            if ALWAYS_EXCLUDE_COACH.lower() not in coach_name.lower():
                                target_entry = entry
                                break
            else:
                # No specific coach requested: choose any class NOT coached by דניאל טנג'י
                for entry in target_info_list:
                    coach_name = get_coach_full_name(entry)
                    if ALWAYS_EXCLUDE_COACH.lower() not in coach_name.lower():
                        target_entry = entry
                        break
            
            if target_entry:
                target_class_id = target_entry.get('id')
                training_name = target_entry.get('box_categories', {}).get('name') or 'Class'
                coach_name = target_entry.get('coach', {}).get('name', 'Unknown')
                
                # Check registration status
                is_already_booked = target_entry.get('is_user_signed_to_schedule', False)
                spots_max = target_entry.get('max_participants', 0)
                spots_booked = target_entry.get('num_signed_to_schedule', 0)
                spots_free = spots_max - spots_booked
                
                target_summary = f"{tomorrow_day} {tomorrow} at {target_time} (Coach: {coach_name})"
                target_summary_with_spots = f"{target_summary}\nSpots: {spots_free}/{spots_max}"
                logger.info(f"TARGET ACQUIRED: {target_summary_with_spots}")
                
                if is_already_booked:
                    logger.info("Target class is ALREADY BOOKED for this user.")
            else:
                target_summary_with_spots = f"No class found at {target_time} for {tomorrow_day}."
                logger.warning(f"WARNING: {target_summary_with_spots}")
    except Exception as e:
        logger.exception(f"Pre-scan error: {e}")
        sys.exit(1)

    # If no target class was identified, we have nothing to book. Exit early to avoid billing waste.
    if not target_class_id:
        logger.warning("No target class found matching the configuration for tomorrow. Exiting immediately.")
        sys.exit(0)

    # 3. Start Precision Timer with target info for the 20:59 notification
    if not is_already_booked:
        wait_for_precision_window(pre_notify_msg=target_summary_with_spots)
    else:
        logger.info("Class is already booked! Skipping precision wait.")

    # Re-authenticate if we had a precision wait to ensure the token has not expired
    if not is_already_booked and target_class_id:
        logger.info("Refreshing authentication token prior to booking execution...")
        try:
            resp = session.post(login_url, json={"email": EMAIL, "password": PASSWORD, "phone": ""}, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("data", resp.json())
            token = data.get("token") or resp.headers.get("token")
            if token:
                session.headers.update({'accesstoken': token})
                logger.info("Token refreshed successfully.")
            else:
                logger.warning("Token refresh failed. Proceeding with existing session.")
        except Exception as e:
            logger.warning(f"Token refresh error: {e}. Proceeding with existing session.")

    # 4. EXECUTION (Fire immediately at 21:00:00)
    classes_info = []
    booking_summaries = []
    
    if target_class_id:
        if is_already_booked:
            success = True
            log_msg = "Successfully secured spot! (Already Registered)"
        else:
            success, log_msg = book_class(session, target_class_id)
        # Clean the log message of any success/fail emojis
        clean_log_msg = log_msg.replace("✅", "").replace("❌", "").strip()
        booking_summaries.append(f"{target_summary}: {clean_log_msg}")
        
        # We still fetch the full list for the final report table
        try:
            resp = session.post(schedule_url, json=payload, timeout=10)
            resp.raise_for_status()
            events = resp.json().get("data", [])
        except Exception as e:
            logger.warning(f"Could not fetch updated schedule for HTML report ({e}). Using pre-scan events.")
        
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
        logger.warning("No target ID found. Skipping booking attempt.")

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
