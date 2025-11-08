"""
Calendar Connector for creating calendar events in multiple calendar systems.
Supports Apple Calendar (via ICS files) and Google Calendar (via browser URLs).
"""

import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from dateutil import tz as dateutil_tz

try:
    import tzlocal  # type: ignore

    TZLOCAL_AVAILABLE = True
except ImportError:
    TZLOCAL_AVAILABLE = False
    tzlocal = None  # type: ignore

from src.logging_helper import Log
from src.notifications import notification_on_calendar_opening

# Try to import EventKit
try:
    from EventKit import EKEventStore, EKEvent, EKCalendar, EKEventEditViewController, EKEventEditViewAction  # type: ignore
    from EventKitUI import EKEventEditViewController  # type: ignore
    from Foundation import NSDate  # type: ignore
    from AppKit import NSWindow, NSApplication, NSWindowStyleMaskBorderless, NSWindowStyleMaskResizable  # type: ignore
    EVENTKIT_AVAILABLE = True
except ImportError:
    EVENTKIT_AVAILABLE = False


CALENDAR_OPEN_DELAY_SECONDS = 2.0


def _tzinfo_to_iana(tzinfo) -> Optional[str]:
    """
    Attempt to extract an IANA timezone identifier from a tzinfo object.
    """
    if tzinfo is None:
        return None

    # Common attributes exposed by zoneinfo.DateTimeTZInfo or pytz timezones
    for attr in ("key", "zone", "name"):
        value = getattr(tzinfo, attr, None)
        if isinstance(value, str) and value:
            # IANA identifiers typically contain '/' but "UTC" is also valid
            if "/" in value or value.upper() == "UTC":
                return value

    # Some tzinfo implementations expose tzname()
    try:
        value = tzinfo.tzname(None)
        if isinstance(value, str) and value and ("/" in value or value.upper() == "UTC"):
            return value
    except Exception:
        pass

    return None


