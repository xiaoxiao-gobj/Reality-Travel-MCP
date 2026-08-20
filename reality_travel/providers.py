from __future__ import annotations

import math
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .config import (
    PUBLIC_BASE_URL,
    STREET_VIEW_CACHE_DIR,
    STREET_VIEW_CACHE_SECONDS,
    google_street_view_key,
)


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
STREET_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
STREET_IMAGE_URL = "https://maps.googleapis.com/maps/api/streetview"

_COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*$")

_WEATHER_TEXT = {
    0: "晴", 1: "大致晴朗", 2: "局部多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "较强毛毛雨", 61: "小雨", 63: "中雨",
    65: "大雨", 71: "小雪", 73: "中雪", 75: "大雪", 80: "小阵雨",
    81: "阵雨", 82: "强阵雨", 85: "小阵雪", 86: "强阵雪", 95: "雷暴",
    96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}


def _display_name(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("name", "admin2", "admin1", "country"):
        value = str(row.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)
    return "，".join(parts)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def destination_point(lat: float, lon: float, heading: float, distance_m: float) -> tuple[float, float]:
    radius = 6_371_000.0
    angular = distance_m / radius
    bearing = math.radians(heading % 360)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular)
        + math.cos(lat1) * math.sin(angular) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180


class RealityProviders:
    async def geocode(self, place: str) -> dict[str, Any] | None:
        query = " ".join(str(place or "").split()).strip()
        if not query:
            return None
        match = _COORDINATES.match(query)
        if match:
            lat, lon = float(match.group(1)), float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return {
                    "query": query,
                    "name": f"坐标 {lat:.5f}, {lon:.5f}",
                    "latitude": lat,
                    "longitude": lon,
                    "timezone": "",
                    "elevation_m": None,
                    "country_code": "",
                    "source": "coordinates",
                }
        params = {"name": query, "count": 8, "language": "zh", "format": "json"}
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(GEOCODING_URL, params=params)
                response.raise_for_status()
                rows = response.json().get("results") or []
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return None
        row = next((item for item in rows if isinstance(item, dict)), None)
        if not row:
            return None
        try:
            return {
                "query": query,
                "name": _display_name(row) or query,
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "timezone": str(row.get("timezone") or ""),
                "elevation_m": float(row["elevation"]) if row.get("elevation") is not None else None,
                "country_code": str(row.get("country_code") or ""),
                "admin1": str(row.get("admin1") or ""),
                "source": "open_meteo_geocoding",
            }
        except (KeyError, TypeError, ValueError):
            return None

    async def weather(self, latitude: float, longitude: float) -> dict[str, Any]:
        params = {
            "latitude": f"{latitude:.7f}",
            "longitude": f"{longitude:.7f}",
            "current": ",".join((
                "temperature_2m", "apparent_temperature", "relative_humidity_2m",
                "weather_code", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
            )),
            "timezone": "auto",
            "wind_speed_unit": "kmh",
        }
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(WEATHER_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return {"available": False, "status": "REQUEST_FAILED"}
        current = data.get("current") if isinstance(data.get("current"), dict) else {}
        code = current.get("weather_code")
        try:
            code_number = int(code) if code is not None else None
        except (TypeError, ValueError):
            code_number = None
        return {
            "available": bool(current),
            "status": "OK" if current else "EMPTY",
            "observed_at": current.get("time"),
            "timezone": data.get("timezone"),
            "timezone_abbreviation": data.get("timezone_abbreviation"),
            "utc_offset_seconds": data.get("utc_offset_seconds"),
            "weather_code": code_number,
            "weather_text": _WEATHER_TEXT.get(code_number, "未知"),
            "temperature_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "humidity_percent": current.get("relative_humidity_2m"),
            "wind_kmh": current.get("wind_speed_10m"),
            "wind_direction_deg": current.get("wind_direction_10m"),
            "gust_kmh": current.get("wind_gusts_10m"),
            "elevation_m": data.get("elevation"),
            "source": "open_meteo_weather",
        }

    @staticmethod
    def cleanup_street_cache() -> None:
        STREET_VIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - max(300, STREET_VIEW_CACHE_SECONDS)
        for path in STREET_VIEW_CACHE_DIR.glob("street-*.jpg"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue

    async def street_view(
        self,
        latitude: float,
        longitude: float,
        *,
        heading: float = 0,
        radius_m: int = 500,
        pano_id: str = "",
    ) -> dict[str, Any]:
        key = google_street_view_key()
        if not key:
            return {"available": False, "status": "NOT_CONFIGURED", "message": "Google Street View API Key 未配置。"}
        self.cleanup_street_cache()
        metadata_params: dict[str, str] = {"key": key}
        if pano_id:
            metadata_params["pano"] = pano_id
        else:
            metadata_params.update({
                "location": f"{latitude:.7f},{longitude:.7f}",
                "radius": str(max(1, min(int(radius_m), 50_000))),
                "source": "outdoor",
            })
        try:
            async with httpx.AsyncClient(timeout=18, follow_redirects=False) as client:
                meta_response = await client.get(STREET_METADATA_URL, params=metadata_params)
                meta_response.raise_for_status()
                metadata = meta_response.json()
                status = str(metadata.get("status") or "UNKNOWN_ERROR")
                if status != "OK":
                    return {
                        "available": False,
                        "status": status,
                        "message": "当前地点附近没有 Google 街景覆盖。" if status == "ZERO_RESULTS" else "Google 街景查询失败。",
                        "requested_position": {"latitude": latitude, "longitude": longitude},
                    }
                pano = str(metadata.get("pano_id") or pano_id or "")
                location = metadata.get("location") or {}
                image_params = {
                    "size": "640x640",
                    "pano": pano,
                    "heading": f"{heading % 360:.1f}",
                    "fov": "90",
                    "pitch": "0",
                    "return_error_code": "true",
                    "key": key,
                }
                image_response = await client.get(STREET_IMAGE_URL, params=image_params)
                image_response.raise_for_status()
                content_type = str(image_response.headers.get("content-type") or "").lower()
                if not content_type.startswith("image/") or not image_response.content:
                    raise ValueError("Street View did not return an image")
        except (httpx.HTTPError, ValueError, TypeError):
            return {
                "available": False,
                "status": "REQUEST_FAILED",
                "message": "Google Street View 请求暂时失败。",
                "requested_position": {"latitude": latitude, "longitude": longitude},
            }

        filename = f"street-{uuid.uuid4().hex}.jpg"
        path = STREET_VIEW_CACHE_DIR / filename
        path.write_bytes(image_response.content)
        pano_lat = float(location.get("lat"))
        pano_lon = float(location.get("lng"))
        return {
            "available": True,
            "status": "OK",
            "capture_date": metadata.get("date"),
            "copyright": metadata.get("copyright") or "Google",
            "pano_id": pano,
            "heading": heading % 360,
            "requested_position": {"latitude": latitude, "longitude": longitude},
            "panorama_position": {"latitude": pano_lat, "longitude": pano_lon},
            "distance_from_requested_m": round(haversine_m(latitude, longitude, pano_lat, pano_lon)),
            "image_url": f"{PUBLIC_BASE_URL}/media/streetview/{filename}",
            "cached_filename": filename,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "google_street_view_static",
        }

    async def street_view_image_by_pano(
        self,
        pano_id: str,
        *,
        heading: float | None = None,
    ) -> dict[str, Any]:
        """Fetch one saved panorama view for immediate display without caching it."""
        key = google_street_view_key()
        clean_pano = str(pano_id or "").strip()
        if not key or not clean_pano:
            return {
                "ok": False,
                "status": "NOT_CONFIGURED" if not key else "INVALID_PANO",
                "message": "这张街景暂时无法重新取得。",
            }
        params = {
            "size": "640x640",
            "pano": clean_pano,
            "fov": "90",
            "pitch": "0",
            "return_error_code": "true",
            "key": key,
        }
        if heading is not None:
            params["heading"] = f"{float(heading) % 360:.1f}"
        try:
            async with httpx.AsyncClient(timeout=18, follow_redirects=False) as client:
                response = await client.get(STREET_IMAGE_URL, params=params)
                response.raise_for_status()
                content_type = str(response.headers.get("content-type") or "").lower()
                if not content_type.startswith("image/") or not response.content:
                    raise ValueError("Street View did not return an image")
        except (httpx.HTTPError, ValueError, TypeError):
            return {
                "ok": False,
                "status": "REQUEST_FAILED",
                "message": "这张街景暂时无法重新取得，可能已经更新或失效。",
            }
        return {
            "ok": True,
            "status": "OK",
            "content": response.content,
            "content_type": content_type.split(";", 1)[0] or "image/jpeg",
        }
