import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timezone
from fetch_schedule import get_israel_time, generate_html_table, TARGET_CONFIG

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
    assert TARGET_CONFIG['Sunday']['coach'] == 'not דניאל טנג\'י'
    assert TARGET_CONFIG['Tuesday']['coach'] == 'not דניאל טנג\'י'
    assert TARGET_CONFIG['Thursday']['coach'] == 'not דניאל טנג\'י'
    assert TARGET_CONFIG['Friday']['coach'] == 'not דניאל טנג\'י'

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
