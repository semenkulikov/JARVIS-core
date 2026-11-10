import datetime

from jarvis.core.schedule import workout_summary

CFG = {"workout_time": "12:00", "workout_days": [0, 2]}  # Monday, Wednesday


def test_before_todays_workout():
    assert workout_summary(CFG, datetime.datetime(2026, 11, 9, 10, 30)).endswith("До тренировки один час тридцать минут.")


def test_next_workout_day():
    out = workout_summary(CFG, datetime.datetime(2026, 11, 10, 9, 0))  # Tuesday
    assert "Сегодня тренировки нет, следующая завтра в" in out


def test_unconfigured_schedule():
    assert workout_summary({"workout_time": "12:00", "workout_days": []}).startswith("Расписание тренировок")
