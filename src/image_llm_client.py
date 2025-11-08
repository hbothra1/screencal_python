"""
Image LLM Client interface for extracting events from images.
Supports StubImageLLMClient (offline) and OpenAIImageLLMClient (real provider).
"""

import base64
import io
import json
import os
from abc import ABC, abstractmethod
from typing import Optional
from PIL import Image
import requests
from dateutil import tz as dateutil_tz

from src.event_models import VisionEvent
from src.logging_helper import Log

# Maximum image size in bytes (20MB - OpenAI's limit)
MAX_IMAGE_SIZE = 20 * 1024 * 1024
# Maximum image dimensions (prevent extremely large images)
MAX_IMAGE_DIMENSION = 10000


class ImageLLMClient(ABC):
    """Abstract base class for image LLM clients."""
    
    @abstractmethod
    def extract_event(self, image: Image.Image, context: dict) -> Optional[VisionEvent]:
        """
        Extract calendar event from image using LLM.
        
        Args:
            image: PIL Image to analyze
            context: Dict with app_name, bundle_id, window_title
            
        Returns:
            VisionEvent if event found, None otherwise
        """
        pass


class StubImageLLMClient(ImageLLMClient):
    """
    Stub LLM client for offline testing.
    Returns a hardcoded event for testing purposes.
    """
    
    def extract_event(self, image: Image.Image, context: dict) -> Optional[VisionEvent]:
        """Stub implementation - returns hardcoded event in real API response format."""
        Log.section("Stub LLM Client")
        Log.info("Using stub LLM client (offline mode)")
        
        # Simulate API response time (typical OpenAI API call takes 2-4 seconds)
        import time
        import random
        # Simulate variable response time between 2-4 seconds
        delay = random.uniform(2.0, 4.0)
        Log.info(f"Simulating API response time: {delay:.1f} seconds")
        time.sleep(delay)
        Log.info("Simulated API response received")

        # The format here should exactly match OpenAIImageLLMClient:
        # 1. Simulate a string of JSON from a response
        # 2. Parse it with json.loads (like OpenAI)
        stub_response_content = json.dumps({
            "title": "Sample Meeting",
            "date": "2024-11-15",
            "time": "10:30",
            "description": "Quarterly business review. This is a dummy event for stub client.",
            "participants": "Alice, Bob, Charlie",
            "location": "Conference Room A"
        })
        try:
            event_data = json.loads(stub_response_content)
            if event_data is None:
                Log.info("No calendar event detected in stub client")
                Log.kv({"stage": "llm", "provider": "stub", "result": "no_event"})
                return None

            vision_event = VisionEvent(
                title=event_data.get('title'),
                date=event_data.get('date'),
                time=event_data.get('time'),
                description=event_data.get('description'),
                participants=event_data.get('participants'),
                location=event_data.get('location')
            )

            if not vision_event.is_valid():
                Log.warn("Extracted stub event is invalid (missing required fields)")
                Log.kv({
                    "stage": "llm",
                    "provider": "stub",
                    "result": "failed",
                    "reason": "invalid_event",
                    "data": str(event_data)
                })
                return None

            Log.info(
                f"Event extracted (stub): title={vision_event.title}, date={vision_event.date}, time={vision_event.time}, "
                f"description={vision_event.description}, location={vision_event.location}, participants={vision_event.participants}"
            )
            Log.kv({
                "stage": "llm",
                "provider": "stub",
                "result": "success",
                "event_title": vision_event.title,
                "event_date": vision_event.date,
                "event_time": vision_event.time,
                "event_description": vision_event.description,
                "event_location": vision_event.location,
                "event_participants": vision_event.participants
            })

            return vision_event
        except Exception as e:
            Log.error(f"Unexpected error in StubImageLLMClient: {e}")
            Log.kv({"stage": "llm", "provider": "stub", "result": "failed", "reason": "unexpected_error", "error": str(e)})
            return None

