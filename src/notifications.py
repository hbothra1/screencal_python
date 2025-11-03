"""
Notification helper for showing macOS notifications to the user.
Uses AppKit to create transparent overlay windows (like "Hold ⌘Q to Quit").
"""

from collections import deque

from src.logging_helper import Log

try:
    from AppKit import (
        NSWindow, NSView, NSColor, NSFont, NSMutableParagraphStyle,
        NSTextAlignmentCenter, NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered, NSTextField, NSBezierPath,
        NSApplication, NSAttributedString, NSMakeRect, NSMakeSize,
        NSRectFill, NSVisualEffectView,
        NSVisualEffectMaterialSheet, NSVisualEffectStateActive,
        NSScreen, NSFloatingWindowLevel, NSAnimationContext
    )
    from Foundation import NSObject, NSTimer, NSRunLoop, NSRunLoopCommonModes, NSDictionary
    from Foundation import NSThread
    import objc
    APPKIT_AVAILABLE = True
except ImportError:
    APPKIT_AVAILABLE = False


if APPKIT_AVAILABLE:

    class NotificationWindow(object):
        def __init__(self, ns_window):
            self.ns_window = ns_window
            self._notification_active = False
            self._fade_helper = None
            self._fade_timer = None


    try:
        NotificationFadeHelper = objc.lookUpClass("NotificationFadeHelper")  # type: ignore[assignment]
    except objc.error:

        class NotificationFadeHelper(NSObject):
            """Helper object owned by NSTimer callbacks to run fade-out animation."""

            def init(self):  # type: ignore[override]
                self = objc.super(NotificationFadeHelper, self).init()
                if self is None:
                    return None
                self._window_ref = None
                self._fade_duration = 0.25
                return self

            def setWindow_(self, notification_window):
                """Store reference to the active notification window."""
                self._window_ref = notification_window

            def startFadeOut_(self, timer):  # noqa: N802 - ObjC selector
                Log.info("Starting fade-out animation.")
                notification_window_ref = self._window_ref
                if not notification_window_ref or not notification_window_ref._notification_active:
                    return

                if timer is not None and getattr(notification_window_ref, "_fade_timer", None):
                    try:
                        notification_window_ref._fade_timer.invalidate()
                    except Exception:
                        pass
                    notification_window_ref._fade_timer = None

                def _animation_group(context):
                    context.setDuration_(self._fade_duration)
                    notification_window_ref.ns_window.animator().setAlphaValue_(0.0)

                def _completion_handler():
                    global _ACTIVE_NOTIFICATION
                    if not notification_window_ref:
                        return
                    Log.info("Fade out complete, closing window.")
                    try:
                        notification_window_ref.ns_window.orderOut_(None)
                        notification_window_ref.ns_window.close()
                    finally:
                        notification_window_ref._notification_active = False
                        notification_window_ref._fade_helper = None
                        notification_window_ref._fade_timer = None
                        if _ACTIVE_NOTIFICATION is notification_window_ref:
                            _ACTIVE_NOTIFICATION = None
                        _dequeue_and_show_next()
                        self._window_ref = None

                NSAnimationContext.runAnimationGroup_completionHandler_(_animation_group, _completion_handler)
else:
    NotificationWindow = None  # type: ignore[assignment]
    NotificationFadeHelper = None  # type: ignore[assignment]

# Track currently visible notification and queue of pending notifications
_ACTIVE_NOTIFICATION = None
_PENDING_NOTIFICATIONS = deque()


def _dequeue_and_show_next():
    """Show the next pending notification if nothing is currently visible."""
    if not APPKIT_AVAILABLE:
        return

    global _ACTIVE_NOTIFICATION

    if _ACTIVE_NOTIFICATION is not None:
        return

    if not _PENDING_NOTIFICATIONS:
        return

    title, message, timeout = _PENDING_NOTIFICATIONS.popleft()
    Log.info(f"Dequeued notification: {message}")
    _show_overlay_window(title, message, timeout)

