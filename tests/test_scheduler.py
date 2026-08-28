"""Unit tests for arbox-scheduler automation and precision booking logic."""

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
import pytest
import requests

# Ensure project root is in sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from fetch_schedule import (
    TARGET_CONFIG,
    book_class,
    extract_coach_name,
    extract_spots,
    extract_training_type,
    generate_html_table,
    get_israel_time,
    is_user_booked_for_schedule,
    select_target_entry,
    send_ntfy,
    wait_for_precision_window,
)


def test_get_israel_time() -> None:
    """Verifies get_israel_time returns a valid Asia/Jerusalem timezone datetime."""
    isr_now = get_israel_time()
    assert isr_now is not None
    assert isr_now.tzinfo is not None
    assert str(isr_now.tzinfo) == "Asia/Jerusalem"
    offset_hours = isr_now.utcoffset().total_seconds() / 3600
    assert offset_hours in (2.0, 3.0)


def test_generate_html_table() -> None:
    """Tests HTML report generation and structure formatting."""
    classes_info = [
        {
            "day": "Thursday",
            "date": "2026-07-09",
            "hour": "08:30",
            "training": "WOD",
            "was_booked": True,
            "best_match": True,
        },
    ]
    html = generate_html_table(classes_info, "2026-07-09", status_html="Confirmed")
    assert "Gorillot Booking Report" in html
    assert "WOD" in html
    assert "SECURED" in html
    assert "padding: 24px;" in html
    assert "padding: 16px;" in html


def test_target_config_fallback() -> None:
    """Asserts default series ID configuration for core schedule days."""
    assert TARGET_CONFIG is not None
    assert TARGET_CONFIG["Sunday"]["series_id"] == 187541
    assert TARGET_CONFIG["Tuesday"]["series_id"] == 3300
    assert TARGET_CONFIG["Thursday"]["series_id"] == 187542
    assert TARGET_CONFIG["Friday"]["series_id"] == 2498


def test_category_matching_prioritizes_box_categories() -> None:
    """Verifies box_categories matching takes precedence over series names."""
    target_type = "WOD"
    events = [
        {
            "id": 1,
            "time": "18:30",
            "box_categories": {"name": "Weightlifting"},
            "series": {"series_name": "WOD ,שלישי,18:30"},
            "coach": {"full_name": "רוני שחם"},
        },
        {
            "id": 2,
            "time": "18:30",
            "box_categories": {"name": "WOD "},
            "series": {"series_name": "W.O.D,Tuesday,18:30"},
            "coach": {"full_name": "אופיר רודיטי"},
        },
    ]

    def matches_training_type(entry_item: dict) -> bool:
        cat_name = extract_training_type(entry_item).lower()
        return target_type.lower() in cat_name

    matched = [e for e in events if matches_training_type(e)]
    assert len(matched) == 1
    assert matched[0]["id"] == 2
    assert extract_coach_name(matched[0]) == "אופיר רודיטי"


def test_extract_coach_name_variations() -> None:
    """Tests extract_coach_name across various Arbox API structures."""
    assert extract_coach_name({"coach": {"full_name": "  Dan Cohen  "}}) == "Dan Cohen"
    assert extract_coach_name({"coach": {"name": "Sara Levi"}}) == "Sara Levi"
    assert extract_coach_name({"coach": {"first_name": "Alex", "last_name": "Gold"}}) == "Alex Gold"
    assert extract_coach_name({"coach": " Direct String Name "}) == "Direct String Name"
    assert extract_coach_name({"coach": None}) == ""
    assert extract_coach_name({}) == ""
    assert extract_coach_name(None) == ""
    assert extract_coach_name("invalid") == ""


def test_extract_training_type_variations() -> None:
    """Tests extract_training_type across box_categories and series fallbacks."""
    assert extract_training_type({"box_categories": {"name": "Hyrox"}}) == "Hyrox"
    assert extract_training_type({"series": {"series_name": "Open Gym"}}) == "Open Gym"
    assert extract_training_type({"box_categories": None, "series": None}) == "WOD"
    assert extract_training_type({}) == "WOD"
    assert extract_training_type(None) == "WOD"


def test_extract_spots_variations() -> None:
    """Tests extract_spots with valid ints, null values, and string representations."""
    assert extract_spots({"max_participants": 20, "num_signed_to_schedule": 15}) == (5, 15, 20)
    assert extract_spots({"max_participants": None, "num_signed_to_schedule": None}) == (0, 0, 0)
    assert extract_spots({"max_participants": "18", "num_signed_to_schedule": "10"}) == (8, 10, 18)
    assert extract_spots({}) == (0, 0, 0)
    assert extract_spots(None) == (0, 0, 0)


