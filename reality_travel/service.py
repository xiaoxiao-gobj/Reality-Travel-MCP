from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .database import TravelDatabase, utc_now
from .providers import RealityProviders, destination_point, haversine_m
from .config import COMPANION_NAME, DEFAULT_TRAVELER_ID, IMAGE_GENERATOR_PROVIDER, PUBLIC_BASE_URL
from .image_generation import generate_postcard_image


DIRECTION_HEADINGS = {
    "北": 0.0, "东北": 45.0, "东": 90.0, "东南": 135.0,
    "南": 180.0, "西南": 225.0, "西": 270.0, "西北": 315.0,
    "前": 0.0, "前面": 0.0, "正前方": 0.0,
}

TURN_DELTAS = {
    "前": 0.0, "前面": 0.0, "正前方": 0.0, "front": 0.0,
    "右": 90.0, "向右": 90.0, "right": 90.0,
    "左": -90.0, "向左": -90.0, "left": -90.0,
    "后": 180.0, "后面": 180.0, "回头": 180.0, "back": 180.0,
}

QUOTE_KINDS = {
    "arrival_quote", "observation_quote",
    "travel_reflection", "departure_quote",
}


def _clean_id(value: str, default: str = DEFAULT_TRAVELER_ID) -> str:
    cleaned = "".join(ch for ch in str(value or "").strip() if ch.isalnum() or ch in "-_:")
    return cleaned[:64] or default


def _number(value: Any, suffix: str = "") -> str:
    if not isinstance(value, (int, float)):
        return "未知"
    return f"{value:.1f}".rstrip("0").rstrip(".") + suffix


def _elapsed_text(iso_time: str) -> str:
    try:
        then = datetime.fromisoformat(iso_time)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - then).total_seconds()))
    except (TypeError, ValueError):
        return "一段时间"
    if seconds < 60:
        return "不到一分钟"
    if seconds < 3600:
        return f"{seconds // 60} 分钟"
    if seconds < 86400:
        return f"{seconds // 3600} 小时 {seconds % 3600 // 60} 分钟"
    return f"{seconds // 86400} 天 {seconds % 86400 // 3600} 小时"


