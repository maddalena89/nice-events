"""The forecast for Nice, one word per day, for the small weather mark beside each
day's heading on the site.

Fetched once per build from Open-Meteo (free, no account, no key) and baked into
the page, so visitors' phones never call a weather service and nothing about
them is sent anywhere. Sixteen days is as far as the free forecast goes; days
past it simply get no mark.

Never fatal. No network, a slow answer, a changed format: the build carries on
with no weather at all, exactly as the site looked before this existed.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

NICE = (43.70, 7.27)
URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
       "&daily=weather_code&timezone=Europe%2FParis&forecast_days=16")


def kind(code: int) -> str | None:
    """WMO weather code -> one of the six marks the page can draw."""
    if code in (0, 1):
        return "sun"
    if code == 2:
        return "part"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if 95 <= code <= 99:
        return "storm"
    return None


def fetch_forecast(timeout: float = 8.0) -> dict[str, str]:
    """{"2026-09-18": "sun", ...}, or {} if anything goes wrong."""
    try:
        r = httpx.get(URL.format(lat=NICE[0], lon=NICE[1]), timeout=timeout)
        r.raise_for_status()
        daily = r.json()["daily"]
        out = {}
        for day, code in zip(daily["time"], daily["weather_code"]):
            k = kind(int(code)) if code is not None else None
            if k:
                out[day] = k
        return out
    except Exception as e:                     # never let the weather stop a build
        log.warning("weather: no forecast this build (%s)", e)
        return {}
