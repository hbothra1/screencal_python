"""
Notification helper for showing macOS notifications to the user.
Uses AppKit to create transparent overlay windows (like "Hold ⌘Q to Quit").
"""

from collections import deque
import math
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
        NSScreen, NSFloatingWindowLevel, NSAnimationContext,
        NSStringDrawingUsesLineFragmentOrigin, NSStringDrawingUsesFontLeading,
        NSLineBreakByWordWrapping
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
                global _SHUTTING_DOWN
                
                Log.info("[FADE] startFadeOut_ called")
                
                # Don't do anything if shutting down
                if _SHUTTING_DOWN:
                    Log.info("[FADE] Shutting down - aborting fade-out")
                    return
                
                Log.info("Starting fade-out animation.")
                notification_window_ref = self._window_ref
                if not notification_window_ref or not notification_window_ref._notification_active:
                    Log.info("[FADE] No active notification window - aborting")
                    return

                if _SHUTTING_DOWN:
                    Log.info("[FADE] Shutting down during fade setup - aborting")
                    return

                if timer is not None and getattr(notification_window_ref, "_fade_timer", None):
                    try:
                        Log.info("[FADE] Invalidating existing timer")
                        notification_window_ref._fade_timer.invalidate()
                    except Exception as e:
                        Log.warn(f"[FADE] Error invalidating timer: {e}")
                    notification_window_ref._fade_timer = None

                def _animation_group(context):
                    Log.info("[FADE] Animation group started")
                    if _SHUTTING_DOWN:
                        Log.info("[FADE] Shutting down during animation - aborting")
                        return
                    context.setDuration_(self._fade_duration)
                    if not _SHUTTING_DOWN and notification_window_ref:
                        try:
                            Log.info("[FADE] Setting window alpha to 0.0")
                            notification_window_ref.ns_window.animator().setAlphaValue_(0.0)
                        except Exception as e:
                            Log.warn(f"[FADE] Error setting alpha: {e}")

                def _completion_handler():
                    Log.info("[FADE] Completion handler called")

                    if _SHUTTING_DOWN:
                        Log.info("[FADE] Shutting down - aborting completion handler")
                        return

                    if not notification_window_ref:
                        Log.info("[FADE] No notification window ref - aborting")
                        return

                    # Check if window is still active before attempting to close
                    if not getattr(notification_window_ref, "_notification_active", False):
                        Log.info("[FADE] Window already inactive - skipping close in completion handler")
                        self._window_ref = None
                        return

                    # Close the window (this will also mark it as inactive)
                    _close_notification_window(notification_window_ref, source="fade")
                    self._window_ref = None
                    Log.info("[FADE] Completion handler finished")

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
        Log.info("[DISPATCH] Shutting down - aborting dispatch")
        return
    
    if not APPKIT_AVAILABLE:
        callback()
        return

    # Check if we're on main thread using Python threading first (safer)
    # This avoids AppKit access from background threads which can cause crashes
    try:
        is_main_thread = threading.current_thread() is threading.main_thread()
        if is_main_thread:
            # We're on main thread - safe to call directly
            callback()
            return
    except Exception:
        # If threading check fails, fall through to AppKit check
        pass

    # If not on main thread, dispatch using AppKit
    # Wrap AppKit calls in try-except to handle crashes gracefully
    try:
        Log.info("[DISPATCH] Dispatching to main thread")
        try:
            main_runloop = NSRunLoop.mainRunLoop()
            if hasattr(main_runloop, 'performBlock_'):
                main_runloop.performBlock_(callback)
                return
        except Exception as e:
            Log.warn(f"[DISPATCH] performBlock_ failed: {e}, trying alternative")
        
        try:
            helper = _MainThreadDispatchHelper.alloc().initWithCallable_(callback)
            helper.performSelectorOnMainThread_withObject_waitUntilDone_(
                'run:', None, False
            )
        except Exception as e:
            Log.warn(f"[DISPATCH] performSelectorOnMainThread failed: {e}")
            # Last resort: try calling callback directly (risky but better than crashing)
            Log.warn("[DISPATCH] Falling back to direct callback call (may be unsafe)")
            callback()
    except Exception as e:
        Log.warn(f"[DISPATCH] Error dispatching: {e}")

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


