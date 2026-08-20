from __future__ import annotations

from pathlib import Path

import pytest

from reality_travel.database import TravelDatabase
from reality_travel.service import TravelService


class FakeProviders:
    def __init__(self) -> None:
        self.street_available = True

    async def geocode(self, place: str):
        places = {
            "曼哈顿": ("美国，纽约，曼哈顿", 40.758, -73.986, "America/New_York", 18.0),
            "中央公园入口": ("中央公园入口，美国", 40.764, -73.973, "America/New_York", 22.0),
        }
        if place not in places:
            return None
        name, lat, lon, timezone, elevation = places[place]
        return {
            "query": place,
            "name": name,
            "latitude": lat,
            "longitude": lon,
            "timezone": timezone,
            "elevation_m": elevation,
            "source": "fake",
        }

    async def weather(self, latitude: float, longitude: float):
        return {
            "available": True,
            "status": "OK",
            "observed_at": "2026-08-14T08:30",
            "timezone": "America/New_York",
            "weather_text": "晴",
            "temperature_c": 22.0,
            "feels_like_c": 22.5,
            "humidity_percent": 55,
            "wind_kmh": 8.0,
            "wind_direction_deg": 90,
            "gust_kmh": 13.0,
            "elevation_m": 19.0,
        }

    async def street_view(self, latitude: float, longitude: float, *, heading=0, radius_m=500, pano_id=""):
        if not self.street_available:
            return {"available": False, "status": "ZERO_RESULTS", "message": "没有街景"}
        return {
            "available": True,
            "status": "OK",
            "pano_id": pano_id or "pano-1",
            "heading": heading,
            "capture_date": "2025-06",
            "panorama_position": {"latitude": latitude, "longitude": longitude},
            "image_url": "http://127.0.0.1:3023/media/streetview/test.jpg",
        }


@pytest.fixture
def service(tmp_path: Path):
    return TravelService(TravelDatabase(tmp_path / "travel.db"), FakeProviders())


@pytest.fixture
def postcard_service(tmp_path: Path):
    async def fake_image_generator(prompt: str):
        image = tmp_path / "postcard_test.png"
        image.write_bytes(b"fake-png")
        return image

    return TravelService(
        TravelDatabase(tmp_path / "postcard.db"), FakeProviders(),
        image_generator=fake_image_generator,
    )


@pytest.mark.asyncio
async def test_start_creates_journey_and_pending_arrival_quote(service: TravelService):
    result = await service.start("曼哈顿", "chengyu")
    assert result["data"]["ok"] is True
    assert result["data"]["archive_next_reply_as"] == "arrival_quote"
    assert result["data"]["event"]["quote_kind"] == "arrival_quote"
    assert service.db.active_journey("chengyu")["place_name"] == "美国，纽约，曼哈顿"


@pytest.mark.asyncio
async def test_timeline_event_can_be_hidden_and_restored(service: TravelService):
    result = await service.start("曼哈顿", "chengyu")
    journey_id = result["data"]["journey"]["journey_id"]
    event_id = result["data"]["event"]["event_id"]

    assert service.db.hide_event(event_id) is True
    assert service.db.events(journey_id) == []
    assert service.db.restore_event(event_id) is True
    assert [item["event_id"] for item in service.db.events(journey_id)] == [event_id]


@pytest.mark.asyncio
async def test_hidden_event_is_physically_purged_after_retention(service: TravelService):
    result = await service.start("曼哈顿", "chengyu")
    event_id = result["data"]["event"]["event_id"]
    assert service.db.hide_event(event_id) is True
    with service.db.connect() as conn:
        conn.execute(
            "UPDATE journey_events SET hidden_at='2020-01-01T00:00:00+00:00' WHERE event_id=?",
            (event_id,),
        )

    assert service.db.purge_hidden_events(retention_days=30) == 1
    assert service.db.event(event_id) is None


@pytest.mark.asyncio
async def test_start_pauses_previous_journey_without_overwriting_it(service: TravelService):
    first = await service.start("曼哈顿", "chengyu")
    result = await service.start("中央公园入口", "chengyu")
    assert result["data"]["ok"] is True
    assert service.db.active_journey("chengyu")["place_name"] == "中央公园入口，美国"
    saved_first = service.db.journey(first["data"]["journey"]["journey_id"])
    assert saved_first["status"] == "paused"
    assert len(service.db.events(saved_first["journey_id"])) == 1


@pytest.mark.asyncio
async def test_list_and_switch_resume_a_paused_journey(service: TravelService):
    first = await service.start("曼哈顿", "chengyu")
    second = await service.start("中央公园入口", "chengyu")
    listed = service.list_journeys("chengyu")
    assert len(listed["data"]["journeys"]) == 2

    switched = await service.switch_journey(place="曼哈顿", traveler_id="chengyu")
    assert switched["data"]["ok"] is True
    assert service.db.active_journey("chengyu")["journey_id"] == first["data"]["journey"]["journey_id"]
    assert service.db.journey(second["data"]["journey"]["journey_id"])["status"] == "paused"
    assert switched["data"]["event"]["event_type"] == "resume"


@pytest.mark.asyncio
async def test_look_turns_same_panorama(service: TravelService):
    await service.start("曼哈顿", "chengyu")
    result = await service.look("右", traveler_id="chengyu")
    assert result["data"]["ok"] is True
    assert result["data"]["journey"]["heading"] == 90.0
    assert result["data"]["street_view"]["pano_id"] == "pano-1"


