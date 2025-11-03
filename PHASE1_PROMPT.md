# Phase 1 Prompt: Permissions & Capture

Use this prompt AFTER Phase 0 is complete:

---

PHASE 1: Permissions & Capture

Implement the permissions and screen capture modules with **proper one-shot permission handling** to avoid repeated permission prompts.

**Critical Permission Handling Requirements:**
- ✅ Permissions MUST be checked ONCE at app startup and cached
- ✅ If permission is already granted, NEVER prompt again
- ✅ If permission is denied, log it ONCE and NEVER prompt again in the same session
- ✅ Use a module-level cache variable to store permission status
- ✅ Check cache FIRST before attempting any screenshot operations
- ✅ DO NOT call screenshot functions for permission checking during capture
- ✅ DO NOT loop or repeatedly prompt for permissions
- ✅ If denied, exit gracefully with a log message

**Phase 1 Scope:**
1. Create `src/permissions.py`:
   - `ensure_screen_recording()` function
   - Module-level cache: `_permission_cache = None`
   - Check cache first - if not None, return cached value
   - If None, attempt ONE screenshot (triggers system dialog if needed)
   - Cache result (True/False) immediately
   - NEVER check again in same session
   - Log permission status using Log module
   - Return True if granted, False if denied

2. Create `src/frontmost_capture.py`:
   - `capture()` function that captures frontmost window
   - Uses `pyautogui` or `mss` library
   - Returns PIL Image and context dict: `{"app_name": str, "bundle_id": str, "window_title": str}`
   - Gets frontmost app info using `AppKit` bindings (via `pyobjc` or `appscript`)
   - Logs capture attempts with Log module
   - If capture fails, return None and log error

3. Create `src/statusbar_controller.py`:
   - Menu bar app using `rumps`
   - Menu items: "Capture", separator, "Quit"
   - Click handler for "Capture" that calls capture logic
   - Logs when app starts

4. Create `src/app.py`:
   - Main entry point using `rumps.App`
   - At startup: check permissions ONCE
   - If permissions not granted, log and show menu anyway (user can still quit)
   - Initializes StatusBarController

**Allowed files to create/modify:**
- `src/permissions.py`
- `src/frontmost_capture.py`
- `src/statusbar_controller.py`
- `src/app.py`
- `requirements.txt` (add pyobjc-framework-AppKit if needed for app info)

**Forbidden changes:**
- Do NOT create router, processor, or LLM client modules yet (Phase 2)
- Do NOT create ICS generator (Phase 3)
- Do NOT add notification code (Phase 4)

**Permission Implementation Pattern:**
```python
# In permissions.py
_permission_cache = None  # Module-level cache

def ensure_screen_recording():
    global _permission_cache
    
    # Check cache first - if already checked, return cached value
    if _permission_cache is not None:
        Log.info(f"Permission cache hit: {_permission_cache}")
        return _permission_cache
    
    # Only check ONCE - attempt screenshot
    Log.section("Screen Recording Permissions")
    Log.info("Checking screen recording permission (one-time check)")
    
    try:
        # This will trigger system dialog if permission not granted
        import pyautogui
        test_image = pyautogui.screenshot(region=(0, 0, 1, 1))
        _permission_cache = True
        Log.info("Screen recording permission granted")
        Log.kv({"stage": "permissions", "result": "granted"})
    except Exception as e:
        _permission_cache = False
        Log.warn("Screen recording permission denied or not available")
        Log.kv({"stage": "permissions", "result": "denied", "error": str(e)})
    
    return _permission_cache
```

**Testing Requirements:**
- `make run` should start menu bar app
- Permission check happens ONCE at startup (not on every capture)
- If permission denied, app still shows menu (doesn't crash)
- Capture button works if permission granted
- Logs show permission status clearly

**Deliverables:**
- Menu bar app appears with camera icon
- Permissions checked once at startup (not repeatedly)
- Capture button in menu works
- Logs show clear permission and capture status
- No repeated permission prompts

**When done:**
- STOP. Do not proceed to Phase 2.
- Test that permissions are checked only once
- Output summary: files created + permission handling works correctly

---

