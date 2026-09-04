"""Automated Arbox scheduler and precision booking agent.

This module monitors, pre-scans, and automates high-precision class registrations
on the Arbox platform according to configured per-day schedules and date overrides.
"""

import html
import json
import logging
import os
from pathlib import Path
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("arbox_scheduler")

# Load environment variables from .env file
load_dotenv()

# Force UTF-8 for Windows terminal support
if sys.platform == "win32" and "pytest" not in sys.modules:
    import io

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

GYM_ID = os.getenv("ARBOX_BOX_ID", "80")
LOCATION_ID = os.getenv("ARBOX_LOCATION_ID", "70")
EMAIL = os.getenv("ARBOX_EMAIL")
PASSWORD = os.getenv("ARBOX_PASSWORD")
USER_ID = os.getenv("ARBOX_USER_ID")
MEMBERSHIP_USER_ID = os.getenv("ARBOX_MEMBERSHIP_USER_ID", "16582410")
if not MEMBERSHIP_USER_ID or str(MEMBERSHIP_USER_ID).strip() in (
    "12165397",
    "1588686203",
):
    MEMBERSHIP_USER_ID = "16582410"

# NTFY Settings
NTFY_TOPIC = os.getenv("ARBOX_NTFY_TOPIC") or "arbox-scheduler-ranimela"

IDENTIFIER = "f1UhUDad1588686203"

# Default TARGET CONFIGURATION (Custom Per-Day Schedule)
TARGET_CONFIG: dict[str, dict] = {
    "Sunday": {"time": "08:30", "type": "WOD", "series_id": 187541},
    "Tuesday": {"time": "18:30", "type": "WOD", "series_id": 3300},
    "Thursday": {"time": "08:30", "type": "WOD", "series_id": 187542},
    "Friday": {"time": "08:30", "type": "WOD", "series_id": 2498},
}
DATE_OVERRIDES: dict[str, dict] = {}

PROJECT_DIR = Path(__file__).resolve().parent

# Load Configuration from external config.json
config_path = PROJECT_DIR / "config.json"
if config_path.exists():
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            TARGET_CONFIG = config_data.get("TARGET_CONFIG") or TARGET_CONFIG
            DATE_OVERRIDES = config_data.get("DATE_OVERRIDES") or DATE_OVERRIDES
            logger.info("Loaded target configuration from config.json.")
    except Exception as e:
        logger.warning(
            f"Failed to load config.json ({e}). Using default configuration."
        )
else:
    logger.info("config.json not found. Using default configuration.")

# Purge stale report files at startup
for stale_name in ["schedule.html", "schedule_output.json"]:
    stale_file = PROJECT_DIR / stale_name
    if stale_file.exists():
        try:
            stale_file.unlink()
            logger.info(f"Purged stale execution report: {stale_name}")
        except Exception as e:
            logger.warning(f"Could not purge stale file {stale_name}: {e}")

# SET TO False TO ACTUALLY BOOK CLASSES
DRY_RUN = os.getenv("DRY_RUN", "False").lower() == "true"


def get_israel_time() -> datetime:
    """Returns the current time in Israel using the Asia/Jerusalem timezone.

    Returns:
        datetime: Current timezone-aware datetime in Asia/Jerusalem.
    """
    return datetime.now(ZoneInfo("Asia/Jerusalem"))


def send_ntfy(
    title: str, message: str, priority: str = "default", tags: str = ""
) -> bool:
    """Send push notification via ntfy.sh within allowed evening window.

    Args:
        title: Notification title.
        message: Notification body content.
        priority: Priority level ('low', 'default', 'high', 'urgent').
        tags: Comma-separated tag strings.

    Returns:
        bool: True if sent successfully, False otherwise.
    """
    # Allowed notification window: 8:00 PM (20:00) to 11:00 PM (23:00) Israel Time
    isr_now = get_israel_time()
    isr_minutes = isr_now.hour * 60 + isr_now.minute
    if not (1200 <= isr_minutes <= 1380):
        logger.info(
            f"Skipping ntfy notification (outside allowed window 20:00 - 23:00 Israel Time): {title}"
        )
        return False

    logger.info(f"Sending ntfy notification: {title}")
    try:
        headers = {
            "Title": title.encode("utf-8"),
            "Priority": priority,
            "Tags": tags,
        }
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10,
        ).raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to send ntfy: {e}")
        return False