def _create_overlay_window(title: str, message: str):
    """Create a transparent overlay window for notifications."""
    # Get screen size
    screen = NSScreen.mainScreen().frame()
    screen_width = screen.size.width
    screen_height = screen.size.height
    
    # Window size
    window_width = 400
    window_height = 120
    
    # Center position
    x = (screen_width - window_width) / 2
    y = screen_height * 0.7  # Position in upper portion of screen
    
    # Create borderless window using PyObjC pattern
    content_rect = NSMakeRect(x, y, window_width, window_height)
    
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        content_rect,
        NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered,
        False
    )
    
    # Make window properties
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    window.setLevel_(NSFloatingWindowLevel)
    window.setIgnoresMouseEvents_(True)  # Don't block mouse events
    
    # Create visual effect view (blurred background)
    content_view = NSVisualEffectView.alloc().initWithFrame_(
        NSMakeRect(0, 0, window_width, window_height)
    )
    content_view.setMaterial_(NSVisualEffectMaterialSheet)
    content_view.setState_(NSVisualEffectStateActive)
    content_view.setWantsLayer_(True)
    content_view.layer().setCornerRadius_(12.0)
    
    # Create label for text
    text_field = NSTextField.alloc().initWithFrame_(
        NSMakeRect(20, 20, window_width - 40, window_height - 40)
    )
    text_field.setStringValue_(message)
    text_field.setBezeled_(False)
    text_field.setDrawsBackground_(False)
    text_field.setEditable_(False)
    text_field.setSelectable_(False)
    
    # Style the text
    font = NSFont.boldSystemFontOfSize_(18.0)
    text_field.setFont_(font)
    text_field.setTextColor_(NSColor.whiteColor())
    
    # Center align
    paragraph_style = NSMutableParagraphStyle.alloc().init()
    paragraph_style.setAlignment_(NSTextAlignmentCenter)
    # Create attributed string with proper attribute keys
    attributes = {
        'NSFont': font,
        'NSForegroundColor': NSColor.whiteColor(),
        'NSParagraphStyle': paragraph_style
    }
    attributed_string = NSAttributedString.alloc().initWithString_attributes_(message, attributes)
    text_field.setAttributedStringValue_(attributed_string)
    
    # Add to view
    content_view.addSubview_(text_field)
    window.setContentView_(content_view)
    
    # Start transparent for fade-in
    window.setAlphaValue_(0.0)
    
    # Wrap the NSWindow in our custom NotificationWindow class
    notification_window = NotificationWindow(window)
    notification_window.title = title
    
    return notification_window