def _close_notification_window(notification_window=None, source="unknown") -> bool:
    """Close the active notification window safely.

    Args:
        notification_window: Optional specific NotificationWindow instance.
        source: String identifier for logging.

    Returns:
        True if a window was closed or already cleaned up, False if nothing to do.
    """
    global _ACTIVE_NOTIFICATION, _CURRENT_STATE, _STATE_START_TIME

    if notification_window is None:
        notification_window = _ACTIVE_NOTIFICATION

    if notification_window is None:
        Log.info(f"[CLOSE:{source}] No notification window to close")
        return False

    # Check if window is already inactive - prevents double-close race condition
    if not getattr(notification_window, "_notification_active", False):
        Log.info(f"[CLOSE:{source}] Window already inactive - skipping close")
        return False

    # Mark as inactive IMMEDIATELY to prevent concurrent close attempts
    notification_window._notification_active = False
    Log.info(f"[CLOSE:{source}] Marked window as inactive")

    def _close_on_main():
        global _ACTIVE_NOTIFICATION, _CURRENT_STATE, _STATE_START_TIME

        Log.info(f"[CLOSE:{source}] Closing notification window on main thread")

        # Cancel fade timer if present
        fade_timer = getattr(notification_window, "_fade_timer", None)
        if fade_timer is not None:
            try:
                fade_timer.invalidate()
                Log.info(f"[CLOSE:{source}] NSTimer invalidated")
            except Exception as exc:
                Log.warn(f"[CLOSE:{source}] Failed to invalidate NSTimer: {exc}")
        notification_window._fade_timer = None

        # Drop reference to fade helper
        notification_window._fade_helper = None

        if APPKIT_AVAILABLE and not _SHUTTING_DOWN:
            try:
                ns_window = getattr(notification_window, "ns_window", None)
                if ns_window is not None:
                    try:
                        ns_window.orderOut_(None)
                        Log.info(f"[CLOSE:{source}] NSWindow ordered out")
                    except Exception as exc:
                        Log.warn(f"[CLOSE:{source}] Error ordering out NSWindow: {exc}")

                    try:
                        ns_window.setAlphaValue_(0.0)
                    except Exception:
                        pass  # Safe to ignore if window already gone

                    # Drop reference so autorelease can clean up safely
                    notification_window.ns_window = None
                else:
                    Log.info(f"[CLOSE:{source}] NSWindow already None")
            except Exception as exc:
                Log.warn(f"[CLOSE:{source}] Error handling NSWindow: {exc}")
        else:
            Log.info(f"[CLOSE:{source}] Skipping NSWindow close (APPKIT_AVAILABLE={APPKIT_AVAILABLE}, _SHUTTING_DOWN={_SHUTTING_DOWN})")

        # Clear global Python reference - let PyObjC handle AppKit object lifecycle
        # The autorelease pool created by performSelectorOnMainThread will properly
        # release the AppKit objects (ns_window, text_field, etc.) when it drains
        _ACTIVE_NOTIFICATION = None
        _CURRENT_STATE = NotificationState.IDLE
        _STATE_START_TIME = 0.0
        _cancel_min_display_timer()

    if not APPKIT_AVAILABLE:
        Log.info(f"[CLOSE:{source}] AppKit unavailable - clearing references only")
        _ACTIVE_NOTIFICATION = None
        _CURRENT_STATE = NotificationState.IDLE
        _STATE_START_TIME = 0.0
        _cancel_min_display_timer()
        return True

    # Check if we're on main thread using Python threading first (safer)
    # This avoids AppKit access which can cause crashes
    is_main_thread = False
    try:
        is_main_thread = threading.current_thread() is threading.main_thread()
    except Exception:
        pass  # Fall through to AppKit check

    if is_main_thread:
        # We're on main thread - safe to call directly
        try:
            # Double-check with AppKit if available (for safety)
            if NSThread.isMainThread():
                _close_on_main()
                return True
        except Exception:
            # If AppKit check fails, still call _close_on_main since we're on main thread
            _close_on_main()
            return True
    else:
        if _SHUTTING_DOWN:
            Log.info(f"[CLOSE:{source}] Shutting down off-main thread - clearing references without AppKit access")
            _ACTIVE_NOTIFICATION = None
            _CURRENT_STATE = NotificationState.IDLE
            _STATE_START_TIME = 0.0
            _cancel_min_display_timer()
        else:
            try:
                Log.info(f"[CLOSE:{source}] Dispatching close to main thread")
                # Wrap AppKit calls in try-except
                try:
                    main_runloop = NSRunLoop.mainRunLoop()
                    if hasattr(main_runloop, 'performBlock_'):
                        main_runloop.performBlock_(_close_on_main)
                        return True
                except Exception as e:
                    Log.warn(f"[CLOSE:{source}] performBlock_ failed: {e}, trying alternative")
                
                try:
                    helper = _MainThreadDispatchHelper.alloc().initWithCallable_(_close_on_main)
                    helper.performSelectorOnMainThread_withObject_waitUntilDone_(
                        'run:', None, False
                    )
                except Exception as exc:
                    Log.warn(f"[CLOSE:{source}] Error dispatching close: {exc}")
                    # Fallback: clear references without AppKit access
                    _ACTIVE_NOTIFICATION = None
                    _CURRENT_STATE = NotificationState.IDLE
                    _STATE_START_TIME = 0.0
                    _cancel_min_display_timer()
            except Exception as exc:
                Log.warn(f"[CLOSE:{source}] Error in dispatch logic: {exc}")
                # Fallback: clear references without AppKit access
                _ACTIVE_NOTIFICATION = None
                _CURRENT_STATE = NotificationState.IDLE
                _STATE_START_TIME = 0.0
                _cancel_min_display_timer()

    return True


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
    
    Log.info("[TIMER] Minimum display timer elapsed")
    
    if _SHUTTING_DOWN:
        Log.info("[TIMER] Shutting down - aborting timer callback")
        _MIN_DISPLAY_TIMER = None
        return

    def _on_main():
        global _MIN_DISPLAY_TIMER
        Log.info("[TIMER] Timer callback on main thread")
        
        if _SHUTTING_DOWN:
            Log.info("[TIMER] Shutting down on main thread - aborting")
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
        else:
            Log.info(f"[TIMER] State is {_CURRENT_STATE.value}, not updating")

    _dispatch_to_main(_on_main)


