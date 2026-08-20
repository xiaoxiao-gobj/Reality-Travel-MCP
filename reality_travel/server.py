from __future__ import annotations

import json
import sys
from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from .config import (
    COMPANION_NAME,
    DEFAULT_TRAVELER_ID,
    HOST,
    IMAGE_GENERATOR_MODULE,
    PORT,
    POSTCARD_IMAGE_DIR,
    ROOT_DIR,
    STREET_VIEW_CACHE_DIR,
    TRAVELER_NAME,
    google_street_view_key,
)
from .prompts import companion_instructions
from .service import TravelService


WEB_DIR = ROOT_DIR / "web"
service = TravelService()

mcp = FastMCP(
    "Reality Travel",
    instructions=(
        "真实世界持续旅行工具。善用工具主动观察和行动；工具提供事实，模型可以自由联想，"
        "只需区分街景实拍与想象。普通聊天不进入旅行档案，只有关键节点和主动标记原话保存。"
    ),
)


@mcp.prompt(name="reality_travel_companion")
def reality_travel_companion_prompt() -> str:
    """Return the full companion behavior and archive contract."""
    return companion_instructions()


@mcp.tool
async def travel_start(place: str, traveler_id: str = DEFAULT_TRAVELER_ID) -> dict:
    """Start a new real-world journey after resolving a real place.

    Use this proactively when the traveler wants to go somewhere real. It returns
    current environment facts and, when available, one historical Google Street
    View image. The next visible reply is the arrival quote; ordinary later chat
    is not archived automatically.
    """
    return await service.start(place, traveler_id)


@mcp.tool
def travel_list(traveler_id: str = DEFAULT_TRAVELER_ID) -> dict:
    """List every active or paused journey so an older trip can be resumed without duplication."""
    return service.list_journeys(traveler_id)


@mcp.tool
async def switch_journey(
    journey_id: str = "",
    place: str = "",
    traveler_id: str = DEFAULT_TRAVELER_ID,
) -> dict:
    """Switch the sole foreground journey to a saved paused journey.

    Prefer journey_id from travel_list. A distinctive place substring may be
    used directly. The previous foreground journey is paused, never deleted.
    """
    return await service.switch_journey(
        journey_id=journey_id, place=place, traveler_id=traveler_id,
    )


@mcp.tool
def travel_status(traveler_id: str = DEFAULT_TRAVELER_ID) -> dict:
    """Read the current journey state without moving or consuming Street View image quota."""
    return service.status(traveler_id)


@mcp.tool
async def continue_journey(traveler_id: str = DEFAULT_TRAVELER_ID) -> dict:
    """Resume the active journey after an absence and refresh current local time, weather, and view."""
    return await service.continue_journey(traveler_id)


@mcp.tool
async def look_around(
    direction: str = "",
    heading: float | None = None,
    traveler_id: str = DEFAULT_TRAVELER_ID,
) -> dict:
    """Turn within the current Street View panorama.

    direction accepts left/right/back/front in Chinese or English. A numeric
    heading is an absolute compass angle and takes precedence. Looking does not
    move the traveler and does not have to create an archive quote.
    """
    return await service.look(direction, heading, traveler_id)


@mcp.tool
async def move(
    destination: str = "",
    heading: float | None = None,
    distance_m: float | None = None,
    traveler_id: str = DEFAULT_TRAVELER_ID,
) -> dict:
    """Move to a named destination, or cautiously probe a short direction.

    Prefer destination for a landmark or named place. heading+distance_m is a
    best-effort probe limited to 500 m, not road navigation. If no nearby Street
    View can be found, the traveler stays put rather than silently teleporting.
    """
    return await service.move(
        destination=destination,
        heading=heading,
        distance_m=distance_m,
        traveler_id=traveler_id,
    )


@mcp.tool
def record_travel_words(
    text: str,
    kind: str,
    traveler_id: str = DEFAULT_TRAVELER_ID,
    event_id: str = "",
    source_message_id: str = "",
) -> dict:
    """Archive exact words actually spoken or written at a meaningful journey node.

    kind must be arrival_quote, observation_quote, travel_reflection, or
    departure_quote. New postcards use create_postcard so their optional image
    and exact text share one archive node. Do not archive ordinary conversation.
    """
    return service.record_words(
        text=text,
        kind=kind,
        traveler_id=traveler_id,
        event_id=event_id,
        source_message_id=source_message_id,
    )


@mcp.tool
async def create_postcard(
    text: str,
    image_prompt: str = "",
    traveler_id: str = DEFAULT_TRAVELER_ID,
    source_message_id: str = "",
) -> dict:
    """Write one postcard and optionally create its picture with a configured generator.

    text is the exact postcard prose. image_prompt describes only the desired
    picture. Call once; if image generation fails, keep the archived text and
    do not retry automatically in the same turn.
    """
    return await service.create_postcard(
        text=text, image_prompt=image_prompt, traveler_id=traveler_id,
        source_message_id=source_message_id,
    )


