# Initialization Prompt for ScreenCal4

Copy and paste this entire prompt into Cursor to start building the Python-based macOS menu bar app:

---

PHASE 0: Tooling & Logging Setup

I want to create a Python-based macOS menu bar app for extracting calendar events from screenshots. Start with Phase 0: setup and tooling.

**Project Requirements:**
- Python 3.9+ with `rumps` for menu bar interface
- Location: `/Users/hemantbothra/Documents/Local Projects/ScreenCal_Attempt4`
- Follow the architecture rules in `.cursor/erules/`
- logging in Terminal and using python's logging module. Log file should be named according to dateandtimestamp (all output to stdout)

**Phase 0 Scope:**
1. Create project structure (src/, tests/)
2. Create `requirements.txt` with dependencies:
   - `rumps` (menu bar app)
   - `pyautogui` or `mss` (screen capture)
   - `pillow` (image handling)
   - `requests` (OpenAI API)
   - `python-dotenv` (environment variables)
   - `pytest` (testing)
3. Create `Makefile` with targets:
   - `make build` - install dependencies
   - `make run` - run the app
   - `make test` - run tests
   - `make clean` - clean build artifacts
4. Create `src/logging_helper.py` with logging module:
   - `Log.section(title)` - prints blank line + `===== TITLE =====`
   - `Log.info(message)` - prints `[INFO] message`
   - `Log.warn(message)` - prints `[WARN] message`
   - `Log.error(message)` - prints `[ERROR] message`
   - `Log.kv(pairs)` - prints `[KV] key=value | key2=value2`
5. apiKey can be accessed from ~/.zshrc and stored in .env for this project
6. Create `README.md` with setup instructions

**Allowed files to create/modify:**
- `requirements.txt`
- `Makefile`
- `src/logging_helper.py`
- `src/__init__.py`
- `tests/__init__.py`
- `README.md`
- `.env.example`

**Forbidden changes:**
- Do NOT create any other modules yet (wait for Phase 1)
- Do NOT add any app logic or capture code
- Do NOT run or test anything beyond `make build`

**Critical Requirements:**
- Makefile should use `python3` explicitly
- Logging module should be importable: `from src.logging_helper import Log`
- Environment variables should use `python-dotenv` to load from `.env` file

**Deliverables:**
- Project structure created
- `make build` installs all dependencies successfully
- `make run` shows app skeleton (even if it exits immediately)
- Logging module works when imported and called
- All logs visible in terminal

**When done:**
- STOP. Do not proceed to Phase 1.
- Output summary: files created + `make build` works.

---

