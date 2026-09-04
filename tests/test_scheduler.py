"""Unit tests for arbox-scheduler automation and precision booking logic."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
import requests

# Ensure project root is in sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from fetch_schedule import (
    ALREADY_BOOKED_PATTERNS,
    TARGET_CONFIG,
    book_class,
    extract_coach_name,
    extract_spots,
    extract_training_type,
    generate_html_table,
    get_israel_time,
    is_already_registered_response,
    is_user_booked_for_schedule,
    normalize_response_text,
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
    assert (
        extract_coach_name({"coach": {"first_name": "Alex", "last_name": "Gold"}})
        == "Alex Gold"
    )
    assert (
        extract_coach_name({"coach": {"first_name": "Dan", "last_name": None}}) == "Dan"
    )
    assert (
        extract_coach_name({"coach": {"first_name": None, "last_name": "Cohen"}})
        == "Cohen"
    )
    assert extract_coach_name({"coach": {"first_name": None, "last_name": None}}) == ""
    assert extract_coach_name({"coach": " Direct String Name "}) == "Direct String Name"
    assert extract_coach_name({"coach": None}) == ""
    assert extract_coach_name({}) == ""
    assert extract_coach_name(None) == ""
    assert extract_coach_name("invalid") == ""


def test_extract_training_type_variations() -> None:
    """Tests extract_training_type across box_categories and series fallbacks."""
    assert extract_training_type({"box_categories": {"name": "Hyrox"}}) == "Hyrox"
    assert extract_training_type({"box_categories": "Hyrox String"}) == "Hyrox String"
    assert extract_training_type({"series": {"series_name": "Open Gym"}}) == "Open Gym"
    assert extract_training_type({"series": "Open Gym String"}) == "Open Gym String"
    assert extract_training_type({"box_categories": None, "series": None}) == "WOD"
    assert extract_training_type({}) == "WOD"
    assert extract_training_type(None) == "WOD"


def test_extract_spots_variations() -> None:
    """Tests extract_spots with valid ints, null values, and string representations."""
    assert extract_spots({"max_participants": 20, "num_signed_to_schedule": 15}) == (
        5,
        15,
        20,
    )
    assert extract_spots(
        {"max_participants": None, "num_signed_to_schedule": None}
    ) == (0, 0, 0)
    assert extract_spots(
        {"max_participants": "18", "num_signed_to_schedule": "10"}
    ) == (8, 10, 18)
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

    # Fallback to top-level series_id
    entries_flat = [
        {"id": 1, "time": "08:30", "series_id": 3300},
        {"id": 2, "time": "08:30", "series_id": 4400},
    ]
    res_flat = select_target_entry(entries_flat, target_series_id=3300)
    assert res_flat is not None
    assert res_flat["id"] == 1


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
    assert (
        is_user_booked_for_schedule(
            {"is_user_signed_to_schedule": True, "booking_option": None}
        )
        is True
    )
    assert (
        is_user_booked_for_schedule(
            {"is_user_signed_to_schedule": 1, "booking_option": None}
        )
        is True
    )
    assert (
        is_user_booked_for_schedule(
            {"is_user_signed_to_schedule": "true", "booking_option": None}
        )
        is True
    )
    assert (
        is_user_booked_for_schedule(
            {"is_user_signed_to_schedule": "1", "booking_option": None}
        )
        is True
    )
    assert (
        is_user_booked_for_schedule(
            {"is_user_signed_to_schedule": "false", "booking_option": "book"}
        )
        is False
    )
    assert (
        is_user_booked_for_schedule(
            {"is_user_signed_to_schedule": "0", "booking_option": "book"}
        )
        is False
    )
    assert (
        is_user_booked_for_schedule(
            {"is_user_signed_to_schedule": None, "booking_option": "cancelScheduleUser"}
        )
        is True
    )
    assert (
        is_user_booked_for_schedule(
            {
                "is_user_signed_to_schedule": False,
                "booking_option": "cancelScheduleUser",
            }
        )
        is True
    )
    assert (
        is_user_booked_for_schedule(
            {
                "is_user_signed_to_schedule": False,
                "booking_option": "CancelScheduleUser",
            }
        )
        is True
    )
    assert (
        is_user_booked_for_schedule(
            {"is_user_signed_to_schedule": False, "booking_option": "book"}
        )
        is False
    )
    assert (
        is_user_booked_for_schedule(
            {"is_user_signed_to_schedule": None, "booking_option": "book"}
        )
        is False
    )
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
    assert (
        is_user_booked_for_schedule({"booking_option": " CANCELscheduleUSER "}) is True
    )


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


def test_book_class_retryable_errors_then_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_book_class_retryable_connection_timeout_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_normalize_response_text() -> None:
    """Verifies normalize_response_text strips whitespace, underscores, hyphens, and punctuation."""
    assert normalize_response_text("already registered") == "alreadyregistered"
    assert normalize_response_text("already_registered") == "alreadyregistered"
    assert normalize_response_text("already-registered") == "alreadyregistered"
    assert normalize_response_text("already_signed") == "alreadysigned"
    assert normalize_response_text("user_already_registered") == "useralreadyregistered"
    assert normalize_response_text("user_already_signed") == "useralreadysigned"
    assert normalize_response_text("כבר רשום") == "כבררשום"
    assert normalize_response_text("הנך רשום") == "הנךרשום"
    assert (
        normalize_response_text("  --User Already_Registered!!  ")
        == "useralreadyregistered"
    )
    assert normalize_response_text("כבר-רשום!") == "כבררשום"
    assert normalize_response_text("הנך, רשום?") == "הנךרשום"
    assert normalize_response_text("כְּבָר רָשׁוּם") == "כבררשום"
    assert (
        normalize_response_text("<p>already&nbsp;registered</p>") == "alreadyregistered"
    )
    assert normalize_response_text("<p>כבר&nbsp;רשום</p>") == "כבררשום"
    assert normalize_response_text("<p class='msg'>כבר <b>רשום</b></p>") == "כבררשום"
    assert (
        normalize_response_text(
            "<span class='status'>already</span> <span>registered</span>"
        )
        == "alreadyregistered"
    )
    assert normalize_response_text("already%20registered") == "alreadyregistered"
    assert (
        normalize_response_text("%D7%9B%D7%91%D7%A8%20%D7%A8%D7%A9%D7%95%D7%9D")
        == "כבררשום"
    )
    assert (
        normalize_response_text(r'{"error": "\U000005db\U000005d1\U000005e8"}')
        == "errorכבר"
    )
    assert normalize_response_text(b"already_registered") == "alreadyregistered"
    assert normalize_response_text(r'{"error": "\u05db\u05d1\u05e8"}') == "errorכבר"
    assert normalize_response_text("") == ""
    assert normalize_response_text(None) == ""
    assert normalize_response_text(123) == ""


def test_already_booked_patterns_contains_all_required_variations() -> None:
    """Verifies ALREADY_BOOKED_PATTERNS contains all mandatory English and Hebrew phrases."""
    required_patterns = {
        "alreadyregistered",
        "already_registered",
        "already_signed",
        "user_already_registered",
        "user_already_signed",
        "כבר רשום",
        "הנך רשום",
    }
    for req in required_patterns:
        assert req in ALREADY_BOOKED_PATTERNS or normalize_response_text(req) in {
            normalize_response_text(p) for p in ALREADY_BOOKED_PATTERNS
        }


def test_is_already_registered_response() -> None:
    """Tests already-registered detection across raw and normalized English and Hebrew responses."""
    # JSON dict payloads
    assert is_already_registered_response({"error": "already_registered"}) is True
    assert is_already_registered_response({"error": "already_signed"}) is True
    assert (
        is_already_registered_response({"message": "user_already_registered"}) is True
    )
    assert is_already_registered_response({"message": "user_already_signed"}) is True
    assert is_already_registered_response({"error": "already booked"}) is True
    assert is_already_registered_response({"error": "user_already_booked"}) is True
    assert (
        is_already_registered_response(
            {"error": {"messageToUser": "כבר רשום לשיעור זה"}}
        )
        is True
    )
    assert (
        is_already_registered_response({"error": {"message": "הנך רשום לסדרה"}}) is True
    )
    assert is_already_registered_response({"error": "כבר רשומה"}) is True
    assert is_already_registered_response({"error": "הנך רשומה"}) is True
    assert is_already_registered_response({"error": "הינך רשום לשיעור"}) is True
    assert is_already_registered_response({"error": "הינך רשומה לסדרה"}) is True
    assert is_already_registered_response({"error": "רשום כבר לשיעור זה"}) is True
    assert is_already_registered_response({"error": "רשומה כבר"}) is True
    assert is_already_registered_response({"error": "כבר נרשמת לשיעור זה"}) is True
    assert is_already_registered_response({"error": "נרשמת כבר"}) is True
    assert is_already_registered_response({"error": "משתמש כבר נרשם לשיעור"}) is True
    assert is_already_registered_response({"error": "נרשם כבר לסדרה"}) is True
    assert is_already_registered_response({"error": "כבר נרשמה"}) is True
    assert is_already_registered_response({"error": "נרשמה כבר"}) is True
    assert is_already_registered_response({"error": "משתמש רשום"}) is True
    assert is_already_registered_response({"error": "רישום כפול"}) is True
    assert is_already_registered_response({"error": "קיים רישום"}) is True
    assert is_already_registered_response({"error": "already enrolled"}) is True
    assert is_already_registered_response({"error": "user already enrolled"}) is True
    assert is_already_registered_response({"error": "already signed up"}) is True

    # Raw response text & HTML
    assert (
        is_already_registered_response({}, "User already registered for class") is True
    )
    assert is_already_registered_response({}, "User already-registered") is True
    assert is_already_registered_response({}, "<p>already&nbsp;registered</p>") is True
    assert is_already_registered_response({}, "<p>כבר&nbsp;רשום</p>") is True
    assert (
        is_already_registered_response({}, "<p class='msg'>כבר <b>רשום</b></p>") is True
    )
    assert (
        is_already_registered_response(
            {}, "<span class='status'>already</span> <span>registered</span>"
        )
        is True
    )
    assert is_already_registered_response({}, "already%20registered") is True
    assert (
        is_already_registered_response(
            {}, "%D7%9B%D7%91%D7%A8%20%D7%A8%D7%A9%D7%95%D7%9D"
        )
        is True
    )
    assert is_already_registered_response({}, "הנך רשום!") is True
    assert is_already_registered_response({}, "כבר רשום") is True
    assert (
        is_already_registered_response(
            None, r'{"error": "\u05db\u05d1\u05e8 \u05e8\u05e9\u05d5\u05dd"}'
        )
        is True
    )
    assert (
        is_already_registered_response(
            None,
            r'{"error": "\U000005db\U000005d1\U000005e8 \U000005e8\U000005e9\U000005d5\U000005dd"}',
        )
        is True
    )
    assert (
        is_already_registered_response(None, b'{"error": "already_registered"}') is True
    )

    # Negative responses
    assert is_already_registered_response({"error": "Class is full"}) is False
    assert is_already_registered_response({"message": "Membership expired"}) is False
    assert (
        is_already_registered_response({"message": "User registered successfully"})
        is False
    )
    assert is_already_registered_response({}, "Bad Gateway") is False
    assert is_already_registered_response(None, "") is False


@pytest.mark.parametrize(
    "pattern,status_code",
    [
        ("already registered", 400),
        ("already_registered", 400),
        ("already-registered", 400),
        ("alreadyregistered", 400),
        ("already_signed", 400),
        ("already signed", 400),
        ("already booked", 400),
        ("already_booked", 400),
        ("already enrolled", 400),
        ("alreadyenrolled", 400),
        ("already signed up", 400),
        ("user_already_registered", 409),
        ("user already registered", 409),
        ("user_already_signed", 409),
        ("user already signed", 409),
        ("user_already_booked", 409),
        ("user already enrolled", 409),
        ("כבר רשום", 422),
        ("הנך רשום", 500),
        ("הינך רשום", 400),
        ("כבר רשומה", 400),
        ("הנך רשומה", 400),
        ("הינך רשומה", 400),
        ("רשום כבר", 400),
        ("רשומה כבר", 400),
        ("כבר נרשם", 400),
        ("נרשם כבר", 400),
        ("כבר נרשמה", 400),
        ("נרשמה כבר", 400),
        ("משתמש רשום", 400),
        ("רישום כפול", 422),
        ("קיים רישום", 422),
        ("כבר נרשמת", 400),
        ("נרשמת כבר", 400),
        ("already_registered", 200),
    ],
)
def test_book_class_already_registered_variations_stops_immediately(
    pattern: str,
    status_code: int,
) -> None:
    """Verifies book_class recognizes all English and Hebrew patterns and halts on Attempt 1 with 0 retries."""
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = json.dumps(
        {"error": f"Prefix {pattern} suffix"}, ensure_ascii=False
    )
    mock_resp.json.return_value = {"error": {"message": f"Prefix {pattern} suffix"}}
    mock_session.post.return_value = mock_resp

    success, msg = book_class(mock_session, 12345)
    assert success is True
    assert msg == "Successfully secured spot! (Already Registered)"
    assert mock_session.post.call_count == 1


def test_is_user_booked_for_schedule_expanded_fields() -> None:
    """Verifies is_user_booked_for_schedule catches all pre-scan signed flags."""
    # user_booked flag (snake_case and camelCase)
    assert is_user_booked_for_schedule({"user_booked": True}) is True
    assert is_user_booked_for_schedule({"user_booked": 1}) is True
    assert is_user_booked_for_schedule({"user_booked": "true"}) is True
    assert is_user_booked_for_schedule({"user_booked": "1"}) is True
    assert is_user_booked_for_schedule({"user_booked": "booked"}) is True
    assert is_user_booked_for_schedule({"user_booked": False}) is False
    assert is_user_booked_for_schedule({"user_booked": 0}) is False
    assert is_user_booked_for_schedule({"user_booked": "false"}) is False
    assert is_user_booked_for_schedule({"user_booked": None}) is False

    assert is_user_booked_for_schedule({"userBooked": True}) is True
    assert is_user_booked_for_schedule({"userBooked": 1}) is True
    assert is_user_booked_for_schedule({"userBooked": "true"}) is True
    assert is_user_booked_for_schedule({"userBooked": False}) is False
    assert is_user_booked_for_schedule({"userBooked": 0}) is False
    assert is_user_booked_for_schedule({"userBooked": None}) is False

    # num_user_signed count (snake_case and camelCase)
    assert is_user_booked_for_schedule({"num_user_signed": 1}) is True
    assert is_user_booked_for_schedule({"num_user_signed": 2}) is True
    assert is_user_booked_for_schedule({"num_user_signed": "1"}) is True
    assert is_user_booked_for_schedule({"num_user_signed": 0}) is False
    assert is_user_booked_for_schedule({"num_user_signed": "0"}) is False
    assert is_user_booked_for_schedule({"num_user_signed": None}) is False

    assert is_user_booked_for_schedule({"numUserSigned": 1}) is True
    assert is_user_booked_for_schedule({"numUserSigned": 2}) is True
    assert is_user_booked_for_schedule({"numUserSigned": "1"}) is True
    assert is_user_booked_for_schedule({"numUserSigned": 0}) is False
    assert is_user_booked_for_schedule({"numUserSigned": None}) is False

    # is_signed flag (snake_case and camelCase)
    assert is_user_booked_for_schedule({"is_signed": True}) is True
    assert is_user_booked_for_schedule({"is_signed": 1}) is True
    assert is_user_booked_for_schedule({"is_signed": "true"}) is True
    assert is_user_booked_for_schedule({"is_signed": "signed"}) is True
    assert is_user_booked_for_schedule({"is_signed": False}) is False
    assert is_user_booked_for_schedule({"is_signed": 0}) is False
    assert is_user_booked_for_schedule({"is_signed": "false"}) is False
    assert is_user_booked_for_schedule({"is_signed": "unsigned"}) is False
    assert is_user_booked_for_schedule({"is_signed": None}) is False

    assert is_user_booked_for_schedule({"isSigned": True}) is True
    assert is_user_booked_for_schedule({"isSigned": 1}) is True
    assert is_user_booked_for_schedule({"isSigned": False}) is False
    assert is_user_booked_for_schedule({"isSigned": None}) is False

    # user_signed and is_user_signed flags (snake_case and camelCase)
    assert is_user_booked_for_schedule({"user_signed": True}) is True
    assert is_user_booked_for_schedule({"user_signed": "registered"}) is True
    assert is_user_booked_for_schedule({"user_signed": False}) is False
    assert is_user_booked_for_schedule({"userSigned": True}) is True
    assert is_user_booked_for_schedule({"userSigned": False}) is False

    assert is_user_booked_for_schedule({"is_user_signed": True}) is True
    assert is_user_booked_for_schedule({"is_user_signed": False}) is False
    assert is_user_booked_for_schedule({"isUserSigned": True}) is True
    assert is_user_booked_for_schedule({"isUserSigned": False}) is False

    assert is_user_booked_for_schedule({"isUserSignedToSchedule": True}) is True
    assert is_user_booked_for_schedule({"isUserSignedToSchedule": False}) is False

    # cancelScheduleUser flag and cancellation actions
    assert is_user_booked_for_schedule({"cancelScheduleUser": True}) is True
    assert is_user_booked_for_schedule({"cancelScheduleUser": 1}) is True
    assert is_user_booked_for_schedule({"cancelScheduleUser": "true"}) is True
    assert (
        is_user_booked_for_schedule({"cancelScheduleUser": "cancelScheduleUser"})
        is True
    )
    assert (
        is_user_booked_for_schedule({"cancelScheduleUser": "cancel_schedule_user"})
        is True
    )
    assert (
        is_user_booked_for_schedule({"cancelScheduleUser": "cancel-schedule-user"})
        is True
    )
    assert is_user_booked_for_schedule({"cancelScheduleUser": "cancel"}) is True
    assert (
        is_user_booked_for_schedule({"cancelScheduleUser": "cancel_schedule"}) is True
    )
    assert (
        is_user_booked_for_schedule({"cancelScheduleUser": {"booking_id": 999}}) is True
    )
    assert is_user_booked_for_schedule({"cancelScheduleUser": False}) is False
    assert is_user_booked_for_schedule({"cancelScheduleUser": 0}) is False
    assert is_user_booked_for_schedule({"cancelScheduleUser": None}) is False

    # cancel_schedule_user flag
    assert is_user_booked_for_schedule({"cancel_schedule_user": True}) is True
    assert is_user_booked_for_schedule({"cancel_schedule_user": False}) is False

    # schedule_user / scheduleUser object inspection
    assert is_user_booked_for_schedule({"schedule_user": {"id": 12345}}) is True
    assert is_user_booked_for_schedule({"scheduleUser": {"id": 12345}}) is True
    assert is_user_booked_for_schedule({"schedule_user": None}) is False
    assert is_user_booked_for_schedule({"schedule_user": {}}) is False
    assert is_user_booked_for_schedule({"scheduleUser": {}}) is False

    # booking_option variations (camelCase, snake_case, kebab-case, and cancellation actions)
    assert is_user_booked_for_schedule({"booking_option": "cancelScheduleUser"}) is True
    assert (
        is_user_booked_for_schedule({"booking_option": "cancel_schedule_user"}) is True
    )
    assert (
        is_user_booked_for_schedule({"booking_option": "CANCEL_SCHEDULE_USER"}) is True
    )
    assert (
        is_user_booked_for_schedule({"booking_option": "cancel-schedule-user"}) is True
    )
    assert is_user_booked_for_schedule({"booking_option": "cancel"}) is True
    assert is_user_booked_for_schedule({"booking_option": "cancel_schedule"}) is True
    assert is_user_booked_for_schedule({"booking_option": "cancelBooking"}) is True
    assert is_user_booked_for_schedule({"booking_option": "book"}) is False
    assert is_user_booked_for_schedule({"booking_option": "join_waitlist"}) is False

    # bookingOption camelCase
    assert is_user_booked_for_schedule({"bookingOption": "cancelScheduleUser"}) is True
    assert (
        is_user_booked_for_schedule({"bookingOption": "cancel_schedule_user"}) is True
    )
    assert is_user_booked_for_schedule({"bookingOption": "cancel"}) is True
    assert is_user_booked_for_schedule({"bookingOption": "book"}) is False


def test_book_class_already_registered_raw_text_json_decode_error() -> None:
    """Verifies book_class detects already-registered from raw text even if json decoding fails."""
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "<html><body>Error: הנך רשום כבר לסדרה זו</body></html>"
    mock_resp.json.side_effect = ValueError("Invalid JSON")
    mock_session.post.return_value = mock_resp

    success, msg = book_class(mock_session, 12345)
    assert success is True
    assert msg == "Successfully secured spot! (Already Registered)"
    assert mock_session.post.call_count == 1


def test_is_user_booked_for_schedule_combinations() -> None:
    """Tests combinations where some flags are False but others are True."""
    # is_user_signed_to_schedule False, but user_booked True
    assert (
        is_user_booked_for_schedule(
            {
                "is_user_signed_to_schedule": False,
                "user_booked": True,
                "booking_option": "book",
            }
        )
        is True
    )

    # is_user_signed_to_schedule False, user_booked False, but num_user_signed 1
    assert (
        is_user_booked_for_schedule(
            {
                "is_user_signed_to_schedule": False,
                "user_booked": False,
                "num_user_signed": 1,
                "booking_option": "book",
            }
        )
        is True
    )

    # is_user_signed_to_schedule False, user_booked False, num_user_signed 0, but is_signed True
    assert (
        is_user_booked_for_schedule(
            {
                "is_user_signed_to_schedule": False,
                "user_booked": False,
                "num_user_signed": 0,
                "is_signed": True,
                "booking_option": "book",
            }
        )
        is True
    )
