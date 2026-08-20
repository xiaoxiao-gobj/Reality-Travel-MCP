from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DATABASE_PATH, ensure_directories


JSON_COLUMNS = {"location_json", "weather_json", "street_view_json", "metadata_json"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TravelDatabase:
    def __init__(self, path: Path | str = DATABASE_PATH) -> None:
        self.path = Path(path)
        ensure_directories()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS journeys (
                    journey_id TEXT PRIMARY KEY,
                    traveler_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    last_activity_at TEXT NOT NULL,
                    place_name TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    timezone TEXT,
                    heading REAL NOT NULL DEFAULT 0,
                    pano_id TEXT,
                    distance_m REAL NOT NULL DEFAULT 0,
                    scene_count INTEGER NOT NULL DEFAULT 0,
                    visited_count INTEGER NOT NULL DEFAULT 1,
                    location_json TEXT NOT NULL DEFAULT '{}',
                    weather_json TEXT NOT NULL DEFAULT '{}',
                    street_view_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_journeys_one_active
                ON journeys(traveler_id) WHERE status = 'active';

                CREATE TABLE IF NOT EXISTS journey_events (
                    event_id TEXT PRIMARY KEY,
                    journey_id TEXT NOT NULL REFERENCES journeys(journey_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    place_name TEXT,
                    latitude REAL,
                    longitude REAL,
                    heading REAL,
                    distance_m REAL NOT NULL DEFAULT 0,
                    summary TEXT,
                    quote_kind TEXT,
                    quote_text TEXT,
                    source_message_id TEXT,
                    weather_json TEXT NOT NULL DEFAULT '{}',
                    street_view_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_events_journey_time
                ON journey_events(journey_id, occurred_at);
                """
            )
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(journey_events)").fetchall()
            }
            if "hidden_at" not in columns:
                conn.execute(
                    "ALTER TABLE journey_events ADD COLUMN hidden_at TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_hidden_at ON journey_events(hidden_at)"
            )
        self.purge_hidden_events()

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in JSON_COLUMNS:
            if key not in result:
                continue
            try:
                result[key.removesuffix("_json")] = json.loads(result.pop(key) or "{}")
            except (TypeError, json.JSONDecodeError):
                result[key.removesuffix("_json")] = {}
        return result

    def active_journey(self, traveler_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM journeys WHERE traveler_id=? AND status='active' LIMIT 1",
                (traveler_id,),
            ).fetchone()
        return self._decode(row)

    def open_journeys(self, traveler_id: str) -> list[dict[str, Any]]:
        """Return the current and paused journeys, newest activity first."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM journeys WHERE traveler_id=? AND status IN ('active','paused') "
                "ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, last_activity_at DESC",
                (traveler_id,),
            ).fetchall()
        return [self._decode(row) or {} for row in rows]

    def pause_active_journey(self, traveler_id: str) -> dict[str, Any] | None:
        active = self.active_journey(traveler_id)
        if not active:
            return None
        with self.connect() as conn:
            conn.execute(
                "UPDATE journeys SET status='paused' WHERE journey_id=? AND status='active'",
                (active["journey_id"],),
            )
        return self.journey(active["journey_id"])

    def activate_journey(self, journey_id: str, traveler_id: str) -> dict[str, Any] | None:
        """Atomically make one non-ended journey the traveler's sole foreground journey."""
        with self.connect() as conn:
            target = conn.execute(
                "SELECT * FROM journeys WHERE journey_id=? AND traveler_id=? AND status IN ('active','paused')",
                (journey_id, traveler_id),
            ).fetchone()
            if not target:
                return None
            conn.execute(
                "UPDATE journeys SET status='paused' WHERE traveler_id=? AND status='active' AND journey_id<>?",
                (traveler_id, journey_id),
            )
            conn.execute(
                "UPDATE journeys SET status='active', ended_at=NULL, last_activity_at=? WHERE journey_id=?",
                (utc_now(), journey_id),
            )
        return self.journey(journey_id)

    def journey(self, journey_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM journeys WHERE journey_id=?", (journey_id,)).fetchone()
        return self._decode(row)

    def create_journey(
        self,
        *,
        traveler_id: str,
        title: str,
        location: dict[str, Any],
        weather: dict[str, Any],
        street_view: dict[str, Any],
        heading: float,
    ) -> dict[str, Any]:
        now = utc_now()
        journey_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO journeys (
                    journey_id, traveler_id, title, started_at, last_activity_at,
                    place_name, latitude, longitude, timezone, heading, pano_id,
                    scene_count, location_json, weather_json, street_view_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    journey_id,
                    traveler_id,
                    title,
                    now,
                    now,
                    location["name"],
                    location["latitude"],
                    location["longitude"],
                    location.get("timezone"),
                    heading,
                    street_view.get("pano_id"),
                    1 if street_view.get("available") else 0,
                    json.dumps(location, ensure_ascii=False),
                    json.dumps(weather, ensure_ascii=False),
                    json.dumps(street_view, ensure_ascii=False),
                ),
            )
        return self.journey(journey_id) or {}

    def update_journey(self, journey_id: str, **values: Any) -> dict[str, Any]:
        if not values:
            return self.journey(journey_id) or {}
        allowed = {
            "title", "status", "ended_at", "last_activity_at", "place_name",
            "latitude", "longitude", "timezone", "heading", "pano_id",
            "distance_m", "scene_count", "visited_count", "location_json",
            "weather_json", "street_view_json",
        }
        clean = {key: value for key, value in values.items() if key in allowed}
        if not clean:
            return self.journey(journey_id) or {}
        assignments = ", ".join(f"{key}=?" for key in clean)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE journeys SET {assignments} WHERE journey_id=?",
                (*clean.values(), journey_id),
            )
        return self.journey(journey_id) or {}

    def add_event(
        self,
        journey_id: str,
        event_type: str,
        *,
        place_name: str = "",
        latitude: float | None = None,
        longitude: float | None = None,
        heading: float | None = None,
        distance_m: float = 0,
        summary: str = "",
        quote_kind: str = "",
        quote_text: str = "",
        source_message_id: str = "",
        weather: dict[str, Any] | None = None,
        street_view: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO journey_events (
                    event_id, journey_id, event_type, occurred_at, place_name,
                    latitude, longitude, heading, distance_m, summary, quote_kind,
                    quote_text, source_message_id, weather_json, street_view_json,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, journey_id, event_type, utc_now(), place_name,
                    latitude, longitude, heading, distance_m, summary, quote_kind,
                    quote_text, source_message_id,
                    json.dumps(weather or {}, ensure_ascii=False),
                    json.dumps(street_view or {}, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return self.event(event_id) or {}

    def event(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM journey_events WHERE event_id=?", (event_id,)).fetchone()
        return self._decode(row)

    def hide_event(self, event_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE journey_events SET hidden_at=? WHERE event_id=? AND hidden_at=''",
                (utc_now(), event_id),
            )
        return cursor.rowcount > 0

    def restore_event(self, event_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE journey_events SET hidden_at='' WHERE event_id=? AND hidden_at<>''",
                (event_id,),
            )
        return cursor.rowcount > 0

    def purge_hidden_events(self, retention_days: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))).isoformat()
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM journey_events WHERE hidden_at<>'' AND hidden_at<?",
                (cutoff,),
            )
        return cursor.rowcount

    def set_event_quote(
        self,
        event_id: str,
        *,
        quote_kind: str,
        quote_text: str,
        source_message_id: str = "",
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE journey_events
                SET quote_kind=?, quote_text=?, source_message_id=?
                WHERE event_id=?
                """,
                (quote_kind, quote_text, source_message_id, event_id),
            )
        return self.event(event_id)

    def set_event_summary(self, event_id: str, summary: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE journey_events SET summary=? WHERE event_id=?",
                (summary, event_id),
            )
        return self.event(event_id)

    def events(self, journey_id: str) -> list[dict[str, Any]]:
        self.purge_hidden_events()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM journey_events WHERE journey_id=? AND hidden_at='' ORDER BY occurred_at, rowid",
                (journey_id,),
            ).fetchall()
        return [self._decode(row) or {} for row in rows]

    def archives(self, traveler_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM journeys
                WHERE traveler_id=? AND status='ended'
                ORDER BY ended_at DESC LIMIT ?
                """,
                (traveler_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._decode(row) or {} for row in rows]
