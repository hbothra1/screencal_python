"""
ICS Generator for creating iCalendar (.ics) files.
Generates RFC5545-compliant ICS files and opens them in Calendar to show import dialog for user approval.
"""

import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from dateutil import tz as dateutil_tz

from src.logging_helper import Log
from src.notifications import notification_on_calendar_opening

# Try to import EventKit
try:
    from EventKit import EKEventStore, EKEvent, EKCalendar, EKEventEditViewController, EKEventEditViewAction
    from EventKitUI import EKEventEditViewController
    from Foundation import NSDate
    from AppKit import NSWindow, NSApplication, NSWindowStyleMaskBorderless, NSWindowStyleMaskResizable
    EVENTKIT_AVAILABLE = True
except ImportError:
    EVENTKIT_AVAILABLE = False


CALENDAR_OPEN_DELAY_SECONDS = 2.0


def _escape_ical_text(text: str) -> str:
    """
    Escape text for iCalendar format (RFC5545).
    Escapes commas, semicolons, backslashes, and newlines.
    
    Args:
        text: Text to escape
        
    Returns:
        Escaped text safe for iCalendar
    """
    if text is None:
        return ""
    
    # Replace backslashes first (before other replacements)
    text = text.replace('\\', '\\\\')
    # Escape semicolons
    text = text.replace(';', '\\;')
    # Escape commas
    text = text.replace(',', '\\,')
    # Escape newlines
    text = text.replace('\n', '\\n')
    text = text.replace('\r', '')
    
    # Fold long lines (75 chars per line, continuation starts with space)
    # RFC5545 requires lines to be max 75 bytes
    lines = []
    current_line = ""
    
    for char in text:
        # Check if adding this char would exceed 75 bytes
        test_line = current_line + char
        if len(test_line.encode('utf-8')) <= 75:
            current_line = test_line
        else:
            # Fold the line
            if current_line:
                lines.append(current_line)
                current_line = " " + char  # Continuation starts with space
            else:
                # Single char that's too long (shouldn't happen with UTF-8)
                current_line = char
    
    if current_line:
        lines.append(current_line)
    
    return '\r\n'.join(lines)


def _format_ical_datetime(dt: datetime) -> str:
    """
    Format datetime to iCalendar format (UTC).
    
    Args:
        dt: UTC datetime object
        
    Returns:
        Formatted datetime string (YYYYMMDDTHHMMSSZ)
    """
    return dt.strftime('%Y%m%dT%H%M%SZ')