def _update_active_notification_text_on_main(message: str):
    """Update the text of the active notification window (main thread only)."""
    if not APPKIT_AVAILABLE:
        return

    notification_window = _ACTIVE_NOTIFICATION
    if notification_window is None:
        return

    _layout_centered_text(notification_window, message)
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


def _layout_centered_text(notification_window, message: str):
    """Update the notification text and center it within the window."""
    if not APPKIT_AVAILABLE or notification_window is None:
        return

    text_field = getattr(notification_window, "text_field", None)
    if text_field is None:
        return

    attributes = getattr(notification_window, "text_attributes", {}) or {}

    # Ensure we have a centered paragraph style stored
    paragraph_style = attributes.get('NSParagraphStyle')
    if paragraph_style is None:
        paragraph_style = NSMutableParagraphStyle.alloc().init()
        paragraph_style.setAlignment_(NSTextAlignmentCenter)
        attributes['NSParagraphStyle'] = paragraph_style

    # Rebuild attributed string with the stored attributes
    attributed_string = NSAttributedString.alloc().initWithString_attributes_(message, attributes)

    max_width = getattr(notification_window, "_max_text_width", text_field.frame().size.width)
    max_height = getattr(notification_window, "_max_text_height", text_field.frame().size.height)

    options = NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading
    bounding_rect = attributed_string.boundingRectWithSize_options_(
        NSMakeSize(max_width, max_height),
        options,
    )

    # Calculate text height from bounding rect (allows wrapping)
    text_height = min(max_height, math.ceil(bounding_rect.size.height))

    if text_height <= 0:
        # Fallback to a single line height based on the current font
        font = attributes.get('NSFont', text_field.font())
        if font is not None:
            text_height = math.ceil(font.ascender() - font.descender())
        else:
            text_height = max_height

    window_width = getattr(notification_window, "_window_width", max_width)
    window_height = getattr(notification_window, "_window_height", max_height)

    # Always use full max_width for text field to allow proper wrapping
    # The bounding rect calculation handles wrapping, but the text field needs full width
    text_width = max_width
    text_x = (window_width - text_width) / 2.0
    text_y = (window_height - text_height) / 2.0

    text_field.setFrame_(NSMakeRect(text_x, text_y, text_width, text_height))
    text_field.setAttributedStringValue_(attributed_string)

    # Ensure multi-line centered text rendering
    text_field.setAlignment_(NSTextAlignmentCenter)
    text_field.setMaximumNumberOfLines_(0)
    cell = text_field.cell()
    if cell is not None:
        cell.setWraps_(True)
        cell.setLineBreakMode_(NSLineBreakByWordWrapping)


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
    global _SHUTTING_DOWN
    
    if _SHUTTING_DOWN:
        return
        
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
    
    # Window size (more compact for top-right)
    window_width = 380  # Increased from 320 to accommodate longer text
    window_height = 90  # Increased from 80 to 90 for more vertical space
    
    # Position in top-right corner (macOS coordinates: origin at bottom-left)
    margin = 20  # Distance from edges
    x = screen_width - window_width - margin  # Right edge with margin
    y = screen_height - window_height - margin  # Top edge with margin
    
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
    
    # Create view with transparent light silver background
    content_view = NSView.alloc().initWithFrame_(
        NSMakeRect(0, 0, window_width, window_height)
    )
    content_view.setWantsLayer_(True)
    layer = content_view.layer()
    layer.setCornerRadius_(10.0)
    # Set transparent light silver background color (RGB: 220, 220, 220 with 0.75 alpha)
    light_silver_color = NSColor.colorWithSRGBRed_green_blue_alpha_(0.86, 0.86, 0.86, 0.75)
    # Convert NSColor to CGColor for layer background
    cg_color = light_silver_color.CGColor()
    layer.setBackgroundColor_(cg_color)
    
    # Create label for text
    text_field = NSTextField.alloc().initWithFrame_(
        NSMakeRect(16, 16, window_width - 32, window_height - 32)  # Initial frame; will be centered later (16px padding)
    )
    text_field.setBezeled_(False)
    text_field.setDrawsBackground_(False)
    text_field.setEditable_(False)
    text_field.setSelectable_(False)
    
    # Style the text (smaller font)
    font = NSFont.systemFontOfSize_(13.0)  # Reduced from 18.0 to 13.0
    text_field.setFont_(font)
    text_field.setTextColor_(NSColor.blackColor())  # Black text color
    
    # Center align
    paragraph_style = NSMutableParagraphStyle.alloc().init()
    paragraph_style.setAlignment_(NSTextAlignmentCenter)
    # Create attributed string with proper attribute keys
    attributes = {
        'NSFont': font,
        'NSForegroundColor': NSColor.blackColor(),  # Black text color
        'NSParagraphStyle': paragraph_style
    }
    # Add to view
    content_view.addSubview_(text_field)
    window.setContentView_(content_view)
    
    # Start transparent for fade-in
    window.setAlphaValue_(0.0)
    
    # Wrap the NSWindow in our custom NotificationWindow class
    notification_window = NotificationWindow(window, text_field, attributes)
    notification_window.title = title
    notification_window._window_width = window_width
    notification_window._window_height = window_height
    notification_window._max_text_width = window_width - 32  # 16px padding on each side
    notification_window._max_text_height = window_height - 32  # 16px padding on each side

    _layout_centered_text(notification_window, message)
    
    return notification_window