def test_select_target_entry() -> None:
    """Tests coach exclusion filtering in target selection."""
    entries = [
        {"id": 10, "coach": {"full_name": "דניאל טנג'י"}},
        {"id": 20, "coach": {"full_name": "אופיר רודיטי"}},
    ]
    res = select_target_entry(entries, "not דניאל טנג'י")
    assert res is not None
    assert res["id"] == 20


def test_select_target_entry_bypasses_coach_if_series_id_matches() -> None:
    """Verifies target_series_id takes ultimate precedence over coach names."""
    entries = [
        {
            "id": 52500490,
            "time": "08:30",
            "coach": {"full_name": "דניאל טנג'י"},
            "series": {"id": 2498, "series_name": "W.O.D,Friday,08:30"},
            "booking_option": "book",
            "free": 5,
        },
        {
            "id": 52504730,
            "time": "08:30",
            "coach": {"full_name": "שיראל ריצמן"},
            "series": {"id": 9999, "series_name": "WOD ,Friday,08:30"},
            "booking_option": "book",
            "free": 5,
        },
    ]
    res = select_target_entry(entries, target_time="08:30", target_series_id=2498)
    assert res is not None
    assert res["id"] == 52500490
    assert (res.get("series") or {}).get("id") == 2498


def test_select_target_entry_empty_or_malformed() -> None:
    """Tests select_target_entry resilience against empty lists or non-dict entries."""
    assert select_target_entry([]) is None
    assert select_target_entry([None, "string", 123]) is None


def test_book_class_extracts_arbox_message_to_user() -> None:
    """Asserts user error message extraction and stopping on deterministic 513 error."""
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 513
    mock_resp.text = '{"statusCode":513,"error":{"message":"Schedule Exception","messageToUser":"Class is full","code":513},"data":null}'
    mock_resp.json.return_value = {
        "statusCode": 513,
        "error": {
            "message": "Schedule Exception",
            "messageToUser": "Class is full",
            "code": 513,
        },
        "data": None,
    }
    mock_session.post.return_value = mock_resp

    success, msg = book_class(mock_session, 52504730)
    assert success is False
    assert "Class is full" in msg
    assert "Status 513" in msg
    assert mock_session.post.call_count == 1


def test_book_class_success_and_already_registered() -> None:
    """Tests book_class handles HTTP 200 and alreadyRegistered response payload."""
    mock_session = MagicMock()

    # Case 1: Status 200
    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {"status": "ok"}
    mock_session.post.return_value = mock_resp_200

    success, msg = book_class(mock_session, 12345)
    assert success is True
    assert "Confirmed" in msg

    # Case 2: Status 400 but body contains alreadyRegistered
    mock_resp_already = MagicMock()
    mock_resp_already.status_code = 400
    mock_resp_already.text = "User alreadyRegistered for this class"
    mock_resp_already.json.return_value = {"error": "alreadyRegistered"}
    mock_session.post.return_value = mock_resp_already

    success, msg = book_class(mock_session, 12345)
    assert success is True
    assert "Already Registered" in msg


