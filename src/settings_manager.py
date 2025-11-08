"""
Application settings management for user preferences.

Currently only tracks the preferred calendar provider (Apple or Google).
Settings are persisted to the user's Application Support directory so the
choice survives across app restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Literal, Optional, TypedDict

from src.logging_helper import Log

CalendarPreference = Literal["apple", "google"]


class SettingsSchema(TypedDict, total=False):
    preferred_calendar: CalendarPreference


SETTINGS_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "ScreenCal"
)
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULT_SETTINGS: SettingsSchema = {
    "preferred_calendar": "apple",
}


def _ensure_settings_dir() -> None:
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as err:
        Log.warn(f"Unable to create settings directory {SETTINGS_DIR}: {err}")


def load_settings() -> SettingsSchema:
    """
    Load settings from disk, falling back to defaults if anything fails.
    """
    _ensure_settings_dir()
    if not SETTINGS_FILE.exists():
        Log.info(f"Settings file not found, using defaults: {SETTINGS_FILE}")
        return DEFAULT_SETTINGS.copy()

    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Settings data is not a JSON object")
    except Exception as err:
        Log.warn(f"Failed to read settings file ({SETTINGS_FILE}): {err}")
        return DEFAULT_SETTINGS.copy()

    merged: SettingsSchema = DEFAULT_SETTINGS.copy()
    # Merge only known keys
    for key in DEFAULT_SETTINGS:
        if key in data:
            merged[key] = data[key]  # type: ignore[assignment]
    return merged


def save_settings(settings: SettingsSchema) -> None:
    """
    Persist settings to disk.
    """
    _ensure_settings_dir()
    try:
        SETTINGS_FILE.write_text(
            json.dumps(settings, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as err:
        Log.warn(f"Failed to write settings file ({SETTINGS_FILE}): {err}")


def get_preferred_calendar() -> CalendarPreference:
    settings = load_settings()
    preferred = settings.get("preferred_calendar", DEFAULT_SETTINGS["preferred_calendar"])
    if preferred not in ("apple", "google"):
        Log.warn(f"Invalid preferred_calendar value '{preferred}', defaulting to apple")
        preferred = "apple"
    return preferred


def set_preferred_calendar(value: CalendarPreference) -> None:
    if value not in ("apple", "google"):
        raise ValueError(f"Invalid calendar preference: {value}")
    settings = load_settings()
    settings["preferred_calendar"] = value
    save_settings(settings)
    Log.info(f"Saved preferred calendar setting: {value}")