def _is_truthy_flag(val: Any) -> bool:
    """Helper to determine if a value represents a truthy booking status flag.

    Args:
        val: Any field value from the Arbox API entry.

    Returns:
        bool: True if the value indicates a booked/signed-up status.
    """
    if val is None or val is False:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val > 0
    if isinstance(val, str):
        v = val.strip().lower()
        v_norm = v.replace("_", "").replace("-", "")
        if v in ("true", "1", "yes") or v_norm == "cancelscheduleuser":
            return True
        if v in ("false", "0", "no", "", "none", "null"):
            return False
        try:
            return float(v) > 0
        except ValueError:
            return False
    if isinstance(val, (dict, list, set, tuple)):
        return len(val) > 0
    return False


def is_user_booked_for_schedule(entry: dict | None) -> bool:
    """Checks if the user is already booked for the given schedule entry.

    Inspects Arbox registration flags including is_user_signed_to_schedule,
    user_booked, is_signed, cancelScheduleUser, num_user_signed, and booking_option.

    Args:
        entry: Schedule entry dictionary or None.

    Returns:
        bool: True if user is booked/signed up, False otherwise.
    """
    if not isinstance(entry, dict):
        return False

    # Check boolean/flag fields
    flag_fields = (
        "is_user_signed_to_schedule",
        "user_booked",
        "is_signed",
        "user_signed",
        "is_user_signed",
        "cancelScheduleUser",
        "cancel_schedule_user",
    )
    for field in flag_fields:
        if field in entry and _is_truthy_flag(entry.get(field)):
            return True

    # Check numeric signed count for user
    if "num_user_signed" in entry and _is_truthy_flag(entry.get("num_user_signed")):
        return True

    # Check booking_option (e.g. cancelScheduleUser, cancel_schedule_user)
    booking_option = str(entry.get("booking_option") or "").strip().lower()
    booking_option_norm = booking_option.replace("_", "").replace("-", "")
    return booking_option_norm == "cancelscheduleuser"


def extract_coach_name(entry: dict | None) -> str:
    """Extracts a normalized coach name string from a schedule entry dictionary.

    Args:
        entry: Schedule entry dictionary or None.

    Returns:
        str: Extracted coach full name, or empty string if unavailable.
    """
    if not isinstance(entry, dict):
        return ""
    coach_data = entry.get("coach")
    if isinstance(coach_data, dict):
        full_name = coach_data.get("full_name") or coach_data.get("name")
        if full_name and isinstance(full_name, str):
            return full_name.strip()
        first_name = coach_data.get("first_name") or ""
        last_name = coach_data.get("last_name") or ""
        return f"{first_name} {last_name}".strip()
    if isinstance(coach_data, str):
        return coach_data.strip()
    return ""


def extract_training_type(entry: dict | None) -> str:
    """Extracts the training category or series name from a schedule entry.

    Args:
        entry: Schedule entry dictionary or None.

    Returns:
        str: Identified training category name, or default 'WOD'.
    """
    if not isinstance(entry, dict):
        return "WOD"
    box_cats = entry.get("box_categories")
    if isinstance(box_cats, dict) and box_cats.get("name"):
        return str(box_cats["name"]).strip()
    if isinstance(box_cats, str) and box_cats.strip():
        return box_cats.strip()
    series_data = entry.get("series")
    if isinstance(series_data, dict) and series_data.get("series_name"):
        return str(series_data["series_name"]).strip()
    if isinstance(series_data, str) and series_data.strip():
        return series_data.strip()
    return "WOD"


