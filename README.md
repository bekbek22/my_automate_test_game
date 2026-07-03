# CookieRun Automation — Local Developer Guide

An ADB-driven automation framework for **CookieRun** running on the **MuMu emulator**
(default endpoint `127.0.0.1:16384`). It drives a full game loop through an explicit
state machine, plays recorded input macros, detects screen state via a vectorized
vision layer, and solves the in-game "find the card" verification inline.

This document is the **local developer environment** reference: how to set up a
clean Python environment, where the external binaries go, and how to run the local
test harness we use for profiling, optimization, and architecture regression testing.

> **Scope:** local development and profiling on your own machine. No packaging or
> redistribution is covered here.

---

## 1. Architecture at a glance

```
app_gui.py            tkinter control panel — configure, start/stop, live log viewer
      │  (sets module config, runs the orchestrator on a background thread)
      ▼
main_automation.py    State-machine orchestrator (the core)
      │   MAIN_MENU → BEFORE_START → PLAYING → [CAPTCHA] → GAME_OVER → OPEN_BOX → LEVEL_UP → …
      │   • background watchdog thread  (screen sampling, decoupled from the macro)
      │   • inline captcha solver        (reuses find_the_card's CV engine)
      │   • vectorized detection         (NumPy zero-copy frame views)
      ▼
adb_macro_manager.py  ADB service layer + raw RGBA Screenshot + persistent ppadb socket
test_macro_io.py      Semantic macro record/playback engine (jump / slide / boost)
vision_trigger.py     Closed-loop vision reflex + color detection helpers
find_the_card.py      "Find the card" CV solver (OCR + grid fingerprinting)
```

| File | Role |
|------|------|
| `main_automation.py` | State-machine orchestrator; watchdog thread; inline captcha solve; `--self-check` harness |
| `adb_macro_manager.py` | `Adb` layer (persistent ppadb + subprocess fallback), `Screenshot` (raw RGBA) |
| `test_macro_io.py` | Records/plays semantic gameplay macros (absolute scheduling) |
| `vision_trigger.py` | Vision-reflex engine + `region_color_ratio` / captcha color helpers |
| `find_the_card.py` | Captcha CV engine (Tesseract OCR trigger + card grid solver) |
| `app_gui.py` | Zero-config tkinter panel with the live log viewer |
| `sample_color.py`, `calibrate.py` | Region color/threshold calibration utilities |

---

## 2. Local environment setup

**Target:** Python **3.12** on Windows (developed/verified on 3.12.10).

### 2.1 Virtual environment

From the project root (`D:\detection`):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### 2.2 Python packages

```powershell
pip install numpy opencv-python pytesseract pure-python-adb pynput
```

| Package | Import | Used by | Purpose |
|---|---|---|---|
| `numpy` | `numpy` | orchestrator, vision, solver | zero-copy frame views; vectorized color checks |
| `opencv-python` | `cv2` | `find_the_card` | captcha grid CV / OCR preprocessing |
| `pytesseract` | `pytesseract` | `find_the_card` | Python binding to the Tesseract engine |
| `pure-python-adb` | `ppadb` | `adb_macro_manager`, `find_the_card` | persistent adb-server socket (no per-call process spawn) |
| `pynput` | `pynput` | `test_macro_io` | global keyboard hook for macro recording |

`tkinter` (the GUI) ships with the standard python.org 3.12 installer — no pip
needed. If `import tkinter` fails, re-run the installer and enable **"tcl/tk and IDLE."**

> A pinned `requirements.txt` can be generated from the active venv with
> `pip freeze > requirements.txt` if you want reproducible installs.

---

## 3. External binaries & paths

### 3.1 Tesseract-OCR

`find_the_card.py` looks for the engine at the **default install location**:

```
C:\Program Files\Tesseract-OCR\tesseract.exe
```

Install the UB-Mannheim Tesseract build to that path and it is picked up
automatically (`pytesseract.pytesseract.tesseract_cmd` is set to it when present).
Expected layout:

```
C:\Program Files\Tesseract-OCR\
├── tesseract.exe
└── tessdata\        (eng.traineddata, …)
```

Verify: `& "C:\Program Files\Tesseract-OCR\tesseract.exe" --version`

### 3.2 ADB (platform-tools)

`Adb.connect()` shells out to `adb`, so `adb.exe` must be **on `PATH`**:

```powershell
adb version        # prints a version, not "not recognized"
```

