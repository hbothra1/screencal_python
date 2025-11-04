"""
Notification helper for showing macOS notifications to the user.
Uses AppKit to create transparent overlay windows (like "Hold ⌘Q to Quit").
"""

from collections import deque
import threading
import time
from enum import Enum
from typing import Optional

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
        def __init__(self, ns_window, text_field, text_attributes):
            self.ns_window = ns_window
            self.text_field = text_field
            self.text_attributes = text_attributes
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
                        global _CURRENT_STATE, _STATE_START_TIME
                        _CURRENT_STATE = NotificationState.IDLE
                        _STATE_START_TIME = 0.0
                        _cancel_min_display_timer()
                        if _ACTIVE_NOTIFICATION is notification_window_ref:
                            _ACTIVE_NOTIFICATION = None
                        _dequeue_and_show_next()
                        self._window_ref = None

                NSAnimationContext.runAnimationGroup_completionHandler_(_animation_group, _completion_handler)


    class _MainThreadDispatchHelper(NSObject):
        """Utility object to dispatch Python callables onto the main thread."""

        def initWithCallable_(self, callback):
            self = objc.super(_MainThreadDispatchHelper, self).init()
            if self is None:
                return None
            self._callback = callback
            return self

        def run_(self, _):  # noqa: N802 - ObjC selector style
            if self._callback is None:
                return
            try:
                self._callback()
            finally:
                self._callback = None
else:
    NotificationWindow = None  # type: ignore[assignment]
    NotificationFadeHelper = None  # type: ignore[assignment]


def _dispatch_to_main(callback):
    """Ensure the provided callable runs on the main thread."""
    global _SHUTTING_DOWN
    
    if _SHUTTING_DOWN:
        return
    
    if not APPKIT_AVAILABLE:
        callback()
        return

    if NSThread.isMainThread():
        callback()
        return

    try:
        main_runloop = NSRunLoop.mainRunLoop()
        if hasattr(main_runloop, 'performBlock_'):
            main_runloop.performBlock_(callback)
            return

        helper = _MainThreadDispatchHelper.alloc().initWithCallable_(callback)
        helper.performSelectorOnMainThread_withObject_waitUntilDone_(
            'run:', None, False
        )
    except Exception:
        if not _SHUTTING_DOWN:
            callback()

# Track currently visible notification and queue of pending notifications
_ACTIVE_NOTIFICATION = None
_PENDING_NOTIFICATIONS = deque()

_NOTIFICATION_TITLE = "ScreenCal"
_CAPTURE_MESSAGE = "Screen captured, passing information to LLM"
_PROCESSING_MESSAGE = "Analyzing captured screen..."
_EVENT_DETECTED_MESSAGE = "Event detected, creating appointment"
_NO_EVENT_MESSAGE = "No event detected"
_CALENDAR_MESSAGE = "Opening calendar"


class NotificationState(Enum):
    IDLE = "idle"
    SCREEN_CAPTURED = "screen_captured"
    PROCESSING_LLM = "processing_llm"
    EVENT_DETECTED = "event_detected"
    NO_EVENT = "no_event"


_CURRENT_STATE = NotificationState.IDLE
_STATE_START_TIME = 0.0
_MIN_DISPLAY_TIMER: Optional[threading.Timer] = None
_SHUTTING_DOWN = False

_MIN_CAPTURE_DISPLAY = 2.0
_EVENT_FADE_TIMEOUT = 3.0
_NO_EVENT_FADE_TIMEOUT = 2.5
_CALENDAR_FADE_TIMEOUT = 2.0


def _cancel_min_display_timer():
    """Cancel the minimum display timer if it's running."""
    global _MIN_DISPLAY_TIMER
    timer = _MIN_DISPLAY_TIMER
    if timer is None:
        return
    try:
        timer.cancel()
    except Exception:
        pass
    finally:
        _MIN_DISPLAY_TIMER = None


def _start_min_display_timer():
    """Start or restart the minimum display timer for the capture notification."""
    global _MIN_DISPLAY_TIMER
    _cancel_min_display_timer()

    timer = threading.Timer(_MIN_CAPTURE_DISPLAY, _handle_minimum_display_elapsed)
    timer.daemon = True
    _MIN_DISPLAY_TIMER = timer
    timer.start()


