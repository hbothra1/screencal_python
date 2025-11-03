# ScreenCal4 - Python macOS Menu Bar App

## Setup Instructions

Create a Python-based macOS menu bar app that extracts calendar events from screenshots.

**Technology Stack:**
- **Python 3.9+** with `rumps` for menu bar interface
- **pyautogui** or **mss** for screen capture
- **requests** for OpenAI API calls
- **pytest** for testing

**Critical Permission Handling Requirements:**
- Permissions MUST be checked once at startup and cached
- If permission is already granted, never prompt again
- If permission is denied, log it once and never prompt again in the same session
- Use `pyautogui.screenshot()` only once to check permissions - this will trigger the system dialog
- Cache the permission result in memory (do NOT check permissions on every capture)
- Never loop or repeatedly prompt for permissions

**Project Structure:**
```
ScreenCal_Attempt4/
├── .cursor/
│   └── erules/          # Architecture rules (already created)
├── src/
│   ├── __init__.py
│   ├── app.py           # Main menu bar app entry point
│   ├── logging_helper.py # Log module (Phase 0)
│   ├── permissions.py    # Permission handling (Phase 1)
│   ├── frontmost_capture.py  # Screen capture (Phase 1)
│   ├── statusbar_controller.py  # Menu bar UI (Phase 1)
│   ├── app_router.py    # App detection (Phase 2)
│   ├── screen_cal_processor.py  # Main pipeline (Phase 2)
│   ├── image_llm_client.py  # LLM interface (Phase 2)
│   ├── event_models.py  # Data structures (Phase 2)
│   ├── event_normalizer.py  # Date normalization (Phase 2)
│   ├── ics_generator.py  # ICS file creation (Phase 3)
│   └── notifications.py  # User notifications (Phase 4)
├── tests/
│   ├── __init__.py
│   ├── test_app_router.py
│   ├── test_event_normalizer.py
│   └── test_stub_llm_client.py
├── requirements.txt
├── Makefile
├── .env.example
└── README.md
```

## PHASE 0: Tooling & Setup

**Scope:**
- Create project structure
- Set up Python environment (requirements.txt)
- Create Logging module
- Create Makefile for build/run commands
- Ensure all logs print to terminal

**Allowed files to create/modify:**
- `requirements.txt`
- `Makefile`
- `src/logging_helper.py`
- `README.md`
- `.env.example`

**Deliverables:**
- `make build` works (installs dependencies)
- `make run` starts the app
- Logging module with `section()`, `info()`, `warn()`, `error()`, `kv()` methods
- All logs print to stdout (terminal-first)

**Permission Handling Implementation (Phase 0):**
```python
# In permissions.py (you'll create this in Phase 1, but plan it now):
# - Check permission ONCE using pyautogui.screenshot() at startup
# - Cache result in a module-level variable: _permission_granted = None
# - If already granted from previous check, return True immediately
# - If denied, set cache to False and never check again this session
# - Never call pyautogui.screenshot() for permission checking during capture
```

## Implementation Notes

1. **Permissions Module Design:**
   - Use a module-level cache: `_permission_cache = None`
   - `ensure_screen_recording()` checks cache first
   - If `None`, attempt one screenshot (triggers system dialog)
   - Cache the result and never check again
   - Return cached value on subsequent calls

2. **Menu Bar App Structure:**
   - Use `rumps` library for menu bar app
   - Create `@rumps.clicked("Capture")` handler
   - App runs as menu bar only (no window)

3. **Screen Capture:**
   - Use `pyautogui.screenshot()` for capture (but NOT for permission checking)
   - Or use `mss` library for better performance
   - Capture frontmost window only (not full screen)
   - Return PIL Image object

4. **Logging:**
   - Must print to stdout (not stderr)
   - Format: `[INFO] message` or `[KV] key=value | key2=value2`
   - Section headers: `\n===== TITLE =====\n`

5. **Environment:**
   - Use `.env` file for OpenAI API key (optional, defaults to stub)
   - Read with `python-dotenv`

**Start with Phase 0, then proceed to Phase 1 only when Phase 0 is complete.**