def extract_spots(entry: dict | None) -> tuple[int, int, int]:
    """Safely extracts participant counts (free, booked, max) from a schedule entry.

    Args:
        entry: Schedule entry dictionary or None.

    Returns:
        tuple[int, int, int]: Tuple of (free_spots, booked_spots, max_spots).
    """
    if not isinstance(entry, dict):
        return 0, 0, 0
    try:
        max_p = int(entry.get("max_participants") or 0)
    except (ValueError, TypeError):
        max_p = 0
    try:
        booked_p = int(entry.get("num_signed_to_schedule") or 0)
    except (ValueError, TypeError):
        booked_p = 0
    free_p = max(0, max_p - booked_p)
    return free_p, booked_p, max_p


def wait_for_precision_window(
    target_hour_israel: int = 21,
    target_minute_israel: int = 0,
    expected_wake_hour_utc: int = 13,
    expected_wake_minute_utc: int = 47,
    pre_notify_msg: str | None = None,
) -> None:
    """If the script starts early, waits until exactly the target time in Israel.

    Sends a status update at 20:59 (1 minute before launch).

    Args:
        target_hour_israel: Target hour in Israel timezone (default: 21).
        target_minute_israel: Target minute in Israel timezone (default: 0).
        expected_wake_hour_utc: Expected runner wake hour in UTC (default: 13).
        expected_wake_minute_utc: Expected runner wake minute in UTC (default: 47).
        pre_notify_msg: Message preview for 1-minute pre-notification.
    """
    now_isr = get_israel_time()
    target_time_isr = now_isr.replace(
        hour=target_hour_israel,
        minute=target_minute_israel,
        second=0,
        microsecond=0,
    )

    # Calculate the expected wake-up time to report delays
    now_utc = datetime.now(timezone.utc)
    expected_wake = now_utc.replace(
        hour=expected_wake_hour_utc,
        minute=expected_wake_minute_utc,
        second=0,
        microsecond=0,
    )
    if now_utc < expected_wake:
        expected_wake -= timedelta(days=1)
    delay_delta = now_utc - expected_wake
    delay_mins = int(delay_delta.total_seconds() / 60)

    # Only wait if we are within the 5-hour window
    diff_sec = (target_time_isr - now_isr).total_seconds()
    if diff_sec > 18000 or diff_sec < 0:
        logger.info(
            f"Skipping wait: Not in the precision window. Current Israel Time: {now_isr.strftime('%H:%M:%S')}"
        )
        return

    target_time_utc = target_time_isr.astimezone(timezone.utc)
    logger.info("--- PRECISION COUNTDOWN ENGAGED ---")
    logger.info(
        f"Target Time: {target_time_isr.strftime('%H:%M:%S')} Israel Time ({target_time_utc.strftime('%H:%M:%S')} UTC)"
    )

    # Initial "I am here" notification
    send_ntfy(
        title="Arbox Agent Active",
        message=f"Standing by for 21:00:00 registration.\nExpected wake-up: {expected_wake.strftime('%H:%M')} UTC\nGitHub Delay: {delay_mins}m",
    )

    has_sent_pre_notification = False

    while True:
        now = get_israel_time()
        remaining = (target_time_isr - now).total_seconds()

        # 20:59 Notification (60 seconds before target)
        if 59 <= remaining <= 61 and not has_sent_pre_notification:
            logger.info("[20:59] Sending T-minus 1 minute status update...")
            send_ntfy(
                title="T-minus 1 Minute",
                message=f"Targeting: {pre_notify_msg or 'No specific target found.'}",
                priority="high",
            )
            has_sent_pre_notification = True

        if remaining <= 0:
            logger.info(
                f"BEEP BEEP BEEP! 21:00:00 REACHED! GO GO GO! (Actual: {now.strftime('%H:%M:%S.%f')})"
            )
            break

        if remaining > 1:
            # Periodic progress update for terminal logs
            print(f"T-minus {int(remaining)} seconds...", end="\r")
            time.sleep(0.5)
        elif remaining < 0.05:
            # Busy-wait for sub-millisecond accuracy when within 50ms of target
            while (target_time_isr - get_israel_time()).total_seconds() > 0:
                pass
        else:
            time.sleep(0.001)