def _handle_minimum_display_elapsed():
    """Callback when the capture notification has been visible for the minimum duration."""
    global _SHUTTING_DOWN, _MIN_DISPLAY_TIMER
    
    if _SHUTTING_DOWN:
        _MIN_DISPLAY_TIMER = None
        return

    def _on_main():
        global _MIN_DISPLAY_TIMER
        if _SHUTTING_DOWN:
            _MIN_DISPLAY_TIMER = None
            return
        
        _MIN_DISPLAY_TIMER = None

        if _CURRENT_STATE == NotificationState.SCREEN_CAPTURED:
            Log.info("Capture notification minimum display duration elapsed; updating message.")
            _transition_state(
                NotificationState.PROCESSING_LLM,
                _PROCESSING_MESSAGE,
                fade_timeout=None,
                start_min_timer=False,
            )

    _dispatch_to_main(_on_main)


def _update_active_notification_text_on_main(message: str):
    """Update the text of the active notification window (main thread only)."""
    if not APPKIT_AVAILABLE:
        return

    notification_window = _ACTIVE_NOTIFICATION
    if notification_window is None:
        return

    text_field = getattr(notification_window, "text_field", None)
    if text_field is None:
        return

    attributes = getattr(notification_window, "text_attributes", None)
    if attributes is None:
        attributes = {}

    attributed_string = NSAttributedString.alloc().initWithString_attributes_(
        message,
        attributes,
    )
    text_field.setAttributedStringValue_(attributed_string)
    notification_window.ns_window.displayIfNeeded()


def _cancel_fade_on_main(notification_window):
    if not APPKIT_AVAILABLE or notification_window is None:
        return

    timer = getattr(notification_window, "_fade_timer", None)
    if timer is not None:
        try:
            timer.invalidate()
        except Exception:
            pass
    notification_window._fade_timer = None


def _reschedule_fade_on_main(notification_window, timeout: float):
    if not APPKIT_AVAILABLE or notification_window is None:
        return

    if timeout is None:
        _cancel_fade_on_main(notification_window)
        return

    _cancel_fade_on_main(notification_window)

    fade_helper = getattr(notification_window, "_fade_helper", None)
    if fade_helper is None and NotificationFadeHelper is not None:
        fade_helper = NotificationFadeHelper.alloc().init()
        fade_helper.setWindow_(notification_window)
        notification_window._fade_helper = fade_helper

    if fade_helper is None:
        return

    timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        timeout,
        fade_helper,
        'startFadeOut:',
        None,
        False,
    )
    notification_window._fade_timer = timer


def _present_or_update_notification_on_main(message: str, fade_timeout: Optional[float]):
    global _SHUTTING_DOWN
    
    if _SHUTTING_DOWN:
        return
    
    if not APPKIT_AVAILABLE:
        show_notification(_NOTIFICATION_TITLE, message, fade_timeout if fade_timeout is not None else 3.0)
        return

    global _ACTIVE_NOTIFICATION
    notification_window = _ACTIVE_NOTIFICATION

    if notification_window is None or not getattr(notification_window, "_notification_active", False):
        _show_overlay_window(_NOTIFICATION_TITLE, message, fade_timeout)
        notification_window = _ACTIVE_NOTIFICATION
        if fade_timeout is None and notification_window is not None:
            _cancel_fade_on_main(notification_window)
        return

    _update_active_notification_text_on_main(message)

    if fade_timeout is None:
        _cancel_fade_on_main(notification_window)
    else:
        _reschedule_fade_on_main(notification_window, fade_timeout)