If missing, unzip Google **platform-tools** to a stable folder (e.g.
`C:\platform-tools\`) and add it to `PATH`.

### 3.3 Emulator / ADB wiring

The config targets MuMu at **`127.0.0.1:16384`** (`Config.serial`); the persistent
ppadb client connects to the adb **server** on **`127.0.0.1:5037`**. Start MuMu
first, then:

```powershell
adb connect 127.0.0.1:16384
adb devices        # must list  127.0.0.1:16384   device
```

If your MuMu ADB port differs, update `adb_port` in `adb_macro_manager.py` and
`find_the_card.py`.

> There are **no bundled asset/icon files** — the GUI is pure tkinter and detection
> templates are captured live at runtime.

---

## 4. Local test harness (no emulator required)

The regression/architecture harness runs the real state machine against a mock
device — pure logic + NumPy parity, ~1 second, exit code `0` on success:

```powershell
python main_automation.py --self-check
```

It currently runs **13 checks** across these scenarios:

| Scenario | What it verifies |
|---|---|
| **A** Golden pipeline | Full backbone `MAIN_MENU → … → MAIN_MENU` is reachable |
| **B** Captcha handoff | Watchdog detect → macro killed → input purge → inline solve → resume |
| **C** Mutual exclusion | Captcha OCR suppresses a false Game Over on the same frame |
| **D** Confirm-retry | Captcha OCR retried before conceding Game Over |
| **H** Clutch save | Flaky OCR (miss ×3, hit on 4th) still catches the captcha, early-exits |
| **N** NumPy parity | Vectorized `_region_color_ratio` is **bit-exact** vs the pixel-loop reference |

Use this as the fast inner loop after any change to the state machine, detection,
or hot-path math.

---

## 5. Running the app & tools (emulator connected)

```powershell
# GUI control panel (configure, start/stop, live log)
python app_gui.py

# Orchestrator directly (mode/flags set at the top of main_automation.py)
python main_automation.py

# Live vision/OCR-region calibration readout
python vision_trigger.py calibrate

# Record a macro (focus MuMu; press Q/Esc to stop) then replay it
python test_macro_io.py record
python test_macro_io.py play session.json
```

**Confirm the persistent-ADB fast path is active:**

```powershell
python -c "from adb_macro_manager import Adb, Config; a=Adb(Config()); a.connect(); s=a.screenshot(); print(s.width, s.height, len(s.data))"
```

Sane dimensions (e.g. `1600 900 5760008`) mean the ppadb socket screencap works.
Kill-switch: set `USE_PERSISTENT_ADB = False` in `adb_macro_manager.py` to force the
original subprocess path.

---

## 6. Performance notes (local profiling)

Optimizations validated by the harness and micro-benchmarks:

- **Persistent ppadb connection** — talks to the adb server over a socket per
  command instead of fork+exec'ing `adb.exe` each call; raw `exec:screencap`
  preserves the RGBA framebuffer (no PNG decode). Auto-falls back to subprocess.
- **NumPy hot path** — `_region_color_ratio` and the captcha-region fingerprint use
  zero-copy `np.frombuffer` views + vectorized masks. Measured **~13.6× faster**
  than the per-pixel loop (2.15 ms → 0.16 ms), bit-exact.
- **Smart OCR cache** — the 5 Hz watchdog reuses the last Tesseract verdict while
  the banner region is unchanged and within TTL, skipping OCR on static frames.
- **Threaded watchdog** — screen sampling runs on a daemon thread, decoupled from
  the macro subprocess so detection cadence is never starved.

---

## 7. Configuration quick reference

Top of `main_automation.py`:

```python
MODE = "FULL_AUTO"            # or "CAPTCHA_ONLY"
PLAYING_MODE = "macro"        # or "long_run"
USE_VISION_REFLEX = False     # closed-loop pixel reflex vs recorded macro
MAX_CYCLES = -1               # full game-loop cycles before stopping (-1 = infinite)
buy_boost_start = True
buy_relay_character = False
roll_random_buff = True
```

Top of `adb_macro_manager.py`:

```python
USE_PERSISTENT_ADB = True     # persistent ppadb socket (fast) vs subprocess fallback
```

---

## Quick sanity sequence

```powershell
.\.venv\Scripts\Activate.ps1
python main_automation.py --self-check          # 13/13, no device
adb connect 127.0.0.1:16384 ; adb devices       # attach MuMu
python -c "from adb_macro_manager import Adb, Config; a=Adb(Config()); a.connect(); print(a.screenshot().width)"
python app_gui.py
```
