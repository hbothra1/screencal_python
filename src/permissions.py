"""
Permissions module for screen recording and notification permission checks.
Implements one-shot permission checking with caching.
"""

from src.logging_helper import Log

# Module-level cache for permission status
_permission_cache = None
_notification_permission_cache = None


def ensure_screen_recording():
    """
    Ensures screen recording permission is granted.
    Checks ONCE at startup and caches result.
    
    Returns:
        bool: True if permission granted, False if denied
    """
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
        Log.warn("permission_denied")
        Log.kv({"stage": "permissions", "result": "denied", "error": str(e)})
    
    return _permission_cache


def ensure_notification_permission():
    """
    Ensures notification permission is granted.
    Checks ONCE at startup and caches result.
    Uses osascript which typically works without explicit permission for Python scripts.
    Also tries UserNotifications framework to request permission if needed.
    
    Returns:
        bool: True if notification can be sent, False if definitely denied
    """
    global _notification_permission_cache
    
    # Check cache first - if already checked, return cached value
    if _notification_permission_cache is not None:
        Log.info(f"Notification permission cache hit: {_notification_permission_cache}")
        return _notification_permission_cache
    
    # Only check ONCE - mark as enabled without triggering visible notifications
    Log.section("Notification Permissions")
    Log.info("Checking notification permission (one-time check)")
    
    # For Python menu bar apps, osascript notifications typically work
    # Let's test if we can send a notification via osascript
    try:
        import subprocess
        import time
        
        # Instead of displaying a notification, verify that osascript is available
        process = subprocess.Popen(
            ['osascript', '-e', 'return "ready"'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()
        
        if process.returncode == 0 and stdout.strip() == b"ready":
            _notification_permission_cache = True
            Log.info("osascript available; assuming notification permission ready")
            Log.kv({"stage": "notification_permissions", "result": "osascript_available"})
        else:
            # osascript failed - try UserNotifications framework as fallback
            error_msg = stderr.decode() if stderr else "unknown error"
            Log.info(f"osascript test returned non-zero, trying UserNotifications framework: {error_msg}")
            
            # Try UserNotifications framework to request permission
            try:
                from UserNotifications import (
                    UNUserNotificationCenter,
                    UNAuthorizationOptionAlert,
                    UNAuthorizationOptionSound,
                    UNAuthorizationOptionBadge
                )
                
                notification_center = UNUserNotificationCenter.currentNotificationCenter()
                options = (
                    UNAuthorizationOptionAlert |
                    UNAuthorizationOptionSound |
                    UNAuthorizationOptionBadge
                )
                
                # Use a simple synchronous approach with timeout
                permission_granted = None
                
                def auth_callback(granted, error):
                    nonlocal permission_granted
                    if error:
                        Log.warn(f"Notification permission request error: {error}")
                        permission_granted = False
                    elif granted:
                        permission_granted = True
                        Log.info("Notification permission granted via UserNotifications")
                    else:
                        permission_granted = False
                        Log.warn("Notification permission denied via UserNotifications")
                
                Log.info("Requesting notification permission via UserNotifications framework...")
                notification_center.requestAuthorizationWithOptions_completionHandler_(options, auth_callback)
                
                # Wait for async callback (with timeout)
                wait_time = 0
                while permission_granted is None and wait_time < 3:
                    time.sleep(0.1)
                    wait_time += 0.1
                
                if permission_granted is True:
                    _notification_permission_cache = True
                    Log.kv({"stage": "notification_permissions", "result": "granted_via_usernotifications"})
                elif permission_granted is False:
                    _notification_permission_cache = False
                    Log.kv({"stage": "notification_permissions", "result": "denied"})
                else:
                    # Timeout or unclear - assume allowed (osascript might still work)
                    _notification_permission_cache = True
                    Log.info("Notification permission request timeout - assuming allowed (osascript may work)")
                    Log.kv({"stage": "notification_permissions", "result": "timeout_assumed_allowed"})
                    
            except ImportError:
                # UserNotifications not available - assume allowed (osascript typically works)
                _notification_permission_cache = True
                Log.info("UserNotifications framework not available - assuming allowed (osascript notifications)")
                Log.kv({"stage": "notification_permissions", "result": "assumed_allowed_no_usernotifications"})
            except Exception as e:
                # Error with UserNotifications - assume allowed
                _notification_permission_cache = True
                Log.warn(f"UserNotifications framework error: {e} - assuming allowed")
                Log.kv({"stage": "notification_permissions", "result": "assumed_allowed", "error": str(e)})
        
    except Exception as e:
        Log.warn(f"Notification permission check failed: {e}")
        # Default to True - osascript notifications typically work without explicit permission
        _notification_permission_cache = True
        Log.kv({"stage": "notification_permissions", "result": "assumed_allowed", "error": str(e)})
    
    return _notification_permission_cache