def _transition_state(
    new_state: NotificationState,
    message: str,
    fade_timeout: Optional[float],
    *,
    start_min_timer: bool,
):
    """Transition notification state machine to a new state."""
    global _SHUTTING_DOWN
    
    if _SHUTTING_DOWN:
        return

    def _execute_transition():
        global _CURRENT_STATE, _STATE_START_TIME

        if _SHUTTING_DOWN:
            return

        previous_state = _CURRENT_STATE
        _cancel_min_display_timer()

        if start_min_timer and not _SHUTTING_DOWN:
            _start_min_display_timer()

        _CURRENT_STATE = new_state
        _STATE_START_TIME = time.monotonic()

        Log.info(
            f"Notification state transition: {previous_state.value} -> {new_state.value}"
        )
        _present_or_update_notification_on_main(message, fade_timeout)

    _dispatch_to_main(_execute_transition)



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
    notification_window = NotificationWindow(window, text_field, attributes)
    notification_window.title = title
    
    return notification_window


def _show_overlay_window(title: str, message: str, timeout: Optional[float] = 3.0):
    """Show overlay window and animate fade in/out. Must be called on main thread."""
    global _ACTIVE_NOTIFICATION
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

        if timeout is not None:
            timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                timeout, fade_helper, 'startFadeOut:', None, False
            )
            notification_window._fade_timer = timer
            Log.info(f"Scheduled fade-out timer for {timeout} seconds")
        else:
            notification_window._fade_timer = None
            Log.info("Notification will remain visible until dismissed explicitly")

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
        _ACTIVE_NOTIFICATION = None
        _dequeue_and_show_next()


def show_notification(title: str, message: str, timeout: Optional[float] = 3.0) -> bool:
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
        
        timeout_desc = f"{timeout}s" if timeout is not None else "no timeout"
        Log.info(f"Overlay notification shown: {message} (will fade out in {timeout_desc})")
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


def update_notification(message: str, timeout: Optional[float] = None) -> bool:
    """Update currently visible notification with new message and optional timeout."""

    if not APPKIT_AVAILABLE:
        # Fall back to showing a new banner notification
        return show_notification(_NOTIFICATION_TITLE, message, timeout if timeout is not None else 3.0)

    result = {"success": False}

    def _update():
        notification_window = _ACTIVE_NOTIFICATION
        if notification_window is None or not getattr(notification_window, "_notification_active", False):
            result["success"] = show_notification(
                _NOTIFICATION_TITLE,
                message,
                timeout if timeout is not None else 3.0,
            )
            return

        _update_active_notification_text_on_main(message)

        if timeout is None:
            _cancel_fade_on_main(notification_window)
        else:
            _reschedule_fade_on_main(notification_window, timeout)

        result["success"] = True

    _dispatch_to_main(_update)

    return result["success"]


def notification_on_capture_complete() -> bool:
    """State-machine aware notification for successful screen capture."""

    if not APPKIT_AVAILABLE:
        return notify_screen_captured(timeout=_MIN_CAPTURE_DISPLAY)

    _transition_state(
        NotificationState.SCREEN_CAPTURED,
        _CAPTURE_MESSAGE,
        fade_timeout=None,
        start_min_timer=True,
    )
    return True


def notification_on_llm_processing_start():
    """Optional hook when LLM processing begins."""

    if not APPKIT_AVAILABLE:
        return

    def _maybe_transition():
        if _CURRENT_STATE == NotificationState.SCREEN_CAPTURED:
            elapsed = time.monotonic() - _STATE_START_TIME
            if elapsed >= _MIN_CAPTURE_DISPLAY:
                _transition_state(
                    NotificationState.PROCESSING_LLM,
                    _PROCESSING_MESSAGE,
                    fade_timeout=None,
                    start_min_timer=False,
                )
        elif _CURRENT_STATE == NotificationState.IDLE:
            _transition_state(
                NotificationState.PROCESSING_LLM,
                _PROCESSING_MESSAGE,
                fade_timeout=None,
                start_min_timer=False,
            )

    _dispatch_to_main(_maybe_transition)


def notification_on_llm_complete(event_found: bool):
    """Update notification based on LLM outcome."""

    if not APPKIT_AVAILABLE:
        if event_found:
            notify_event_detected(timeout=_EVENT_FADE_TIMEOUT)
        else:
            notify_no_event_detected(timeout=_NO_EVENT_FADE_TIMEOUT)
        return

    if event_found:
        _transition_state(
            NotificationState.EVENT_DETECTED,
            _EVENT_DETECTED_MESSAGE,
            fade_timeout=None,
            start_min_timer=False,
        )
    else:
        _transition_state(
            NotificationState.NO_EVENT,
            _NO_EVENT_MESSAGE,
            fade_timeout=_NO_EVENT_FADE_TIMEOUT,
            start_min_timer=False,
        )


