# Permission Handling Strategy

## Problem from Previous Implementation

The Swift version repeatedly prompted for screen recording permissions, causing a poor user experience. This happened because:
1. Permission checks were called on every capture attempt
2. No caching of permission status
3. Multiple modules checking permissions independently

## Solution: One-Shot Cached Permission Check

### Key Principles

1. **Check Once at Startup**
   - Permissions are checked ONCE when the app starts
   - Result is cached in a module-level variable
   - Never check again in the same session

2. **Cache the Result**
   - Use module-level variable: `_permission_cache = None`
   - First check sets cache to `True` or `False`
   - Subsequent calls return cached value immediately

3. **Never Prompt During Capture**
   - Capture functions assume permissions are already checked
   - Do NOT attempt screenshots to check permissions
   - If permission denied, capture fails gracefully with log

4. **Graceful Degradation**
   - If permission denied, app still runs (menu appears)
   - User can quit gracefully
   - Clear log message explains why capture won't work

## Implementation Pattern

```python
# In src/permissions.py

_permission_cache = None  # Module-level cache

def ensure_screen_recording():
    """
    Ensures screen recording permission is granted.
    Checks ONCE at startup and caches result.
    """
    global _permission_cache
    
    # If already checked, return cached result
    if _permission_cache is not None:
        return _permission_cache
    
    # First-time check - attempt screenshot
    Log.section("Screen Recording Permissions")
    Log.info("Checking screen recording permission (one-time check)")
    
    try:
        # This triggers system dialog if permission not granted
        import pyautogui
        test_image = pyautogui.screenshot(region=(0, 0, 1, 1))
        _permission_cache = True
        Log.info("Screen recording permission granted")
        Log.kv({"stage": "permissions", "result": "granted"})
    except Exception as e:
        _permission_cache = False
        Log.warn("permission_denied")
        Log.kv({"stage": "permissions", "result": "denied", "error": str(e)})
    
    return _permission_cache
```

## Usage in App Flow

```python
# In src/app.py (startup)

# Check permissions ONCE at startup
if not permissions.ensure_screen_recording():
    Log.warn("Screen recording permission not granted - capture will fail")

# In src/statusbar_controller.py (capture handler)

@rumps.clicked("Capture")
def capture_menu_item(_):
    # Assume permissions already checked - don't check again
    # If denied, capture will fail gracefully
    result = frontmost_capture.capture()
    if result is None:
        Log.error("Capture failed - check permissions")
```

## Testing

1. **First Run**: Should trigger permission dialog once
2. **After Grant**: Should never prompt again
3. **After Deny**: Should log warning and never prompt again
4. **Restart App**: Will check again (fresh session, new cache)

## Benefits

- ✅ No repeated prompts
- ✅ Better user experience
- ✅ Clear logging of permission status
- ✅ Graceful failure when denied
- ✅ Simple to implement and maintain

