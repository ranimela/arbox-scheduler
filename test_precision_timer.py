import os
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Arbox/SMTP credentials
EMAIL = os.getenv('ARBOX_EMAIL')
SMTP_USER = os.getenv('SMTP_USER', EMAIL)
SMTP_PASS = os.getenv('SMTP_PASS')
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

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
        print(f"Test Email notification sent to {EMAIL}.")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def wait_for_precision_window(target_hour_utc, target_minute_utc):
    """
    Precision timer to hit exactly target_hour:target_minute:00 UTC.
    """
    now_utc = datetime.now(timezone.utc)
    target_time = now_utc.replace(hour=target_hour_utc, minute=target_minute_utc, second=0, microsecond=0)
    
    # If target is in the past, don't wait (immediate execution)
    if (target_time - now_utc).total_seconds() < 0:
        print(f"Target {target_time.strftime('%H:%M:%S')} is in the past. Firing immediately.")
        return

    print(f"--- PRECISION TEST ENGAGED ---")
    print(f"Target Time: {target_time.strftime('%H:%M:%S')} UTC")
    
    while True:
        now = datetime.now(timezone.utc)
        remaining = (target_time - now).total_seconds()
        
        if remaining <= 0:
            print(f"BEEP BEEP BEEP! target REACHED! (Actual: {now.strftime('%H:%M:%S.%f')} UTC)")
            break
            
        if remaining > 1:
            print(f"T-minus {int(remaining)} seconds...", end='\r')
            time.sleep(0.5)
        else:
            # High-frequency polling for the last second
            time.sleep(0.01)

if __name__ == "__main__":
    # Test target set for 08:45:00 UTC (11:45:00 AM Israel Time)
    target_h = 8
    target_m = 45
    
    print(f"Script started. Waiting for {target_h:02}:{target_m:02}:00 UTC...")
    wait_for_precision_window(target_h, target_m)
    
    subject = "Arbox Agent: Precision Timing Test"
    body = f"This email was fired at exactly {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC.\nIf you received this within seconds of 11:45:00 AM, the precision timer is working!"
    send_email(subject, body)
