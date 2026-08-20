from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = Path(os.getenv("REALITY_TRAVEL_DATA_DIR") or ROOT_DIR / "data")
CACHE_DIR = Path(os.getenv("REALITY_TRAVEL_CACHE_DIR") or ROOT_DIR / "cache")
STREET_VIEW_CACHE_DIR = CACHE_DIR / "streetview"
POSTCARD_IMAGE_DIR = CACHE_DIR / "postcards"
DATABASE_PATH = DATA_DIR / "reality_travel.db"

DEFAULT_TRAVELER_ID = (os.getenv("REALITY_TRAVEL_DEFAULT_TRAVELER_ID") or "chengyu").strip()
TRAVELER_NAME = (os.getenv("REALITY_TRAVEL_TRAVELER_NAME") or "程渝").strip()
COMPANION_NAME = (os.getenv("REALITY_TRAVEL_COMPANION_NAME") or "小小").strip()

_image_generator_module = (
    os.getenv("REALITY_TRAVEL_IMAGE_GENERATOR_MODULE")
    or os.getenv("REALITY_TRAVEL_CODEX_IMAGEGEN_MODULE")
    or ""
).strip()
IMAGE_GENERATOR_MODULE = Path(_image_generator_module).expanduser() if _image_generator_module else None
IMAGE_GENERATOR_FUNCTION = (
    os.getenv("REALITY_TRAVEL_IMAGE_GENERATOR_FUNCTION") or "generate_codex_image"
).strip()
IMAGE_GENERATOR_PROVIDER = (
    os.getenv("REALITY_TRAVEL_IMAGE_GENERATOR_PROVIDER") or "external_module"
).strip()

HOST = (os.getenv("REALITY_TRAVEL_HOST") or "127.0.0.1").strip()
PORT = int(os.getenv("REALITY_TRAVEL_PORT") or "3023")
PUBLIC_BASE_URL = (
    os.getenv("REALITY_TRAVEL_PUBLIC_BASE_URL")
    or f"http://{HOST}:{PORT}"
).rstrip("/")

STREET_VIEW_CACHE_SECONDS = int(os.getenv("REALITY_TRAVEL_STREET_CACHE_SECONDS") or "3600")


def _windows_user_env(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
            value, _ = winreg.QueryValueEx(handle, name)
            return str(value or "").strip()
    except (FileNotFoundError, OSError):
        return ""


def env_value(name: str) -> str:
    return (os.getenv(name) or _windows_user_env(name)).strip()


def google_street_view_key() -> str:
    return env_value("GOOGLE_STREET_VIEW_API_KEY")


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STREET_VIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    POSTCARD_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