def _show_overlay_window(title: str, message: str, timeout: float = 3.0):
    """Show overlay window and animate fade in/out. Must be called on main thread."""
    Log.info(f"Creating overlay window with message: '{message}' and timeout: {timeout}")
    if not APPKIT_AVAILABLE:
        # Fallback to banner notification
        try:
            import subprocess
            subprocess.Popen(
                ['osascript', '-e', f'display notification "{message}" with title "ScreenCal"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            Log.info(f"Fell back to banner notification: {message}")
        except:
            pass
        return
    
    try:
        # Ensure NSApplication is running and activated
        app = NSApplication.sharedApplication()
        app.activateIgnoringOtherApps_(True)
        
        # Create overlay window (must be on main thread)
        notification_window = _create_overlay_window(title, message)
        
        # Set notification active flag on the wrapper object
        notification_window._notification_active = True

        # Ensure window starts fully transparent before animating in
        notification_window.ns_window.setAlphaValue_(0.0)
        notification_window.ns_window.makeKeyAndOrderFront_(None)
        notification_window.ns_window.orderFront_(None)
        Log.info("Overlay window created and ordered front.")

        # Fade the window in for a subtle appearance
        def _fade_in_group(context):
            context.setDuration_(0.18)
            notification_window.ns_window.animator().setAlphaValue_(1.0)

        NSAnimationContext.runAnimationGroup_completionHandler_(_fade_in_group, lambda: None)

        # Prepare fade helper and schedule fade out after timeout
        fade_helper = NotificationFadeHelper.alloc().init()
        fade_helper.setWindow_(notification_window)
        notification_window._fade_helper = fade_helper

        timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            timeout, fade_helper, 'startFadeOut:', None, False
        )
        notification_window._fade_timer = timer
        Log.info(f"Scheduled fade-out timer for {timeout} seconds")

        _ACTIVE_NOTIFICATION = notification_window
        
    except Exception as e:
        Log.warn(f"Error showing overlay window: {e}")
        # Fallback to banner notification
        try:
            import subprocess
            subprocess.Popen(
                ['osascript', '-e', f'display notification "{message}" with title "{title}"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except:
            pass
        finally:
            global _ACTIVE_NOTIFICATION
            _ACTIVE_NOTIFICATION = None
            _dequeue_and_show_next()


def show_notification(title: str, message: str, timeout: float = 3.0) -> bool:
    """
    Show a transparent, non-intrusive center-screen overlay (like "Hold ⌘Q to Quit").
    Auto-dismisses with fade animation after timeout seconds.
    Does not block user interaction.
    
    Args:
        title: Notification title (not currently displayed)
        message: Notification message
        timeout: Seconds before auto-dismissing (default: 3)
        
    Returns:
        True if notification was shown successfully, False otherwise
    """
    try:
        Log.info(f"show_notification called. APPKIT_AVAILABLE: {APPKIT_AVAILABLE}")
        if APPKIT_AVAILABLE:
            Log.info(f"Is main thread: {NSThread.isMainThread()}")
        if not APPKIT_AVAILABLE:
            # Fallback to banner notification
            try:
                import subprocess
                subprocess.Popen(
                    ['osascript', '-e', f'display notification "{message}" with title "ScreenCal"'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                Log.info(f"Fell back to banner notification: {message}")
                return True
            except:
                return False
        
        def enqueue_on_main():
            _PENDING_NOTIFICATIONS.append((title, message, timeout))
            Log.info(f"Notification enqueued: {message}")
            _dequeue_and_show_next()

        if NSThread.isMainThread():
            enqueue_on_main()
        else:
            try:
                main_runloop = NSRunLoop.mainRunLoop()
                if hasattr(main_runloop, 'performBlock_'):
                    main_runloop.performBlock_(enqueue_on_main)
                else:
                    class EnqueueRunner(NSObject):
                        def run_block(self):
                            enqueue_on_main()

                    runner = EnqueueRunner.alloc().init()
                    runner.performSelectorOnMainThread_withObject_waitUntilDone_(
                        'run_block', None, False
                    )
            except Exception as e:
                Log.warn(f"Error scheduling notification enqueue on main thread: {e}")
                enqueue_on_main()
        
        Log.info(f"Overlay notification shown: {message} (will fade out in {timeout}s)")
        return True
    except Exception as e:
        Log.warn(f"Error showing notification: {e}")
        # Fallback to banner notification
        try:
            import subprocess
            subprocess.Popen(
                ['osascript', '-e', f'display notification "{message}" with title "ScreenCal"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except:
            return False


def notify_screen_captured(timeout: float = 2.0) -> bool:
    """Show notification that screen was captured and being processed by LLM."""
    return show_notification(
        "ScreenCal",
        "Screen captured, passing information to LLM",
        timeout=timeout
    )


def notify_event_detected(timeout: float = 3.0) -> bool:
    """Show notification that event was detected and creating appointment."""
    return show_notification(
        "ScreenCal",
        "Event detected, creating appointment",
        timeout=timeout
    )


def notify_no_event_detected(timeout: float = 2.5) -> bool:
    """Show notification that no event was detected."""
    return show_notification(
        "ScreenCal",
        "No event detected",
        timeout=timeout
    )


def notify_calendar_opening(timeout: float = 2.5) -> bool:
    """Show notification that calendar is opening."""
    return show_notification(
        "ScreenCal",
        "Opening calendar",
        timeout=timeout
    )