def notification_on_calendar_opening():
    """Notify user that Calendar is about to open."""

    if not APPKIT_AVAILABLE:
        notify_calendar_opening(timeout=_CALENDAR_FADE_TIMEOUT)
        return

    _transition_state(
        NotificationState.EVENT_DETECTED,
        _CALENDAR_MESSAGE,
        fade_timeout=_CALENDAR_FADE_TIMEOUT,
        start_min_timer=False,
    )


def notification_reset():
    """Force-dismiss the active notification window."""

    if not APPKIT_AVAILABLE:
        return

    def _dismiss():
        global _CURRENT_STATE, _STATE_START_TIME
        notification_window = _ACTIVE_NOTIFICATION
        if notification_window and getattr(notification_window, "_notification_active", False):
            _reschedule_fade_on_main(notification_window, 0.1)
        _CURRENT_STATE = NotificationState.IDLE
        _STATE_START_TIME = 0.0
        _cancel_min_display_timer()

    _dispatch_to_main(_dismiss)


def notification_shutdown():
    """Clean up all notification resources before app shutdown."""
    global _SHUTTING_DOWN, _ACTIVE_NOTIFICATION, _CURRENT_STATE, _STATE_START_TIME
    
    _SHUTTING_DOWN = True
    
    # Cancel timer first
    _cancel_min_display_timer()
    
    # Clean up notification window if APPKIT is available and we're on main thread
    if not APPKIT_AVAILABLE:
        return
    
    def _cleanup():
        global _ACTIVE_NOTIFICATION, _CURRENT_STATE, _STATE_START_TIME
        
        try:
            notification_window = _ACTIVE_NOTIFICATION
            if notification_window is not None:
                # Cancel any fade timers
                timer = getattr(notification_window, "_fade_timer", None)
                if timer is not None:
                    try:
                        timer.invalidate()
                    except Exception:
                        pass
                
                # Close window
                try:
                    ns_window = getattr(notification_window, "ns_window", None)
                    if ns_window is not None:
                        ns_window.orderOut_(None)
                        ns_window.close()
                except Exception:
                    pass
                
                _ACTIVE_NOTIFICATION = None
            
            _CURRENT_STATE = NotificationState.IDLE
            _STATE_START_TIME = 0.0
        except Exception:
            # Silently ignore errors during shutdown
            pass
    
    # Try to run cleanup on main thread, but if that fails, just clear state
    try:
        if NSThread.isMainThread():
            _cleanup()
        else:
            # Don't try to dispatch during shutdown - just clear state
            _ACTIVE_NOTIFICATION = None
            _CURRENT_STATE = NotificationState.IDLE
            _STATE_START_TIME = 0.0
    except Exception:
        # Silently ignore - app is shutting down
        pass


def notify_screen_captured(timeout: float = 2.0) -> bool:
    """Show notification that screen was captured and being processed by LLM."""
    return show_notification(
        _NOTIFICATION_TITLE,
        _CAPTURE_MESSAGE,
        timeout=timeout
    )


def notify_event_detected(timeout: float = 3.0) -> bool:
    """Show notification that event was detected and creating appointment."""
    return show_notification(
        _NOTIFICATION_TITLE,
        _EVENT_DETECTED_MESSAGE,
        timeout=timeout
    )


def notify_no_event_detected(timeout: float = 2.5) -> bool:
    """Show notification that no event was detected."""
    return show_notification(
        _NOTIFICATION_TITLE,
        _NO_EVENT_MESSAGE,
        timeout=timeout
    )


def notify_calendar_opening(timeout: float = 2.5) -> bool:
    """Show notification that calendar is opening."""
    return show_notification(
        _NOTIFICATION_TITLE,
        _CALENDAR_MESSAGE,
        timeout=timeout
    )

