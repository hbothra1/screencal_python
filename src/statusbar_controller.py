"""
Status bar controller for menu bar app interface.
Handles menu bar UI and capture button clicks.
"""

import threading

import rumps
from src.logging_helper import Log
from src.frontmost_capture import capture
from src.image_llm_client import get_llm_client
from src.event_normalizer import normalize
from src.ics_generator import generate_ics
from src.notifications import (
    notify_screen_captured,
    notify_event_detected,
    notify_no_event_detected,
)


class StatusBarController(rumps.App):
    """
    Menu bar app controller using rumps.
    Provides menu items for capture and quit.
    """
    
    def __init__(self):
        """Initialize the status bar app."""
        super(StatusBarController, self).__init__(
            "ScreenCal",
            icon=None,  # No icon for now
            template=True,
            quit_button=None  # We'll add quit manually
        )
        
        # Set up menu items: "Capture", separator, "Quit"
        self.menu = [
            rumps.MenuItem("Capture", callback=self.capture_menu_item),
            None,  # Separator
            rumps.MenuItem("Quit", callback=self.quit_menu_item)
        ]
        
        Log.section("StatusBar Controller")
        Log.info("Initializing menu bar app")
    
    def capture_menu_item(self, _):
        """Handle capture button click."""
        Log.section("Capture Menu Item Clicked")
        Log.info("User clicked Capture button")
        
        # Step 1: Capture screenshot
        capture_result = capture()
        
        if capture_result is None:
            Log.error("Capture failed - check permissions or try again")
            Log.kv({"stage": "menu_action", "result": "capture_failed"})
            return
        
        image, context = capture_result
        Log.info(f"Capture completed: {context['app_name']}")
        Log.kv({
            "stage": "menu_action",
            "result": "capture_success",
            "app": context['app_name']
        })
        
        # Show notification: Screen captured
        Log.info("Attempting to show 'screen captured' notification.")
        notify_screen_captured(timeout=2.0)

        # Offload heavy processing to background thread so notifications can render immediately
        processing_thread = threading.Thread(
            target=self._process_capture_async,
            args=(image, context),
            daemon=True,
            name="ScreenCalCaptureProcessor",
        )
        processing_thread.start()
    
    def quit_menu_item(self, _):
        """Handle quit button click."""
        Log.section("Quit Menu Item Clicked")
        Log.info("User clicked Quit - exiting app")
        rumps.quit_application()

    def _process_capture_async(self, image, context):
        """Process captured screenshot in background thread."""
        try:
            Log.info("Processing captured image with LLM (async thread)")
            llm_client = get_llm_client()
            vision_event = llm_client.extract_event(image, context)

            if vision_event is None:
                Log.warn("LLM did not extract an event from image")
                Log.kv({"stage": "menu_action", "result": "no_event_extracted"})
                notify_no_event_detected()
                return

            Log.info("Normalizing event data")
            normalized_event = normalize(vision_event)

            if normalized_event is None:
                Log.error("Failed to normalize event")
                Log.kv({"stage": "menu_action", "result": "normalization_failed"})
                notify_no_event_detected()
                return

            notify_event_detected()

            Log.info("Generating ICS file and opening Calendar")
            ics_path = generate_ics(normalized_event)

            if ics_path is None:
                Log.error("Failed to generate ICS file")
                Log.kv({"stage": "menu_action", "result": "ics_generation_failed"})
                return

            Log.info(f"Event processing complete - ICS saved to: {ics_path}")
            Log.kv({
                "stage": "menu_action",
                "result": "success",
                "event_title": normalized_event.title,
                "ics_path": str(ics_path),
                "start_time": normalized_event.start_time.isoformat(),
            })
        except Exception as exc:
            Log.error(f"Unexpected error during capture processing: {exc}")
            Log.kv({
                "stage": "menu_action",
                "result": "processing_exception",
                "error": str(exc),
            })
            notify_no_event_detected()

