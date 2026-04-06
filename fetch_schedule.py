import os
import json
import requests
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

IDENTIFIER = "f1UhUDad1588686203"

# TARGET SLOTS
TARGET_DAYS = ['Sunday', 'Tuesday', 'Thursday', 'Friday']
TARGET_HOUR = '08:00'

# SET TO False TO ACTUALLY BOOK CLASSES
DRY_RUN = False

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
        return True

    try:
        resp = session.post(url, json=payload)
        if resp.status_code == 200:
            print(f"Successfully booked class {schedule_id}!")
            return True
        else:
            print(f"Failed to book class {schedule_id}: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"Error during booking: {e}")
        return False

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

    # 2. Fetch schedule for next 8 days
    today = datetime.now()
    tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    next_week = (today + timedelta(days=8)).strftime("%Y-%m-%d")
    
    print(f"Checking schedule from {tomorrow} to {next_week}...")
    schedule_url = 'https://apiappv2.arboxapp.com/api/v2/site/schedule/betweenDates'
    payload = {"from": tomorrow, "to": next_week, "locations_box_id": int(LOCATION_ID)}
    
    resp = session.post(schedule_url, json=payload)
    events = resp.json().get("data", [])
    
    classes_info = []
    
    for entry in events:
        dt_obj = datetime.strptime(entry.get('date'), "%Y-%m-%d")
        day_name = dt_obj.strftime("%A")
        hour = entry.get('time', '')
        training = entry.get('box_categories', {}).get('name', 'WOD')
        coach = entry.get('coach', {}).get('full_name', 'Unknown')
        schedule_id = entry.get('id')
        
        class_data = {
            'day': day_name,
            'date': entry.get('date'),
            'hour': hour,
            'training': training,
            'coach': coach,
            'id': schedule_id,
            'was_booked': False
        }

        # 3. Target Matching & Booking
        if day_name in TARGET_DAYS and hour == TARGET_HOUR:
            print(f"FOUND TARGET CLASS: {day_name} at {hour} (ID: {schedule_id})")
            
            # Check if already booked (user_signed_up or similar if available, otherwise just try)
            # In V2, we just try to book; if already booked, Arbox returns an error we skip.
            success = book_class(session, schedule_id)
            class_data['was_booked'] = success

        classes_info.append(class_data)

    # Output results
    classes_info.sort(key=lambda x: (x['date'], x['hour']))
    generate_html_table(classes_info, f"{tomorrow} to {next_week}")
    print(f"Found {len(classes_info)} classes. Agent report generated.")

if __name__ == '__main__':
    main()