class StubImageLLMClient_NoEventDetected(ImageLLMClient):
    """
    Stub LLM client that simulates no event detected in the image.
    Always returns None to represent "no event found".
    Useful for tests & simulation of LLM 'no event' responses.
    """
    def extract_event(self, image, context):
        Log.section("Stub LLM Client - No Event Detected")
        Log.info("Using stub LLM client (offline mode - no event)")
        
        # Simulate API response time (typical OpenAI API call takes 2-4 seconds)
        import time
        import random
        # Simulate variable response time between 2-4 seconds
        delay = random.uniform(2.0, 4.0)
        Log.info(f"Simulating API response time: {delay:.1f} seconds")
        time.sleep(delay)
        Log.info("Simulated API response received")
        
        Log.info("Simulating: LLM detected NO calendar event in the image.")
        Log.kv({
            "stage": "llm",
            "provider": "stub_noevent",
            "result": "no_event"
        })
        # Simulate same output as OpenAI client for no-event case
        return None

class OpenAIImageLLMClient(ImageLLMClient):
    """
    OpenAI Vision API client for real event extraction.
    Uses GPT-4o-mini for vision tasks.
    """
    
    def __init__(self, api_key: str):
        """
        Initialize OpenAI client.
        
        Args:
            api_key: OpenAI API key from environment
        """
        self.api_key = api_key
        self.api_url = "https://api.openai.com/v1/chat/completions"
        self.model = "gpt-4o-mini"
    
    def _validate_image(self, image: Image.Image) -> bool:
        """
        Validate image before processing.
        
        Args:
            image: PIL Image to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            # Check if image is None or empty
            if image is None:
                Log.error("Image is None")
                return False
            
            # Check image dimensions
            width, height = image.size
            if width == 0 or height == 0:
                Log.error(f"Invalid image dimensions: {width}x{height}")
                return False
            
            if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                Log.warn(f"Image too large: {width}x{height}, may need resizing")
                # Continue anyway - PIL will handle large images
            
            # Basic validation - check if we can access image data
            # Don't use verify() as it closes the image
            try:
                _ = image.mode
                _ = image.format
            except Exception:
                Log.error("Image appears corrupted - cannot access properties")
                return False
            
            return True
            
        except Exception as e:
            Log.error(f"Image validation failed: {e}")
            Log.kv({"stage": "llm", "error": "image_validation_failed", "details": str(e)})
            return False
    
    def _image_to_base64(self, image: Image.Image) -> Optional[str]:
        """
        Convert PIL Image to base64 encoded string.
        
        Args:
            image: PIL Image to convert
            
        Returns:
            Base64 string or None if conversion fails
        """
        try:
            # Convert to RGB if necessary (removes transparency)
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Save to bytes buffer
            buffer = io.BytesIO()
            # Use JPEG format with quality 85 to reduce size
            image.save(buffer, format='JPEG', quality=85, optimize=True)
            buffer.seek(0)
            
            # Check size
            image_bytes = buffer.getvalue()
            if len(image_bytes) > MAX_IMAGE_SIZE:
                Log.warn(f"Image size {len(image_bytes)} bytes exceeds limit, compressing...")
                # Try with lower quality
                buffer = io.BytesIO()
                image.save(buffer, format='JPEG', quality=60, optimize=True)
                image_bytes = buffer.getvalue()
                
                if len(image_bytes) > MAX_IMAGE_SIZE:
                    Log.error(f"Image too large even after compression: {len(image_bytes)} bytes")
                    return None
            
            # Encode to base64
            base64_string = base64.b64encode(image_bytes).decode('utf-8')
            Log.info(f"Image converted to base64: {len(base64_string)} chars")
            
            return base64_string
            
        except Exception as e:
            Log.error(f"Failed to convert image to base64: {e}")
            Log.kv({"stage": "llm", "error": "base64_conversion_failed", "details": str(e)})
            return None
    
    def extract_event(self, image: Image.Image, context: dict) -> Optional[VisionEvent]:
        """
        Extract event using OpenAI Vision API (GPT-4o-mini).
        
        Args:
            image: PIL Image to analyze
            context: Dict with app context
            
        Returns:
            VisionEvent if event found, None otherwise
        """
        Log.section("OpenAI LLM Client")
        Log.info(f"Using OpenAI Vision API ({self.model})")
        
        # Edge case 1: Validate image
        if not self._validate_image(image):
            Log.error("Image validation failed - cannot process")
            Log.kv({"stage": "llm", "provider": "openai", "result": "failed", "reason": "invalid_image"})
            return None
        
        # Edge case 2: Convert to base64
        base64_image = self._image_to_base64(image)
        if base64_image is None:
            Log.error("Failed to convert image to base64")
            Log.kv({"stage": "llm", "provider": "openai", "result": "failed", "reason": "base64_conversion_failed"})
            return None
        
        # Log image details for debugging
        Log.info(f"Image base64 length: {len(base64_image)} chars")
        Log.kv({"stage": "llm", "image_base64_length": len(base64_image), "image_size": f"{image.size[0]}x{image.size[1]}"})
        
        # Construct prompt that includes window and app context
        import datetime
        import time

        # Get current system time, date, and timezone
        now = datetime.datetime.now()
        local_tz = dateutil_tz.tzlocal()
        system_time_str = now.strftime("%H:%M:%S")
        system_date_str = now.strftime("%Y-%m-%d")
        system_timezone_str = str(local_tz)

        prompt = (
            f"Analyze this screenshot and extract any calendar event information you find. Consider the context of the window/app and the image to extract the event information. For example, if the window title is 'WhatsApp', the event information should be extracted from the WhatsApp window. Additionally, use the names inside the message exchange to also include appointment participants. If the messages are from a group, try and include all the names visibile in the image.\n"
            f"You need to be careful about which part of the screen you are looking at. For example, in Whatsapp, only look at the active chat window. There may be previews of other chats visible in the screenshot, but you need to focus on the active chat window.\n"
            f"Contextual metadata:\n"
            f"- App Name: {context.get('app_name', 'unknown')}\n"
            f"- Bundle ID: {context.get('bundle_id', 'unknown')}\n"
            f"- Window Title: {context.get('window_title', 'unknown')}\n"
            f"- System Date: {system_date_str}\n"
            f"- System Time: {system_time_str}\n"
            f"- System Time Zone: {system_timezone_str}\n\n"
            "Return a JSON object with the following fields (use null if not found), and make sure all date and time information is returned in the system time zone:\n"
            "- title: string (event title)\n"
            "- date: string (ISO date format like \"2024-11-05\" or natural language, in system time zone)\n"
            "- time: string (time like \"14:00\" or natural language, in system time zone)\n"
            "- description: string (optional event description)\n"
            "- participants: string (optional event participants)\n"
            "- location: string (optional location)\n\n"
            "If no calendar event is found in the image, return null.\n"
            "Keep the response compact and only include actual event information."
        )

        try:
            # Prepare API request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 500,
                "temperature": 0.1
            }
            
            Log.info("Calling OpenAI Vision API...")
            Log.info(f"Payload structure: model={self.model}, messages=1, content_items={len(payload['messages'][0]['content'])}")
            Log.info(f"Content types: {[item.get('type') for item in payload['messages'][0]['content']]}")
            Log.kv({
                "stage": "llm",
                "provider": "openai",
                "model": self.model,
                "status": "requesting",
                "image_included": True,
                "base64_preview": base64_image[:50] + "..." if len(base64_image) > 50 else base64_image
            })
            
            # Make API call
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            # Log response status
            Log.info(f"API response status: {response.status_code}")
            
            # If error, log the response body
            if response.status_code != 200:
                try:
                    error_data = response.json()
                    Log.error(f"OpenAI API error: {error_data}")
                except:
                    Log.error(f"OpenAI API error (non-JSON): {response.text[:500]}")
            
            response.raise_for_status()
            
            # Parse response
            result = response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            
            if not content:
                Log.warn("Empty response from OpenAI")
                Log.kv({"stage": "llm", "provider": "openai", "result": "failed", "reason": "empty_response"})
                return None
            
            # Parse JSON from response
            # Sometimes the response includes markdown code blocks
            content = content.strip()
            if content.startswith('```'):
                # Remove markdown code blocks
                lines = content.split('\n')
                content = '\n'.join(lines[1:-1]) if len(lines) > 2 else content
            
            # Try to parse as JSON
            try:
                event_data = json.loads(content)
            except json.JSONDecodeError:
                # If not JSON, try to extract JSON from text
                import re
                json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
                if json_match:
                    event_data = json.loads(json_match.group())
                else:
                    Log.warn(f"Could not parse JSON from response: {content[:100]}")
                    Log.kv({"stage": "llm", "provider": "openai", "result": "failed", "reason": "json_parse_error"})
                    return None
            
            # Check if null (no event found)
            if event_data is None:
                Log.info("OpenAI detected no calendar event in image")
                Log.kv({"stage": "llm", "provider": "openai", "result": "no_event"})
                return None
            
            # Create VisionEvent from response
            vision_event = VisionEvent(
                title=event_data.get('title'),
                date=event_data.get('date'),
                time=event_data.get('time'),
                description=event_data.get('description'),
                participants=event_data.get('participants'),
                location=event_data.get('location')
            )
            
            if not vision_event.is_valid():
                Log.warn("Extracted event is invalid (missing required fields)")
                Log.kv({
                    "stage": "llm",
                    "provider": "openai",
                    "result": "failed",
                    "reason": "invalid_event",
                    "data": str(event_data)
                })
                return None
            
            Log.info(
                f"Event extracted: title={vision_event.title}, date={vision_event.date}, time={vision_event.time}, "
                f"description={vision_event.description}, location={vision_event.location}, participants={vision_event.participants}"
            )
            Log.kv({
                "stage": "llm",
                "provider": "openai",
                "result": "success",
                "event_title": vision_event.title,
                "event_date": vision_event.date,
                "event_time": vision_event.time,
                "event_description": vision_event.description,
                "event_location": vision_event.location,
                "event_participants": vision_event.participants
            })
            
            return vision_event
            
        except requests.exceptions.RequestException as e:
            Log.error(f"OpenAI API request failed: {e}")
            Log.kv({"stage": "llm", "provider": "openai", "result": "failed", "reason": "api_error", "error": str(e)})
            return None
            
        except Exception as e:
            Log.error(f"Unexpected error in OpenAI client: {e}")
            Log.kv({"stage": "llm", "provider": "openai", "result": "failed", "reason": "unexpected_error", "error": str(e)})
            return None


def get_llm_client() -> ImageLLMClient:
    """
    Factory function to get the appropriate LLM client.
    Defaults to StubImageLLMClient. Use OpenAIImageLLMClient if API key available.
    
    Can be forced to use stub by setting USE_STUB environment variable.
    Can be forced to use no-event stub by setting USE_STUB_NOEVENT environment variable.
    
    Returns:
        ImageLLMClient instance
    """
    import os
    
    # Check if no-event stub is forced via environment variable
    use_stub_noevent = os.getenv("USE_STUB_NOEVENT")
    if use_stub_noevent:
        Log.info("USE_STUB_NOEVENT flag set - using stub client (no event detected)")
        return StubImageLLMClient_NoEventDetected()
    
    # Check if stub is forced via environment variable
    use_stub = os.getenv("USE_STUB")
    if use_stub:
        Log.info("USE_STUB flag set - using stub client")
        return StubImageLLMClient()
    
    api_key = os.getenv("apiKey")  # Note: using "apiKey" as specified in INIT_PROMPT
    
    if api_key:
        Log.info("API key found - using OpenAI client")
        return OpenAIImageLLMClient(api_key)
    else:
        Log.info("No API key - using stub client")
        return StubImageLLMClient()