def select_target_entry(
    target_info_list: list[dict],
    target_coach: str = "",
    target_time: str = "",
    target_series_id: int | str | None = None,
    always_exclude: str = "",
) -> dict | None:
    """Selects the target class entry. Prioritizes target_series_id above all else.

    Args:
        target_info_list: List of schedule entry dictionaries.
        target_coach: Target coach name or 'not <Coach>' filter.
        target_time: Preferred class start time string (e.g. '08:30').
        target_series_id: Specific series ID to prioritize.
        always_exclude: Coach name substring to always exclude.

    Returns:
        dict | None: The matching schedule entry dict, or None if no match.
    """
    if not target_info_list:
        return None

    valid_entries = [e for e in target_info_list if isinstance(e, dict)]
    if not valid_entries:
        return None

    # 1. Highest Priority: Match target_series_id directly regardless of coach name
    if target_series_id is not None:
        for entry in valid_entries:
            series_obj = entry.get("series")
            entry_series_id = (
                series_obj.get("id")
                if isinstance(series_obj, dict)
                else (entry.get("series_id") or entry.get("series_fk"))
            )
            if entry_series_id is not None and str(entry_series_id) == str(
                target_series_id
            ):
                return entry

    def score_entry(entry: dict) -> int:
        score = 0
        if entry.get("booking_option"):
            score += 20
        ser_name = extract_training_type(entry)
        if target_time and target_time in ser_name:
            score += 10
        free_spots = entry.get("free")
        if isinstance(free_spots, (int, float)) and free_spots > 0:
            score += 5
        return score

    sorted_list = sorted(valid_entries, key=score_entry, reverse=True)

    if target_coach:
        if target_coach.lower().startswith("not "):
            exclude_coach = target_coach[4:].strip().lower()
            if exclude_coach:
                for entry in sorted_list:
                    if exclude_coach not in extract_coach_name(entry).lower():
                        return entry
        else:
            coach_query = target_coach.strip().lower()
            if coach_query:
                for entry in sorted_list:
                    if coach_query in extract_coach_name(entry).lower():
                        return entry

    if always_exclude:
        exclude_val = always_exclude.strip().lower()
        if exclude_val:
            for entry in sorted_list:
                if exclude_val not in extract_coach_name(entry).lower():
                    return entry

    return sorted_list[0] if sorted_list else None


ALREADY_BOOKED_PATTERNS: tuple[str, ...] = (
    # English variations
    "alreadyregistered",
    "already_registered",
    "already registered",
    "already-registered",
    "already_signed",
    "already signed",
    "alreadysigned",
    "user_already_registered",
    "user already registered",
    "useralreadyregistered",
    "user_already_signed",
    "user already signed",
    "useralreadysigned",
    "already_booked",
    "already booked",
    "alreadybooked",
    "user_already_booked",
    "user already booked",
    "useralreadybooked",
    # Hebrew variations
    "כבר רשום",
    "כבררשום",
    "כבר רשומה",
    "כבררשומה",
    "הנך רשום",
    "הנךרשום",
    "הנך רשומה",
    "הנךרשומה",
    "הינך רשום",
    "הינךרשום",
    "הינך רשומה",
    "הינךרשומה",
    "רשום כבר",
    "רשוםכבר",
    "רשומה כבר",
    "רשומהכבר",
    "כבר נרשמת",
    "כברנרשמת",
    "נרשמת כבר",
    "נרשמתכבר",
)