def _show_overlay_window(title: str, message: str, timeout: Optional[float] = 3.0):
    """Show overlay window and animate fade in/out. Must be called on main thread."""
    global _ACTIVE_NOTIFICATION, _SHUTTING_DOWN
    
    if _SHUTTING_DOWN:
        return
    
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
            try:
                Log.info(f"Is main thread: {NSThread.isMainThread()}")
            except Exception:
                # AppKit check failed, use Python threading instead
                is_main = threading.current_thread() is threading.main_thread()
                Log.info(f"Is main thread (Python): {is_main}")
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

        # Check if we're on main thread using Python threading first (safer)
        is_main_thread = False
        try:
            is_main_thread = threading.current_thread() is threading.main_thread()
        except Exception:
            pass  # Fall through to AppKit check

        if is_main_thread:
            try:
                # Double-check with AppKit if available
                if NSThread.isMainThread():
                    enqueue_on_main()
                    return True
            except Exception:
                # If AppKit check fails, still call enqueue_on_main since we're on main thread
                enqueue_on_main()
                return True
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
    """Force-dismiss the active notification window.
    
    Uses asynchronous dispatch to avoid autorelease pool conflicts.
    The window will be closed on the main thread asynchronously.
    """
    global _SHUTTING_DOWN
    
    if _SHUTTING_DOWN:
        Log.info("[RESET] Shutting down - skipping reset")
        return
    
    def _dismiss():
        global _ACTIVE_NOTIFICATION
        
        notification_window = _ACTIVE_NOTIFICATION
        if notification_window is None:
            Log.info("[RESET] No active notification to dismiss")
            return
        
        # Close window on main thread
        _close_notification_window(notification_window, source="reset")

    # Check if we're on main thread using Python threading first (safer)
    # This avoids AppKit access which can cause crashes
    is_main_thread = False
    try:
        is_main_thread = threading.current_thread() is threading.main_thread()
    except Exception:
        pass  # Fall through to dispatch

    if is_main_thread:
        # We're on main thread - safe to call directly
        try:
            # Double-check with AppKit if available (for safety)
            if NSThread.isMainThread():
                _dismiss()
                return
        except Exception:
            # If AppKit check fails, still call _dismiss since we're on main thread
            _dismiss()
            return
    else:
        # Use asynchronous dispatch to avoid autorelease pool conflicts
        # Synchronous dispatch creates an autorelease pool that conflicts with
        # the AppKit objects we're trying to release
        try:
            _dispatch_to_main(_dismiss)
        except Exception as e:
            Log.warn(f"[RESET] Error dispatching dismiss: {e}")