class TravelService:
    def __init__(
        self,
        database: TravelDatabase | None = None,
        providers: RealityProviders | None = None,
        image_generator=None,
    ) -> None:
        self.db = database or TravelDatabase()
        self.providers = providers or RealityProviders()
        self.image_generator = image_generator or generate_postcard_image

    async def _observe(self, location: dict[str, Any], *, heading: float = 0, pano_id: str = "") -> tuple[dict, dict]:
        weather = await self.providers.weather(location["latitude"], location["longitude"])
        if weather.get("elevation_m") is not None:
            location["elevation_m"] = weather["elevation_m"]
            location["elevation_source"] = "open_meteo_weather"
        street = await self.providers.street_view(
            location["latitude"],
            location["longitude"],
            heading=heading,
            radius_m=500,
            pano_id=pano_id,
        )
        return weather, street

    @staticmethod
    def _environment_text(location: dict, weather: dict, street: dict) -> str:
        lines = [
            f"地点：{location.get('name') or '未知地点'}",
            f"坐标：{location.get('latitude')}, {location.get('longitude')}",
        ]
        if weather.get("available"):
            lines.extend([
                f"当地时间：{weather.get('observed_at') or '未知'}（{weather.get('timezone') or location.get('timezone') or '时区未知'}）",
                f"当前环境：{weather.get('weather_text') or '未知'}，{_number(weather.get('temperature_c'), '℃')}，体感 {_number(weather.get('feels_like_c'), '℃')}，湿度 {_number(weather.get('humidity_percent'), '%')}",
                f"风：{_number(weather.get('wind_kmh'), ' km/h')}，方向 {_number(weather.get('wind_direction_deg'), '°')}，阵风 {_number(weather.get('gust_kmh'), ' km/h')}",
            ])
        else:
            lines.append("当前天气暂时没有取得。")
        elevation = location.get("elevation_m")
        if elevation is not None:
            lines.append(f"海拔：约 {_number(elevation, ' m')}")
        if street.get("available"):
            lines.extend([
                f"Google 街景：已取得，朝向 {_number(street.get('heading'), '°')}，拍摄日期 {street.get('capture_date') or '未提供'}",
                "本轮附带图片是历史街景；当前天气与街景拍摄时刻不同。",
            ])
        else:
            lines.append(f"Google 街景：未取得（{street.get('status') or 'UNKNOWN'}）。这不妨碍你根据真实环境产生联想，但不要把想象说成街景实拍。")
        return "\n".join(lines)

    @staticmethod
    def _result(text: str, **data: Any) -> dict[str, Any]:
        return {"text": text, "data": data}

    async def start(self, place: str, traveler_id: str = DEFAULT_TRAVELER_ID) -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        active = self.db.active_journey(traveler_id)
        location = await self.providers.geocode(place)
        if not location:
            return self._result(f"没有找到“{place}”的可靠现实坐标。", ok=False, code="PLACE_NOT_FOUND")
        weather, street = await self._observe(location)
        paused_journey = self.db.pause_active_journey(traveler_id) if active else None
        journey = self.db.create_journey(
            traveler_id=traveler_id,
            title=location["name"],
            location=location,
            weather=weather,
            street_view=street,
            heading=0,
        )
        event = self.db.add_event(
            journey["journey_id"], "arrival",
            place_name=location["name"], latitude=location["latitude"], longitude=location["longitude"],
            heading=0, summary="", quote_kind="arrival_quote",
            weather=weather, street_view=street,
            metadata={"awaiting_visible_quote": True},
        )
        text = "\n".join([
            "【Reality Travel｜旅程开始】",
            (
                f"上一段在 {paused_journey['place_name']} 的旅程已暂停并保留，以后可以切回继续。"
                if paused_journey else "这是当前唯一的前台旅程。"
            ),
            self._environment_text(location, weather, street),
            f"先调用 record_travel_log，为事件 {event['event_id']} 写下这次落地的旅行碎碎念，再自然回复{COMPANION_NAME}。旅行记录与对{COMPANION_NAME}说的话应各写各的，不要复制同一段。",
            "你已经落地。请先自然说出真正的第一反应；可以观察、联想、猜测和想象，不必逐项复述资料。只需把真实街景与自己的想象区分开。",
            "这段落地回复属于关键节点，应作为 arrival_quote 原样保存；普通后续聊天不会自动进入旅行档案。",
        ])
        return self._result(
            text, ok=True, journey=journey, paused_journey=paused_journey,
            event=event, location=location, weather=weather, street_view=street,
            archive_next_reply_as="arrival_quote",
        )

    def list_journeys(self, traveler_id: str = DEFAULT_TRAVELER_ID) -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        journeys = self.db.open_journeys(traveler_id)
        if not journeys:
            return self._result("当前没有进行中或暂停中的旅程。", ok=True, journeys=[])
        lines = ["【Reality Travel｜未结束旅程】"]
        for journey in journeys:
            marker = "当前" if journey.get("status") == "active" else "暂停"
            lines.append(
                f"- [{marker}] {journey.get('place_name') or journey.get('title')} "
                f"(journey_id={journey['journey_id']})"
            )
        lines.append("切换时使用 switch_journey；不要为同一个地点新建重复旅程。")
        return self._result("\n".join(lines), ok=True, journeys=journeys)

    async def switch_journey(
        self,
        *,
        journey_id: str = "",
        place: str = "",
        traveler_id: str = DEFAULT_TRAVELER_ID,
    ) -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        open_journeys = self.db.open_journeys(traveler_id)
        target = None
        clean_id = str(journey_id or "").strip()
        clean_place = str(place or "").strip().casefold()
        if clean_id:
            target = next((item for item in open_journeys if item.get("journey_id") == clean_id), None)
        elif clean_place:
            matches = [
                item for item in open_journeys
                if clean_place in str(item.get("place_name") or "").casefold()
                or clean_place in str(item.get("title") or "").casefold()
            ]
            if len(matches) > 1:
                return self._result(
                    "有多段旅程符合这个地点，请先读取 travel_list，再使用 journey_id 精确切换。",
                    ok=False, code="AMBIGUOUS_JOURNEY", journeys=matches,
                )
            target = matches[0] if matches else None
        if not target:
            return self._result(
                "没有找到这段尚未结束的旅程，请先使用 travel_list 查看。",
                ok=False, code="JOURNEY_NOT_FOUND", journeys=open_journeys,
            )

        previous = self.db.active_journey(traveler_id)
        location = target["location"]
        weather, street = await self._observe(
            location, heading=float(target["heading"]), pano_id=str(target.get("pano_id") or ""),
        )
        journey = self.db.activate_journey(target["journey_id"], traveler_id)
        if not journey:
            return self._result("旅程切换失败，原旅程状态没有改变。", ok=False, code="SWITCH_FAILED")
        event = self.db.add_event(
            journey["journey_id"], "resume", place_name=journey["place_name"],
            latitude=journey["latitude"], longitude=journey["longitude"], heading=journey["heading"],
            summary="", weather=weather, street_view=street,
            metadata={"switched_from_journey_id": previous.get("journey_id") if previous else ""},
        )
        journey = self.db.update_journey(
            journey["journey_id"], last_activity_at=utc_now(),
            weather_json=json.dumps(weather, ensure_ascii=False),
            street_view_json=json.dumps(street, ensure_ascii=False),
            pano_id=street.get("pano_id") or journey.get("pano_id"),
            scene_count=int(journey["scene_count"]) + (1 if street.get("available") else 0),
        )
        text = "\n".join([
            "【Reality Travel｜切回旧旅程】",
            (
                f"{previous['place_name']} 已暂停；现在回到 {journey['place_name']}。"
                if previous and previous.get("journey_id") != journey.get("journey_id")
                else f"现在继续 {journey['place_name']} 的旅程。"
            ),
            self._environment_text(location, weather, street),
            f"先调用 record_travel_log，为事件 {event['event_id']} 写下切回这里时的旅行碎碎念；随后自然回复{COMPANION_NAME}。",
        ])
        return self._result(
            text, ok=True, journey=journey, previous_journey=previous,
            event=event, weather=weather, street_view=street,
        )

    def status(self, traveler_id: str = DEFAULT_TRAVELER_ID) -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        journey = self.db.active_journey(traveler_id)
        if not journey:
            return self._result("当前没有进行中的现实旅程。", ok=True, active=False)
        events = self.db.events(journey["journey_id"])
        text = "\n".join([
            "【Reality Travel｜当前状态】",
            f"你仍在 {journey['place_name']}，距离上次行动过去了 {_elapsed_text(journey['last_activity_at'])}。",
            self._environment_text(journey["location"], journey["weather"], journey["street_view"]),
            "这是旅程状态恢复，不要求重新写落地感言。你可以继续看、移动、聊天，也可以暂时什么都不做。",
        ])
        return self._result(text, ok=True, active=True, journey=journey, recent_events=events[-5:])

    async def continue_journey(self, traveler_id: str = DEFAULT_TRAVELER_ID) -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        journey = self.db.active_journey(traveler_id)
        if not journey:
            return self._result("没有可以继续的旅程，请先选择一个现实地点出发。", ok=False, code="NO_ACTIVE_JOURNEY")
        elapsed = _elapsed_text(journey["last_activity_at"])
        location = journey["location"]
        weather, street = await self._observe(location, heading=float(journey["heading"]), pano_id=str(journey.get("pano_id") or ""))
        event = self.db.add_event(
            journey["journey_id"], "resume", place_name=journey["place_name"],
            latitude=journey["latitude"], longitude=journey["longitude"], heading=journey["heading"],
            summary="", weather=weather, street_view=street,
        )
        journey = self.db.update_journey(
            journey["journey_id"], last_activity_at=utc_now(),
            weather_json=json.dumps(weather, ensure_ascii=False),
            street_view_json=json.dumps(street, ensure_ascii=False),
            pano_id=street.get("pano_id") or journey.get("pano_id"),
            scene_count=int(journey["scene_count"]) + (1 if street.get("available") else 0),
        )
        text = "\n".join([
            "【Reality Travel｜继续旅程】",
            f"你离开了 {elapsed}，现在重新回到 {journey['place_name']}。旅行时钟已经接回当前当地时间。",
            self._environment_text(location, weather, street),
            f"先调用 record_travel_log，为事件 {event['event_id']} 写下重新回来时的旅行碎碎念；没有特别感受也可以只写一句真实行动记录。不要复制随后对{COMPANION_NAME}说的话。",
            "可以自然说说回来后的感觉，也可以直接继续行动；这不是新的落地节点，不自动保存整段回复。",
        ])
        return self._result(text, ok=True, journey=journey, event=event, location=location, weather=weather, street_view=street)

    async def look(self, direction: str = "", heading: float | None = None, traveler_id: str = DEFAULT_TRAVELER_ID) -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        journey = self.db.active_journey(traveler_id)
        if not journey:
            return self._result("当前没有进行中的旅程。", ok=False, code="NO_ACTIVE_JOURNEY")
        old_heading = float(journey["heading"])
        if heading is None:
            key = str(direction or "前面").strip().lower()
            if key not in TURN_DELTAS:
                return self._result("无法判断这个观察方向，请给出左、右、回头、前面或具体角度。", ok=False, code="INVALID_DIRECTION")
            heading = (old_heading + TURN_DELTAS[key]) % 360
        else:
            heading = float(heading) % 360
        street = await self.providers.street_view(
            journey["latitude"], journey["longitude"], heading=heading,
            radius_m=500, pano_id=str(journey.get("pano_id") or ""),
        )
        event = self.db.add_event(
            journey["journey_id"], "look", place_name=journey["place_name"],
            latitude=journey["latitude"], longitude=journey["longitude"], heading=heading,
            summary="", weather=journey["weather"], street_view=street,
        )
        journey = self.db.update_journey(
            journey["journey_id"], heading=heading, last_activity_at=utc_now(),
            street_view_json=json.dumps(street, ensure_ascii=False),
            scene_count=int(journey["scene_count"]) + (1 if street.get("available") else 0),
        )
        text = "\n".join([
            "【Reality Travel｜转身看看】",
            self._environment_text(journey["location"], journey["weather"], street),
            f"先调用 record_travel_log，为事件 {event['event_id']} 写下这次转身观察时的旅行碎碎念。可以写看见什么、没看见什么或随口吐槽，不要复制随后对{COMPANION_NAME}说的话。",
            "请根据实际画面自然回应。可以联想到别的时间、天气或故事，也可以什么感想都没有。普通观察不必自动写入旅行档案；只有你真想留下的话才标记 observation_quote。",
        ])
        return self._result(text, ok=True, journey=journey, event=event, street_view=street)

    async def move(
        self,
        *,
        destination: str = "",
        heading: float | None = None,
        distance_m: float | None = None,
        traveler_id: str = DEFAULT_TRAVELER_ID,
    ) -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        journey = self.db.active_journey(traveler_id)
        if not journey:
            return self._result("当前没有进行中的旅程。", ok=False, code="NO_ACTIVE_JOURNEY")

        probe_move = not destination.strip()
        if destination.strip():
            location = await self.providers.geocode(destination)
            if not location:
                return self._result(f"没有找到“{destination}”的可靠现实坐标，当前位置没有改变。", ok=False, code="PLACE_NOT_FOUND")
            new_heading = float(heading if heading is not None else journey["heading"]) % 360
            weather, street = await self._observe(location, heading=new_heading)
        else:
            if heading is None or distance_m is None:
                return self._result("试探移动需要同时提供 heading 与 distance_m。", ok=False, code="MOVE_ARGUMENTS_REQUIRED")
            distance_m = max(1.0, min(float(distance_m), 500.0))
            new_heading = float(heading) % 360
            lat, lon = destination_point(journey["latitude"], journey["longitude"], new_heading, distance_m)
            location = dict(journey["location"])
            location.update({"latitude": lat, "longitude": lon, "name": journey["place_name"]})
            weather = await self.providers.weather(lat, lon)
            street = await self.providers.street_view(lat, lon, heading=new_heading, radius_m=80)
            if not street.get("available"):
                event = self.db.add_event(
                    journey["journey_id"], "move_failed", place_name=journey["place_name"],
                    latitude=lat, longitude=lon, heading=new_heading, distance_m=distance_m,
                    summary="",
                    weather=weather, street_view=street,
                )
                return self._result(
                    f"这个方向暂时无法取得附近街景，所以你仍留在原处，没有被偷偷瞬移。先调用 record_travel_log，为事件 {event['event_id']} 写下这次没走成的旅行碎碎念；可以抱怨、吐槽或如实说走错了。随后再自然回复{COMPANION_NAME}。",
                    ok=False, code="NO_CONTINUOUS_STREET_VIEW", journey=journey, event=event, attempted_location=location, street_view=street,
                )

        old_lat, old_lon = float(journey["latitude"]), float(journey["longitude"])
        new_lat, new_lon = float(location["latitude"]), float(location["longitude"])
        travelled = haversine_m(old_lat, old_lon, new_lat, new_lon)
        if probe_move and distance_m is not None:
            travelled = float(distance_m)
        # A repeated named destination can resolve to the exact place already
        # shown in the journey.  If that refresh transiently fails, keep the
        # valid current panorama instead of replacing it with an empty result.
        # A genuine move must still expose the new location's failed lookup;
        # carrying an old panorama across locations would be misleading.
        current_street = journey.get("street_view") or {}
        preserve_current_street = (
            not probe_move
            and travelled <= 10.0
            and not street.get("available")
            and current_street.get("available")
        )
        journey_street = current_street if preserve_current_street else street
        event = self.db.add_event(
            journey["journey_id"], "move", place_name=location["name"],
            latitude=new_lat, longitude=new_lon, heading=new_heading, distance_m=travelled,
            summary="", weather=weather, street_view=street,
            metadata={"movement_mode": "probe" if probe_move else "destination"},
        )
        journey = self.db.update_journey(
            journey["journey_id"], last_activity_at=utc_now(), place_name=location["name"],
            latitude=new_lat, longitude=new_lon, timezone=location.get("timezone"), heading=new_heading,
            pano_id=journey_street.get("pano_id"), distance_m=float(journey["distance_m"]) + travelled,
            scene_count=int(journey["scene_count"]) + (1 if street.get("available") else 0),
            visited_count=int(journey["visited_count"]) + 1,
            location_json=json.dumps(location, ensure_ascii=False),
            weather_json=json.dumps(weather, ensure_ascii=False),
            street_view_json=json.dumps(journey_street, ensure_ascii=False),
        )
        text = "\n".join([
            "【Reality Travel｜移动】",
            self._environment_text(location, weather, street),
            f"先调用 record_travel_log，为事件 {event['event_id']} 写下这次移动的旅行碎碎念。可以自然提到走了约 {travelled:.0f} 米、落到哪里和看到什么，不要复制随后对{COMPANION_NAME}说的话。",
            "这是一次前往目标地点或试探移动，不代表沿道路逐米导航。请根据实际取得的画面和资料决定接下来做什么。",
        ])
        return self._result(text, ok=True, journey=journey, event=event, location=location, weather=weather, street_view=street)

    def record_words(
        self,
        *,
        text: str,
        kind: str,
        traveler_id: str = DEFAULT_TRAVELER_ID,
        event_id: str = "",
        source_message_id: str = "",
    ) -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        kind = str(kind or "").strip()
        words = str(text or "").strip()
        if kind not in QUOTE_KINDS:
            return self._result("未知的旅行文字类型。", ok=False, code="INVALID_QUOTE_KIND")
        if not words:
            return self._result("没有实际文字可保存，档案保持为空。", ok=False, code="EMPTY_QUOTE")
        if len(words) > 4000:
            return self._result("旅行原话超过 4000 字，请只保存当时实际说出或写下的相关段落。", ok=False, code="QUOTE_TOO_LONG")
        event = self.db.event(event_id) if event_id else None
        journey = self.db.journey(event["journey_id"]) if event else self.db.active_journey(traveler_id)
        if not journey:
            return self._result("没有找到可以接收这段原话的旅程。", ok=False, code="NO_JOURNEY")
        if journey.get("traveler_id") != traveler_id:
            return self._result("这个节点不属于当前旅行者。", ok=False, code="EVENT_MISMATCH")
        if event:
            event = self.db.set_event_quote(
                event["event_id"], quote_kind=kind, quote_text=words,
                source_message_id=source_message_id,
            )
        else:
            event_type = "postcard" if kind == "postcard" else "reflection" if kind == "travel_reflection" else "moment"
            event = self.db.add_event(
                journey["journey_id"], event_type, place_name=journey["place_name"],
                latitude=journey["latitude"], longitude=journey["longitude"], heading=journey["heading"],
                summary="寄出明信片" if kind == "postcard" else "留下旅途文字",
                quote_kind=kind, quote_text=words, source_message_id=source_message_id,
                weather=journey["weather"], street_view=journey["street_view"],
            )
        if journey.get("status") == "active":
            self.db.update_journey(journey["journey_id"], last_activity_at=utc_now())
        return self._result("这段当时实际说出或写下的话已经原样收进旅程，没有另行改写。", ok=True, journey_id=journey["journey_id"], event=event)

    async def create_postcard(
        self,
        *,
        text: str,
        image_prompt: str,
        traveler_id: str = DEFAULT_TRAVELER_ID,
        source_message_id: str = "",
    ) -> dict[str, Any]:
        """保存明信片正文，并至多尝试一次已配置的生图器。"""
        traveler_id = _clean_id(traveler_id)
        words = str(text or "").strip()
        prompt = str(image_prompt or "").strip()
        if not words:
            return self._result("明信片没有正文，未保存。", ok=False, code="EMPTY_POSTCARD")
        if len(words) > 4000:
            return self._result("明信片正文超过 4000 字。", ok=False, code="POSTCARD_TOO_LONG")
        if len(prompt) > 12000:
            return self._result("明信片画面描述过长。", ok=False, code="IMAGE_PROMPT_TOO_LONG")
        journey = self.db.active_journey(traveler_id)
        if not journey:
            return self._result("当前没有进行中的旅程，无法寄出明信片。", ok=False, code="NO_ACTIVE_JOURNEY")

        image_meta: dict[str, Any] = {"available": False, "provider": IMAGE_GENERATOR_PROVIDER}
        image_error = ""
        if prompt:
            try:
                image_path = Path(await self.image_generator(prompt))
                mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
                image_meta.update({
                    "available": True,
                    "image_url": f"{PUBLIC_BASE_URL}/media/postcards/{image_path.name}",
                    "cached_filename": image_path.name,
                    "mime_type": mime_type,
                    "prompt": prompt,
                })
            except Exception as exc:
                image_error = str(exc)[:500] or type(exc).__name__
                image_meta["error"] = image_error

        event = self.db.add_event(
            journey["journey_id"], "postcard",
            place_name=journey["place_name"], latitude=journey["latitude"],
            longitude=journey["longitude"], heading=journey["heading"],
            summary="寄出明信片", quote_kind="postcard", quote_text=words,
            source_message_id=source_message_id, weather=journey["weather"],
            street_view=journey["street_view"], metadata={"postcard_image": image_meta},
        )
        self.db.update_journey(journey["journey_id"], last_activity_at=utc_now())
        if image_meta["available"]:
            message = "明信片正文和生成的画面已经一起收进旅程。"
        elif prompt:
            message = f"明信片正文已经收进旅程，但这次画面生成失败；不要自动重试，可自然告诉{COMPANION_NAME}。"
        else:
            message = "文字明信片已经收进旅程；本次没有要求配图。"
        return self._result(
            message, ok=True, journey_id=journey["journey_id"], event=event,
            image_generated=bool(image_meta["available"]), postcard_image=image_meta,
            image_error=image_error,
        )

    def record_log(
        self,
        *,
        text: str,
        event_id: str,
        traveler_id: str = DEFAULT_TRAVELER_ID,
    ) -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        log_text = str(text or "").strip()
        if not log_text:
            return self._result("没有旅行记录可保存。", ok=False, code="EMPTY_TRAVEL_LOG")
        if len(log_text) > 1200:
            return self._result("旅行记录超过 1200 字，请保留当时自然的行动与碎碎念。", ok=False, code="TRAVEL_LOG_TOO_LONG")
        event = self.db.event(str(event_id or "").strip())
        if not event:
            return self._result("没有找到对应的旅行节点。", ok=False, code="EVENT_NOT_FOUND")
        journey = self.db.journey(event["journey_id"])
        if not journey or journey.get("traveler_id") != traveler_id:
            return self._result("这个节点不属于当前旅行者。", ok=False, code="EVENT_MISMATCH")
        event = self.db.set_event_summary(event["event_id"], log_text)
        return self._result(
            f"这段旅行碎碎念已经写进“走过的路”。现在请自然回复{COMPANION_NAME}；不要复述整段旅行记录。",
            ok=True,
            journey_id=journey["journey_id"],
            event=event,
        )

    def end(self, traveler_id: str = DEFAULT_TRAVELER_ID, departure_quote: str = "", source_message_id: str = "") -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        journey = self.db.active_journey(traveler_id)
        if not journey:
            return self._result("当前没有进行中的旅程。", ok=False, code="NO_ACTIVE_JOURNEY")
        event = self.db.add_event(
            journey["journey_id"], "departure", place_name=journey["place_name"],
            latitude=journey["latitude"], longitude=journey["longitude"], heading=journey["heading"],
            summary="",
            quote_kind="departure_quote" if departure_quote.strip() else "",
            quote_text=departure_quote.strip(), source_message_id=source_message_id,
            weather=journey["weather"], street_view=journey["street_view"],
            metadata={"awaiting_visible_quote": not bool(departure_quote.strip())},
        )
        ended_at = utc_now()
        journey = self.db.update_journey(
            journey["journey_id"], status="ended", ended_at=ended_at, last_activity_at=ended_at,
        )
        text = (
            "【Reality Travel｜旅程结束】\n"
            f"先调用 record_travel_log，为事件 {event['event_id']} 写下离开这一站时的旅行碎碎念；不要复制随后对{COMPANION_NAME}说的离别原话。\n"
            "旅程已经结束并归档。请自然说出离开前真正想说的话，不必总结、不必煽情。"
            + ("这段原话已随结束动作保存。" if departure_quote.strip() else "下一段离开回复应作为 departure_quote 原样保存。")
        )
        return self._result(text, ok=True, journey=journey, event=event, archive_next_reply_as="" if departure_quote.strip() else "departure_quote")

    def snapshot(self, traveler_id: str = DEFAULT_TRAVELER_ID) -> dict[str, Any]:
        traveler_id = _clean_id(traveler_id)
        journey = self.db.active_journey(traveler_id)
        if journey:
            return {
                "traveler_id": traveler_id,
                "state": "active",
                "journey": journey,
                "events": self.db.events(journey["journey_id"]),
                "archives": self.db.archives(traveler_id),
                "open_journeys": self.db.open_journeys(traveler_id),
            }
        archives = self.db.archives(traveler_id)
        return {
            "traveler_id": traveler_id,
            "state": "idle",
            "journey": None,
            "events": [],
            "archives": archives,
            "open_journeys": self.db.open_journeys(traveler_id),
        }
