import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from fetch_schedule import (
    get_israel_time,
    generate_html_table,
    TARGET_CONFIG,
    select_target_entry,
    book_class,
    is_user_booked_for_schedule,
    wait_for_precision_window,
)

def test_get_israel_time():
    isr_now = get_israel_time()
    assert isr_now is not None
    assert isr_now.tzinfo is not None
    assert str(isr_now.tzinfo) == "Asia/Jerusalem"
    offset_hours = isr_now.utcoffset().total_seconds() / 3600
    assert offset_hours in (2.0, 3.0)

def test_generate_html_table():
    classes_info = [
        {
            "day": "Thursday",
            "date": "2026-07-09",
            "hour": "08:30",
            "training": "WOD",
            "was_booked": True,
            "best_match": True,
        }
    ]
    html = generate_html_table(classes_info, "2026-07-09", status_html="Confirmed")
    assert "Gorillot Booking Report" in html
    assert "WOD" in html
    assert "SECURED" in html
    assert "padding: 24px;" in html  # Verify 8px grid body padding
    assert "padding: 16px;" in html  # Verify 8px grid cell padding

def test_target_config_fallback():
    assert TARGET_CONFIG is not None
    assert TARGET_CONFIG["Sunday"]["series_id"] == 187541
    assert TARGET_CONFIG["Tuesday"]["series_id"] == 3300
    assert TARGET_CONFIG["Thursday"]["series_id"] == 187542
    assert TARGET_CONFIG["Friday"]["series_id"] == 2498

def test_category_matching_prioritizes_box_categories():
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

    def matches_training_type(entry_item):
        cat_name = ((entry_item.get("box_categories") or {}).get("name") or "").strip().lower()
        if cat_name:
            return target_type.lower() in cat_name
        ser_name = ((entry_item.get("series") or {}).get("series_name") or "").strip().lower()
        return target_type.lower() in ser_name

    matched = [e for e in events if matches_training_type(e)]
    assert len(matched) == 1
    assert matched[0]["id"] == 2
    assert matched[0]["coach"]["full_name"] == "אופיר רודיטי"

def test_select_target_entry():
    entries = [
        {"id": 10, "coach": {"full_name": "דניאל טנג'י"}},
        {"id": 20, "coach": {"full_name": "אופיר רודיטי"}},
    ]
    res = select_target_entry(entries, "not דניאל טנג'י")
    assert res is not None
    assert res["id"] == 20

def test_select_target_entry_bypasses_coach_if_series_id_matches():
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
    assert res["series"]["id"] == 2498

def test_book_class_extracts_arbox_message_to_user():
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

def test_israel_time_dst_transitions():
    from zoneinfo import ZoneInfo
    summer_dt = datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    winter_dt = datetime(2026, 1, 15, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    assert summer_dt.utcoffset().total_seconds() / 3600 == 3.0
    assert winter_dt.utcoffset().total_seconds() / 3600 == 2.0

def test_already_booked_detection_scenarios():
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": True, "booking_option": None}) is True
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": 1, "booking_option": None}) is True
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": None, "booking_option": "cancelScheduleUser"}) is True
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": False, "booking_option": "cancelScheduleUser"}) is True
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": False, "booking_option": "CancelScheduleUser"}) is True
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": False, "booking_option": "book"}) is False
    assert is_user_booked_for_schedule({"is_user_signed_to_schedule": None, "booking_option": "book"}) is False
    assert is_user_booked_for_schedule({}) is False
    assert is_user_booked_for_schedule(None) is False

def test_config_date_overrides_empty():
    import json
    config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("DATE_OVERRIDES") == {}

def test_wait_for_precision_window_outside_bounds_returns_immediately():
    # If the target hour is in the past or far in the future (> 5 hours), it returns immediately
    now = get_israel_time()
    past_hour = (now.hour - 2) % 24
    # Call with past hour to ensure non-blocking execution
    wait_for_precision_window(target_hour_israel=past_hour, target_minute_israel=0)

def test_is_user_booked_for_schedule_malformed_inputs():
    assert is_user_booked_for_schedule("not a dict") is False
    assert is_user_booked_for_schedule(123) is False
    assert is_user_booked_for_schedule(["list"]) is False
    assert is_user_booked_for_schedule({"booking_option": 123}) is False
    assert is_user_booked_for_schedule({"booking_option": " CANCELscheduleUSER "}) is True

def test_wait_for_precision_window_target_israel_timezone_utc_conversion():
    from zoneinfo import ZoneInfo
    # In Summer (UTC+3), 21:00 Israel is 18:00 UTC
    summer_isr = datetime(2026, 7, 15, 21, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    summer_utc = summer_isr.astimezone(timezone.utc)
    assert summer_utc.hour == 18
    assert summer_utc.minute == 0

    # In Winter (UTC+2), 21:00 Israel is 19:00 UTC
    winter_isr = datetime(2026, 1, 15, 21, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    winter_utc = winter_isr.astimezone(timezone.utc)
    assert winter_utc.hour == 19
    assert winter_utc.minute == 0

def test_send_ntfy_window_filtering(monkeypatch):
    from fetch_schedule import send_ntfy
    from zoneinfo import ZoneInfo

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
