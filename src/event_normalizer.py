"""
Event normalizer for converting VisionEvent to NormalizedEvent.
Handles date/time parsing and normalization to system timezone datetime objects.
"""

from datetime import datetime, timedelta
from typing import Optional
from dateutil import parser as dateutil_parser
from dateutil import tz as dateutil_tz

from src.event_models import VisionEvent
from src.logging_helper import Log


class NormalizedEvent:
    """
    Normalized calendar event with proper datetime objects.
    Ready for ICS generation.
    """
    
    def __init__(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        description: Optional[str] = None,
        participants: Optional[str] = None,
        location: Optional[str] = None
    ):
        self.title = title
        self.start_time = start_time  # System timezone datetime
        self.end_time = end_time      # System timezone datetime
        self.description = description
        self.participants = participants
        self.location = location
    
    def duration_minutes(self) -> int:
        """Get event duration in minutes."""
        delta = self.end_time - self.start_time
        return int(delta.total_seconds() / 60)


def normalize(event: VisionEvent) -> Optional[NormalizedEvent]:
    """
    Normalize a VisionEvent to NormalizedEvent with system timezone datetime objects.
    
    Args:
        event: VisionEvent from LLM extraction
        
    Returns:
        NormalizedEvent with system timezone datetime, or None if normalization fails
    """
    Log.section("Event Normalizer")
    Log.info(f"Normalizing event: {event.title}")
    
    if not event.is_valid():
        Log.warn("Event missing required fields - cannot normalize")
        Log.kv({"stage": "normalize", "result": "failed", "reason": "missing_fields"})
        return None
    
    try:
        # Parse date - handle ISO format and natural language
        start_datetime = _parse_datetime(event.date, event.time)
        
        if start_datetime is None:
            Log.warn("Failed to parse date/time")
            Log.kv({"stage": "normalize", "result": "failed", "reason": "parse_error"})
            return None
        
        # Get timezone info for logging
        if start_datetime.tzinfo:
            tz_offset = start_datetime.strftime("%z")  # e.g., "-0800"
            tz_name = start_datetime.strftime("%Z")      # e.g., "PST"
            offset_hours = int(tz_offset[1:3])
            offset_mins = int(tz_offset[3:5])
            if offset_mins == 0:
                tz_display = f"{tz_name} (UTC{tz_offset[0]}{offset_hours})"
            else:
                tz_display = f"{tz_name} (UTC{tz_offset[0]}{offset_hours}:{offset_mins:02d})"
        else:
            tz_display = "None"
        Log.info(f"Using timezone: {tz_display}")
        
        # Default duration: +60 minutes if not specified
        end_datetime = start_datetime + timedelta(minutes=60)
        
        normalized = NormalizedEvent(
            title=event.title,
            start_time=start_datetime,
            end_time=end_datetime,
            description=event.description,
            participants=event.participants,
            location=event.location
        )
        
        Log.info(f"Normalized event: {normalized.title} at {normalized.start_time} ({tz_display})")
        Log.kv({
            "stage": "normalize",
            "result": "success",
            "start": normalized.start_time.isoformat(),
            "end": normalized.end_time.isoformat(),
            "timezone": tz_display,
            "duration_min": normalized.duration_minutes()
        })
        
        return normalized
        
    except Exception as e:
        Log.error(f"Normalization error: {e}")
        Log.kv({"stage": "normalize", "result": "failed", "error": str(e)})
        return None


def _parse_datetime(date_str: Optional[str], time_str: Optional[str]) -> Optional[datetime]:
    """
    Parse date and time strings into system timezone datetime.
    
    Args:
        date_str: Date string (ISO format or natural language)
        time_str: Optional time string
        
    Returns:
        datetime in system timezone, or None if parsing fails
    """
    if date_str is None:
        return None
    
    try:
        # Get system timezone
        system_tz = dateutil_tz.tzlocal()
        
        # Use current date in system timezone as default for parsing dates without year
        # This ensures dates default to current year instead of an old default
        # Use only date components (no time), so parsed times don't inherit current seconds/microseconds
        now = datetime.now(system_tz)
        default_dt = datetime(now.year, now.month, now.day, 0, 0, 0, 0, system_tz)
        
        # Get readable timezone info
        tz_offset = now.strftime("%z")  # e.g., "-0800"
        tz_name = now.strftime("%Z")      # e.g., "PST"
        if tz_offset:
            # Format offset as UTC-8:00 or UTC+5:30
            offset_hours = int(tz_offset[1:3])
            offset_mins = int(tz_offset[3:5])
            if offset_mins == 0:
                tz_display = f"{tz_name} (UTC{tz_offset[0]}{offset_hours})"
            else:
                tz_display = f"{tz_name} (UTC{tz_offset[0]}{offset_hours}:{offset_mins:02d})"
        else:
            tz_display = str(system_tz)
        
        Log.info(f"Parsing date: '{date_str}', time: '{time_str}'")
        Log.info(f"System timezone: {tz_display}")
        
        # Try parsing date string (ISO format like "2024-11-05")
        if time_str:
            # Combine date and time
            datetime_str = f"{date_str} {time_str}"
            dt = dateutil_parser.parse(datetime_str, default=default_dt)
        else:
            # Date only - assume current time or default time
            dt = dateutil_parser.parse(date_str, default=default_dt)
            # If no time provided, default to 12:00 in system timezone
            if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                dt = dt.replace(hour=12, minute=0)
        
        # Ensure datetime is timezone-aware (use system timezone)
        if dt.tzinfo is None:
            # Assume local time - apply system timezone
            dt = dt.replace(tzinfo=system_tz)
        else:
            # If datetime already has timezone, keep it (don't convert)
            # This preserves the timezone from the parsed string if it was specified
            pass
        
        # Strip microseconds to avoid precision issues and cleaner logs
        if dt.microsecond != 0:
            dt = dt.replace(microsecond=0)
        
        # Get readable timezone info for logging
        if dt.tzinfo:
            tz_offset = dt.strftime("%z")  # e.g., "-0800"
            tz_name = dt.strftime("%Z")      # e.g., "PST"
            offset_hours = int(tz_offset[1:3])
            offset_mins = int(tz_offset[3:5])
            if offset_mins == 0:
                tz_display = f"{tz_name} (UTC{tz_offset[0]}{offset_hours})"
            else:
                tz_display = f"{tz_name} (UTC{tz_offset[0]}{offset_hours}:{offset_mins:02d})"
        else:
            tz_display = "None"
        
        Log.info(f"Parsed datetime: {dt} ({tz_display})")
        return dt
        
    except Exception as e:
        Log.warn(f"Date parsing error: {e}")
        return None