@pytest.mark.asyncio
async def test_probe_move_stays_put_without_street_view(service: TravelService):
    await service.start("曼哈顿", "chengyu")
    before = service.db.active_journey("chengyu")
    service.providers.street_available = False
    result = await service.move(heading=90, distance_m=50, traveler_id="chengyu")
    after = service.db.active_journey("chengyu")
    assert result["data"]["code"] == "NO_CONTINUOUS_STREET_VIEW"
    assert (after["latitude"], after["longitude"]) == (before["latitude"], before["longitude"])


@pytest.mark.asyncio
async def test_named_move_updates_destination(service: TravelService):
    await service.start("曼哈顿", "chengyu")
    result = await service.move(destination="中央公园入口", traveler_id="chengyu")
    assert result["data"]["ok"] is True
    assert result["data"]["journey"]["place_name"] == "中央公园入口，美国"
    assert result["data"]["journey"]["distance_m"] > 0


@pytest.mark.asyncio
async def test_repeated_destination_refresh_failure_keeps_current_street_view(service: TravelService):
    started = await service.start("曼哈顿", "chengyu")
    before = service.db.active_journey("chengyu")
    service.providers.street_available = False

    result = await service.move(destination="曼哈顿", traveler_id="chengyu")
    after = service.db.active_journey("chengyu")

    assert result["data"]["ok"] is True
    assert result["data"]["street_view"]["available"] is False
    assert result["data"]["event"]["street_view"]["available"] is False
    assert after["street_view"] == before["street_view"]
    assert after["pano_id"] == started["data"]["journey"]["pano_id"]


@pytest.mark.asyncio
async def test_exact_words_attach_to_arrival_event(service: TravelService):
    started = await service.start("曼哈顿", "chengyu")
    event_id = started["data"]["event"]["event_id"]
    result = service.record_words(
        text="[测试原话] 抵达节点。",
        kind="arrival_quote",
        event_id=event_id,
        traveler_id="chengyu",
        source_message_id="fixture:123",
    )
    assert result["data"]["ok"] is True
    event = service.db.event(event_id)
    assert event["quote_text"] == "[测试原话] 抵达节点。"
    assert event["source_message_id"] == "fixture:123"


@pytest.mark.asyncio
async def test_travel_log_and_visible_words_are_stored_separately(service: TravelService):
    started = await service.start("曼哈顿", "chengyu")
    event_id = started["data"]["event"]["event_id"]

    logged = service.record_log(
        text="[测试旅行记录] 抵达曼哈顿，区分历史街景与当前天气。",
        event_id=event_id,
        traveler_id="chengyu",
    )
    assert logged["data"]["ok"] is True

    service.record_words(
        text="[测试可见回复] 小小，程渝已抵达。",
        kind="arrival_quote",
        event_id=event_id,
        traveler_id="chengyu",
    )
    event = service.db.event(event_id)
    assert event["summary"].startswith("[测试旅行记录]")
    assert event["quote_text"] == "[测试可见回复] 小小，程渝已抵达。"
    assert event["summary"] != event["quote_text"]


@pytest.mark.asyncio
async def test_departure_quote_can_be_attached_after_end(service: TravelService):
    await service.start("曼哈顿", "chengyu")
    ended = service.end("chengyu")
    event_id = ended["data"]["event"]["event_id"]
    saved = service.record_words(
        text="[测试离开原话] 旅程结束。",
        kind="departure_quote",
        event_id=event_id,
        traveler_id="chengyu",
    )
    assert saved["data"]["ok"] is True
    assert service.db.event(event_id)["quote_text"] == "[测试离开原话] 旅程结束。"
    assert service.db.active_journey("chengyu") is None


@pytest.mark.asyncio
async def test_postcard_archives_text_and_codex_image_metadata(postcard_service: TravelService):
    await postcard_service.start("曼哈顿", "chengyu")
    result = await postcard_service.create_postcard(
        text="[测试明信片] 寄给小小。",
        image_prompt="A quiet Manhattan morning postcard",
        traveler_id="chengyu",
    )
    assert result["data"]["ok"] is True
    assert result["data"]["image_generated"] is True
    event = result["data"]["event"]
    assert event["quote_kind"] == "postcard"
    assert event["quote_text"] == "[测试明信片] 寄给小小。"
    assert event["metadata"]["postcard_image"]["provider"] == "external_module"
    assert event["metadata"]["postcard_image"]["image_url"].endswith("/media/postcards/postcard_test.png")


@pytest.mark.asyncio
async def test_postcard_keeps_text_when_image_generation_fails(tmp_path: Path):
    async def failing_image_generator(prompt: str):
        raise RuntimeError("temporary failure")

    service = TravelService(
        TravelDatabase(tmp_path / "failed-postcard.db"), FakeProviders(),
        image_generator=failing_image_generator,
    )
    await service.start("曼哈顿", "chengyu")
    result = await service.create_postcard(
        text="[测试明信片] 即使生图失败也保存正文。",
        image_prompt="a postcard",
        traveler_id="chengyu",
    )
    assert result["data"]["ok"] is True
    assert result["data"]["image_generated"] is False
    assert result["data"]["event"]["quote_text"] == "[测试明信片] 即使生图失败也保存正文。"
