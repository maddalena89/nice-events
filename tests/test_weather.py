"""The weather mark beside each day's heading. It must never be able to stop a
build, and a code the page cannot draw must come out as no mark, not a wrong one."""
import httpx

from niceevents import weather


def test_codes_map_to_the_marks_the_page_draws():
    assert weather.kind(0) == "sun"
    assert weather.kind(2) == "part"
    assert weather.kind(3) == "cloud"
    assert weather.kind(45) == "fog"
    assert weather.kind(61) == "rain" and weather.kind(81) == "rain"
    assert weather.kind(95) == "storm"
    assert weather.kind(73) == "snow"
    assert weather.kind(12345) is None


def test_no_network_means_no_weather_not_a_failed_build(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(weather.httpx, "get", boom)
    assert weather.fetch_forecast() == {}


def test_a_changed_answer_means_no_weather(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"something": "else"}
    monkeypatch.setattr(weather.httpx, "get", lambda *a, **k: R())
    assert weather.fetch_forecast() == {}