def notification_shutdown():
    """Clean up all notification resources before app shutdown.
    
    IMPORTANT: Do NOT access AppKit objects during shutdown.
    When rumps.quit_application() is called, NSApplication starts tearing down
    and all NSWindows are automatically deallocated. Accessing them causes segfaults.
    We only need to cancel Python timers and clear references.
    """
    global _SHUTTING_DOWN, _ACTIVE_NOTIFICATION, _CURRENT_STATE, _STATE_START_TIME
    
    Log.section("Notification Shutdown")
    if _SHUTTING_DOWN:
        Log.info("Shutdown already in progress - skipping")
        return

    Log.info("Starting notification shutdown sequence")
    
    # Set shutdown flag FIRST to prevent any new operations
    _SHUTTING_DOWN = True
    Log.info("_SHUTTING_DOWN flag set to True")

    # Cancel Python threading timer - this is safe
    Log.info("Cancelling Python threading timer")
    _cancel_min_display_timer()
    Log.info("Python timer cancelled")

    # Clear Python references only - do NOT access AppKit objects
    # AppKit will handle its own cleanup when NSApplication terminates
    Log.info("Clearing Python references")
    _ACTIVE_NOTIFICATION = None
    _CURRENT_STATE = NotificationState.IDLE
    _STATE_START_TIME = 0.0
    _PENDING_NOTIFICATIONS.clear()

    Log.info("Notification shutdown complete - all references cleared")


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

