import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from fetch_schedule import get_israel_time, generate_html_table, TARGET_CONFIG, select_target_entry, book_class

def test_get_israel_time():
    isr_now = get_israel_time()
    assert isr_now is not None
    now_utc = datetime.now(timezone.utc)
    diff_hours = (isr_now - now_utc).total_seconds() / 3600
    assert 1.9 <= diff_hours <= 3.1

def test_generate_html_table():
    classes_info = [
        {
            'day': 'Thursday',
            'date': '2026-07-09',
            'hour': '08:30',
            'training': 'WOD',
            'was_booked': True,
            'best_match': True
        }
    ]
    html = generate_html_table(classes_info, '2026-07-09', status_html='Confirmed')
    assert "Gorillot Booking Report" in html
    assert "WOD" in html
    assert "SECURED" in html
    assert "padding: 24px;" in html  # Verify 8px grid body padding
    assert "padding: 16px;" in html  # Verify 8px grid cell padding

def test_target_config_fallback():
    assert TARGET_CONFIG is not None
    assert TARGET_CONFIG['Sunday']['series_id'] == 187541
    assert TARGET_CONFIG['Tuesday']['series_id'] == 3300
    assert TARGET_CONFIG['Thursday']['series_id'] == 187542
    assert TARGET_CONFIG['Friday']['series_id'] == 2498

def test_category_matching_prioritizes_box_categories():
    target_type = "WOD"
    events = [
        {
            'id': 1,
            'time': '18:30',
            'box_categories': {'name': 'Weightlifting'},
            'series': {'series_name': 'WOD ,שלישי,18:30'},
            'coach': {'full_name': 'רוני שחם'}
        },
        {
            'id': 2,
            'time': '18:30',
            'box_categories': {'name': 'WOD '},
            'series': {'series_name': 'W.O.D,Tuesday,18:30'},
            'coach': {'full_name': 'אופיר רודיטי'}
        }
    ]
    
    def matches_training_type(entry_item):
        cat_name = ((entry_item.get('box_categories') or {}).get('name') or '').strip().lower()
        if cat_name:
            return target_type.lower() in cat_name
        ser_name = ((entry_item.get('series') or {}).get('series_name') or '').strip().lower()
        return target_type.lower() in ser_name

    matched = [e for e in events if matches_training_type(e)]
    assert len(matched) == 1
    assert matched[0]['id'] == 2
    assert matched[0]['coach']['full_name'] == 'אופיר רודיטי'

def test_select_target_entry():
    entries = [
        {'id': 10, 'coach': {'full_name': 'דניאל טנג\'י'}},
        {'id': 20, 'coach': {'full_name': 'אופיר רודיטי'}}
    ]
    res = select_target_entry(entries, "not דניאל טנג'י")
    assert res is not None
    assert res['id'] == 20

def test_select_target_entry_bypasses_coach_if_series_id_matches():
    entries = [
        {
            'id': 52500490,
            'time': '08:30',
            'coach': {'full_name': 'דניאל טנג\'י'},
            'series': {'id': 2498, 'series_name': 'W.O.D,Friday,08:30'},
            'booking_option': 'book',
            'free': 5
        },
        {
            'id': 52504730,
            'time': '08:30',
            'coach': {'full_name': 'שיראל ריצמן'},
            'series': {'id': 9999, 'series_name': 'WOD ,Friday,08:30'},
            'booking_option': 'book',
            'free': 5
        }
    ]
    res = select_target_entry(entries, target_time="08:30", target_series_id=2498)
    assert res is not None
    assert res['id'] == 52500490
    assert res['series']['id'] == 2498

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
            "code": 513
        },
        "data": None
    }
    mock_session.post.return_value = mock_resp

    success, msg = book_class(mock_session, 52504730)
    assert success is False
    assert "Class is full" in msg
    assert "Status 513" in msg
    assert mock_session.post.call_count == 1
