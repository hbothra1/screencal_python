"""
Main app entry point for ScreenCal4 menu bar app.
Phase 1: Permissions & Capture implementation.
"""

from src.logging_helper import Log
from src.permissions import ensure_screen_recording, ensure_notification_permission
from src.statusbar_controller import StatusBarController


def main():
    """Main entry point for the app."""
    Log.section("ScreenCal4")
    Log.info("Starting ScreenCal4 menu bar app")
    Log.info(f"Log file: {Log.get_log_path()}")
    
    # Check permissions ONCE at startup
    permission_granted = ensure_screen_recording()
    
    if not permission_granted:
        Log.warn("Screen recording permission not granted - capture will fail")
        Log.info("App will still show menu (user can quit)")
    else:
        Log.info("Screen recording permission granted")
    
    # Check notification permission
    notification_permission = ensure_notification_permission()
    
    if not notification_permission:
        Log.warn("Notification permission not granted - notifications may not appear")
        Log.info("You can enable notifications in System Settings > Notifications if needed")
    else:
        Log.info("Notification permission available")
    
    # Initialize and run status bar controller
    Log.info("Initializing menu bar interface")
    app = StatusBarController()
    app.run()


if __name__ == "__main__":
    main()

