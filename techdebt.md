# Technical Debt

This document tracks known issues and improvements that need to be addressed in ScreenCal.

## 1. Fix Display Bug with Item Dense Menu Bar

**Status:** In Progress  
**Priority:** High  
**Location:** `src/statusbar_controller.py`

### Problem
When the macOS menu bar is crowded with many items, the ScreenCal menu bar item becomes hidden/invisible. This occurs particularly on smaller displays or when external monitors are disconnected.

### Current State
- Diagnostics are in place to detect when the status item is not visible (via `_check_status_item_visibility()`)
- Status item can be accessed via `self._nsapp.nsstatusitem` after `app.run()` starts
- Visibility check currently only runs on menu item click (which requires the item to be visible)

### Required Fix
- Implement automatic visibility check after `app.run()` starts using a `rumps.timer`
- When item is not visible (zero-size button frame), show notification to user
- Quit gracefully after notifying user about menu bar space issue
- Consider providing guidance on how to free up menu bar space

### Related Code
- `src/statusbar_controller.py`: `_check_status_item_creation_after_start()`, `_check_status_item_visibility()`
- Visibility check should be scheduled automatically, not triggered by user interaction

---

## 2. Screenshot Storage Management

**Status:** Not Started  
**Priority:** Medium  
**Location:** `src/frontmost_capture.py`

### Problem
Screenshots are currently saved to disk in `screenshot_dump_tobedeleted/` folder and persist indefinitely, accumulating storage over time.

### Current State
- Screenshots saved to `{project_root}/screenshot_dump_tobedeleted/{timestamp}.png` (line 88-98 in `frontmost_capture.py`)
- Screenshots are saved on every capture
- No cleanup mechanism exists
- Folder name suggests it's temporary but files are never deleted

### Required Fix
- Default behavior: Keep screenshots only in memory (don't save to disk)
- Add environment variable flag (e.g., `SAVE_SCREENSHOTS=1`) to enable persistent storage
- When storage is enabled, implement cleanup mechanism:
  - Delete screenshots after processing completes
  - Or delete screenshots older than X minutes/hours
  - Or delete screenshots on app shutdown
- Consider using temporary file system for short-term storage if needed

### Related Code
- `src/frontmost_capture.py`: Lines 84-109 handle screenshot saving
- Consider using `tempfile` module for temporary storage if file access is needed

---

## 3. Delete ICS File After Execution

**Status:** Not Started  
**Priority:** Medium  
**Location:** `src/calendar_connector.py`

### Problem
ICS files are generated in the Downloads folder and opened in Calendar app, but they are never deleted, cluttering the Downloads folder.

### Current State
- ICS files saved to `~/Downloads/ScreenCal_{title}_{timestamp}.ics` (line 407-408 in `calendar_connector.py`)
- Files are opened in Calendar app via `_open_calendar_async()` (line 465-507)
- No cleanup mechanism exists after Calendar app imports the event

### Required Fix
- Delete ICS file after Calendar app has successfully imported the event
- Implement deletion with appropriate delay to ensure Calendar has time to read the file
- Handle edge cases: Calendar app not installed, import fails, user cancels import
- Consider using temporary directory for ICS files instead of Downloads
- Add error handling for file deletion failures

### Related Code
- `src/calendar_connector.py`: `_generate_ics()` (lines 385-462) and `_open_calendar_async()` (lines 465-507)
- `src/statusbar_controller.py`: `_process_capture_async()` calls `create_calendar_event()` which returns ICS path

---

## 4. Move Away from ICS Method to Native Apple Calendar Integration

**Status:** Not Started  
**Priority:** Low  
**Location:** `src/calendar_connector.py`

### Problem
Current implementation uses ICS file generation and import dialog, which requires user interaction to approve each event. This is not a smooth user experience.

### Current State
- ICS files are generated and opened in Calendar app
- Calendar app shows import dialog requiring user to click "Import" for each event
- This interrupts the workflow and requires manual action

### Required Fix
- Implement native Apple Calendar integration using EventKit framework
- Use `EKEventStore` and `EKEvent` to programmatically create calendar events
- Request calendar access permissions (similar to screen recording permissions)
- Create events directly in user's default calendar without import dialog
- Maintain backward compatibility with ICS method (via flag) for users who prefer it
- Consider providing calendar selection option for users with multiple calendars

### Related Code
- `src/calendar_connector.py`: `create_calendar_event()`, `_generate_ics()`, `_open_calendar_async()`
- `src/permissions.py`: Add calendar permission handling similar to screen recording permissions
- Requires EventKit framework access via PyObjC/AppKit

### Implementation Notes
- EventKit integration requires:
  - `import EventKit` via PyObjC
  - `EKEventStore` for calendar access
  - `EKEvent` for event creation
  - Permission request using `requestAccess(to:completion:)`
  - Calendar selection (default or user-selected)
- Consider adding preference for calendar selection
- Maintain ICS fallback for edge cases or user preference

---

## Priority Summary

1. **High Priority:** Item #1 (Menu bar visibility) - Blocks core functionality
2. **Medium Priority:** Items #2 and #3 (Storage management) - Quality of life improvements
3. **Low Priority:** Item #4 (Native calendar integration) - UX enhancement