def _show_eventkit_dialog(normalized_event) -> bool:
    """
    Show EventKit event creation dialog with pre-populated event data.
    User can edit/add the event directly.
    
    Args:
        normalized_event: NormalizedEvent object
        
    Returns:
        True if dialog was shown, False otherwise
    """
    if not EVENTKIT_AVAILABLE:
        Log.warn("EventKit not available - skipping dialog")
        return False
    
    try:
        Log.info("Opening EventKit event creation dialog")
        
        # Convert UTC datetime to local time first (needed for both EventKit and AppleScript)
        start_local = normalized_event.start_time.astimezone()
        end_local = normalized_event.end_time.astimezone()
        
        # Try EventKit approach first (if available)
        if EVENTKIT_AVAILABLE:
            try:
                # Create event store
                event_store = EKEventStore.alloc().init()
                
                # Request calendar access (async, but we'll handle it synchronously)
                # Note: This requires user permission on first use
                from Foundation import dispatch_semaphore_create, dispatch_semaphore_wait, dispatch_semaphore_signal, DISPATCH_TIME_FOREVER
                import time
                
                access_granted = False
                access_error = None
                
                def access_callback(granted, error):
                    nonlocal access_granted, access_error
                    access_granted = granted
                    if error:
                        access_error = error
                
                # Request access - this is async, so we'll wait a bit
                event_store.requestAccessToEntityType_completion_(
                    0,  # EKEntityTypeEvent
                    access_callback
                )
                
                # Wait for callback (with timeout)
                time.sleep(0.5)  # Give it a moment to get permission
                
                if not access_granted:
                    Log.warn("Calendar access not granted, falling back to AppleScript")
                else:
                    # Get default calendar
                    calendars = event_store.calendarsForEntityType_(0)  # EKEntityTypeEvent
                    if calendars and len(calendars) > 0:
                        default_calendar = calendars[0]
                        
                        # Create event
                        event = EKEvent.eventWithEventStore_(event_store)
                        event.setCalendar_(default_calendar)
                        event.setTitle_(normalized_event.title)
                        
                        start_date = NSDate.dateWithTimeIntervalSince1970_(start_local.timestamp())
                        end_date = NSDate.dateWithTimeIntervalSince1970_(end_local.timestamp())
                        
                        event.setStartDate_(start_date)
                        event.setEndDate_(end_date)
                        
                        if normalized_event.description:
                            desc_text = normalized_event.description
                            if normalized_event.participants:
                                desc_text = f"{desc_text}\n\nParticipants: {normalized_event.participants}"
                            event.setNotes_(desc_text)
                        
                        if normalized_event.location:
                            event.setLocation_(normalized_event.location)
                        
                        # For menu bar app without a window, we'll use AppleScript to show Calendar
                        # EventKit's EKEventEditViewController requires a window which we don't have
                        Log.info("Event created via EventKit, using AppleScript to show in Calendar")
                        
            except Exception as e:
                Log.info(f"EventKit direct approach failed: {e}, using AppleScript")
        
        # Use AppleScript to create event in Calendar app
        # This will open Calendar and create a new event that the user can edit/approve
        def escape_applescript(text):
            """Escape text for AppleScript strings."""
            if not text:
                return ""
            return (text
                   .replace('\\', '\\\\')
                   .replace('"', '\\"')
                   .replace('\n', '\\n')
                   .replace('\r', ''))
        
        # Format date/time for AppleScript (Calendar expects specific format)
        # AppleScript date format: "Sunday, November 3, 2024 at 2:00:00 PM"
        start_date_str = start_local.strftime('%A, %B %d, %Y at %I:%M:%S %p')
        end_date_str = end_local.strftime('%A, %B %d, %Y at %I:%M:%S %p')
        
        # Also create a simpler date string for navigation
        nav_date_str = start_local.strftime('%B %d, %Y')
        
        # Build description with participants if available
        description_text = ""
        if normalized_event.description:
            description_text = normalized_event.description
        if normalized_event.participants:
            if description_text:
                description_text = f"{description_text}\\n\\nParticipants: {normalized_event.participants}"
            else:
                description_text = f"Participants: {normalized_event.participants}"
        
        # Build AppleScript to create event in Calendar
        # Calendar will show the event creation dialog with pre-populated fields
        applescript_lines = [
            'tell application "Calendar"',
            '    activate',
            '    tell calendar 1',
            f'        set newEvent to make new event at end with properties {{summary:"{escape_applescript(normalized_event.title)}", start date:(date "{start_date_str}"), end date:(date "{end_date_str}")}}'
        ]
        
        if description_text:
            applescript_lines.append(f'        set description of newEvent to "{escape_applescript(description_text)}"')
        
        if normalized_event.location:
            applescript_lines.append(f'        set location of newEvent to "{escape_applescript(normalized_event.location)}"')
        
        applescript_lines.extend([
            '    end tell',
            '    -- Navigate to the event date so user can see/edit the created event',
            f'    view calendar at date (date "{nav_date_str}")',
            'end tell'
        ])
        
        applescript = '\n'.join(applescript_lines)
        
        try:
            # Use osascript to run AppleScript
            process = subprocess.Popen(
                ['osascript', '-e', applescript],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate()
            
            if process.returncode == 0:
                Log.info("EventKit dialog shown via Calendar app")
                Log.kv({"stage": "ics", "action": "eventkit_dialog_shown"})
                return True
            else:
                Log.warn(f"Failed to open Calendar event: {stderr.decode()}")
                return False
        except Exception as e:
            Log.warn(f"Failed to execute AppleScript: {e}")
            return False
        
    except Exception as e:
        Log.error(f"EventKit dialog failed: {e}")
        Log.kv({"stage": "ics", "action": "eventkit_failed", "error": str(e)})
        return False


def generate_ics(normalized_event) -> Optional[Path]:
    """
    Generate an ICS file from NormalizedEvent and save it to Downloads.
    Opens the ICS file in Calendar to show import dialog with pre-populated data.
    
    Args:
        normalized_event: NormalizedEvent object
        
    Returns:
        Path to generated ICS file, or None if generation fails
    """
    Log.section("ICS Generator")
    Log.info(f"Generating ICS file for: {normalized_event.title}")
    
    # Generate ICS file
    try:
        # Get Downloads directory
        downloads_dir = Path.home() / "Downloads"
        downloads_dir.mkdir(exist_ok=True)
        
        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[^\w\s-]', '', normalized_event.title)[:50]
        safe_title = re.sub(r'[-\s]+', '_', safe_title)
        ics_filename = f"ScreenCal_{safe_title}_{timestamp}.ics"
        ics_path = downloads_dir / ics_filename
        
        # Generate unique ID for event (using timestamp + title hash)
        import hashlib
        uid_string = f"{timestamp}_{normalized_event.title}"
        uid = hashlib.md5(uid_string.encode()).hexdigest() + "@screencal.local"
        
        # Build ICS content
        ics_lines = []
        ics_lines.append("BEGIN:VCALENDAR")
        ics_lines.append("VERSION:2.0")
        ics_lines.append("PRODID:-//ScreenCal//ScreenCal4//EN")
        ics_lines.append("CALSCALE:GREGORIAN")
        ics_lines.append("METHOD:PUBLISH")
        ics_lines.append("BEGIN:VEVENT")
        ics_lines.append(f"UID:{uid}")
        ics_lines.append(f"DTSTART:{_format_ical_datetime(normalized_event.start_time)}")
        ics_lines.append(f"DTEND:{_format_ical_datetime(normalized_event.end_time)}")
        ics_lines.append(f"SUMMARY:{_escape_ical_text(normalized_event.title)}")
        
        if normalized_event.description:
            # Combine description with participants if available
            desc_text = normalized_event.description
            if normalized_event.participants:
                desc_text = f"{desc_text}\n\nParticipants: {normalized_event.participants}"
            ics_lines.append(f"DESCRIPTION:{_escape_ical_text(desc_text)}")
        
        if normalized_event.location:
            ics_lines.append(f"LOCATION:{_escape_ical_text(normalized_event.location)}")
        
        # Add timestamp for when event was created (current time in UTC)
        created_time = datetime.now(dateutil_tz.tzutc())
        ics_lines.append(f"DTSTAMP:{_format_ical_datetime(created_time)}")
        
        ics_lines.append("END:VEVENT")
        ics_lines.append("END:VCALENDAR")
        
        # Write ICS file
        ics_content = '\r\n'.join(ics_lines) + '\r\n'
        ics_path.write_text(ics_content, encoding='utf-8')
        
        Log.info(f"ICS file generated: {ics_path}")
        Log.kv({
            "stage": "ics",
            "result": "success",
            "ics_path": str(ics_path),
            "event_title": normalized_event.title
        })
        
        # Open ICS file in Calendar to show import dialog
        # This will show a dialog where user can approve/edit before adding
        try:
            try:
                notification_on_calendar_opening()
            except Exception as notify_error:
                Log.warn(f"Failed to update notification before opening Calendar: {notify_error}")

            if CALENDAR_OPEN_DELAY_SECONDS > 0:
                Log.info(
                    f"Waiting {CALENDAR_OPEN_DELAY_SECONDS:.1f}s before opening Calendar"
                )
                time.sleep(CALENDAR_OPEN_DELAY_SECONDS)

            subprocess.run(['open', '-a', 'Calendar', str(ics_path)], check=True)
            Log.info(f"Opened ICS file in Calendar: {ics_path}")
            Log.kv({"stage": "ics", "action": "ics_opened_in_calendar"})
        except subprocess.CalledProcessError as e:
            Log.warn(f"Failed to open ICS file in Calendar: {e}")
        except Exception as e:
            Log.warn(f"Error opening ICS file in Calendar: {e}")
        
        return ics_path
        
    except Exception as e:
        Log.error(f"ICS generation failed: {e}")
        Log.kv({"stage": "ics", "result": "failed", "error": str(e)})
        return None

