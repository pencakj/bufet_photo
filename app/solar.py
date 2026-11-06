"""Sunrise/sunset calculations and adaptive capture interval."""
from datetime import datetime, timedelta, time

import pytz
from astral import LocationInfo
from astral.sun import sun

TZ = pytz.timezone("Europe/Prague")
LOCATION = LocationInfo("Chalupa", "Czech Republic", "Europe/Prague", 50.7056489, 15.6749678)
LOCATION.observer.elevation = 1350


def sun_times(when: datetime | None = None) -> tuple[datetime, datetime]:
    when = when or datetime.now()
    s = sun(LOCATION.observer, date=when)
    return s["sunrise"], s["sunset"]


def is_daytime(now: datetime | None = None) -> bool:
    now = now or datetime.now(TZ)
    sunrise, sunset = sun_times(now)
    return sunrise.timestamp() <= now.timestamp() <= sunset.timestamp()


def capture_interval_seconds(now: datetime | None = None) -> int:
    """Return the current photo capture interval in seconds.

    5 min for 30 min after sunrise/before sunset, 30 min by day, 1 h at night.
    """
    now = now or datetime.now(TZ)
    sunrise, sunset = sun_times(now)
    t = now.timestamp()

    if not (sunrise.timestamp() <= t < sunset.timestamp()):
        return 3600

    near_sunrise = t < sunrise.timestamp() + 1800
    near_sunset = t >= sunset.timestamp() - 1800
    return 300 if (near_sunrise or near_sunset) else 1800


def next_capture_time(now: datetime | None = None) -> datetime:
    """Next scheduled shot, including solar boundaries that hourly sleeps miss.

    Day/night shots use local half-hours/full hours. Each solar window gets
    six shots anchored to its exact start. Epoch-based grid stepping handles
    both repeated and missing local hours at DST transitions.
    """
    now = (now or datetime.now(TZ)).astimezone(TZ)
    solar = {}

    def times(day):
        if day not in solar:
            solar[day] = sun_times(TZ.localize(datetime.combine(day, time.min)))
        return solar[day]

    candidates = []
    for offset in (0, 1):
        sunrise, sunset = times(now.date() + timedelta(days=offset))
        for start in (sunrise, sunset - timedelta(minutes=30)):
            for shot in range(6):
                candidate = start + timedelta(minutes=5 * shot)
                if candidate > now:
                    candidates.append(candidate)

    tick = (int(now.timestamp()) // 1800 + 1) * 1800
    for step in range(100):
        candidate = datetime.fromtimestamp(tick + step * 1800, TZ)
        sunrise, sunset = times(candidate.date())
        daylight = sunrise <= candidate < sunset
        near = (sunrise <= candidate < sunrise + timedelta(minutes=30)
                or sunset - timedelta(minutes=30) <= candidate < sunset)
        if not near and (daylight or candidate.minute == 0):
            candidates.append(candidate)
            break
    return min(candidates).astimezone(TZ)
