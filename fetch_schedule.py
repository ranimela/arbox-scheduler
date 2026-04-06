import os
import json
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
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

# TARGET SLOTS (Edit these or use GitHub Variables to change your schedule)
TARGET_DAYS = os.getenv('TARGET_DAYS', 'Sunday,Tuesday,Thursday,Friday').split(',')
TARGET_HOUR = os.getenv('TARGET_HOUR', '08:00')

# SET TO False TO ACTUALLY BOOK CLASSES
DRY_RUN = False

def send_email(subject, body):
    if not SMTP_PASS:
        print("Skipping email: SMTP_PASS not set.")
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
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
        if resp.status_code == 200:
            msg = f"Successfully booked class {schedule_id}!"
            print(msg)
            return True, msg
        else:
            msg = f"Failed to book class {schedule_id}: {resp.status_code} {resp.text}"
            print(msg)
            return False, msg
    except Exception as e:
        msg = f"Error during booking: {e}"
        print(msg)
        return False, msg

def generate_html_table(classes_info, date_range_str):
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Schedule for {date_range_str}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #0f172a;
            --text-color: #f8fafc;
            --card-bg: rgba(30, 41, 59, 0.7);
            --accent: #3b82f6;
            --accent-hover: #60a5fa;
            --table-border: #334155;
            --row-hover: rgba(59, 130, 246, 0.1);
            --target-row: rgba(34, 197, 94, 0.15);
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
            color: var(--text-color);
            min-height: 100vh;
            margin: 0;
            padding: 2rem;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        .container {{
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 2rem;
            width: 100%;
            max-width: 900px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }}
        h1 {{
            margin-top: 0;
            text-align: center;
            color: var(--accent-hover);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 1.5rem;
        }}
        th, td {{
            padding: 1rem;
            text-align: left;
            border-bottom: 1px solid var(--table-border);
        }}
        tr.target {{
            background-color: var(--target-row);
        }}
        .badge {{
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: 500;
        }}
        .booked {{ background: #16a34a; color: white; }}
        .open {{ background: #3b82f6; color: white; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Gorillot Agent - Schedule Report</h1>
        <p style="text-align:center">Looking for: {", ".join(TARGET_DAYS)} at {TARGET_HOUR}</p>
        <table>
            <thead>
                <tr>
                    <th>Day</th>
                    <th>Date</th>
                    <th>Hour</th>
                    <th>Training</th>
                    <th>Coach</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
"""
    for cls in classes_info:
        is_target = cls['day'] in TARGET_DAYS and cls['hour'] == TARGET_HOUR
        row_class = "target" if is_target else ""
        status_badge = '<span class="badge booked">Booked!</span>' if cls.get('was_booked') else '<span class="badge open">Available</span>'
        
        html_content += f"""
                <tr class="{row_class}">
                    <td>{cls['day']}</td>
                    <td>{cls['date']}</td>
                    <td>{cls['hour']}</td>
                    <td>{cls['training']}</td>
                    <td>{cls['coach']}</td>
                    <td>{status_badge if is_target else ''}</td>
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
    tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"Checking schedule for tomorrow ({tomorrow})...")
    schedule_url = 'https://apiappv2.arboxapp.com/api/v2/site/schedule/betweenDates'
    payload = {"from": tomorrow, "to": tomorrow, "locations_box_id": int(LOCATION_ID)}
    
    resp = session.post(schedule_url, json=payload)
    events = resp.json().get("data", [])
    
    classes_info = []
    booking_summaries = []
    
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
            
            class_data = {
                'day': day_name,
                'date': dt_str,
                'hour': hour,
                'training': training,
                'coach': coach,
                'id': schedule_id,
                'was_booked': False
            }

            # 3. Target Matching & Booking
            if day_name in TARGET_DAYS and hour == TARGET_HOUR:
                msg_start = f"TARGET MATCH FOUND: {day_name} at {hour}"
                print(msg_start)
                
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
    generate_html_table(classes_info, tomorrow)
    
    if booking_summaries:
        subject = f"Arbox Agent Status: Successful Target Match"
        body = "Arbox Gym Booking Report\n\n" + "\n".join(booking_summaries)
        send_email(subject, body)
    else:
        print(f"No target classes found for {tomorrow} to book.")
        # Update user even if no target classes found
        subject = f"Arbox Agent Status: No sessions found for {tomorrow}"
        body = f"Checked the schedule for tomorrow ({tomorrow}).\nNo 8:00 AM slots found for the target days: {', '.join(TARGET_DAYS)}."
        send_email(subject, body)

if __name__ == '__main__':
    main()
