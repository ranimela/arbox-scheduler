import os
import json
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

GYM_ID = os.getenv('ARBOX_BOX_ID', '80')
LOCATION_ID = os.getenv('ARBOX_LOCATION_ID', '70')
EMAIL = os.getenv('ARBOX_EMAIL')
PASSWORD = os.getenv('ARBOX_PASSWORD')
USER_ID = os.getenv('ARBOX_USER_ID')
MEMBERSHIP_USER_ID = os.getenv('ARBOX_MEMBERSHIP_USER_ID', '12165397')

# SMTP Settings
SMTP_USER = os.getenv('SMTP_USER', EMAIL)
SMTP_PASS = os.getenv('SMTP_PASS') # 16-char App Password
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

IDENTIFIER = "f1UhUDad1588686203"

# TARGET CONFIGURATION (Custom Per-Day Schedule)
TARGET_CONFIG = {
    'Sunday':   {'time': '08:30', 'coach': 'בר טנג\'י'},
    'Tuesday':  {'time': '18:30', 'coach': ''}, 
    'Thursday': {'time': '08:30', 'coach': 'שיראל ריצמן'},
    'Friday':   {'time': '08:30', 'coach': 'דניאל טנג\'י'}
}

# ONE-TIME OVERRIDES (Date-specific exceptions)
DATE_OVERRIDES = {
    "2026-04-21": {"time": "08:30", "coach": "רוני שחם"}
}

# SET TO False TO ACTUALLY BOOK CLASSES
DRY_RUN = False

