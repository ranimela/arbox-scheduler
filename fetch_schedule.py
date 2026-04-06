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

IDENTIFIER = "f1UhUDad1588686203"

def generate_html_table(classes_info, tomorrow):
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Schedule for {tomorrow}</title>
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
            max-width: 800px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            animation: fadeIn 0.5s ease-out;
        }}
        h1 {{
            margin-top: 0;
            font-weight: 600;
            font-size: 1.5rem;
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
        th {{
            font-weight: 500;
            color: #94a3b8;
            text-transform: uppercase;
            font-size: 0.875rem;
            letter-spacing: 0.05em;
        }}
        tr {{
            transition: all 0.2s ease;
        }}
        tr:hover {{
            background-color: var(--row-hover);
            transform: translateX(4px);
        }}
        td {{
            font-size: 1rem;
        }}
        .training-badge {{
            background: rgba(59, 130, 246, 0.2);
            color: #93c5fd;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            font-weight: 500;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Gorillot Schedule - {tomorrow}</h1>
        <table>
            <thead>
                <tr>
                    <th>Coach</th>
                    <th>Training</th>
                    <th>Hour</th>
                </tr>
            </thead>
            <tbody>
"""
            
    for cls in classes_info:
        html_content += f"""
                <tr>
                    <td>{cls['coach']}</td>
                    <td><span class="training-badge">{cls['training']}</span></td>
                    <td>{cls['hour']}</td>
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
    print("Beautiful HTML schedule generated at 'schedule.html'")

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
    
    login_url = 'https://apiappv2.arboxapp.com/api/v2/user/siteLogin'
    creds = {"email": EMAIL, "password": PASSWORD, "phone": ""}
    
    try:
        resp = session.post(login_url, json=creds)
    except Exception as e:
        print(f"Error connecting: {e}")
        return

    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code} {resp.text}")
        return

    resp_json = resp.json()
    data = resp_json.get("data", resp_json)
    token = data.get("token") or resp.headers.get("token")

    if token:
        session.headers.update({'accesstoken': token})

    tomorrow_dt = datetime.now() + timedelta(days=1)
    tomorrow = tomorrow_dt.strftime("%Y-%m-%d")
    
    schedule_url = 'https://apiappv2.arboxapp.com/api/v2/site/schedule/betweenDates'
    schedule_payload = {
        "from": tomorrow,
        "to": tomorrow,
        "locations_box_id": int(LOCATION_ID) if LOCATION_ID.isdigit() else LOCATION_ID,
    }
    
    resp = session.post(schedule_url, json=schedule_payload)
    if resp.status_code != 200:
        print(f"Failed to fetch schedule: {resp.status_code}")
        return

    schedule_data = resp.json()
    events = schedule_data.get("data", schedule_data)
    
    classes_info = []

    def extract_info(class_entry):
        # Extract coach name
        coach_dict = class_entry.get('coach', {})
        coach_name = coach_dict.get('full_name') or f"{coach_dict.get('first_name', '')} {coach_dict.get('last_name', '')}".strip()
        if not coach_name:
            coach_name = "Unknown"
            
        # Extract training name
        box_cats = class_entry.get('box_categories', {})
        series = class_entry.get('series', {})
        
        training = box_cats.get('name') or series.get('series_name') or "Training"
        
        # Extract hour
        hour = class_entry.get('time', '')
        
        return {
            'coach': coach_name,
            'training': training,
            'hour': hour
        }

    if isinstance(events, list):
        for class_entry in events:
            classes_info.append(extract_info(class_entry))
    elif isinstance(events, dict):
        for location_name, days in events.items():
            if str(LOCATION_ID) in str(location_name) or True: 
                if not days or not isinstance(days, list):
                    continue
                classes_list = days[0] if isinstance(days[0], list) else days
                for class_entry in classes_list:
                    if isinstance(class_entry, dict):
                        classes_info.append(extract_info(class_entry))

    # Sort classes by hour
    classes_info.sort(key=lambda x: x['hour'])
    
    generate_html_table(classes_info, tomorrow)

if __name__ == '__main__':
    main()
