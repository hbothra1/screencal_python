# Crash-Fix Plan for Segmentation Fault (Error 139)

This plan lays out **four hypotheses** for the persistent seg-fault seen when running `python3 -m src.app` and quitting the menu-bar app.  For each hypothesis we specify diagnostics, an incremental code change, and a verification step.  We will apply fixes **one-at-a-time** and only keep them if the fault disappears.

---

## Environment prerequisites
* Rebuild any C caches: `python3 -m pip install --upgrade pyobjc` (ensure latest stable).
* Ensure we are testing with **USE_STUB=1** (no network) and **macOS Sonoma 14+**.
* Logging level already at **INFO**; for deep dives we enable **DEBUG** via env: `SCREENCAL_LOG_LEVEL=DEBUG`.

---

## Hypothesis 1 – Residual NSTimer / NSAnimationContext after shutdown
Seg-fault may arise if an NSTimer or animation callback fires *after* NSApplication teardown.

### Diagnostics
1. Temporarily add `objc_setHook_getException()` catcher to log any Obj-C exceptions (PyObjC test helper).
2. Turn on `NSZombiesEnabled=YES` via launchd to detect over-released objects.

### Fix-Step 1
* In `notifications.py` add global list `_ACTIVE_APPKIT_TIMERS` storing every NSTimer we create; iterate and invalidate them in `notification_shutdown()` **before** setting `_SHUTTING_DOWN`.

### Verification
* Run app, capture, quit.  If no segfault → keep code.  Else rollback.

---

## Hypothesis 2 – Background thread accessing AppKit after quit
The Calendar opener thread or other background pieces might still call into AppKit after shutdown.

### Diagnostics
* Add `threading.excepthook` and log thread names right before segfault via `faulthandler.register(signal.SIGUSR2, ...)`.

### Fix-Step 2
* Guard every AppKit call in background threads with `if not _SHUTTING_DOWN` check.
* As an experiment, disable Calendar-opener thread (mock `subprocess.run(['open', ...])`).

### Verification
* Re-run.  If segfault disappears only when Calendar thread disabled → root cause confirmed.

---

## Hypothesis 3 – PyObjC class re-registration conflict
Stack trace earlier showed `objc_class_register` and `NSMapInsert notAKeyMarker`; may be duplicate subclass names created every run (memory corruption on quit).

### Diagnostics
* Search for dynamic subclass creation (e.g., `class NotificationWindow(NSObject): ...`) inside loops.
* Count address of class pointer before/after multiple capture cycles.

### Fix-Step 3
* Replace dynamic inner classes with module-level singletons, ensure `objc.registerMetaDataForSelector()` only executed once.

### Verification
* Run 5 capture cycles, quit.  No segfault ⇒ keep change.

---

## Hypothesis 4 – Rumps / NSStatusItem lifetime mismatch
Rumps may destroy NSMenu objects on quit while our callbacks still reference them.

### Diagnostics
* Build minimal reproduction using plain rumps with no extra threads; if still crashes, rumps bug.
* Use `DYLD_PRINT_STATISTICS=1` to see dealloc order.

### Fix-Step 4
* Switch from `rumps.quit_application()` to calling `NSApp.terminate_(None)` directly **after** setting `_SHUTTING_DOWN` and invalidating timers.
* Alternatively, patch rumps catchpoint to ignore SIGABRT.

### Verification
* Run, quit.  Check.

---

## Execution order
1. Implement **Fix-Step 1**, test.
2. If crash persists implement **Fix-Step 2**, test.
3. … continue in order.

At each stage commit with message `crash-fix/H< N >` and tag log.

---

Once the segfault is eliminated we will clean stale diagnostics and keep only necessary changes.