def test_israel_time_dst_transitions() -> None:
    """Verifies timezone transitions between Israel Summer (UTC+3) and Winter (UTC+2)."""
    summer_dt = datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    winter_dt = datetime(2026, 1, 15, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    assert summer_dt.utcoffset().total_seconds() / 3600 == 3.0
    assert winter_dt.utcoffset().total_seconds() / 3600 == 2.0


def test_already_booked_detection_scenarios() -> None:
    """Tests is_user_booked_for_schedule against various sign-up and booking flags."""
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": True, "booking_option": None}) is True
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": 1, "booking_option": None}) is True
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": None, "booking_option": "cancelScheduleUser"}) is True
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": False, "booking_option": "cancelScheduleUser"}) is True
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": False, "booking_option": "CancelScheduleUser"}) is True
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": False, "booking_option": "book"}) is False
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": None, "booking_option": "book"}) is False
    assert is_user_booked_for_schedule({}) is False
    assert is_user_booked_for_schedule(None) is False


def test_config_date_overrides_empty() -> None:
    """Verifies config.json DATE_OVERRIDES is empty dictionary."""
    config_file = PROJECT_DIR / "config.json"
    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("DATE_OVERRIDES") == {}


def test_wait_for_precision_window_outside_bounds_returns_immediately() -> None:
    """Ensures precision countdown returns immediately when outside the 5-hour window."""
    now = get_israel_time()
    past_hour = (now.hour - 2) % 24
    wait_for_precision_window(target_hour_israel=past_hour, target_minute_israel=0)


def test_is_user_booked_for_schedule_malformed_inputs() -> None:
    """Tests is_user_booked_for_schedule robustness with malformed or non-dict values."""
    assert is_user_booked_for_schedule("not a dict") is False
    assert is_user_booked_for_schedule(123) is False
    assert is_user_booked_for_schedule(["list"]) is False
    assert is_user_booked_for_schedule({"booking_option": 123}) is False
    assert is_user_booked_for_schedule({"booking_option": " CANCELscheduleUSER "}) is True


def test_wait_for_precision_window_target_israel_timezone_utc_conversion() -> None:
    """Tests conversion of 21:00 Israel time to UTC in summer and winter."""
    summer_isr = datetime(2026, 7, 15, 21, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    summer_utc = summer_isr.astimezone(timezone.utc)
    assert summer_utc.hour == 18
    assert summer_utc.minute == 0

    winter_isr = datetime(2026, 1, 15, 21, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    winter_utc = winter_isr.astimezone(timezone.utc)
    assert winter_utc.hour == 19
    assert winter_utc.minute == 0


def test_send_ntfy_window_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests notification window restriction between 20:00 and 23:00 Israel Time."""
    # Mock time outside 20:00 - 23:00 (e.g. 10:00)
    mock_now_outside = datetime(2026, 8, 28, 10, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    monkeypatch.setattr("fetch_schedule.get_israel_time", lambda: mock_now_outside)
    assert send_ntfy("Test", "Test message") is False

    # Mock time inside 20:00 - 23:00 (e.g. 21:30) with mocked requests.post
    mock_now_inside = datetime(2026, 8, 28, 21, 30, tzinfo=ZoneInfo("Asia/Jerusalem"))
    monkeypatch.setattr("fetch_schedule.get_israel_time", lambda: mock_now_inside)
    mock_post = MagicMock()
    mock_post.return_value.raise_for_status = MagicMock()
    monkeypatch.setattr("requests.post", mock_post)
    assert send_ntfy("Test", "Test message") is True
    assert mock_post.call_count == 1


def test_book_class_retryable_errors_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that book_class retries on transient errors (e.g., 502) and succeeds on recovery."""
    mock_session = MagicMock()
    mock_resp_502 = MagicMock()
    mock_resp_502.status_code = 502
    mock_resp_502.text = "Bad Gateway"
    mock_resp_502.json.return_value = {}

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {"status": "ok"}

    mock_session.post.side_effect = [mock_resp_502, mock_resp_200]
    monkeypatch.setattr("time.sleep", lambda _: None)

    success, msg = book_class(mock_session, 12345)
    assert success is True
    assert "Attempt 2" in msg
    assert mock_session.post.call_count == 2


def test_book_class_retryable_connection_timeout_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests book_class handles connection errors and exhausts all 5 retries gracefully."""
    mock_session = MagicMock()
    mock_session.post.side_effect = requests.exceptions.Timeout("Connection timed out")
    monkeypatch.setattr("time.sleep", lambda _: None)

    success, msg = book_class(mock_session, 12345)
    assert success is False
    assert "after 5 attempts" in msg
    assert mock_session.post.call_count == 5


def test_book_class_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests book_class dry run mode bypasses network calls."""
    monkeypatch.setattr("fetch_schedule.DRY_RUN", True)
    mock_session = MagicMock()

    success, msg = book_class(mock_session, 12345)
    assert success is True
    assert "Dry run success" in msg
    assert mock_session.post.call_count == 0


def test_book_class_invalid_ids() -> None:
    """Tests book_class returns error on non-numeric schedule ID."""
    mock_session = MagicMock()
    success, msg = book_class(mock_session, "invalid_id")
    assert success is False
    assert "Invalid membership or schedule ID" in msg


def test_select_target_entry_coach_positive_and_always_exclude() -> None:
    """Tests target selection with positive coach filtering and always_exclude matching."""
    entries = [
        {"id": 10, "coach": {"full_name": "Coach Adam"}},
        {"id": 20, "coach": {"full_name": "Coach Bob"}},
        {"id": 30, "coach": {"full_name": "Coach Charlie"}},
    ]

    # Positive match
    res_pos = select_target_entry(entries, target_coach="Bob")
    assert res_pos is not None
    assert res_pos["id"] == 20

    # Always exclude match
    res_exc = select_target_entry(entries, always_exclude="Adam")
    assert res_exc is not None
    assert res_exc["id"] == 20


def test_generate_html_table_missed_badge() -> None:
    """Tests HTML report generation includes MISSED badge when was_booked is False."""
    classes_info = [
        {
            "day": "Friday",
            "date": "2026-07-10",
            "hour": "08:30",
            "training": "WOD",
            "was_booked": False,
            "best_match": True,
        },
    ]
    html = generate_html_table(classes_info, "2026-07-10", status_html="Failed")
    assert "MISSED" in html