def normalize_response_text(text: str | bytes | Any) -> str:
    """Normalizes response text by converting to lowercase and stripping spaces, underscores, hyphens, and punctuation.

    Args:
        text: Input string, bytes, or representation to normalize.

    Returns:
        str: Normalized alphanumeric lowercase string.
    """
    if not text:
        return ""
    if isinstance(text, (bytes, bytearray)):
        try:
            text = text.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, AttributeError):
            return ""
    if not isinstance(text, str):
        return ""
    cleaned = html.unescape(text)
    if "\\u" in cleaned:
        try:
            cleaned = re.sub(
                r"\\u([0-9a-fA-F]{4})",
                lambda m: chr(int(m.group(1), 16)),
                cleaned,
            )
        except (ValueError, re.error):
            pass
    lowered = cleaned.lower()
    return re.sub(r"[\s_\-\W]+", "", lowered)


def is_already_registered_response(
    resp_json: Any, resp_text: str | bytes | None = None
) -> bool:
    """Checks whether the response indicates the user is already booked/registered.

    Args:
        resp_json: Parsed response payload (dict, list, or primitive).
        resp_text: Raw response body string or bytes.

    Returns:
        bool: True if any already-registered pattern matches, False otherwise.
    """
    raw_candidates: list[str] = []
    if resp_text is not None:
        if isinstance(resp_text, (bytes, bytearray)):
            try:
                resp_text = resp_text.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                resp_text = str(resp_text)
        if isinstance(resp_text, str) and resp_text.strip():
            raw_candidates.append(resp_text)

    if isinstance(resp_json, (dict, list)):
        try:
            raw_candidates.append(json.dumps(resp_json, ensure_ascii=False))
        except (TypeError, ValueError):
            raw_candidates.append(str(resp_json))
    elif resp_json is not None:
        raw_candidates.append(str(resp_json))

    norm_patterns = [
        (pat, normalize_response_text(pat)) for pat in ALREADY_BOOKED_PATTERNS
    ]

    for candidate in raw_candidates:
        cand_lower = candidate.lower()
        cand_norm = normalize_response_text(candidate)
        for pattern, norm_pat in norm_patterns:
            if pattern.lower() in cand_lower:
                return True
            if norm_pat and norm_pat in cand_norm:
                return True

    return False