def _resolve_iana_timezone(normalized_event) -> Optional[str]:
    """
    Resolve an IANA timezone identifier for use with Google Calendar URLs.

    Prefers timezone information from the normalized event. Falls back to the
    system timezone via tzlocal if available.
    """
    # Try to extract from start and end tzinfo
    for dt in (normalized_event.start_time, normalized_event.end_time):
        tzinfo = getattr(dt, "tzinfo", None)
        iana = _tzinfo_to_iana(tzinfo)
        if iana:
            return iana

    # Fall back to tzlocal if available
    if TZLOCAL_AVAILABLE and tzlocal is not None:
        try:
            if hasattr(tzlocal, "get_localzone_name"):
                iana = tzlocal.get_localzone_name()  # type: ignore[attr-defined]
                if isinstance(iana, str) and iana:
                    return iana
            local_zone = tzlocal.get_localzone()  # type: ignore[attr-defined]
            iana = _tzinfo_to_iana(local_zone)
            if iana:
                return iana
            # As a last resort, use the string representation
            local_str = str(local_zone)
            if local_str and ("/" in local_str or local_str.upper() == "UTC"):
                return local_str
        except Exception as tz_err:
            Log.warn(f"Failed to determine system IANA timezone: {tz_err}")

    return None


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
    Converts from system timezone to UTC if needed.
    
    Args:
        dt: datetime object (in system timezone or UTC)
        
    Returns:
        Formatted datetime string (YYYYMMDDTHHMMSSZ)
    """
    # Ensure datetime is timezone-aware
    if dt.tzinfo is None:
        # If no timezone, assume it's local time (system timezone)
        system_tz = dateutil_tz.tzlocal()
        dt = dt.replace(tzinfo=system_tz)
        Log.warn(f"Datetime missing timezone info, assuming system timezone: {system_tz}")
    
    # Convert to UTC
    dt_utc = dt.astimezone(dateutil_tz.tzutc())
    return dt_utc.strftime('%Y%m%dT%H%M%SZ')


def _format_google_calendar_datetime(dt: datetime) -> str:
    """
    Format datetime to Google Calendar URL format (ISO 8601 UTC).
    Converts from system timezone to UTC if needed.
    
    Args:
        dt: datetime object (in system timezone or UTC)
        
    Returns:
        Formatted datetime string (YYYYMMDDTHHMMSSZ)
    """
    # Ensure datetime is timezone-aware
    if dt.tzinfo is None:
        # If no timezone, assume it's local time (system timezone)
        system_tz = dateutil_tz.tzlocal()
        dt = dt.replace(tzinfo=system_tz)
        Log.warn(f"Datetime missing timezone info, assuming system timezone: {system_tz}")
    
    # Convert to UTC
    dt_utc = dt.astimezone(dateutil_tz.tzutc())
    Log.info(f"Converting datetime to UTC: {dt} -> {dt_utc}")
    return dt_utc.strftime('%Y%m%dT%H%M%SZ')


def _generate_google_calendar_url(normalized_event) -> str:
    """
    Generate a Google Calendar URL with pre-filled event details.
    
    Args:
        normalized_event: NormalizedEvent object
        
    Returns:
        Google Calendar URL string
    """
    # Format dates in ISO 8601 UTC format
    Log.info(f"Formatting start_time for Google Calendar: {normalized_event.start_time} ({normalized_event.start_time.tzinfo})")
    start_str = _format_google_calendar_datetime(normalized_event.start_time)
    Log.info(f"Formatting end_time for Google Calendar: {normalized_event.end_time} ({normalized_event.end_time.tzinfo})")
    end_str = _format_google_calendar_datetime(normalized_event.end_time)
    
    Log.info(f"Google Calendar URL datetime strings - Start: {start_str}, End: {end_str}")
    
    # URL encode all text fields
    title_encoded = quote(normalized_event.title, safe='')
    
    # Build description with participants if available
    description_text = ""
    if normalized_event.description:
        description_text = normalized_event.description
    if normalized_event.participants:
        if description_text:
            description_text = f"{description_text}\n\nParticipants: {normalized_event.participants}"
        else:
            description_text = f"Participants: {normalized_event.participants}"
    
    description_encoded = quote(description_text, safe='') if description_text else ""
    location_encoded = quote(normalized_event.location, safe='') if normalized_event.location else ""
    
    # Attempt to include the timezone identifier so Google Calendar defaults correctly
    iana_timezone = _resolve_iana_timezone(normalized_event)
    if iana_timezone:
        Log.info(f"Using IANA timezone for Google Calendar URL: {iana_timezone}")
    else:
        Log.warn("Unable to determine IANA timezone for Google Calendar URL; defaulting to Google account settings")

    # Build Google Calendar URL
    # Format: https://calendar.google.com/calendar/r/eventedit?action=TEMPLATE&dates=START%2FEND&text=TITLE&details=DESC&location=LOC
    url = f"https://calendar.google.com/calendar/r/eventedit?action=TEMPLATE&dates={start_str}%2F{end_str}&text={title_encoded}"
    
    if description_encoded:
        url += f"&details={description_encoded}"
    
    if location_encoded:
        url += f"&location={location_encoded}"
    
    if iana_timezone:
        url += f"&ctz={quote(iana_timezone, safe='')}"

    Log.info(f"Generated Google Calendar URL: {url[:200]}...")
    return url


def _open_google_calendar_async(url: str):
    """
    Open Google Calendar URL in browser asynchronously.
    
    Args:
        url: Google Calendar URL string
    """
    import src.notifications as _notif_mod
    
    if _notif_mod._SHUTTING_DOWN:
        Log.info("[CRASH-TEST] Shutting down - aborting Google Calendar opener thread.")
        return
    
    try:
        # NOTE: We do NOT call notification_reset() from background thread
        # as it accesses AppKit objects which can cause crashes.
        # The notification will fade naturally or stay visible until Calendar opens.

        try:
            _notif_mod.notification_on_calendar_opening()
        except Exception as notify_err:
            Log.warn(f"Failed to update notification for calendar opening: {notify_err}")
        
        if CALENDAR_OPEN_DELAY_SECONDS > 0:
            Log.info(
                f"Waiting {CALENDAR_OPEN_DELAY_SECONDS:.1f}s before opening Google Calendar"
            )
            time.sleep(CALENDAR_OPEN_DELAY_SECONDS)

        if _notif_mod._SHUTTING_DOWN:
            Log.info("[CRASH-TEST] Shutting down before Google Calendar open - aborting")
            return

        subprocess.run(['open', url], check=True)
        Log.info(f"Opened Google Calendar URL in browser: {url[:100]}...")
        Log.kv({"stage": "calendar", "action": "google_calendar_url_opened", "url": url})
        
        # Brief wait to ensure everything settles
        time.sleep(0.2)
    except subprocess.CalledProcessError as e:
        Log.warn(f"Failed to open Google Calendar URL: {e}")
    except Exception as e:
        Log.warn(f"Error opening Google Calendar URL: {e}")


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
        
        # Convert datetime to local timezone for EventKit/AppleScript (already in system timezone, but ensure it's local)
        # astimezone() without argument converts to system local timezone
        start_local = normalized_event.start_time.astimezone()
        end_local = normalized_event.end_time.astimezone()
        
        # Try EventKit approach first (if available)
        if EVENTKIT_AVAILABLE:
            try:
                # Create event store
                event_store = EKEventStore.alloc().init()
                
                # Request calendar access (async, but we'll handle it synchronously)
                # Note: This requires user permission on first use
                from Foundation import dispatch_semaphore_create, dispatch_semaphore_wait, dispatch_semaphore_signal, DISPATCH_TIME_FOREVER  # type: ignore
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
                Log.kv({"stage": "calendar", "action": "eventkit_dialog_shown"})
                return True
            else:
                Log.warn(f"Failed to open Calendar event: {stderr.decode()}")
                return False
        except Exception as e:
            Log.warn(f"Failed to execute AppleScript: {e}")
            return False
        
    except Exception as e:
        Log.error(f"EventKit dialog failed: {e}")
        Log.kv({"stage": "calendar", "action": "eventkit_failed", "error": str(e)})
        return False


def _generate_ics(normalized_event) -> Optional[Path]:
    """
    Generate an ICS file from NormalizedEvent and save it to Downloads.
    
    Args:
        normalized_event: NormalizedEvent object
        
    Returns:
        Path to generated ICS file, or None if generation fails
    """
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
            "stage": "calendar",
            "result": "success",
            "ics_path": str(ics_path),
            "event_title": normalized_event.title
        })
        
        return ics_path
        
    except Exception as e:
        Log.error(f"ICS generation failed: {e}")
        Log.kv({"stage": "calendar", "result": "failed", "error": str(e)})
        return None


def _open_calendar_async(ics_path: Path):
    """
    Open ICS file in Calendar app asynchronously.
    
    Args:
        ics_path: Path to ICS file
    """
    import src.notifications as _notif_mod
    
    if _notif_mod._SHUTTING_DOWN:
        Log.info("[CRASH-TEST] Shutting down - aborting Calendar opener thread.")
        return
    
    try:
        # NOTE: We do NOT call notification_reset() from background thread
        # as it accesses AppKit objects which can cause crashes.
        # The notification will fade naturally or stay visible until Calendar opens.

        try:
            _notif_mod.notification_on_calendar_opening()
        except Exception as notify_err:
            Log.warn(f"Failed to update notification for calendar opening: {notify_err}")
        
        if CALENDAR_OPEN_DELAY_SECONDS > 0:
            Log.info(
                f"Waiting {CALENDAR_OPEN_DELAY_SECONDS:.1f}s before opening Calendar"
            )
            time.sleep(CALENDAR_OPEN_DELAY_SECONDS)

        if _notif_mod._SHUTTING_DOWN:
            Log.info("[CRASH-TEST] Shutting down before Calendar open - aborting")
            return

        subprocess.run(['open', '-a', 'Calendar', str(ics_path)], check=True)
        Log.info(f"Opened ICS file in Calendar: {ics_path}")
        Log.kv({"stage": "calendar", "action": "ics_opened_in_calendar"})
        
        # Brief wait to ensure everything settles
        time.sleep(0.2)
    except subprocess.CalledProcessError as e:
        Log.warn(f"Failed to open ICS file in Calendar: {e}")
    except Exception as e:
        Log.warn(f"Error opening ICS file in Calendar: {e}")


def create_calendar_event(
    normalized_event,
    calendar_preference: Optional[str] = None,
) -> Optional[Path]:
    """
    Create a calendar event in the user's preferred calendar system.
    Checks USE_GOOGLE_CALENDAR environment variable to determine which calendar to use.
    
    - If USE_GOOGLE_CALENDAR is set: generates Google Calendar URL and opens in browser
    - Otherwise: generates ICS file and opens in macOS Calendar app
    
    Args:
        normalized_event: NormalizedEvent object
        
    Returns:
        Path to generated ICS file (if Apple Calendar), or None (if Google Calendar or on failure)
    """
    Log.section("Calendar Connector")
    
    # Check if Google Calendar mode is enabled via preference or environment variable
    if calendar_preference is None:
        use_google_calendar = os.environ.get('USE_GOOGLE_CALENDAR', '').lower() in ('1', 'true', 'yes')
    else:
        use_google_calendar = calendar_preference == "google"
    
    if use_google_calendar:
        Log.info(f"Creating Google Calendar event for: {normalized_event.title}")
        
        # Generate Google Calendar URL
        url = _generate_google_calendar_url(normalized_event)
        
        # Open URL in browser asynchronously (similar to Apple Calendar flow)
        # This will update notification and then open the URL with proper fade timeout
        calendar_thread = threading.Thread(
            target=_open_google_calendar_async,
            args=(url,),
            daemon=True,
            name="GoogleCalendarOpener"
        )
        calendar_thread.start()
        
        Log.kv({
            "stage": "calendar",
            "result": "success",
            "calendar_type": "google",
            "event_title": normalized_event.title
        })
        return None  # No file path for Google Calendar URLs
    else:
        Log.info(f"Creating Apple Calendar event for: {normalized_event.title}")
        
        # Generate ICS file
        ics_path = _generate_ics(normalized_event)
        
        if ics_path is None:
            Log.error("Failed to generate ICS file")
            return None
        
        # Open ICS file in Calendar to show import dialog
        # This will show a dialog where user can approve/edit before adding
        # Run in separate thread to avoid blocking main thread
        calendar_thread = threading.Thread(
            target=_open_calendar_async,
            args=(ics_path,),
            daemon=True,
            name="CalendarOpener"
        )
        calendar_thread.start()
        
        return ics_path