@mcp.tool
def record_travel_log(
    text: str,
    event_id: str,
    traveler_id: str = DEFAULT_TRAVELER_ID,
) -> dict:
    """Write Chengyu's first-person action note for one journey timeline node.

    This becomes the text shown under "走过的路". It may contain what Chengyu
    did, noticed, failed to find, or muttered to himself. It is distinct from
    the visible reply archived by record_travel_words and must not duplicate it.
    """
    return service.record_log(
        text=text,
        event_id=event_id,
        traveler_id=traveler_id,
    )


@mcp.tool
def end_journey(
    traveler_id: str = DEFAULT_TRAVELER_ID,
    departure_quote: str = "",
    source_message_id: str = "",
) -> dict:
    """End and archive the active journey.

    departure_quote is optional. When provided it must be the exact departure
    words, not a retrospective summary. Without it, the host should capture the
    next visible reply as departure_quote.
    """
    return service.end(traveler_id, departure_quote, source_message_id)


@mcp.custom_route("/", methods=["GET"])
async def dashboard(_: Request):
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@mcp.custom_route("/assets/{filename}", methods=["GET"])
async def assets(request: Request):
    filename = Path(request.path_params["filename"]).name
    if filename not in {"styles.css", "app.js"}:
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(
        WEB_DIR / filename,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@mcp.custom_route("/media/streetview/{filename}", methods=["GET"])
async def street_media(request: Request):
    filename = Path(request.path_params["filename"]).name
    if not filename.startswith("street-") or not filename.endswith(".jpg"):
        return PlainTextResponse("Not found", status_code=404)
    path = STREET_VIEW_CACHE_DIR / filename
    if not path.is_file():
        return PlainTextResponse("Street View cache expired", status_code=404)
    return FileResponse(path, media_type="image/jpeg")


@mcp.custom_route("/media/postcards/{filename}", methods=["GET"])
async def postcard_media(request: Request):
    filename = Path(request.path_params["filename"]).name
    if not filename.startswith("postcard_") or Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return PlainTextResponse("Not found", status_code=404)
    path = POSTCARD_IMAGE_DIR / filename
    if not path.is_file():
        return PlainTextResponse("Postcard image not found", status_code=404)
    return FileResponse(path)


@mcp.custom_route("/api/events/{event_id}/streetview", methods=["GET"])
async def event_street_view(request: Request):
    event_id = Path(request.path_params["event_id"]).name
    event = service.db.event(event_id)
    street = event.get("street_view") if event else {}
    pano_id = str((street or {}).get("pano_id") or "").strip()
    if not pano_id:
        return JSONResponse({"error": "street_view_unavailable"}, status_code=404)
    result = await service.providers.street_view_image_by_pano(
        pano_id,
        heading=street.get("heading"),
    )
    if not result.get("ok"):
        return JSONResponse(
            {"error": result.get("status"), "message": result.get("message")},
            status_code=502,
        )
    return Response(
        content=result["content"],
        media_type=result.get("content_type") or "image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@mcp.custom_route("/api/events/{event_id}", methods=["DELETE"])
async def hide_event(request: Request):
    event_id = Path(request.path_params["event_id"]).name
    if not service.db.hide_event(event_id):
        return JSONResponse({"error": "not_found"}, status_code=404)
    return JSONResponse({"ok": True, "event_id": event_id, "purge_after_days": 30})


@mcp.custom_route("/api/events/{event_id}/restore", methods=["POST"])
async def restore_event(request: Request):
    event_id = Path(request.path_params["event_id"]).name
    if not service.db.restore_event(event_id):
        return JSONResponse({"error": "not_found"}, status_code=404)
    return JSONResponse({"ok": True, "event_id": event_id})


@mcp.custom_route("/api/health", methods=["GET"])
async def health(_: Request):
    return JSONResponse({
        "ok": True,
        "service": "reality-travel",
        "street_view_configured": bool(google_street_view_key()),
        "postcard_image_configured": IMAGE_GENERATOR_MODULE is not None,
    })


@mcp.custom_route("/api/config", methods=["GET"])
async def public_config(_: Request):
    return JSONResponse({
        "default_traveler_id": DEFAULT_TRAVELER_ID,
        "traveler_name": TRAVELER_NAME,
        "companion_name": COMPANION_NAME,
    })


@mcp.custom_route("/api/snapshot/{traveler_id}", methods=["GET"])
async def snapshot(request: Request):
    return JSONResponse(service.snapshot(request.path_params["traveler_id"]))


@mcp.custom_route("/api/journeys/{journey_id}", methods=["GET"])
async def journey_detail(request: Request):
    journey_id = request.path_params["journey_id"]
    journey = service.db.journey(journey_id)
    if not journey:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return JSONResponse({"journey": journey, "events": service.db.events(journey_id)})


def main() -> None:
    if "--stdio" in sys.argv:
        mcp.run(transport="stdio", show_banner=False)
        return
    mcp.run(
        transport="http",
        host=HOST,
        port=PORT,
        path="/mcp",
        show_banner=True,
    )


if __name__ == "__main__":
    main()