def book_class(session: requests.Session, schedule_id: int | str) -> tuple[bool, str]:
    """Attempts to book a class using the V2 Arbox API.

    Args:
        session: Active requests Session with auth headers.
        schedule_id: Integer or string schedule ID to book.

    Returns:
        tuple[bool, str]: Tuple of (success_status, status_message).
    """
    url = "https://apiappv2.arboxapp.com/api/v2/scheduleUser/insert?XDEBUG_SESSION_START=PHPSTORM"
    try:
        membership_id_int = int(MEMBERSHIP_USER_ID)
        schedule_id_int = int(schedule_id)
    except (ValueError, TypeError) as e:
        return False, f"Invalid membership or schedule ID: {e}"

    payload = {
        "extras": None,
        "membership_user_id": membership_id_int,
        "schedule_id": schedule_id_int,
    }

    if DRY_RUN:
        logger.info(f"[DRY RUN] Would book class with Schedule ID: {schedule_id}")
        return True, "Dry run success"

    last_error_msg = "Unknown error"

    for attempt in range(1, 6):
        try:
            resp = session.post(url, json=payload, timeout=10)

            try:
                resp_json = resp.json()
            except Exception:
                resp_json = {}

            # Check for already registered across all response formats and languages
            if is_already_registered_response(resp_json, resp.text):
                msg = "Successfully secured spot! (Already Registered)"
                logger.info(f"{msg} - Attempt {attempt}")
                return True, msg

            # Check for confirmed booking success
            if resp.status_code == 200:
                msg = f"Successfully secured spot! (Confirmed) - Attempt {attempt}"
                logger.info(msg)
                return True, msg

            # Extract detailed user-facing error message from Arbox JSON
            err_obj = resp_json.get("error") if isinstance(resp_json, dict) else None
            if isinstance(err_obj, dict):
                arbox_err = err_obj.get("messageToUser") or err_obj.get("message") or ""
            elif isinstance(err_obj, str):
                arbox_err = err_obj
            else:
                arbox_err = ""

            if not arbox_err and isinstance(resp_json, dict):
                arbox_err = resp_json.get("message") or resp.text[:200]
            elif not arbox_err:
                arbox_err = resp.text[:200]

            last_error_msg = f"Failed to book (Status {resp.status_code}): {arbox_err}"
            logger.error(f"Attempt {attempt} - {last_error_msg}")

            # Transient errors to retry: rate limits (429), gateway/proxy drops (502, 503, 504)
            retryable_codes = {429, 502, 503, 504}
            if resp.status_code not in retryable_codes:
                # Stop immediately on deterministic business logic/membership errors and return exact reason
                return False, last_error_msg

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_error_msg = f"Connection/Timeout Error: {e}"
            logger.warning(f"Attempt {attempt} failed: {last_error_msg}")
            if attempt == 5:
                return False, f"Error during booking after 5 attempts: {e}"
        except Exception as e:
            last_error_msg = f"Unexpected Error: {e}"
            logger.warning(f"Attempt {attempt} failed: {last_error_msg}")
            if attempt == 5:
                return False, f"Error during booking after 5 attempts: {e}"

        sleep_time = (0.1 * (2 ** (attempt - 1))) + random.uniform(0.01, 0.05)
        logger.info(f"Retrying in {sleep_time:.3f} seconds...")
        time.sleep(sleep_time)

    return False, last_error_msg


