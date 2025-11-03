"""
Event data models for calendar event extraction.
Defines VisionEvent (from LLM).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class VisionEvent:
    """
    Raw event extracted from image by LLM.
    This is the unnormalized output from the vision model.
    """
    title: Optional[str] = None
    date: Optional[str] = None  # ISO format string or natural language
    time: Optional[str] = None  # Time string
    description: Optional[str] = None
    participants: Optional[str] = None  # Event participants
    location: Optional[str] = None
    
    def is_valid(self) -> bool:
        """Check if event has minimum required fields."""
        return self.title is not None and self.date is not None