def send_email(subject, body, html=None):
    if not SMTP_PASS:
        print("Skipping email: SMTP_PASS not set.")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        if html:
            msg.attach(MIMEText(html, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        print(f"Email notification sent to {EMAIL}.")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def wait_for_precision_window(target_hour_utc=18, target_minute_utc=0, expected_wake_hour_utc=16, expected_wake_minute_utc=0):
    """
    If the script starts early, it will wait until exactly the target time.
    """
    now_utc = datetime.now(timezone.utc)
    target_time = now_utc.replace(hour=target_hour_utc, minute=target_minute_utc, second=0, microsecond=0)
    
    # Calculate the expected wake-up time to report delays
    expected_wake = now_utc.replace(hour=expected_wake_hour_utc, minute=expected_wake_minute_utc, second=0, microsecond=0)
    delay_delta = now_utc - expected_wake
    delay_mins = int(delay_delta.total_seconds() / 60)
    
    # Only wait if we are within 150 minutes of the target
    if (target_time - now_utc).total_seconds() > 9000 or (target_time - now_utc).total_seconds() < 0:
        print(f"Skipping wait: Not in the precision window. Current UTC: {now_utc.strftime('%H:%M:%S')}")
        return

    print(f"--- PRECISION COUNTDOWN ENGAGED ---")
    print(f"Target Time: {target_time.strftime('%H:%M:%S')} UTC (21:00:00 Israel)")
    
    # Notify the user that the agent is up and waiting
    status_label = "READY FOR LAUNCH 🚀"
    if delay_mins > 5:
        status_label += f" (Delayed {delay_mins}m)"
        
    send_email(
        subject=f"Arbox Agent: {status_label}",
        body=f"The agent has arrived at the starting line and is standing by.\n\n"
             f"Expected Wake-up: {expected_wake.strftime('%H:%M:%S')} UTC (19:00:00 Israel)\n"
             f"Actual Wake-up:   {now_utc.strftime('%H:%M:%S')} UTC ({ (now_utc + timedelta(hours=3)).strftime('%H:%M:%S') } Israel)\n"
             f"GitHub Delay:     {delay_mins} minutes\n\n"
             f"Target Launch:    {target_time.strftime('%H:%M:%S')} UTC (21:00:00 Israel)\n\n"
             f"The registration will fire exactly at the top of the hour."
    )
    
    while True:
        now = datetime.now(timezone.utc)
        remaining = (target_time - now).total_seconds()
        
        if remaining <= 0:
            print(f"BEEP BEEP BEEP! 21:00:00 REACHED! GO GO GO! (Actual: {now.strftime('%H:%M:%S.%f')})")
            break
            
        if remaining > 1:
            print(f"T-minus {int(remaining)} seconds...", end='\r')
            time.sleep(0.5)
        else:
            time.sleep(0.01)

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
            status = "CONFIRMED" if resp.status_code == 200 else "ALREADY REGISTERED"
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
        day_config = TARGET_CONFIG.get(cls['day'])
        is_target = day_config and cls['hour'] == day_config['time']
        
        row_class = "target" if is_target else ""
        
        # Determine status text and badge
        if is_target:
            if cls.get('was_booked'):
                status_badge = '<span class="badge booked">SECURED</span>'
            elif cls.get('best_match'):
                status_badge = '<span class="badge missed" style="background:#ef4444">MISSED</span>'
            else:
                status_badge = '<span class="badge open" style="opacity: 0.5;">-</span>'
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

    # 1. Start Precision Timer (Wait for registration window opening)
    wait_for_precision_window()

    session = requests.Session()
    session.headers.update(base_headers)
    
    # 1. Login
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

    # 2. Fetch schedule for tomorrow ONLY
    today = datetime.now()
    tomorrow_obj = today + timedelta(days=1)
    tomorrow = tomorrow_obj.strftime("%Y-%m-%d")
    tomorrow_day = tomorrow_obj.strftime("%A")
    
    # 2. Check for overrides or use the regular day config
    day_config = DATE_OVERRIDES.get(tomorrow, TARGET_CONFIG.get(tomorrow_day))
    
    if tomorrow in DATE_OVERRIDES:
        print(f"!!! DATE OVERRIDE DETECTED FOR {tomorrow}: Using time {day_config['time']} with coach {day_config['coach']}")
    
    print(f"Checking schedule for tomorrow ({tomorrow}, {tomorrow_day})...")
    schedule_url = 'https://apiappv2.arboxapp.com/api/v2/site/schedule/betweenDates'
    payload = {"from": tomorrow, "to": tomorrow, "locations_box_id": int(LOCATION_ID)}
    
    resp = session.post(schedule_url, json=payload)
    events = resp.json().get("data", [])
    
    classes_info = []
    booking_summaries = []
    
    # 3. Identify the best match based on config
    best_match_id = None
    if day_config:
        target_time = day_config['time']
        preferred_coach = day_config['coach']
        
        matches = [e for e in events if e.get('time') == target_time]
        
        if matches:
            # If multiple matches, prioritize the coach
            best_match = None
            if preferred_coach:
                for m in matches:
                    coach_dict = m.get('coach') or {}
                    full_name = coach_dict.get('full_name', '')
                    if preferred_coach in full_name:
                        best_match = m
                        break
            
            # If no coach match found or no preference, take the first one
            if not best_match:
                best_match = matches[0]
                
            best_match_id = best_match.get('id')
            print(f"BEST MATCH FOUND: {tomorrow_day} at {target_time} with {best_match.get('coach', {}).get('full_name', 'Unknown')}")

    for entry in events:
        try:
            dt_str = entry.get('date')
            if not dt_str:
                continue
            dt_obj = datetime.strptime(dt_str, "%Y-%m-%d")
            day_name = dt_obj.strftime("%A")
            hour = entry.get('time', '')
            
            # Safe extraction of training name
            box_cats = entry.get('box_categories') or {}
            series_dict = entry.get('series') or {}
            training = box_cats.get('name') or series_dict.get('series_name') or 'WOD'
            
            # Safe extraction of coach name
            coach_dict = entry.get('coach') or {}
            coach = coach_dict.get('full_name') or f"{coach_dict.get('first_name', '')} {coach_dict.get('last_name', '')}".strip()
            if not coach:
                coach = "Unknown"
            
            schedule_id = entry.get('id')
            is_best_match = (schedule_id == best_match_id)
            
            class_data = {
                'day': day_name,
                'date': dt_str,
                'hour': hour,
                'training': training,
                'coach': coach,
                'id': schedule_id,
                'was_booked': False,
                'best_match': is_best_match
            }

            # 4. Attempt Booking if it's the best match
            if is_best_match:
                success, log_msg = book_class(session, schedule_id)
                class_data['was_booked'] = success
                
                status_icon = "✅" if success else "❌"
                booking_summaries.append(f"{status_icon} {day_name} {dt_str} {hour}: {log_msg}")

            classes_info.append(class_data)
        except Exception as e:
            print(f"Skipping a class entry due to processing error: {e}")
            continue

    # 4. Final Processing & Email Report
    classes_info.sort(key=lambda x: (x['date'], x['hour']))
    
    # Determine overall success
    any_target = (day_config is not None)
    all_targets_booked = any(cls['was_booked'] for cls in classes_info if cls['best_match'])
    
    if any_target:
        if all_targets_booked:
            status_html = '<div class="status-header status-success">✅ MISSION SUCCESS: Booking Secured</div>'
            subject = "✅ SUCCESS: Arbox Booking Confirmed"
        else:
            status_html = '<div class="status-header status-failure">⚠️ PARTIAL SUCCESS or FAILURE: Please Check</div>'
            subject = "⚠️ ALERT: Arbox Booking Issue"
    else:
        status_html = '<div class="status-header" style="background: rgba(148, 163, 184, 0.1); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.2)">INFO: No Target Sessions Found Today</div>'
        subject = "ℹ️ INFO: No target sessions tomorrow"

    generate_html_table(classes_info, tomorrow, status_html)
    
    # Send the email with the HTML report
    with open('schedule.html', 'r', encoding='utf-8') as f:
        html_body = f.read()
        
    summary_text = "\n".join(booking_summaries) if booking_summaries else f"No target slots found for {tomorrow}."
        
    send_email(subject, summary_text, html=html_body)

if __name__ == '__main__':
    main()