def generate_html_table(
    classes_info: list[dict], date_range_str: str, status_html: str = ""
) -> str:
    """Generates an HTML table summary of the schedule and booking status.

    Args:
        classes_info: List of class summary dictionaries.
        date_range_str: Formatted date string for header.
        status_html: Optional HTML snippet for the status banner.

    Returns:
        str: Generated HTML content.
    """
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
        is_target = cls["best_match"]
        row_class = "target" if is_target else ""

        if is_target:
            status_badge = (
                '<span class="badge booked">SECURED</span>'
                if cls.get("was_booked")
                else '<span class="badge missed" style="background:#ef4444">MISSED</span>'
            )
        else:
            status_badge = '<span style="color:#cbd5e1">-</span>'

        html_content += f"""
                <tr class="{row_class}">
                    <td><strong>{cls["hour"]}</strong></td>
                    <td>{cls["training"]}</td>
                    <td>{status_badge}</td>
                </tr>"""

    html_content += """
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    output_path = PROJECT_DIR / "schedule.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return html_content


def main() -> None:
    """Main entrypoint for schedule scanning and precision automated booking."""
    if not EMAIL or not PASSWORD:
        logger.error(
            "Please ensure ARBOX_EMAIL and ARBOX_PASSWORD are set in the .env file."
        )
        sys.exit(1)

    events: list[dict] = []

    base_headers = {
        "Content-Type": "application/json",
        "identifier": IDENTIFIER,
        "boxfk": GYM_ID,
        "whitelabel": "Arbox",
        "newsite": "1",
        "referername": "site",
        "version": "10",
        "lang": "en",
        "User-Agent": "Mozilla/5.0",
    }

    session = requests.Session()
    session.headers.update(base_headers)

    # 1. Load cached token or login if missing/invalid
    login_url = "https://apiappv2.arboxapp.com/api/v2/user/siteLogin"
    session_cache_path = PROJECT_DIR / "session.json"
    token = None

    if session_cache_path.exists():
        try:
            with open(session_cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
                token = cache_data.get("token")
                if token:
                    logger.info("Found cached session token.")
        except Exception as e:
            logger.warning(f"Could not load cached session token: {e}")

    parts = EMAIL.split("@")
    masked_email = (
        f"{parts[0][0]}***{parts[0][-1]}@{parts[1]}" if len(parts[0]) > 1 else EMAIL
    )

    if token:
        session.headers.update({"accesstoken": token})
    else:
        logger.info("No cached session token found. Initiating fresh login...")
        try:
            resp = session.post(
                login_url,
                json={"email": EMAIL, "password": PASSWORD, "phone": ""},
                timeout=10,
            )
            resp.raise_for_status()
            resp_body = resp.json()
            data = (
                resp_body.get("data")
                if isinstance(resp_body.get("data"), dict)
                else resp_body
            )
            token = (
                data.get("token") if isinstance(data, dict) else None
            ) or resp.headers.get("token")
            if not token:
                logger.error("Login failed, no token returned.")
                sys.exit(1)
            session.headers.update({"accesstoken": token})
            # Save token to cache
            with open(session_cache_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "token": token,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                    f,
                )
            logger.info(f"Logged in fresh as {masked_email} and cached token.")
        except Exception as e:
            logger.exception(f"Login error: {e}")
            sys.exit(1)

    # 2. Fetch schedule for tomorrow immediately to find the target ID
    today = get_israel_time()
    tomorrow_obj = today + timedelta(days=1)
    tomorrow = tomorrow_obj.strftime("%Y-%m-%d")
    tomorrow_day = tomorrow_obj.strftime("%A")

    day_config = DATE_OVERRIDES.get(tomorrow, TARGET_CONFIG.get(tomorrow_day))

    target_class_id = None
    target_summary = "Searching..."
    target_summary_with_spots = "Searching..."
    is_already_booked = False

    logger.info(f"Pre-scanning schedule for {tomorrow}...")
    schedule_url = "https://apiappv2.arboxapp.com/api/v2/site/schedule/betweenDates"
    payload = {"from": tomorrow, "to": tomorrow, "locations_box_id": int(LOCATION_ID)}

    try:
        resp = session.post(schedule_url, json=payload, timeout=10)
        # Intercept 401/403 errors for token refresh logic
        if resp.status_code in (401, 403):
            logger.info("Cached token expired/invalid. Re-authenticating...")
            resp_login = session.post(
                login_url,
                json={"email": EMAIL, "password": PASSWORD, "phone": ""},
                timeout=10,
            )
            resp_login.raise_for_status()
            resp_body = resp_login.json()
            data = (
                resp_body.get("data")
                if isinstance(resp_body.get("data"), dict)
                else resp_body
            )
            token = (
                data.get("token") if isinstance(data, dict) else None
            ) or resp_login.headers.get("token")
            if token:
                session.headers.update({"accesstoken": token})
                with open(session_cache_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "token": token,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        },
                        f,
                    )
                logger.info("Fresh token cached successfully. Retrying pre-scan...")
                resp = session.post(schedule_url, json=payload, timeout=10)
        resp.raise_for_status()
        resp_data = resp.json()
        if isinstance(resp_data, dict):
            raw_events = resp_data.get("data") or []
        elif isinstance(resp_data, list):
            raw_events = resp_data
        else:
            raw_events = []
        events = [e for e in raw_events if isinstance(e, dict)]

        if day_config:
            target_time = day_config["time"]
            target_coach = day_config.get("coach", "")
            target_type = day_config.get("type")

            target_info_list = [
                entry for entry in events if entry.get("time") == target_time
            ]

            # Match by training type if specified (e.g., "WOD")
            if target_type:

                def matches_training_type(entry_item: dict) -> bool:
                    cat_name = extract_training_type(entry_item).lower()
                    return target_type.lower() in cat_name

                target_info_list = [
                    entry for entry in target_info_list if matches_training_type(entry)
                ]

            target_series_id = day_config.get("series_id")
            target_entry = select_target_entry(
                target_info_list,
                target_coach,
                target_time=target_time,
                target_series_id=target_series_id,
            )

            if target_entry:
                target_class_id = target_entry.get("id")
                coach_name = extract_coach_name(target_entry) or "Unknown"

                # Check registration status
                is_already_booked = is_user_booked_for_schedule(target_entry)
                spots_free, spots_booked, spots_max = extract_spots(target_entry)

                target_summary = (
                    f"{tomorrow_day} {tomorrow} at {target_time} (Coach: {coach_name})"
                )
                target_summary_with_spots = (
                    f"{target_summary}\nSpots: {spots_free}/{spots_max}"
                )
                logger.info(f"TARGET ACQUIRED: {target_summary_with_spots}")

                if is_already_booked:
                    logger.info("Target class is ALREADY BOOKED for this user.")
            else:
                target_summary_with_spots = (
                    f"No class found at {target_time} for {tomorrow_day}."
                )
                logger.warning(f"WARNING: {target_summary_with_spots}")
    except Exception as e:
        logger.exception(f"Pre-scan error: {e}")
        sys.exit(1)

    # If no target class was identified, we have nothing to book. Exit early to avoid billing waste.
    if not target_class_id:
        logger.warning(
            "No target class found matching the configuration for tomorrow. Exiting immediately."
        )
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
            resp = session.post(
                login_url,
                json={"email": EMAIL, "password": PASSWORD, "phone": ""},
                timeout=10,
            )
            resp.raise_for_status()
            resp_body = resp.json()
            data = (
                resp_body.get("data")
                if isinstance(resp_body.get("data"), dict)
                else resp_body
            )
            token = (
                data.get("token") if isinstance(data, dict) else None
            ) or resp.headers.get("token")
            if token:
                session.headers.update({"accesstoken": token})
                logger.info("Token refreshed successfully.")
            else:
                logger.warning(
                    "Token refresh failed. Proceeding with existing session."
                )
        except Exception as e:
            logger.warning(
                f"Token refresh error: {e}. Proceeding with existing session."
            )

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
            resp_data = resp.json()
            if isinstance(resp_data, dict):
                raw_events = resp_data.get("data") or []
            elif isinstance(resp_data, list):
                raw_events = resp_data
            else:
                raw_events = []
            events = [e for e in raw_events if isinstance(e, dict)]
        except Exception as e:
            logger.warning(
                f"Could not fetch updated schedule for HTML report ({e}). Using pre-scan events."
            )

        for entry in events:
            schedule_id = entry.get("id")
            is_best_match = schedule_id == target_class_id

            hour = entry.get("time", "")
            training = extract_training_type(entry)

            classes_info.append(
                {
                    "day": tomorrow_day,
                    "date": tomorrow,
                    "hour": hour,
                    "training": training,
                    "was_booked": True if (is_best_match and success) else False,
                    "best_match": is_best_match,
                }
            )
    else:
        logger.warning("No target ID found. Skipping booking attempt.")

    # 5. Final Processing & Notification Report
    if classes_info:
        classes_info.sort(key=lambda x: (x["date"], x["hour"]))
        any_booked = any(cls["was_booked"] for cls in classes_info if cls["best_match"])

        if any_booked:
            status_html = '<div class="status-header status-success">MISSION SUCCESS: Booking Secured</div>'
            ntfy_title = "✅ Booking Confirmed"
        else:
            status_html = '<div class="status-header status-failure">FAILURE: Class was likely full</div>'
            ntfy_title = "❌ Booking Failed"

        generate_html_table(classes_info, tomorrow, status_html)

        ntfy_msg = "\n".join(booking_summaries)
        send_ntfy(ntfy_title, ntfy_msg, priority="high")


if __name__ == "__main__":
    main()
