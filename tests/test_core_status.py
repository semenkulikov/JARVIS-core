import datetime

import pytest

from jarvis.core import status as S

NOW = datetime.datetime(2026, 11, 10, 14, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
CFG = {"cache_max_age_h": 2.5, "cache_stale_read_max_age_h": 3}


@pytest.mark.parametrize("updated,policy", [("2026-11-10T13:00:00+01:00", "fresh"), ("2026-11-10T11:15:00+01:00", "stale"),
                                            ("2026-11-10T10:30:00+01:00", "old"), ("2026-11-09T23:59:00+01:00", "old"),
                                            ("2026-11-10T15:00:00+01:00", "old"), ("2026-11-10T14:03:00+01:00", "fresh"),
                                            ("2026-11-10T14:14:59+01:00", "fresh"), ("2026-11-10T14:16:00+01:00", "old")])
def test_cache_age_policy(updated, policy):
    assert S.cache_age_policy(updated, CFG, NOW)[0] == policy


def test_derive_field_falls_back_to_summary_sentences():
    data = {"text": "Сводка. Белка 90 грамм. Встреча в три.", "food": ""}
    assert S.derive_field(data, "food") == ("Белка 90 грамм.", "derived")
    assert S.derive_field({"deploy": ["сайт", "бот"]}, "deploy") == ("сайт бот", "field")
    assert S.derive_field({"text": "Сводка."}, "food") == (None, None)


def test_status_answer_restamps_and_reports_missing():
    now = datetime.datetime.now().astimezone().replace(microsecond=0)
    data = {"updated": now.isoformat(), "text": "Данные на 09:00. Всё спокойно.", "today": ""}
    policy, text, _ = S.status_answer(data, None, CFG)
    assert policy == "fresh" and text.startswith("По данным на ") and text.endswith("сэр. Всё спокойно.")
    assert S.status_answer(data, "today", CFG)[0] == "missing"


def test_future_skew_is_configurable():
    assert S.cache_age_policy("2026-11-10T14:03:00+01:00", {**CFG, "cache_future_skew_min": 0}, NOW)[0] == "old"
