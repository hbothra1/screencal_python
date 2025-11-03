"""
Event normalizer for converting VisionEvent to NormalizedEvent.
Handles date/time parsing and normalization to UTC datetime objects.
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
        self.start_time = start_time  # UTC datetime
        self.end_time = end_time      # UTC datetime
        self.description = description
        self.participants = participants
        self.location = location
    
    def duration_minutes(self) -> int:
        """Get event duration in minutes."""
        delta = self.end_time - self.start_time
        return int(delta.total_seconds() / 60)


def normalize(event: VisionEvent) -> Optional[NormalizedEvent]:
    """
    Normalize a VisionEvent to NormalizedEvent with UTC datetime objects.
    
    Args:
        event: VisionEvent from LLM extraction
        
    Returns:
        NormalizedEvent with UTC datetime, or None if normalization fails
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
        
        Log.info(f"Normalized event: {normalized.title} at {normalized.start_time} UTC")
        Log.kv({
            "stage": "normalize",
            "result": "success",
            "start": normalized.start_time.isoformat(),
            "end": normalized.end_time.isoformat(),
            "duration_min": normalized.duration_minutes()
        })
        
        return normalized
        
    except Exception as e:
        Log.error(f"Normalization error: {e}")
        Log.kv({"stage": "normalize", "result": "failed", "error": str(e)})
        return None


def _parse_datetime(date_str: Optional[str], time_str: Optional[str]) -> Optional[datetime]:
    """
    Parse date and time strings into UTC datetime.
    
    Args:
        date_str: Date string (ISO format or natural language)
        time_str: Optional time string
        
    Returns:
        datetime in UTC, or None if parsing fails
    """
    if date_str is None:
        return None
    
    try:
        # Try parsing date string (ISO format like "2024-11-05")
        if time_str:
            # Combine date and time
            datetime_str = f"{date_str} {time_str}"
            dt = dateutil_parser.parse(datetime_str)
        else:
            # Date only - assume current time or default time
            dt = dateutil_parser.parse(date_str)
            # If no time provided, default to 12:00 UTC
            if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                dt = dt.replace(hour=12, minute=0)
        
        # Ensure datetime is timezone-aware (UTC)
        if dt.tzinfo is None:
            # Assume local time and convert to UTC
            # For now, treat as UTC
            dt = dt.replace(tzinfo=dateutil_tz.tzutc())
        else:
            # Convert to UTC
            dt = dt.astimezone(dateutil_tz.tzutc())
        
        return dt
        
    except Exception as e:
        Log.warn(f"Date parsing error: {e}")
        return None

