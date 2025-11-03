"""
Frontmost window capture module.
Captures the frontmost window and returns image with context.
"""

from datetime import datetime
from typing import Optional, Tuple, Dict
from pathlib import Path
from PIL import Image

from src.logging_helper import Log

try:
    from AppKit import NSWorkspace
    APPKIT_AVAILABLE = True
except ImportError:
    APPKIT_AVAILABLE = False


def _get_frontmost_app_info() -> Dict[str, str]:
    """
    Get information about the frontmost application.
    
    Returns:
        dict: Contains app_name, bundle_id, and window_title
    """
    app_name = "Unknown"
    bundle_id = "unknown"
    window_title = "Unknown"
    
    if APPKIT_AVAILABLE:
        try:
            workspace = NSWorkspace.sharedWorkspace()
            frontmost_app = workspace.activeApplication()
            
            if frontmost_app:
                app_name = frontmost_app.get('NSApplicationName', 'Unknown')
                bundle_id = frontmost_app.get('NSApplicationBundleIdentifier', 'unknown')
                
                # Try to get window title (simplified - get frontmost window)
                # Note: This is a simplified approach. Full window title might need Accessibility API
                window_title = app_name  # Fallback to app name
                
        except Exception as e:
            Log.warn(f"Failed to get frontmost app info: {e}")
    else:
        Log.warn("AppKit not available - using defaults for app info")
    
    return {
        "app_name": app_name,
        "bundle_id": bundle_id,
        "window_title": window_title
    }


def capture() -> Optional[Tuple[Image.Image, Dict[str, str]]]:
    """
    Capture the frontmost window.
    
    Returns:
        tuple: (PIL Image, context dict) if successful, None if failed
        context dict contains: app_name, bundle_id, window_title
    """
    Log.section("Frontmost Window Capture")
    Log.info("Capturing frontmost window")
    
    try:
        import pyautogui
        
        # Capture full screen (we'll capture frontmost window by default)
        # Note: pyautogui.screenshot() captures full screen
        # For frontmost window only, we'd need window bounds, but for Phase 1
        # we'll capture the full screen as a starting point
        screenshot = pyautogui.screenshot()
        
        if screenshot is None:
            Log.error("Screenshot returned None")
            Log.kv({"stage": "capture", "result": "failed", "reason": "screenshot_none"})
            return None
        
        # Get frontmost app info
        context = _get_frontmost_app_info()
        
        # Save screenshot to screenshot_dump_tobedeleted folder with timestamp
        try:
            # Get project root directory (assuming src/ is in project root)
            project_root = Path(__file__).parent.parent
            screenshot_dir = project_root / "screenshot_dump_tobedeleted"
            
            # Create directory if it doesn't exist
            screenshot_dir.mkdir(exist_ok=True)
            
            # Generate timestamp for filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            screenshot_path = screenshot_dir / f"{timestamp}.png"
            
            # Save screenshot
            screenshot.save(screenshot_path)
            Log.info(f"Screenshot saved: {screenshot_path}")
            Log.kv({
                "stage": "capture",
                "result": "success",
                "app": context['app_name'],
                "bundle_id": context['bundle_id'],
                "screenshot_path": str(screenshot_path)
            })
        except Exception as save_error:
            Log.warn(f"Failed to save screenshot: {save_error}")
            # Continue anyway - screenshot is still returned in memory
        
        Log.info(f"Capture successful: {context['app_name']}")
        
        return (screenshot, context)
        
    except Exception as e:
        Log.error(f"Capture failed: {e}")
        Log.kv({"stage": "capture", "result": "failed", "error": str(e)})
        return None

