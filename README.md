# ScreenCal4 - Python macOS Menu Bar App

A Python-based macOS menu bar application that extracts calendar events from screenshots using multimodal AI.

## 🎯 Project Goals

- Extract calendar event details from WhatsApp screenshots
- Create iCal (.ics) files for calendar integration
- macOS menu bar app (no window, just menu bar icon)
- One-shot permission handling (no repeated prompts)
- Terminal-first logging for debugging

## 🚀 Quick Start

### Step 1: Initialize Phase 0

Open the file `INIT_PROMPT.md` and copy its contents into Cursor. This will set up:
- Project structure
- Python dependencies
- Logging module
- Makefile for build/run

### Step 2: Initialize Phase 1

After Phase 0 completes, use `PHASE1_PROMPT.md` to implement:
- Permission handling (one-shot, cached)
- Screen capture module
- Menu bar app interface

### Step 3: Continue with Phases 2-5

Follow the phase structure defined in `.cursor/erules/phase-rules.mdc`:
- Phase 2: Router & Processing
- Phase 3: ICS Generation
- Phase 4: Notifications
- Phase 5: Hotkey Support

## 🔧 Makefile Commands

The project includes a Makefile with the following targets and flags:

### Available Targets

- **`make build`** - Install and upgrade dependencies
  - Upgrades pip and installs all packages from `requirements.txt`

- **`make run`** - Run the application
  - Supports optional flags for different execution modes (see Flags below)

- **`make test`** - Run the test suite
  - Executes pytest with verbose output

- **`make clean`** - Clean up generated files
  - Removes `__pycache__` directories, `.pyc` files, and `.DS_Store` files

### Run Flags

The `make run` target accepts the following flags:

- **`GOOGLE_CAL=1`** - Enable Google Calendar integration
  ```bash
  make run GOOGLE_CAL=1
  ```

- **`STUB=1`** - Enable stub mode (uses mock/stub implementations)
  ```bash
  make run STUB=1
  ```

- **`STUB=noevent`** - Enable stub mode with no event (for testing empty responses)
  ```bash
  make run STUB=noevent
  ```

### Flag Combinations

Flags can be combined:

- **Run with Google Calendar and stub mode:**
  ```bash
  make run GOOGLE_CAL=1 STUB=1
  ```

- **Run with Google Calendar and no-event stub:**
  ```bash
  make run GOOGLE_CAL=1 STUB=noevent
  ```

- **Run without any flags (default mode):**
  ```bash
  make run
  ```

## 📋 Key Documents

- **`INIT_PROMPT.md`** - Copy-paste prompt to start Phase 0
- **`PHASE1_PROMPT.md`** - Copy-paste prompt to start Phase 1
- **`PERMISSIONS_STRATEGY.md`** - Explains one-shot permission handling
- **`.cursor/erules/`** - Architecture and development rules

## 🔑 Critical: Permission Handling

This project fixes the repeated permission prompt issue from the Swift version:

- ✅ Permissions checked **once** at startup
- ✅ Result **cached** in memory
- ✅ **Never** prompts again in the same session
- ✅ Graceful failure if denied

See `PERMISSIONS_STRATEGY.md` for implementation details.

## 🏗️ Architecture

Follow the rules in `.cursor/erules/architecture-rules.mdc`:
- No OCR (only Image LLM)
- LLM boundary (all calls through ImageLLMClient)
- Feature flags (default to stub, explicit for real provider)
- Frontmost window capture only
- RFC5545 ICS format (UTC times)

## 🛠️ Technology Stack

- **Python 3.9+** - Language
- **rumps** - macOS menu bar app framework
- **pyautogui** / **mss** - Screen capture
- **pillow** - Image handling
- **requests** - HTTP/API calls
- **python-dotenv** - Environment variables
- **pytest** - Testing

## 📝 Development Workflow

1. **Start with Phase 0**: Run `INIT_PROMPT.md` content in Cursor
2. **Continue Phase by Phase**: Follow phase rules strictly
3. **Test Each Phase**: Ensure deliverables complete before moving on
4. **Follow Logging Rules**: All logs to stdout (terminal-first)
5. **Respect Phase Boundaries**: Only modify allowed files per phase

## 📁 Project Structure (Target)

```
ScreenCal_Attempt4/
├── .cursor/
│   └── erules/          # Architecture & phase rules
├── src/
│   ├── app.py           # Menu bar app entry
│   ├── logging_helper.py
│   ├── permissions.py   # One-shot permission check
│   ├── frontmost_capture.py
│   ├── statusbar_controller.py
│   ├── app_router.py
│   ├── screen_cal_processor.py
│   ├── image_llm_client.py
│   ├── event_models.py
│   ├── event_normalizer.py
│   ├── calendar_connector.py
│   └── notifications.py
├── tests/
│   └── test_*.py
├── requirements.txt
├── Makefile
├── .env.example
└── README.md
```

## 🧪 Testing

- Unit tests with pytest
- Test permission caching (only checks once)
- Test capture returns context or logs error
- Test router detects WhatsApp correctly

## 📄 License

MIT

---

**Ready to start?** Open `INIT_PROMPT.md` and copy its contents into Cursor to begin!
