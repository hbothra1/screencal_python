"""
Status bar controller for menu bar app interface.
Handles menu bar UI and capture button clicks.
"""

import os
import threading
from typing import Optional

import rumps  # type: ignore  # rumps is provided by the 'rumps' package, ensure it is installed
from src.logging_helper import Log

# Import AppKit for diagnostic checks
try:
    from AppKit import NSScreen, NSStatusBar
    APPKIT_AVAILABLE = True
except ImportError:
    APPKIT_AVAILABLE = False
from src.frontmost_capture import capture
from src.image_llm_client import get_llm_client
from src.event_normalizer import normalize
from src.calendar_connector import create_calendar_event
from src.notifications import (
    notification_on_capture_complete,
    notification_on_llm_processing_start,
    notification_on_llm_complete,
    update_notification,
    notification_shutdown,
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
        
        # Check if status item was created (only if rumps_diagnostics flag is set)
        rumps_diagnostics = os.environ.get('rumps_diagnostics', '').lower() in ('1', 'true', 'yes')
        if rumps_diagnostics:
            # Run immediate diagnostics during __init__
            self._check_status_item_creation()
            # Also schedule a check after app.run() starts (status item is created in initializeStatusBar())
            self._should_check_status_item = True
    
    def _check_status_item_creation(self):
        """Check if rumps created the status item and log detailed diagnostic info.
        
        According to rumps source code, the status item is stored in:
        self._nsapp.nsstatusitem (where _nsapp is the NSApp delegate instance)
        """
        try:
            if not APPKIT_AVAILABLE:
                Log.warn("AppKit not available - cannot check status item creation")
                return
            
            # First, list all attributes on self to see what rumps actually created
            all_attrs = [attr for attr in dir(self) if not attr.startswith('__')]
            Log.info(f"All attributes on rumps.App instance: {len(all_attrs)} total")
            
            # Look for any attributes that might contain status item or NSStatusItem
            status_related = [attr for attr in all_attrs if 'status' in attr.lower() or 'item' in attr.lower() or 'ns' in attr.lower()]
            if status_related:
                Log.info(f"Status/item related attributes: {status_related}")
            
            # Check for rumps internal attributes (rumps often uses underscore prefix)
            rumps_internals = [attr for attr in all_attrs if attr.startswith('_')]
            Log.info(f"Private/internal attributes (first 20): {rumps_internals[:20]}")
            
            # According to rumps source, status item is at self._nsapp.nsstatusitem
            # Try this FIRST since we know where it should be
            status_item = None
            found_attr = None
            
            try:
                if hasattr(self, '_nsapp'):
                    nsapp = self._nsapp
                    Log.info(f"Found _nsapp: {type(nsapp).__name__}")
                    if hasattr(nsapp, 'nsstatusitem'):
                        status_item = nsapp.nsstatusitem
                        if status_item:
                            found_attr = '_nsapp.nsstatusitem'
                            Log.info("✓ Found status item at self._nsapp.nsstatusitem (from rumps source)")
                        else:
                            Log.info("  _nsapp.nsstatusitem exists but is None (not created yet - will be created when app.run() starts)")
                    else:
                        Log.info("  _nsapp doesn't have nsstatusitem attribute yet (will be created when app.run() starts)")
                        nsapp_attrs = [attr for attr in dir(nsapp) if not attr.startswith('__')]
                        status_attrs = [attr for attr in nsapp_attrs if 'status' in attr.lower() or 'item' in attr.lower()]
                        if status_attrs:
                            Log.info(f"  _nsapp attributes with 'status' or 'item': {status_attrs}")
                        Log.info(f"  _nsapp attributes (first 10): {nsapp_attrs[:10]}")
                else:
                    Log.info("  self._nsapp doesn't exist yet")
            except Exception as e:
                Log.warn(f"Error accessing _nsapp.nsstatusitem: {e}")
            
            # If not found via _nsapp, try other common attribute names
            if not status_item:
                for attr_name in ['_nsstatusitem', 'nsstatusitem', '_statusItem', 'statusItem', 'status_item', '_status_item']:
                    if hasattr(self, attr_name):
                        status_item = getattr(self, attr_name)
                        found_attr = attr_name
                        Log.info(f"✓ Found status item at attribute: {attr_name}")
                        break
            
            # If not found in expected places, try to find any NSStatusItem type object
            # Since the menu bar item IS visible, it must exist somewhere!
            if not status_item:
                Log.info("Status item not found in expected attributes, searching all attributes...")
                try:
                    from AppKit import NSStatusItem, NSStatusBar
                    
                    # First, try to find it through NSStatusBar directly
                    # Get all status items from the system status bar
                    status_bar = NSStatusBar.systemStatusBar()
                    # Unfortunately NSStatusBar doesn't expose a way to enumerate items
                    
                    # Check all attributes more carefully
                    for attr_name in all_attrs:
                        try:
                            attr_value = getattr(self, attr_name)
                            # Skip callable methods
                            if callable(attr_value):
                                continue
                            # Skip None
                            if attr_value is None:
                                continue
                            
                            # Check if it's an NSStatusItem or has NSStatusItem-like methods
                            if hasattr(attr_value, 'button') and hasattr(attr_value, 'length'):
                                try:
                                    # Try to actually call button() to verify it's a real NSStatusItem
                                    test_button = attr_value.button()
                                    if test_button is not None:
                                        status_item = attr_value
                                        found_attr = attr_name
                                        Log.info(f"✓ Found status item at attribute: {attr_name} (type: {type(attr_value).__name__})")
                                        break
                                except Exception as e:
                                    # Not a real NSStatusItem, skip
                                    pass
                        except Exception as e:
                            # Skip attributes that can't be accessed
                            pass
                    
                    # Also check __dict__ directly
                    if not status_item:
                        Log.info("Checking rumps.__dict__ for status item...")
                        try:
                            for key, value in self.__dict__.items():
                                if hasattr(value, 'button') and hasattr(value, 'length'):
                                    try:
                                        test_button = value.button()
                                        if test_button is not None:
                                            status_item = value
                                            found_attr = key
                                            Log.info(f"✓ Found status item in __dict__ at: {key} (type: {type(value).__name__})")
                                            break
                                    except:
                                        pass
                        except Exception as e:
                            Log.warn(f"Error checking __dict__: {e}")
                    
                    # Try accessing through the menu's view hierarchy
                    # According to web search, rumps might store it in _menu._status_item
                    if not status_item:
                        Log.info("Trying to access status item through menu/view hierarchy...")
                        try:
                            # Try to get the menu's NSMenu object
                            if hasattr(self, '_menu'):
                                Log.info(f"  Found _menu attribute: {type(self._menu).__name__}")
                                
                                # Check if _menu has _status_item (suggested by web search)
                                if hasattr(self._menu, '_status_item'):
                                    status_item_candidate = self._menu._status_item
                                    if status_item_candidate and hasattr(status_item_candidate, 'button'):
                                        try:
                                            test_button = status_item_candidate.button()
                                            if test_button is not None:
                                                status_item = status_item_candidate
                                                found_attr = '_menu._status_item'
                                                Log.info("✓ Found status item at _menu._status_item")
                                        except:
                                            pass
                                    else:
                                        Log.info("  _menu._status_item exists but is not a valid NSStatusItem")
                                else:
                                    Log.info("  _menu doesn't have _status_item attribute")
                                
                                # Also check _menu._menu for NSMenu
                                if hasattr(self._menu, '_menu'):
                                    ns_menu = self._menu._menu
                                    Log.info(f"  Found _menu._menu: {type(ns_menu).__name__}")
                                    # Try to find the status item through the menu's parent
                                    if hasattr(ns_menu, 'superview'):
                                        superview = ns_menu.superview()
                                        if superview:
                                            # The status item button might be accessible this way
                                            Log.info(f"  Menu superview found: {type(superview).__name__}")
                                        else:
                                            Log.info("  Menu superview is None")
                                    else:
                                        Log.info("  NSMenu doesn't have superview attribute")
                                else:
                                    Log.info("  _menu doesn't have _menu attribute")
                                
                                # Check all attributes of _menu object
                                menu_attrs = [attr for attr in dir(self._menu) if not attr.startswith('__')]
                                menu_status_attrs = [attr for attr in menu_attrs if 'status' in attr.lower() or 'item' in attr.lower()]
                                if menu_status_attrs:
                                    Log.info(f"  _menu attributes with 'status' or 'item': {menu_status_attrs}")
                            else:
                                Log.info("  No _menu attribute found")
                        except Exception as e:
                            Log.warn(f"Error accessing menu hierarchy: {e}")
                            import traceback
                            Log.warn(f"Traceback: {traceback.format_exc()}")
                    
                    # Try accessing through NSApplication delegate
                    # According to rumps source, nsstatusitem is stored in NSApp delegate
                    if not status_item:
                        Log.info("Trying to access status item through NSApplication...")
                        try:
                            from AppKit import NSApplication
                            app = NSApplication.sharedApplication()
                            Log.info(f"  NSApplication found: {type(app).__name__}")
                            delegate = app.delegate()
                            if delegate:
                                Log.info(f"  Delegate found: {type(delegate).__name__}")
                                
                                # Check if delegate has nsstatusitem (rumps stores it there!)
                                if hasattr(delegate, 'nsstatusitem'):
                                    Log.info("  Delegate has nsstatusitem attribute!")
                                    status_item = delegate.nsstatusitem
                                    if status_item:
                                        found_attr = 'NSApplication.delegate().nsstatusitem'
                                        Log.info("✓ Found status item through NSApplication delegate.nsstatusitem")
                                    else:
                                        Log.info("  delegate.nsstatusitem is None (not created yet)")
                                elif hasattr(delegate, 'statusItem'):
                                    Log.info("  Delegate has statusItem attribute")
                                    status_item = delegate.statusItem()
                                    if status_item:
                                        found_attr = 'NSApplication.delegate().statusItem()'
                                        Log.info("✓ Found status item through NSApplication delegate.statusItem()")
                                    else:
                                        Log.info("  delegate.statusItem() returned None")
                                else:
                                    Log.info("  Delegate doesn't have nsstatusitem or statusItem attribute yet")
                                    # List delegate attributes
                                    delegate_attrs = [attr for attr in dir(delegate) if not attr.startswith('__')]
                                    status_attrs = [attr for attr in delegate_attrs if 'status' in attr.lower() or 'item' in attr.lower()]
                                    if status_attrs:
                                        Log.info(f"  Delegate attributes with 'status' or 'item': {status_attrs}")
                                    Log.info(f"  All delegate attributes (first 15): {delegate_attrs[:15]}")
                            else:
                                Log.info("  NSApplication delegate is None (will be set when app.run() starts)")
                        except Exception as e:
                            Log.warn(f"Error accessing through NSApplication: {e}")
                            import traceback
                            Log.warn(f"Traceback: {traceback.format_exc()}")
                    
                    # Try accessing through rumps' icon property setter/getter
                    # This might trigger creation or give us access to the status item
                    if not status_item:
                        Log.info("Trying to access status item through icon property...")
                        try:
                            # Try getting the icon property - this might trigger status item creation
                            # or give us access to it
                            current_icon = self.icon
                            Log.info(f"  Current icon value: {current_icon}")
                            
                            # Try setting and getting icon - might expose status item
                            # But first check if accessing icon gives us access to status item
                            if hasattr(self, 'icon'):
                                # The icon property might store/access the status item
                                # Check if there's a property setter that stores it
                                pass
                        except Exception as e:
                            Log.info(f"  Error accessing icon property: {e}")
                    
                    # Try accessing through rumps' internal _nsapp (stores NSApp delegate)
                    # According to rumps source, _nsapp is the NSApp delegate instance
                    # and nsstatusitem is stored in _nsapp.nsstatusitem
                    # BUT: initializeStatusBar() is called when app.run() starts, not during __init__
                    # So we need to check if _nsapp exists first, then check if status item was created
                    if not status_item:
                        Log.info("Trying to access status item through rumps._nsapp...")
                        try:
                            # rumps stores the NSApp delegate in _nsapp
                            # Check if _nsapp exists (it should be created during App.__init__)
                            if hasattr(self, '_nsapp'):
                                nsapp = self._nsapp
                                Log.info(f"  Found _nsapp: {type(nsapp).__name__}")
                                
                                # Check if nsstatusitem exists (it's created when initializeStatusBar() is called)
                                # This happens when app.run() starts, so it might not exist yet during __init__
                                if hasattr(nsapp, 'nsstatusitem'):
                                    status_item = nsapp.nsstatusitem
                                    if status_item:
                                        Log.info("✓ Found status item at self._nsapp.nsstatusitem")
                                    else:
                                        Log.info("  _nsapp.nsstatusitem exists but is None (not created yet?)")
                                else:
                                    Log.info("  _nsapp doesn't have nsstatusitem attribute (status item not created yet)")
                                    Log.info("  Note: status item is created when app.run() starts, not during __init__")
                                    nsapp_attrs = [attr for attr in dir(nsapp) if not attr.startswith('__')]
                                    status_attrs = [attr for attr in nsapp_attrs if 'status' in attr.lower() or 'item' in attr.lower()]
                                    if status_attrs:
                                        Log.info(f"  _nsapp attributes with 'status' or 'item': {status_attrs}")
                                    Log.info(f"  _nsapp attributes (first 10): {nsapp_attrs[:10]}")
                            else:
                                Log.info("  self._nsapp doesn't exist")
                        except Exception as e:
                            Log.warn(f"Error accessing _nsapp: {e}")
                            import traceback
                            Log.warn(f"Traceback: {traceback.format_exc()}")
                    
                    # Try accessing through rumps' internal properties (might be lazy-loaded)
                    if not status_item:
                        Log.info("Trying to access rumps properties directly...")
                        tried_props = []
                        try:
                            # rumps might have properties that aren't in dir() but are accessible
                            # Try common property names that might be hidden
                            for prop_name in ['statusItem', '_statusItem', 'nsstatusitem', '_nsstatusitem', 'status_item']:
                                tried_props.append(prop_name)
                                try:
                                    # Try getattr - might work even if not in dir()
                                    prop_value = getattr(self, prop_name, None)
                                    if prop_value:
                                        Log.info(f"  Found property {prop_name}: {type(prop_value).__name__}")
                                        # If it's _nsapp, try valueForKey_ to get statusItem
                                        if prop_name == '_nsapp' and hasattr(prop_value, 'valueForKey_'):
                                            try:
                                                status_item_candidate = prop_value.valueForKey_('statusItem')
                                                if status_item_candidate and hasattr(status_item_candidate, 'button'):
                                                    test_button = status_item_candidate.button()
                                                    if test_button is not None:
                                                        status_item = status_item_candidate
                                                        found_attr = '_nsapp.valueForKey_("statusItem")'
                                                        Log.info("✓ Found status item via _nsapp.valueForKey_('statusItem')")
                                                        break
                                            except Exception as e:
                                                Log.info(f"  Error accessing _nsapp.valueForKey_('statusItem'): {e}")
                                        elif hasattr(prop_value, 'button'):
                                            test_button = prop_value.button()
                                            if test_button is not None:
                                                status_item = prop_value
                                                found_attr = prop_name
                                                Log.info(f"✓ Found status item via property: {prop_name}")
                                                break
                                    else:
                                        Log.info(f"  Property {prop_name} is None or doesn't exist")
                                except Exception as e:
                                    Log.info(f"  Error accessing property {prop_name}: {e}")
                            Log.info(f"  Tried properties: {tried_props}")
                        except Exception as e:
                            Log.warn(f"Error accessing properties: {e}")
                            import traceback
                            Log.warn(f"Traceback: {traceback.format_exc()}")
                    
                    # Try enumerating NSStatusBar items (if possible)
                    if not status_item:
                        Log.info("Trying to enumerate NSStatusBar items...")
                        try:
                            status_bar = NSStatusBar.systemStatusBar()
                            # Check if NSStatusBar has an items() method or similar
                            if hasattr(status_bar, 'items'):
                                items = status_bar.items()
                                Log.info(f"  Found {len(items) if items else 0} items in status bar")
                                # Try to find our app's status item by matching menu
                                if items:
                                    for item in items:
                                        try:
                                            menu = item.menu()
                                            # Check if this menu matches our menu
                                            if hasattr(self, '_menu') and hasattr(self._menu, '_menu'):
                                                if menu == self._menu._menu:
                                                    status_item = item
                                                    found_attr = 'NSStatusBar.items()'
                                                    Log.info("✓ Found status item by enumerating NSStatusBar items")
                                                    break
                                        except:
                                            pass
                            else:
                                Log.info("  NSStatusBar doesn't have items() method (or it's not accessible)")
                        except Exception as e:
                            Log.warn(f"Error enumerating NSStatusBar items: {e}")
                    
                    # Try accessing through object_getInstanceVariable (runtime introspection)
                    if not status_item:
                        Log.info("Trying runtime introspection to find status item...")
                        try:
                            import objc
                            # Try to get all instance variables using objc runtime
                            # Get the class of self
                            cls = type(self)
                            # This is complex - objc runtime introspection might not work with Python wrappers
                            Log.info(f"Runtime introspection: self type is {cls.__name__}")
                            # Note: PyObjC runtime introspection is complex and may not expose Python attributes
                        except Exception as e:
                            Log.warn(f"Error with runtime introspection: {e}")
                    
                    # Log all attribute names and types for debugging
                    if not status_item:
                        Log.info("Dumping all attributes and their types for debugging:")
                        for attr_name in sorted(all_attrs):
                            try:
                                attr_value = getattr(self, attr_name)
                                if not callable(attr_value) and attr_value is not None:
                                    attr_type = type(attr_value).__name__
                                    Log.info(f"  {attr_name}: {attr_type}")
                            except:
                                pass
                                
                except Exception as e:
                    Log.warn(f"Error searching for status item: {e}")
                    import traceback
                    Log.warn(f"Traceback: {traceback.format_exc()}")
            
            # Check visibility if we found the status item
            if status_item:
                self._check_status_item_visibility(status_item, found_attr)
            else:
                Log.info("Status item not found during __init__ (this is expected - it's created when app.run() starts)")
                Log.info("Will check again after app starts running (on first menu interaction)")
                
                # Check if rumps has any error state or initialization flags
                if hasattr(self, '_icon'):
                    Log.info(f"rumps._icon value: {self._icon}")
                if hasattr(self, 'icon'):
                    Log.info(f"rumps.icon value: {self.icon}")
                if hasattr(self, '_template'):
                    Log.info(f"rumps._template value: {self._template}")
                if hasattr(self, 'title'):
                    Log.info(f"rumps.title value: {self.title}")
                if hasattr(self, '_name'):
                    Log.info(f"rumps._name value: {self._name}")
                if hasattr(self, 'name'):
                    Log.info(f"rumps.name value: {self.name}")
                
                # Try to check rumps version and see if there's a known issue
                try:
                    import rumps
                    Log.info(f"rumps version: {getattr(rumps, '__version__', 'unknown')}")
                except:
                    pass
                
        except Exception as e:
            Log.warn(f"Error checking status item creation: {e}")
            import traceback
            Log.warn(f"Traceback: {traceback.format_exc()}")
    
    def _check_status_item_creation_after_start(self):
        """Check status item after app.run() has started (when it should be created)."""
        try:
            if not APPKIT_AVAILABLE:
                Log.warn("AppKit not available - cannot check status item creation")
                return
            
            status_item = None
            found_attr = None
            
            # Try _nsapp.nsstatusitem first (this is where rumps stores it)
            try:
                if hasattr(self, '_nsapp'):
                    nsapp = self._nsapp
                    Log.info(f"Found _nsapp: {type(nsapp).__name__}")
                    if hasattr(nsapp, 'nsstatusitem'):
                        status_item = nsapp.nsstatusitem
                        if status_item:
                            found_attr = '_nsapp.nsstatusitem'
                            Log.info("✓ Found status item at self._nsapp.nsstatusitem")
                        else:
                            Log.warn("  _nsapp.nsstatusitem exists but is None")
                    else:
                        Log.warn("  _nsapp doesn't have nsstatusitem attribute")
                        nsapp_attrs = [attr for attr in dir(nsapp) if not attr.startswith('__')]
                        status_attrs = [attr for attr in nsapp_attrs if 'status' in attr.lower() or 'item' in attr.lower()]
                        if status_attrs:
                            Log.info(f"  _nsapp attributes with 'status' or 'item': {status_attrs}")
                else:
                    Log.warn("  self._nsapp doesn't exist")
            except Exception as e:
                Log.warn(f"Error accessing _nsapp.nsstatusitem: {e}")
            
            # Also try NSApplication delegate
            if not status_item:
                try:
                    from AppKit import NSApplication
                    app = NSApplication.sharedApplication()
                    delegate = app.delegate()
                    if delegate and hasattr(delegate, 'nsstatusitem'):
                        status_item = delegate.nsstatusitem
                        if status_item:
                            found_attr = 'NSApplication.delegate().nsstatusitem'
                            Log.info("✓ Found status item through NSApplication delegate.nsstatusitem")
                except Exception as e:
                    Log.warn(f"Error accessing through NSApplication: {e}")
            
            if status_item:
                self._check_status_item_visibility(status_item, found_attr)
            else:
                Log.warn("⚠️  Could not find status item even after app.run() started")
                Log.warn("This could indicate a rumps bug or menu bar space issue")
        except Exception as e:
            Log.warn(f"Error checking status item after start: {e}")
            import traceback
            Log.warn(f"Traceback: {traceback.format_exc()}")
    
    def _check_status_item_visibility(self, status_item, found_attr):
        """Check if the status item button is visible and log its properties."""
        try:
            button = status_item.button()
            if button:
                frame = button.frame()
                is_visible = frame.size.width > 0 and frame.size.height > 0
                Log.info(f"Status item button frame: ({frame.origin.x:.0f}, {frame.origin.y:.0f}, {frame.size.width:.0f}x{frame.size.height:.0f}), visible={is_visible}")
                
                # Get button title to confirm it's our item
                try:
                    title = button.title()
                    Log.info(f"Status item button title: '{title}'")
                except:
                    pass
                
                if not is_visible:
                    Log.warn("⚠️  Status item has zero size - menu bar item is hidden (likely space issue)")
                    return False
                else:
                    Log.info("✓ Status item created and has valid size - should be visible")
                    return True
            else:
                Log.warn("⚠️  Status item button is None")
                return False
        except Exception as e:
            Log.warn(f"Error checking status item visibility: {e}")
            import traceback
            Log.warn(f"Traceback: {traceback.format_exc()}")
            return False
    
    def capture_menu_item(self, _):
        """Handle capture button click."""
        # Check status item on first menu interaction (if diagnostics enabled)
        if hasattr(self, '_should_check_status_item') and self._should_check_status_item:
            self._should_check_status_item = False
            rumps_diagnostics = os.environ.get('rumps_diagnostics', '').lower() in ('1', 'true', 'yes')
            if rumps_diagnostics:
                Log.section("Status Item Check (After app.run() started)")
                Log.info("Checking status item on first menu interaction (after app.run() should have started)...")
                self._check_status_item_creation_after_start()
        
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
        Log.info("Attempting to show 'screen captured' notification (state-based).")
        notification_on_capture_complete()

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
        Log.info("Calling notification_shutdown()")
        notification_shutdown()
        Log.info("notification_shutdown() completed")
        Log.info("Calling rumps.quit_application()")
        rumps.quit_application()
        Log.info("rumps.quit_application() returned")

    def _process_capture_async(self, image, context):
        """Process captured screenshot in background thread."""
        try:
            Log.info("Processing captured image with LLM (async thread)")
            notification_on_llm_processing_start()
            llm_client = get_llm_client()
            vision_event = llm_client.extract_event(image, context)

            if vision_event is None:
                Log.warn("LLM did not extract an event from image")
                Log.kv({"stage": "menu_action", "result": "no_event_extracted"})
                notification_on_llm_complete(False)
                return

            Log.info("Normalizing event data")
            normalized_event = normalize(vision_event)

            if normalized_event is None:
                Log.error("Failed to normalize event")
                Log.kv({"stage": "menu_action", "result": "normalization_failed"})
                notification_on_llm_complete(False)
                return

            notification_on_llm_complete(True)

            Log.info("Creating calendar event")
            result = create_calendar_event(normalized_event)

            use_google_calendar = os.environ.get("USE_GOOGLE_CALENDAR", "").lower() in ("1", "true", "yes")
            calendar_type = "apple"
            ics_path: Optional[str] = None

            if result is None:
                if use_google_calendar:
                    Log.info("Event processing complete - Google Calendar URL opened")
                    calendar_type = "google"
                else:
                    Log.error("Failed to create calendar event")
                    Log.kv({"stage": "menu_action", "result": "calendar_event_failed"})
                    update_notification(
                        "Unable to open calendar event",
                        timeout=2.5,
                    )
                    return
            else:
                Log.info(f"Event processing complete - ICS saved to: {result}")
                ics_path = str(result)

            success_kv = {
                "stage": "menu_action",
                "result": "success",
                "event_title": normalized_event.title,
                "calendar_type": calendar_type,
                "start_time": normalized_event.start_time.isoformat(),
            }
            if ics_path is not None:
                success_kv["ics_path"] = ics_path
            Log.kv(success_kv)
        except Exception as exc:
            Log.error(f"Unexpected error during capture processing: {exc}")
            Log.kv({
                "stage": "menu_action",
                "result": "processing_exception",
                "error": str(exc),
            })
            notification_on_llm_complete(False)
            update_notification("An error occurred while processing", timeout=3.0)

