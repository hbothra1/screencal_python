# Notification Changes Summary

## Overview
Comparison between the committed version (HEAD) and the current working version of `notifications.py`.

## Key Changes

### 1. **Visual Changes - Window Appearance**

**Committed Version:**
- Used `NSView` with a custom light silver background color (RGB: 220, 220, 220, alpha 0.75)
- Window size: 380x90 pixels
- Text color: Black (`NSColor.blackColor()`)

**Current Version:**
- Uses `NSVisualEffectView` with `NSVisualEffectMaterialSheet` material
- Window size: 320x80 pixels (smaller)
- Text color: `NSColor.labelColor()` (adapts to light/dark mode)
- More transparent appearance (alpha 0.92)

**Note:** The `NSVisualEffectView` with `NSVisualEffectMaterialSheet` might be what you're seeing as an "icon" - it creates a frosted glass effect that can look like a subtle icon or badge.

### 2. **Multiple Windows Issue**

The code logic for updating vs creating new windows appears unchanged in `_present_or_update_notification_on_main()`. However, there are subtle differences that could cause multiple windows:

**The Check:**
```python
if notification_window is None or not getattr(notification_window, "_notification_active", False):
    _show_overlay_window(_NOTIFICATION_TITLE, message, fade_timeout)  # Creates NEW window
    return
```

**Potential Issue:**
- In `_close_notification_window()`, the code now sets `_notification_active = False` IMMEDIATELY (line 244) before closing
- This means if a window is being closed and a new notification comes in, the check will fail and create a NEW window instead of waiting/updating
- The window reference might still exist (`_ACTIVE_NOTIFICATION` is not None) but `_notification_active` is False, triggering window creation

### 3. **Window Closing Behavior**

**Committed Version:**
- More defensive error handling with multiple try-except blocks
- Sets `notification_window.ns_window = None` after closing
- More careful cleanup of autorelease pools

**Current Version:**
- Simplified closing: `ns_window.orderOut_(None)` followed by `ns_window.close()`
- Less defensive error handling

### 4. **Threading Simplification**

**Committed Version:**
- Used Python `threading.current_thread()` check first (safer)
- Then fell back to AppKit `NSThread.isMainThread()` check
- Multiple layers of error handling

**Current Version:**
- Uses `NSThread.isMainThread()` directly
- Simpler error handling
- Less defensive threading checks

### 5. **New Features Added**

**Calendar Choice Dialog:**
- New function `show_calendar_choice_dialog()` (lines 1040-1316)
- Creates interactive dialog with buttons for Google Calendar vs macOS Calendar
- Uses `NSVisualEffectView` similar to notifications
- This dialog might be contributing to the "multiple windows" perception

### 6. **Text Layout Changes**

**Committed Version:**
- Stored window dimensions in `notification_window` object:
  - `_window_width`, `_window_height`
  - `_max_text_width`, `_max_text_height`
- Used 16px padding

**Current Version:**
- Removed storage of window dimensions in notification_window object
- Uses 12px padding (reduced from 16px)
- Might cause layout issues if dimensions aren't properly tracked

## Root Cause Analysis

### Why Multiple Windows Appear:

1. **Race Condition:** When a notification window is being closed (`_notification_active = False` is set immediately), if a new notification arrives during the fade-out animation, it will see `_notification_active = False` and create a NEW window instead of reusing the closing one.

2. **Missing Window Dimensions:** The removal of `_window_width`, `_window_height`, `_max_text_width`, `_max_text_height` from the `notification_window` object might cause layout issues, but more importantly, the window might not be properly tracked.

3. **Visual Effect View:** The `NSVisualEffectView` material (`NSVisualEffectMaterialSheet`) creates a frosted glass effect that might appear as an "icon" or badge-like appearance, especially on dark backgrounds.

## Recommendations

1. **Fix Multiple Windows:** 
   - Don't set `_notification_active = False` immediately before closing
   - Instead, only set it after the window is fully closed
   - Or, check if a window is currently fading out before creating a new one

2. **Restore Window Dimensions Tracking:**
   - Add back the `_window_width`, `_window_height`, `_max_text_width`, `_max_text_height` properties to ensure proper layout

3. **Fix Update Logic:**
   - Ensure that `_present_or_update_notification_on_main` properly reuses existing windows instead of creating new ones

