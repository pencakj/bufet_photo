"""Sunrise/sunset calculations and adaptive capture interval."""
from datetime import datetime

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

    2 min near sunrise/sunset (±1 h), 10 min during daytime, 30 min at night.
    """
    now = now or datetime.now(TZ)
    sunrise, sunset = sun_times(now)
    t = now.timestamp()

    if not (sunrise.timestamp() <= t <= sunset.timestamp()):
        return 1800

    near_sunrise = abs(t - sunrise.timestamp()) <= 3600
    near_sunset = abs(t - sunset.timestamp()) <= 3600
    return 120 if (near_sunrise or near_sunset) else 600
