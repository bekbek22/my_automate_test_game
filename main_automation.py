
from __future__ import annotations

import os
import random
import subprocess
import sys
import threading
import time
from enum import Enum, auto
from typing import Callable, Dict, Optional

from adb_macro_manager import (
    Config as AdbConfig,
    Adb,
    Screenshot,
)



MODE = "FULL_AUTO"

PLAYING_MODE = "macro"

USE_VISION_REFLEX = False



buy_boost_start = True
buy_relay_character = False
roll_random_buff = True

long_run_boost_enabled = True
long_run_relay_enabled = True



MACRO_SESSION_FILE = "session.json"


MACRO_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "test_macro_io.py")
MACRO_WATCH_INTERVAL_S = 0.2

DEBUG_LOG_FILE = "automation_debug.log"

MAX_CYCLES = -1

BOX_ANIM_MIN_S = 3.0
BOX_ANIM_MAX_S = 5.0

STOP_BUTTON_REGION = (1171, 807, 262, 61)
STOP_VANISH_MAE_THRESH = 8.0
STOP_POLL_INTERVAL_S = 0.4
STOP_FAST_POLL_S = 0.05
STOP_TIMEOUT_S = 20.0

RESULT_REGION = (523, 43, 556, 99)
MYSTERY_BOX_REGION = (592, 50, 431, 103)
MYSTERY_BOX_TEXT = "mystery box"       # OCR needle gating the open-box phase
BOX_DETECT_TIMEOUT_S = 3.0             # how long to look for the box before skipping
BUY_UPGRADES_REGION = (192, 119, 270, 43)
BUY_UPGRADES_TARGET_RGB = (224, 224, 224)

RESULT_COLOR_REGION = (669, 55, 262, 70)
RESULT_TARGET_RGB = (255, 205, 0)
RESULT_COLOR_TOLERANCE = 15
RESULT_REQUIRED_RATIO = 0.15

CAPTCHA_CONFIRM_ATTEMPTS = 5
CAPTCHA_CONFIRM_GAP_S = 0.02

CAPTCHA_OCR_REGION = (492, 43, 722, 71)
CAPTCHA_CACHE_TTL_S = 0.5
CAPTCHA_CACHE_STRIDE = 8

# Boost/Relay support-icon region (Long Run boost reflex uses its blue-pixel density).
BONUS_ICON_REGION = (725, 334, 183, 188)
REFLEX_TARGET_BLUE = (32, 74, 124)          # Long Run boost-icon colour signature
REFLEX_TOLERANCE = 50
REFLEX_REQUIRED_RATIO = 0.05
BOOST_SLOT_CLICK = (816, 428)

# Relay/revive trigger (BOTH modes): the "Tap to activate Cookie Relay Boost!" banner.
# Detected by OCR text (contains "relay") -- far more reliable than icon matching,
# which false-fired on the boost pet during normal play. On a hit we tap the relay
# slot ONCE per run (gated by the Enable Relay toggle). In Macro mode this is the
# only thing the watchdog taps (the recorded macro owns the initial boost).
RELAY_PROMPT_REGION = (478, 277, 664, 38)   # (x, y, w, h) of the banner text
# "Tap to activate Cookie Relay Boost!" -- match only words UNIQUE to the relay
# banner. NOT "activate"/"boost": the initial-boost banner "Tap to activate Fast
# Start Boost!" shares those, and matching it would burn the one-shot relay flag
# at t=0 so the real relay never fires. "relay"/"cookie" appear only here.
RELAY_PROMPT_KEYWORDS = ("relay", "cookie")
RELAY_OCR_INTERVAL_S = 0.6                   # throttle Tesseract in the 5 Hz watchdog
RELAY_DEBUG_OCR = False                       # set True to log the raw OCR read each check (tuning)
RELAY_ACTIVATE_COORD = BOOST_SLOT_CLICK      # relay activates at the SAME slot as boost_start (816,428)
# Macro pause/resume handshake (cwd-relative files, shared with test_macro_io.py).
# During the relay banner the game freezes, so we pause the macro (stop its tap
# flood + freeze its timeline), tap relay cleanly, then resume it aligned.
MACRO_PAUSE_FLAG = "macro_pause.flag"
MACRO_PAUSE_ACK = "macro_paused.ack"

GAMEPLAY_MOTION_REGION = (300, 500, 300, 300)
GAMEPLAY_ACTIVE_MAE = 15.0

LEVEL_UP_DETECTION_REGION = (627, 61, 349, 84)
LEVEL_UP_CLICK_REGION = (642, 747, 316, 96)
LEVEL_UP_CLICK = (800, 795)

REGION_CONGRATS_TEXT = (481, 135, 635, 82)
CONGRATS_TARGET_RGB = (248, 226, 107)
CONGRATS_COLOR_TOLERANCE = 25
CONGRATS_REQUIRED_RATIO = 0.15
CONGRATS_CONFIRM = (799, 707)

# Main-menu gate. The ticket badge region is the MAIN_MENU state anchor (template
# match of the red diamond/chain icon at assets/tickets_base.png). Degrades
# gracefully if cv2/the asset are missing (anchor 'n/a' -> falls through to OCR).
MAIN_MENU_TICKET_REGION = (571, 97, 156, 81)   # (x, y, w, h) -- anchor only
TICKET_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets", "tickets_base.png")
TICKET_MATCH_THRESHOLD = 0.75                   # cv2 matchTemplate confidence

# "Get!" reward-claim flow (replaces the old "x/3" number parsing). When the red
# "Get!" balloon is present on the main menu, run a strict tap sequence to claim
# the reward, then return to MAIN_MENU. All four targets are (x, y, w, h) regions;
# each tap lands on the region CENTER.
TICKET_GET_REGION = (577, 84, 148, 94)         # red "Get!" balloon + "x/x" count (OCR + tap)
CONGRATS_REGION = (669, 688, 259, 71)          # "Congratulations!" popup (tap + OCR)
REWARD_TAP_COORDS = (641, 671, 316, 88)        # collect-reward button region
CLOSE_MENU_COORDS = (1320, 168, 49, 46)        # close-menu (X) button region
CONGRATS_POLL_TIMEOUT_S = 5.0                  # max wait for "Congratulations!" text

COORDS: Dict[str, tuple[int, int]] = {
    "play_button":      (1191, 806),
    "boost_item":       (282, 745),
    "relay_item":       (475, 746),
    "buy_button":       (1150, 363),
    "buff_slot":        (667, 745),
    "multi_buy":        (1371, 246),
    "buff_confirm":     (793, 735),
    "game_start":       (1118, 765),
    "boost_slot":       BOOST_SLOT_CLICK,
    "game_over_ok":     (579, 770),
    "open_all_button":  (805, 795),
    "level_up_dismiss": LEVEL_UP_CLICK,
    "congrats_confirm": CONGRATS_CONFIRM,
}



class State(Enum):
    MAIN_MENU = auto()
    BEFORE_START = auto()
    PLAYING = auto()
    CAPTCHA = auto()
    GAME_OVER = auto()
    OPEN_BOX = auto()
    LEVEL_UP = auto()
    CONGRATS = auto()


CONGRATS_SCAN_STATES = frozenset({
    State.MAIN_MENU, State.BEFORE_START, State.GAME_OVER,
    State.OPEN_BOX, State.LEVEL_UP,
})



class Orchestrator:

    def __init__(self, mode: str = MODE):
        self.mode = mode
        self.playing_mode = PLAYING_MODE
        self.long_run_boost_enabled = long_run_boost_enabled
        self.long_run_relay_enabled = long_run_relay_enabled
        self.adb_cfg = AdbConfig()
        self.adb = Adb(self.adb_cfg)
        self.running = True

        self.completed_runs = 0
        self.on_run_complete = None

        # One-shot guard: relay/revive fires at most once per run. Reset at the
        # start of every run (macro: _run_macro_subprocess; long_run: _monitor_match).
        self._relay_used = False

        self._init_debug_log()

        self.handlers: Dict[State, Callable[[], State]] = {
            State.MAIN_MENU:    self.handle_main_menu,
            State.BEFORE_START: self.handle_before_start,
            State.PLAYING:      self.handle_playing,
            State.CAPTCHA:      self.handle_captcha,
            State.GAME_OVER:    self.handle_game_over,
            State.OPEN_BOX:     self.handle_open_box,
            State.LEVEL_UP:     self.handle_level_up,
            State.CONGRATS:     self.handle_congrats,
        }


    def _init_debug_log(self) -> None:
        try:
            with open(DEBUG_LOG_FILE, "w", encoding="utf-8") as fh:
                fh.write(f"# automation_debug.log -- session start "
                         f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        except OSError:
            pass

    def log(self, state: State, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {state.name:<13} {msg}"
        print(line)
        try:
            with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def tap(self, name: str) -> None:
        x, y = COORDS[name]
        self._tap_xy(x, y)

    def _tap_xy(self, x: int, y: int) -> None:
        offset_x = random.randint(-8, 8)
        offset_y = random.randint(-8, 8)
        self.adb.shell("input", "tap", str(int(x) + offset_x), str(int(y) + offset_y))

    @staticmethod
    def _region_center(region) -> "tuple[int, int]":
        x, y, w, h = region
        return (x + w // 2, y + h // 2)

    def _tap_region_center(self, region) -> None:
        cx, cy = self._region_center(region)
        self._tap_xy(cx, cy)

    def sleep_human(self, base_s: float) -> None:
        self._sleep_responsive(base_s)

    def _sleep_responsive(self, seconds: float) -> None:
        if seconds >= 0.5:
            seconds = max(0.0, seconds + random.uniform(-0.15, 0.30))
        else:
            seconds = max(0.0, seconds + random.uniform(-0.02, 0.05))
        end = time.monotonic() + seconds
        while self.running:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.1, remaining))

    def _throttle(self) -> None:
        self._sleep_responsive(1.0)


    def _ticket_template(self):
        """Cached grayscale template for the MAIN_MENU ticket anchor, or None if
        cv2/the asset is unavailable (-> anchor degrades to 'n/a')."""
        if getattr(self, "_ticket_tmpl_cache", "unset") == "unset":
            self._ticket_tmpl_cache = None
            try:
                import cv2
                if os.path.exists(TICKET_TEMPLATE_PATH):
                    self._ticket_tmpl_cache = cv2.imread(TICKET_TEMPLATE_PATH,
                                                         cv2.IMREAD_GRAYSCALE)
                else:
                    self.log(State.MAIN_MENU,
                             f"ticket template missing: {TICKET_TEMPLATE_PATH}")
            except Exception as exc:
                self.log(State.MAIN_MENU, f"ticket template load error: {exc}")
        return self._ticket_tmpl_cache

    def _match_main_menu_anchor(self, shot) -> float:
        """OpenCV template match of the ticket icon within MAIN_MENU_TICKET_REGION.
        Returns the best match confidence (0..1), or -1.0 if it can't run
        (missing cv2/template) so callers treat it as 'unknown', not 'no match'."""
        try:
            import cv2
            tmpl = self._ticket_template()
            if tmpl is None:
                return -1.0
            x, y, w, h = MAIN_MENU_TICKET_REGION
            roi = self._shot_to_bgr(shot)[y:y + h, x:x + w]
            roi_g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            if tmpl.shape[0] > roi_g.shape[0] or tmpl.shape[1] > roi_g.shape[1]:
                return -1.0                          # template bigger than ROI
            res = cv2.matchTemplate(roi_g, tmpl, cv2.TM_CCOEFF_NORMED)
            return float(res.max())
        except Exception as exc:
            self.log(State.MAIN_MENU, f"anchor match error: {exc}")
            return -1.0

    def _relay_prompt_present(self, shot) -> bool:
        """True when the 'Tap to activate Cookie Relay Boost!' banner is on screen.
        OCR of RELAY_PROMPT_REGION (psm 7, no whitelist) matched against ANY of
        RELAY_PROMPT_KEYWORDS so one misread word doesn't drop the detection.
        Reliable relay/revive trigger for BOTH Macro and Long Run; False if the
        text is absent or the OCR stack is unavailable."""
        # Single normal-polarity pass: relay_probe verified this reads the banner
        # cleanly ("Tap to activate Cookie Relay Boost!"), so one OCR keeps the
        # watchdog fast enough not to miss the brief (~3 s) window.
        txt = self._ocr_region_text(shot, RELAY_PROMPT_REGION, upscale=3)
        low = (txt or "").lower()
        hit = any(kw in low for kw in RELAY_PROMPT_KEYWORDS)
        if RELAY_DEBUG_OCR:
            self.log(State.PLAYING, f"[relay-ocr] read={txt!r} -> {hit}")
        return hit

    def _activate_relay(self) -> None:
        """Activate the Relay Boost by tapping the slot ('Tap to activate ...').

        In MACRO mode the recorded macro floods ADB with `input tap` commands, so
        our relay tap would queue behind them and land after the banner closes.
        The game FREEZES during the banner, so we PAUSE the macro (stops the flood
        + freezes its timeline), tap relay cleanly, then RESUME it aligned."""
        macro = self.playing_mode == "macro"
        if macro:
            self._pause_macro()             # stop the tap flood + freeze timeline
            self._purge_adb_input_buffer()  # clear any last in-flight taps
        cx, cy = RELAY_ACTIVATE_COORD
        self._tap_xy(cx, cy)                # single tap: the game freezes & waits,
                                            # so one tap activates it; a 2nd tap would
                                            # land on the just-unfrozen 2nd runner
        if macro:
            self._resume_macro()            # unfreeze; macro continues where it left off

    def _pause_macro(self) -> None:
        """Raise the pause flag and wait (bounded) for the macro to acknowledge it
        has stopped, so the relay tap isn't fighting the macro's tap flood."""
        try:
            open(MACRO_PAUSE_FLAG, "w").close()
        except OSError as exc:
            self.log(State.PLAYING, f"macro pause flag error: {exc}")
            return
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if os.path.exists(MACRO_PAUSE_ACK):
                self.log(State.PLAYING, "macro paused for relay")
                return
            time.sleep(0.02)
        self.log(State.PLAYING, "macro pause ack timed out -- proceeding anyway")

    def _resume_macro(self) -> None:
        try:
            os.remove(MACRO_PAUSE_FLAG)
        except OSError:
            pass
        self.log(State.PLAYING, "macro resumed")

    def _ocr_region_text(self, shot, region, *, whitelist=None, psm=7,
                         upscale=2, invert=False) -> "Optional[str]":
        """Generic region OCR shared by the ticket + mystery-box + relay gates.
        Crops the region, grayscales, upscales (>= 2x), Otsu-binarizes, then runs
        Tesseract. `invert=True` flips the binarization (for light text on a dark
        background, which Tesseract otherwise reads as inverted). Returns the text
        (possibly ''), or None if the OCR stack is unavailable."""
        try:
            import cv2
            import find_the_card as ftc              # configures pytesseract path
            pyt = getattr(ftc, "pytesseract", None)
            if pyt is None:
                return None
            x, y, w, h = region
            gray = cv2.cvtColor(self._shot_to_bgr(shot)[y:y + h, x:x + w],
                                cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=upscale, fy=upscale,
                              interpolation=cv2.INTER_CUBIC)
            thr = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
            gray = cv2.threshold(gray, 0, 255, thr + cv2.THRESH_OTSU)[1]
            cfg = f"--psm {psm}"
            if whitelist:
                cfg += f" -c tessedit_char_whitelist={whitelist}"
            return pyt.image_to_string(gray, config=cfg)
        except Exception as exc:
            self.log(State.MAIN_MENU, f"region OCR error: {exc}")
            return None

    def _mystery_box_present(self, shot) -> bool:
        """True when the OCR of MYSTERY_BOX_REGION contains 'Mystery Box'
        (case-insensitive). False if the text is absent or the OCR stack is
        unavailable, so the open-box phase is skipped rather than tapping blind."""
        txt = self._ocr_region_text(shot, MYSTERY_BOX_REGION)
        return bool(txt) and MYSTERY_BOX_TEXT in txt.lower()

    def _await_text(self, region, needle: str, timeout_s: float) -> bool:
        """Poll OCR of `region` until it contains `needle` (case-insensitive) or
        `timeout_s` elapses. Returns True on match. Used to confirm a popup has
        rendered before acting on it."""
        needle = needle.lower()
        waited = 0.0
        while self.running and waited < timeout_s:
            txt = self._ocr_region_text(self._grab_watchdog_frame(), region)
            if txt and needle in txt.lower():
                return True
            self._sleep_responsive(STOP_POLL_INTERVAL_S)
            waited += STOP_POLL_INTERVAL_S
        return False

    def _get_balloon_present(self, shot) -> bool:
        """True when the red 'Get!' balloon is up in TICKET_GET_REGION (relics
        full). OCR both polarities (white text on a red balloon) at psm 6 since
        the region also spans the 'x/x' count line; match 'get' in either."""
        for inv in (False, True):
            txt = self._ocr_region_text(shot, TICKET_GET_REGION,
                                        upscale=3, psm=6, invert=inv)
            if txt and "get" in txt.lower():
                return True
        return False

    def handle_main_menu(self) -> State:
        self._throttle()
        # OPTIONAL PRE-FLIGHT REWARD CLAIM (non-blocking). When the relics fill up
        # the game shows a red "Get!" balloon; claim it, then re-evaluate. No "Get!"
        # -> fall straight through to the normal game loop (Play -> BEFORE_START).
        # We do NOT gate on the template anchor: handle_main_menu only runs in the
        # MAIN_MENU state and "Get!" is a distinctive word, so gating risked
        # silently blocking the claim when the anchor template matched poorly. The
        # anchor confidence is logged as a hint only.
        shot = self._grab_watchdog_frame()
        conf = self._match_main_menu_anchor(shot)
        if self._get_balloon_present(shot):
            self.log(State.MAIN_MENU,
                     f"'Get!' balloon detected (anchor={conf:.2f}) -> claiming reward")
            return self._claim_get_reward()          # CASE A: claim, then re-evaluate

        self.log(State.MAIN_MENU,
                 f"no 'Get!' balloon (anchor={conf:.2f}) -> clicking play -> prep")
        self.tap("play_button")                      # CASE B: normal game loop
        self.sleep_human(1.5)
        return State.BEFORE_START

    def _claim_get_reward(self) -> State:
        """Strict post-'Get!' claim sequence: tap the balloon, wait for the reward
        popup, confirm 'Congratulations!' via OCR, collect the reward, close the
        menu, and return to MAIN_MENU. Every tap lands on its region center."""
        # a. tap the "Get!" balloon
        self._tap_region_center(TICKET_GET_REGION)
        # b. fixed settle for the reward popup to animate in
        self._sleep_responsive(3.0)
        # c. tap the congrats popup
        self._tap_region_center(CONGRATS_REGION)
        # d. poll until "Congratulations!" is confirmed (bounded)
        if self._await_text(CONGRATS_REGION, "congratulations",
                            CONGRATS_POLL_TIMEOUT_S):
            self.log(State.MAIN_MENU,
                     "'Congratulations!' confirmed -> collecting reward")
            # e. collect the reward (only once the popup is confirmed)
            self._tap_region_center(REWARD_TAP_COORDS)
        else:
            self.log(State.MAIN_MENU,
                     "'Congratulations!' not confirmed within "
                     f"{CONGRATS_POLL_TIMEOUT_S:.0f}s -> skipping reward tap")
        # f. close the menu (always, so we return to a clean main menu)
        self._tap_region_center(CLOSE_MENU_COORDS)
        # g. back to MAIN_MENU
        self.sleep_human(1.0)
        return State.MAIN_MENU

    def handle_before_start(self) -> State:
        self._throttle()

        self.log(State.BEFORE_START, "validating Buy Upgrades! screen (color)")
        present = False
        waited = 0.0
        while self.running and waited < 3.0:
            if self._check_region_color_density(BUY_UPGRADES_REGION,
                                                BUY_UPGRADES_TARGET_RGB,
                                                tolerance=25, required_ratio=0.10):
                present = True
                break
            self._sleep_responsive(STOP_POLL_INTERVAL_S)
            waited += STOP_POLL_INTERVAL_S
        if not present:
            if self._congrats_active():
                return State.CONGRATS
            self.log(State.BEFORE_START,
                     "[GUARD] 'Buy Upgrades!' anchor not confirmed -- proceeding "
                     "anyway (guard non-blocking; calibrate BUY_UPGRADES_TARGET_RGB).")

        if buy_boost_start:
            self.log(State.BEFORE_START, "Step 1: BOOST START -> boost item")
            self.tap("boost_item"); self._sleep_responsive(0.4)

        if buy_boost_start:
            self.log(State.BEFORE_START, "Step 2: BUY -> confirm boost")
            self.tap("buy_button")
            self.log(State.BEFORE_START, "Waiting 3s for purchase to settle...")
            self._sleep_responsive(3.0)

        if buy_relay_character:
            self.log(State.BEFORE_START, "Step 3: RELAY -> relay character")
            self.tap("relay_item"); self._sleep_responsive(0.4)

        if buy_relay_character:
            self.log(State.BEFORE_START, "Step 4: BUY -> confirm relay")
            self.tap("buy_button")
            self.log(State.BEFORE_START, "Waiting 3s for purchase to settle...")
            self._sleep_responsive(3.0)

        if roll_random_buff:
            self.log(State.BEFORE_START, "Step 5: RANDOM_BUFF -> buff slot")
            self.tap("buff_slot"); self.sleep_human(0.4)

        if roll_random_buff:
            self.log(State.BEFORE_START, "Step 6: Multi Buy")
            self.tap("multi_buy"); self.sleep_human(0.4)

        if roll_random_buff:
            self.log(State.BEFORE_START, "Step 7: Multi Buy Confirm")
            self.tap("buff_confirm"); self.sleep_human(0.6)

        if roll_random_buff:
            self.log(State.BEFORE_START, "Step 8a: scanning for STOP button to appear")
            self._await_stop_button_appear()
            self.log(State.BEFORE_START, "Step 8b: scanning for STOP button to vanish")
            self._await_stop_button_vanish()

        self._sleep_responsive(1.0)
        self.log(State.BEFORE_START, "Step 9: PLAY -> match start")
        self.tap("game_start")
        self._sleep_responsive(1.5)
        if self._check_region_color_density(BUY_UPGRADES_REGION,
                                            BUY_UPGRADES_TARGET_RGB,
                                            tolerance=25, required_ratio=0.10):
            self.log(State.BEFORE_START,
                     "[RETRY] Still on Before Start screen after tapping Play! "
                     "Retrying current state...")
            return State.BEFORE_START
        return State.PLAYING

    def handle_congrats(self) -> State:
        self._throttle()
        self.log(State.CONGRATS, "Congratulations pop-up -> confirming")
        self.tap("congrats_confirm")
        self._sleep_responsive(1.5)
        return State.MAIN_MENU

    def handle_playing(self) -> State:
        self._throttle()

        if self.playing_mode == "long_run":
            self.log(State.PLAYING,
                     "Running in Long Run mode (auto boost/relay, no macro)...")
        else:
            self.log(State.PLAYING,
                     f"Running in Macro Play mode: {MACRO_SESSION_FILE}")
            self._await_boost_start(timeout_s=20.0)
            if USE_VISION_REFLEX:
                detected = self._run_vision_reflex()
            else:
                detected = self._run_macro_subprocess()
            if detected is not None:
                self.log(State.PLAYING, f"macro ended on {detected.name} -> routing")
                return detected

        return self._monitor_match()

    def _run_macro_subprocess(self) -> "Optional[State]":
        if not os.path.exists(MACRO_SESSION_FILE):
            self.log(State.PLAYING, f"(no {MACRO_SESSION_FILE} yet -- skipping)")
            return None
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", MACRO_SCRIPT, "play", MACRO_SESSION_FILE],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
        except OSError as exc:
            self.log(State.PLAYING, f"macro launch failed: {exc}")
            return None
        self.log(State.PLAYING,
                 f"macro subprocess launched (pid {proc.pid}) -> background watchdog")

        def _pump_macro_output() -> None:
            try:
                for line in proc.stdout:
                    print(f"[macro] {line}", end="", flush=True)
            except Exception:
                pass
        threading.Thread(target=_pump_macro_output, daemon=True).start()

        self._watchdog_detected = None
        self._relay_used = False           # new run: relay/revive not yet used
        for f in (MACRO_PAUSE_FLAG, MACRO_PAUSE_ACK):   # clear any stale handshake
            try:
                os.remove(f)
            except OSError:
                pass
        stop_evt = threading.Event()
        wd = threading.Thread(target=self._background_watchdog_loop,
                              args=(proc, stop_evt), daemon=True)
        wd.start()

        while (proc.poll() is None and self.running
               and self._watchdog_detected is None):
            time.sleep(0.05)

        stop_evt.set()
        wd.join(timeout=3)
        detected: "Optional[State]" = self._watchdog_detected
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            self._purge_adb_input_buffer()
        if detected is None:
            self.log(State.PLAYING, "macro subprocess ended (clean finish / Stop)")

        if detected is State.CAPTCHA:
            self.log(State.PLAYING,
                     "watchdog handoff -> invoking inline captcha solver NOW")
            self._solve_captcha_inline()
            return self._post_solver_state()
        return detected

    def _png_to_screenshot(self, png: bytes) -> "Screenshot":
        """Decode a PNG framebuffer into a raw-RGBA Screenshot so every existing
        detection helper (_frame_view / _region_color_ratio / _captcha_* ) keeps
        working unchanged on the PNG path."""
        import struct
        import cv2
        import numpy as np
        bgr = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise RuntimeError("PNG decode failed")
        h, w = bgr.shape[:2]
        rgba = np.empty((h, w, 4), np.uint8)
        rgba[:, :, 0] = bgr[:, :, 2]        # R
        rgba[:, :, 1] = bgr[:, :, 1]        # G
        rgba[:, :, 2] = bgr[:, :, 0]        # B
        rgba[:, :, 3] = 255
        return Screenshot.from_raw(struct.pack("<II", w, h) + rgba.tobytes())

    def _grab_watchdog_frame(self) -> "Screenshot":
        """Watchdog frame source: PNG capture (small payload -> frees the shared
        transport for the macro's taps), decoded to a Screenshot. Falls back to
        the raw capture on any error (also the path the mock self-check takes)."""
        try:
            png = self.adb.screencap_png()
            if png:
                return self._png_to_screenshot(png)
        except Exception:
            pass
        return self.adb.screenshot()

    def _background_watchdog_loop(self, proc, stop_evt: "threading.Event") -> None:
        """Macro-mode screen watchdog (5 Hz, PNG frames). The recorded macro owns
        the initial boost; the watchdog does NOT tap boost. Two phases:

          PHASE 1 (before relay) -- watch ONLY for the relay banner:
            * RELAY/REVIVE: when "Tap to activate Cookie Relay Boost!" is detected
              by OCR AND Enable Relay is ON, tap the relay slot ONCE (one-shot
              _relay_used guard; OCR throttled to RELAY_OCR_INTERVAL_S). Keeping
              captcha + game-over OFF here frees screencap/OCR cycles so the early
              macro's taps stay stable.

          PHASE 2 (armed AFTER relay, or immediately if relay is disabled):
            * Captcha (OCR, cached) -> CAPTCHA (terminate, inline solve).
            * RESULT banner (color, captcha-confirm gated) -> GAME_OVER (terminate).
              The run can only truly end here, which is always after the relay.

        If relay is enabled but never appears, PHASE 2 never arms in the watchdog;
        the macro simply finishes and _monitor_match does the end-of-run detection.
        """
        relay_check_at = 0.0
        while (not stop_evt.is_set() and proc.poll() is None and self.running):
            detected = None
            try:
                shot = self._grab_watchdog_frame()      # PNG (raw fallback)

                # ---- PHASE 1: RELAY/REVIVE (the only thing watched pre-relay) ----
                now = time.monotonic()
                if (self.long_run_relay_enabled and not self._relay_used
                        and now >= relay_check_at):
                    relay_check_at = now + RELAY_OCR_INTERVAL_S   # throttle OCR
                    if self._relay_prompt_present(shot):
                        self._activate_relay()
                        self._relay_used = True
                        self.log(State.PLAYING,
                                 "watchdog: Relay Boost activated (banner tap) "
                                 "-> captcha + game-over detection ARMED")

                # ---- PHASE 2: captcha + game-over, ARMED only after relay (or when
                # relay is disabled -> nothing to wait for) ----
                if self._relay_used or not self.long_run_relay_enabled:
                    if self._captcha_active_cached(shot):        # captcha has priority
                        detected = State.CAPTCHA
                    elif (self._region_color_ratio(
                            RESULT_COLOR_REGION, RESULT_TARGET_RGB,
                            RESULT_COLOR_TOLERANCE, shot=shot) >= RESULT_REQUIRED_RATIO):
                        detected = (State.CAPTCHA if self._captcha_confirm()
                                    else State.GAME_OVER)
            except Exception as exc:
                self.log(State.PLAYING, f"watchdog sample error: {exc}")
                detected = None

            if detected is not None:
                self.log(State.PLAYING,
                         f"watchdog: {detected.name} detected -> terminating macro")
                self._watchdog_detected = detected
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                self._purge_adb_input_buffer()
                return
            stop_evt.wait(MACRO_WATCH_INTERVAL_S)

    def _purge_adb_input_buffer(self) -> None:
        try:
            self.adb.shell("pkill", "-f", "com.android.commands.input")
        except Exception as exc:
            self.log(State.PLAYING, f"input purge note: {exc}")
        time.sleep(0.15)

    def _run_vision_reflex(self) -> "Optional[State]":
        import vision_trigger as vt

        self.log(State.PLAYING,
                 "vision reflex: capturing empty-track baseline...")
        baseline = vt.calibrate_baseline(self.adb)

        def _on_event(kind: str, jm: float, sm: float) -> None:
            if kind in (vt.CAPTCHA, vt.GAME_OVER):
                self.log(State.PLAYING, f"vision reflex: end anchor {kind}")
            else:
                self.log(State.PLAYING,
                         f"vision reflex: {kind} (jump={jm:.1f} slide={sm:.1f})")

        self.log(State.PLAYING, "vision reflex active -> watching sensor zones")
        token = vt.reflex_loop(
            self.adb, baseline,
            stop_check=lambda: not self.running,
            on_event=_on_event)

        if token == vt.CAPTCHA:
            return State.CAPTCHA
        if token == vt.GAME_OVER:
            return State.GAME_OVER
        return None

    def _post_solver_state(self) -> State:
        shot = self.adb.screenshot()
        if self._captcha_active(shot):
            self.log(State.CAPTCHA,
                     "post-captcha: captcha STILL up -> resume PLAYING (re-solve via watchdog)")
            return State.PLAYING
        if self._region_color_ratio(RESULT_COLOR_REGION, RESULT_TARGET_RGB,
                                    RESULT_COLOR_TOLERANCE, shot=shot) >= RESULT_REQUIRED_RATIO:
            if self._captcha_confirm():
                self.log(State.CAPTCHA,
                         "post-captcha: captcha re-confirmed -> resume PLAYING (re-solve)")
                return State.PLAYING
            self.log(State.CAPTCHA,
                     "post-captcha screen = RESULT/Game Over -> GAME_OVER")
            return State.GAME_OVER
        self.log(State.CAPTCHA, "post-captcha screen clear -> resume PLAYING")
        return State.PLAYING

    def handle_captcha(self) -> State:
        self._throttle()
        if self._captcha_active():
            self.log(State.CAPTCHA, "pop-up active -> running solver")
            self._solve_captcha_inline()
        else:
            self.log(State.CAPTCHA, "no pop-up -> bypass")

        if self.mode == "CAPTCHA_ONLY":
            self.sleep_human(1.0)
            return State.CAPTCHA
        return self._post_solver_state()

    def handle_game_over(self) -> State:
        self._throttle()
        self.log(State.GAME_OVER, "awaiting RESULT banner (color density)")
        self._await_color_density(RESULT_COLOR_REGION, RESULT_TARGET_RGB,
                                  State.GAME_OVER, "RESULT")
        self.log(State.GAME_OVER, "clicking OK -> reward chest")
        self.tap("game_over_ok")
        self.sleep_human(1.5)
        return State.OPEN_BOX

    def handle_open_box(self) -> State:
        self._throttle()
        # MYSTERY BOX GATE: never tap the open-box coords blind. Confirm the
        # "Mystery Box" title via OCR first; if it never appears within the
        # detect window, skip the whole phase and move on.
        waited = 0.0
        while self.running and waited < BOX_DETECT_TIMEOUT_S:
            if self._mystery_box_present(self._grab_watchdog_frame()):
                self.log(State.OPEN_BOX, "Mystery Box detected -> opening all boxes")
                self.tap("open_all_button")

                wait = random.uniform(BOX_ANIM_MIN_S, BOX_ANIM_MAX_S)
                self.log(State.OPEN_BOX, f"waiting {wait:.1f}s for reward animation")
                self._sleep_responsive(wait)

                self.log(State.OPEN_BOX, "dismissing rewards")
                self.tap("open_all_button")
                self.sleep_human(1.5)
                return State.LEVEL_UP
            self._sleep_responsive(STOP_POLL_INTERVAL_S)
            waited += STOP_POLL_INTERVAL_S

        self.log(State.OPEN_BOX,
                 "[orchestrator] No Mystery Box detected on screen. Skipping box phase.")
        return State.LEVEL_UP

    def handle_level_up(self) -> State:
        self.log(State.LEVEL_UP, "checking for Level Up pop-up")
        waited = 0.0
        while self.running and waited < 2.0:
            if self._check_region_color_density(
                    LEVEL_UP_DETECTION_REGION, RESULT_TARGET_RGB,
                    RESULT_COLOR_TOLERANCE, RESULT_REQUIRED_RATIO):
                self.log(State.LEVEL_UP, "Level Up pop-up detected! Dismissing...")
                self.tap("level_up_dismiss")
                self._sleep_responsive(1.5)
                return State.MAIN_MENU
            self._sleep_responsive(STOP_POLL_INTERVAL_S)
            waited += STOP_POLL_INTERVAL_S

        self.log(State.LEVEL_UP, "No level up screen detected. Moving to main menu.")
        return State.MAIN_MENU


    def _await_stop_button_appear(self, timeout_s: float = STOP_TIMEOUT_S) -> None:
        x, y, w, h = STOP_BUTTON_REGION
        prev: Optional[Screenshot] = None
        deadline = time.monotonic() + timeout_s
        while self.running and time.monotonic() < deadline:
            shot = self.adb.screenshot()
            if prev is not None:
                mae = self._region_mae(prev, shot, x, y, w, h)
                if mae >= STOP_VANISH_MAE_THRESH:
                    self.log(State.BEFORE_START,
                             f"STOP button appeared (MAE={mae:.2f}) -> rolling engaged")
                    return
            prev = shot
            self._sleep_responsive(STOP_FAST_POLL_S)
        self.log(State.BEFORE_START, "STOP appear wait ended -- proceeding")

    def _await_stop_button_vanish(self, timeout_s: float = STOP_TIMEOUT_S) -> None:
        x, y, w, h = STOP_BUTTON_REGION
        prev: Optional[Screenshot] = None
        deadline = time.monotonic() + timeout_s
        while self.running and time.monotonic() < deadline:
            shot = self.adb.screenshot()
            if prev is not None:
                mae = self._region_mae(prev, shot, x, y, w, h)
                if mae < STOP_VANISH_MAE_THRESH:
                    self.log(State.BEFORE_START,
                             f"STOP vanished (MAE={mae:.2f}) -> buff locked")
                    return
            prev = shot
            self._sleep_responsive(STOP_FAST_POLL_S)
        self.log(State.BEFORE_START, "STOP vanish wait ended -- proceeding")

    def _await_region_settled(self, region: tuple, state: State,
                              label: str) -> None:
        x, y, w, h = region
        prev: Optional[Screenshot] = None
        waited = 0.0
        while self.running and waited < STOP_TIMEOUT_S:
            shot = self.adb.screenshot()
            if prev is not None:
                mae = self._region_mae(prev, shot, x, y, w, h)
                self.log(state, f"{label} region MAE={mae:.2f}")
                if mae < STOP_VANISH_MAE_THRESH:
                    self.log(state, f"{label} detected -- region settled")
                    return
            prev = shot
            self._sleep_responsive(STOP_POLL_INTERVAL_S)
            waited += STOP_POLL_INTERVAL_S
        self.log(state, f"{label} wait ended -- proceeding")

    def _await_gameplay_active(self, timeout_s: float = 8.0) -> None:
        x, y, w, h = GAMEPLAY_MOTION_REGION
        prev: Optional[Screenshot] = None
        waited = 0.0
        while self.running and waited < timeout_s:
            shot = self.adb.screenshot()
            if prev is not None:
                mae = self._region_mae(prev, shot, x, y, w, h)
                self.log(State.PLAYING, f"gameplay-active MAE={mae:.2f}")
                if mae >= GAMEPLAY_ACTIVE_MAE:
                    self.log(State.PLAYING, "gameplay active -> starting macro")
                    return
            prev = shot
            self._sleep_responsive(STOP_POLL_INTERVAL_S)
            waited += STOP_POLL_INTERVAL_S
        self.log(State.PLAYING,
                 "gameplay-active wait ended (timeout) -- starting macro anyway")

    def _await_boost_start(self, timeout_s: float = 8.0) -> None:
        self.log(State.PLAYING, "awaiting Boost Start activation (macro t=0)...")
        self._await_gameplay_active(timeout_s)

    def _monitor_match(self) -> State:
        self.log(State.PLAYING, "monitoring match: scanning captcha + game-over")
        self._relay_used = False           # new run: relay/revive not yet used
        while self.running:
            self._sleep_responsive(1.0)
            if not self.running:
                break

            shot = self.adb.screenshot()
            captcha = self._captcha_active(shot)
            yellow = self._region_color_ratio(
                RESULT_COLOR_REGION, RESULT_TARGET_RGB,
                RESULT_COLOR_TOLERANCE, shot=shot) >= RESULT_REQUIRED_RATIO
            if not captcha and yellow:
                captcha = self._captcha_confirm()
            game_over = yellow and not captcha
            self.log(State.PLAYING,
                     f"scan -> captcha={captcha} | game_over={game_over}")

            if captcha:
                self.log(State.PLAYING,
                         "captcha detected (OCR) -> solving (game-over suppressed)")
                self._solve_captcha_inline()
                continue
            if game_over:
                self.log(State.PLAYING,
                         "RESULT banner confirmed (no captcha) -> GAME_OVER (-> OPEN_BOX)")
                return State.GAME_OVER
            if self.playing_mode == "long_run":
                # STRICTLY gated per GUI toggle:
                #  * Boost  -> blue-pixel density of the support icon (BONUS_ICON).
                #  * Relay  -> OCR of the "Cookie Relay Boost!" banner, ONCE per run.
                # Each check is skipped entirely when its toggle is OFF (no
                # competing trigger, no wasted OCR).
                if self.long_run_boost_enabled:
                    boost_present = self._region_color_ratio(
                        BONUS_ICON_REGION, REFLEX_TARGET_BLUE,
                        REFLEX_TOLERANCE, shot=shot) >= REFLEX_REQUIRED_RATIO
                    if boost_present:
                        self.tap("boost_slot")
                        self.log(State.PLAYING, "long-run reflex: Boost tap (boost_slot)")

                if (self.long_run_relay_enabled and not self._relay_used
                        and self._relay_prompt_present(shot)):
                    self._activate_relay()
                    self._relay_used = True
                    self.log(State.PLAYING,
                             "long-run reflex: Relay Boost activated (banner tap)")
        return State.GAME_OVER

    @staticmethod
    def _region_mae(a: Screenshot, b: Screenshot,
                    x: int, y: int, w: int, h: int, step: int = 8) -> float:
        total = n = 0
        for yy in range(y, y + h, step):
            for xx in range(x, x + w, step):
                ar = a.pixel(xx, yy); br = b.pixel(xx, yy)
                total += sum(abs(c1 - c2) for c1, c2 in zip(ar, br))
                n += 1
        return (total / n / 3.0) if n else 0.0

    @staticmethod
    def _frame_view(shot):
        import numpy as np
        return np.frombuffer(shot.data, np.uint8,
                             count=shot.width * shot.height * 4,
                             offset=shot.offset).reshape(shot.height, shot.width, 4)

    def _region_color_ratio(self, region: tuple, target_rgb: tuple,
                            tolerance: int = 15, step: int = 4, shot=None) -> float:
        import numpy as np
        if shot is None:
            shot = self.adb.screenshot()
        x, y, w, h = region
        sub = self._frame_view(shot)[y:y + h:step, x:x + w:step, :3].astype(np.int16)
        diff = np.abs(sub - np.array(target_rgb, np.int16))
        hit = (diff <= tolerance).all(axis=2)
        return float(hit.mean()) if hit.size else 0.0

    def _check_region_color_density(self, region: tuple, target_rgb: tuple,
                                    tolerance: int = 15,
                                    required_ratio: float = 0.15) -> bool:
        return self._region_color_ratio(region, target_rgb, tolerance) >= required_ratio

    def _await_color_density(self, region: tuple, target_rgb: tuple,
                             state: State, label: str,
                             tolerance: int = RESULT_COLOR_TOLERANCE,
                             required_ratio: float = RESULT_REQUIRED_RATIO) -> None:
        while self.running:
            ratio = self._region_color_ratio(region, target_rgb, tolerance)
            self.log(state, f"Waiting for {label} color... "
                            f"current density: {ratio * 100:.1f}%")
            if ratio >= required_ratio:
                self.log(state, f"{label} confirmed (density {ratio * 100:.1f}%)")
                return
            self._sleep_responsive(1.0)

    def _ftc_config(self):
        if getattr(self, "_ftc_cfg_cache", None) is None:
            import find_the_card as ftc
            self._ftc_cfg_cache = ftc.Config()
        return self._ftc_cfg_cache

    def _captcha_active(self, shot: "Optional[Screenshot]" = None) -> bool:
        try:
            import find_the_card as ftc
        except Exception as exc:
            self.log(State.PLAYING, f"captcha OCR unavailable ({exc}) -> False")
            return False
        if shot is None:
            shot = self.adb.screenshot()
        img = self._shot_to_bgr(shot)
        return bool(ftc.detect_trigger(img, self._ftc_config()))

    def _captcha_region_sig(self, shot) -> int:
        x, y, w, h = CAPTCHA_OCR_REGION
        s = CAPTCHA_CACHE_STRIDE
        sub = self._frame_view(shot)[y:y + h:s, x:x + w:s, :3]
        return hash(sub.tobytes())

    def _captcha_active_cached(self, shot) -> bool:
        cache = getattr(self, "_captcha_cache", None)
        if cache is None:
            cache = self._captcha_cache = {"sig": None, "verdict": False, "t": 0.0}
        now = time.monotonic()
        sig = self._captcha_region_sig(shot)
        if sig == cache["sig"] and (now - cache["t"]) < CAPTCHA_CACHE_TTL_S:
            return cache["verdict"]
        verdict = self._captcha_active(shot)
        cache.update(sig=sig, verdict=verdict, t=now)
        return verdict

    def _captcha_confirm(self, shot: "Optional[Screenshot]" = None,
                         attempts: int = CAPTCHA_CONFIRM_ATTEMPTS) -> bool:
        for i in range(max(1, attempts)):
            frame = shot if (i == 0 and shot is not None) else self.adb.screenshot()
            if self._captcha_active(frame):
                self.log(State.PLAYING,
                         f"captcha CONFIRMED on OCR retry {i + 1}/{attempts} "
                         f"-> CAPTCHA (game-over suppressed)")
                return True
            if i < attempts - 1:
                self._sleep_responsive(CAPTCHA_CONFIRM_GAP_S)
        self.log(State.PLAYING,
                 f"captcha not found after {attempts} OCR attempts -> allow GAME_OVER")
        return False

    def _congrats_active(self) -> bool:
        return self._check_region_color_density(
            REGION_CONGRATS_TEXT, CONGRATS_TARGET_RGB,
            CONGRATS_COLOR_TOLERANCE, CONGRATS_REQUIRED_RATIO)

    @staticmethod
    def _shot_to_bgr(shot):
        import numpy as np
        arr = np.frombuffer(shot.data, dtype=np.uint8,
                            count=shot.width * shot.height * 4,
                            offset=shot.offset).reshape(shot.height, shot.width, 4)
        return arr[:, :, [2, 1, 0]].copy()

    def _solve_captcha_inline(self) -> None:
        try:
            import cv2
            import numpy as np
            import find_the_card as ftc
        except Exception as exc:
            self.log(State.CAPTCHA, f"inline solver unavailable ({exc}) -- skipping")
            return

        cfg = ftc.Config()

        def tap(x, y) -> None:
            self.adb.shell("input", "tap", str(int(x)), str(int(y)))

        img = self._shot_to_bgr(self.adb.screenshot())
        if not ftc.detect_trigger(img, cfg):
            self.log(State.CAPTCHA, "inline solver: no trigger banner -> nothing to solve")
            return

        self.log(State.CAPTCHA, "inline solver: trigger detected (OCR) -> clearing cards")
        bg_ema: dict = {}
        stats = {"success": 0, "miss": 0, "low_conf": 0}
        cleared: set = set()
        dead: set = set()
        session_template = None
        high_conf_next = False
        prev_tries = ftc.tries_signature(img, cfg)
        tap_no = 0
        MAX_TAPS = 40

        while self.running and ftc.detect_trigger(img, cfg):
            if tap_no >= MAX_TAPS:
                self.log(State.CAPTCHA, f"inline solver: hit MAX_TAPS={MAX_TAPS} -> bailing")
                break
            cells = ftc.split_grid(img, cfg)
            excluded = cleared | dead

            cur_tries = ftc.tries_signature(img, cfg)
            tries_mae = float(np.abs(cur_tries - prev_tries).mean())
            tries_changed = tries_mae > cfg.tries_mae_thresh
            std_by_cell = {(r, c): float(cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY).std())
                           for r, c, cell, _ in cells}
            respawned = any(std_by_cell.get(rc, 0.0) > ftc._respawn_thresh(rc, bg_ema, cfg)
                            for rc in cleared)
            if excluded and (tries_changed or respawned):
                self.log(State.CAPTCHA, "inline solver: sub-round/reset -> re-wiping state")
                cleared.clear()
                dead.clear()
                session_template = None
                high_conf_next = False
                excluded = set()
            prev_tries = cur_tries

            if session_template is None and not excluded:
                session_template = ftc.capture_session_template(cells, cfg)

            targets, score = ftc.find_target_cells(cells, cfg, excluded,
                                                   session_template, high_conf_next)
            high_conf_next = False

            if not targets:
                self._sleep_responsive(cfg.tap_delay_s)
                img = self._shot_to_bgr(self.adb.screenshot())
                continue

            tap_no += 1
            r, c, pre_cell, (x, y) = targets[0]
            low = (score is not None and session_template is not None
                   and score < cfg.low_conf_dev)
            if low:
                stats["low_conf"] += 1
            self.log(State.CAPTCHA, f"inline solver: tap {tap_no} ({r},{c}) "
                     f"dev={score:.1f}{' [LOW]' if low else ''}")
            tap(x, y)

            self._sleep_responsive(cfg.tap_delay_s)
            img = self._shot_to_bgr(self.adb.screenshot())

            post_cell = ftc.split_grid(img, cfg)[r * cfg.cols + c][2]
            vanish_mae = ftc._cell_mae(pre_cell, post_cell)
            if vanish_mae > cfg.vanish_mae_thresh:
                cleared.add((r, c))
                stats["success"] += 1
                bg = float(cv2.cvtColor(post_cell, cv2.COLOR_BGR2GRAY).std())
                a = cfg.bg_ema_alpha
                bg_ema[(r, c)] = bg if (r, c) not in bg_ema else (1 - a) * bg_ema[(r, c)] + a * bg
            else:
                dead.add((r, c))
                stats["miss"] += 1
                high_conf_next = True

        self.log(State.CAPTCHA, f"inline solver done: success={stats['success']} "
                 f"miss={stats['miss']} low_conf={stats['low_conf']}")


    def run(self) -> None:
        self.adb.connect()
        state = State.CAPTCHA if self.mode == "CAPTCHA_ONLY" else State.MAIN_MENU
        self.log(state, f"starting orchestrator in {self.mode} mode")

        cycles = 0
        try:
            while self.running:
                if state in CONGRATS_SCAN_STATES and self._congrats_active():
                    self.log(state, "[INTERCEPT] Congratulations detected "
                                    "-> STATE_CONGRATS")
                    state = State.CONGRATS

                if self.mode != "CAPTCHA_ONLY" and state == State.MAIN_MENU:
                    cycles += 1
                    if MAX_CYCLES > 0 and cycles > MAX_CYCLES:
                        self.log(state, f"completed {MAX_CYCLES} cycle(s) -- stopping")
                        break
                    total = str(MAX_CYCLES) if MAX_CYCLES > 0 else "inf"
                    self.log(state, f"--- cycle {cycles}/{total} ---")
                handler = self.handlers[state]
                state = handler()

                if state == State.GAME_OVER:
                    self.completed_runs += 1
                    self.log(State.GAME_OVER,
                             f"run finished -> completed runs this session: "
                             f"{self.completed_runs}")
                    if self.on_run_complete is not None:
                        try:
                            self.on_run_complete()
                        except Exception as exc:
                            self.log(State.GAME_OVER,
                                     f"run-counter hook error: {exc}")
        except KeyboardInterrupt:
            print("\nOrchestrator stopped.")


def _self_check() -> int:
    import struct
    from adb_macro_manager import Screenshot

    print("=" * 64)
    print(" SELF-CHECK  |  dry-running the state machine on a MOCK device")
    print("=" * 64)

    W, H = 1600, 900
    blank = Screenshot.from_raw(struct.pack("<II", W, H) + bytes(W * H * 4))
    taps: list = []
    shells: list = []

    class MockAdb:
        def connect(self): pass
        def screenshot(self): return blank
        def shell(self, *a): shells.append(a); return ""

    _await_names = ("_await_color_density", "_await_region_settled",
                    "_await_stop_button_appear", "_await_stop_button_vanish",
                    "_await_boost_start", "_await_gameplay_active")

    def build(playing="long_run"):
        o = Orchestrator(MODE)
        o.playing_mode = playing
        o.adb = MockAdb()
        o.log = lambda *a, **k: None
        o._throttle = lambda *a, **k: None
        o.sleep_human = lambda *a, **k: None
        o._sleep_responsive = lambda *a, **k: None
        o.tap = lambda name: taps.append(name)
        o._congrats_active = lambda *a, **k: False
        # Happy-path OCR gates by default (anchor confirmed, mystery box present);
        # the T / X scenarios override these to exercise the claim + fail-safe
        # branches. (_grab_watchdog_frame is left real -> falls back to MockAdb's
        # blank screenshot.)
        o._match_main_menu_anchor = lambda shot: 0.9
        o._ocr_region_text = lambda shot, region, **k: ""   # no "Get!" by default
        o._mystery_box_present = lambda shot: True
        for n in _await_names:
            if hasattr(o, n):
                setattr(o, n, lambda *a, **k: None)
        return o

    results: list = []
    def check(desc, cond):
        results.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")

    print("\n-- A. golden pipeline (long_run) --")
    # No "Get!" by default -> MAIN_MENU falls straight through to Play, so the
    # full backbone MAIN_MENU -> ... -> MAIN_MENU is walkable end to end.
    o = build("long_run")
    o._captcha_active = lambda *a, **k: False
    o._check_region_color_density = lambda region, *a, **k: False
    o._region_color_ratio = (lambda region, *a, **k:
                             1.0 if region == RESULT_COLOR_REGION else 0.0)
    seq: list = []
    state = State.MAIN_MENU
    for _ in range(20):
        seq.append(state.name)
        state = o.handlers[state]()
        if state == State.MAIN_MENU:
            seq.append(state.name)
            break
    print("   walk:", " -> ".join(seq))
    backbone = ["MAIN_MENU", "BEFORE_START", "PLAYING", "GAME_OVER",
                "OPEN_BOX", "LEVEL_UP", "MAIN_MENU"]
    check("full backbone MAIN_MENU -> ... -> MAIN_MENU reachable", seq == backbone)

    print("\n-- B. captcha handoff (macro) --")
    saved_popen, saved_exists = subprocess.Popen, os.path.exists

    class FakeProc:
        def __init__(s): s._rc = None; s.pid = 1; s.stdout = iter(())
        def poll(s): return s._rc
        def terminate(s): s._rc = 0
        def wait(s, timeout=None): return 0
        def kill(s): s._rc = -9

    subprocess.Popen = lambda *a, **k: FakeProc()
    os.path.exists = lambda p: True
    try:
        o = build("macro")
        o.long_run_relay_enabled = False   # relay off -> PHASE 2 armed from the start
        cap = {"v": True}
        o._captcha_active = lambda *a, **k: cap["v"]
        o._region_color_ratio = lambda *a, **k: 0.0
        solved = {"n": 0}
        def _solve(): solved["n"] += 1; cap["v"] = False
        o._solve_captcha_inline = _solve
        base = len(shells)
        st = Orchestrator.handle_playing(o)
        purged = any(c == ("pkill", "-f", "com.android.commands.input")
                     for c in shells[base:])
        check("macro captcha -> inline solver invoked once", solved["n"] == 1)
        check("macro captcha -> ADB input buffer purged", purged)
        check("captcha solved (no game over) -> resume PLAYING", st is State.PLAYING)
    finally:
        subprocess.Popen, os.path.exists = saved_popen, saved_exists

    print("\n-- C. mutual exclusion (captcha vs game-over) --")
    o = build("macro")
    o._captcha_active = lambda *a, **k: True
    o._region_color_ratio = lambda *a, **k: 1.0
    check("captcha up + yellow -> _post_solver_state resumes PLAYING (not GAME_OVER)",
          o._post_solver_state() is State.PLAYING)

    print("\n-- D. captcha confirm-retry (3-5x before GAME_OVER) --")
    o = build("macro")
    o._region_color_ratio = lambda *a, **k: 1.0
    reads = {"n": 0}
    def _flaky(*a, **k):
        reads["n"] += 1
        return reads["n"] >= 3
    o._captcha_active = _flaky
    check("yellow + captcha-found-on-retry -> resume PLAYING (not GAME_OVER)",
          o._post_solver_state() is State.PLAYING)
    o = build("macro")
    o._region_color_ratio = lambda *a, **k: 1.0
    o._captcha_active = lambda *a, **k: False
    check("yellow + captcha never found after retries -> GAME_OVER",
          o._post_solver_state() is State.GAME_OVER)

    print("\n-- H. the clutch save (captcha caught on 4th read) --")
    o = build("macro")
    reads = {"n": 0}
    def _clutch(*a, **k):
        reads["n"] += 1
        return reads["n"] >= 4
    o._captcha_active = _clutch
    got = o._captcha_confirm()
    check("clutch: _captcha_confirm returns True (caught on 4th read)", got is True)
    check("clutch: EARLY-EXIT at read 4 of 5 (did not waste read 5)", reads["n"] == 4)
    o = build("macro")
    o._region_color_ratio = lambda *a, **k: 1.0
    reads2 = {"n": 0}
    def _clutch2(*a, **k):
        reads2["n"] += 1
        return reads2["n"] >= 4
    o._captcha_active = _clutch2
    check("clutch: pipeline suppresses false GAME_OVER -> resume PLAYING",
          o._post_solver_state() is State.PLAYING)

    print("\n-- N. numpy hot-path parity (bit-exact vs pixel loop) --")
    import random as _rnd
    o = build("macro")

    def _ref_ratio(shot, region, target, tol, step):
        x, y, w, h = region; tr, tg, tb = target; match = total = 0
        for yy in range(y, y + h, step):
            for xx in range(x, x + w, step):
                r, g, b = shot.pixel(xx, yy); total += 1
                if abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol:
                    match += 1
        return (match / total) if total else 0.0

    _rnd.seed(1)
    body = bytes(_rnd.getrandbits(8) for _ in range(W * H * 4))
    rshot = Screenshot.from_raw(struct.pack("<II", W, H) + body)
    parity_ok = True
    for region, target, tol, step in [
            (RESULT_COLOR_REGION, RESULT_TARGET_RGB, 15, 4),
            ((100, 80, 240, 160), (128, 128, 128), 20, 3),
            (CAPTCHA_OCR_REGION, (92, 131, 132), 15, 8)]:
        a = o._region_color_ratio(region, target, tol, step, shot=rshot)
        b = _ref_ratio(rshot, region, target, tol, step)
        if abs(a - b) > 1e-12:
            parity_ok = False
            print(f"   MISMATCH {region}: numpy={a:.9f} ref={b:.9f}")
    check("numpy _region_color_ratio == pixel-loop reference (bit-exact)", parity_ok)

    sig0 = o._captcha_region_sig(rshot)
    flip = bytearray(struct.pack("<II", W, H) + body)
    fx, fy = CAPTCHA_OCR_REGION[0], CAPTCHA_OCR_REGION[1]
    flip[8 + (fy * W + fx) * 4] ^= 0xFF
    rshot2 = Screenshot.from_raw(bytes(flip))
    check("region sig stable on identical frame", o._captcha_region_sig(rshot) == sig0)
    check("region sig changes on sampled-pixel change",
          o._captcha_region_sig(rshot2) != sig0)

    # -- T. Main-menu optional "Get!" reward claim (non-blocking) ----------- #
    print("\n-- T. main-menu optional 'Get!' claim (non-blocking pass-through) --")
    # CASE A: "Get!" present -> full claim seq taps get/congrats/reward/close.
    o = build()
    o._match_main_menu_anchor = lambda shot: 0.9
    o._ocr_region_text = lambda shot, region, **k: (
        "Get!" if region == TICKET_GET_REGION else "")
    o._await_text = lambda region, needle, timeout_s: True     # congrats confirmed
    region_taps: list = []
    o._tap_region_center = lambda region: region_taps.append(region)
    taps.clear()
    st = Orchestrator.handle_main_menu(o)
    check("'Get!' -> claim seq (get,congrats,reward,close) -> MAIN_MENU (no Play)",
          st is State.MAIN_MENU and "play_button" not in taps and region_taps ==
          [TICKET_GET_REGION, CONGRATS_REGION, REWARD_TAP_COORDS, CLOSE_MENU_COORDS])

    # CASE A (degraded): "Get!" up but "Congratulations!" never confirmed ->
    # skip the reward tap, still close, back to MAIN_MENU.
    o = build()
    o._match_main_menu_anchor = lambda shot: 0.9
    o._ocr_region_text = lambda shot, region, **k: (
        "Get!" if region == TICKET_GET_REGION else "")
    o._await_text = lambda region, needle, timeout_s: False     # congrats timed out
    region_taps = []
    o._tap_region_center = lambda region: region_taps.append(region)
    st = Orchestrator.handle_main_menu(o)
    check("'Get!' + congrats timeout -> skips reward tap, still closes -> MAIN_MENU",
          st is State.MAIN_MENU and region_taps ==
          [TICKET_GET_REGION, CONGRATS_REGION, CLOSE_MENU_COORDS])

    # CASE B: no "Get!" -> NON-BLOCKING pass-through to Play/BEFORE_START.
    o = build()
    o._match_main_menu_anchor = lambda shot: 0.9
    o._ocr_region_text = lambda shot, region, **k: ""           # no balloon
    region_taps = []
    o._tap_region_center = lambda region: region_taps.append(region)
    taps.clear()
    st = Orchestrator.handle_main_menu(o)
    check("no 'Get!' -> pass through to BEFORE_START + Play (no claim taps)",
          st is State.BEFORE_START and "play_button" in taps and region_taps == [])

    # Anchor is NO LONGER a gate: a low anchor still claims when "Get!" is present.
    o = build()
    o._match_main_menu_anchor = lambda shot: 0.30
    o._ocr_region_text = lambda shot, region, **k: (
        "Get!" if region == TICKET_GET_REGION else "")
    o._await_text = lambda region, needle, timeout_s: True
    region_taps = []
    o._tap_region_center = lambda region: region_taps.append(region)
    taps.clear()
    st = Orchestrator.handle_main_menu(o)
    check("low anchor + 'Get!' -> STILL claims (anchor no longer gates)",
          st is State.MAIN_MENU and "play_button" not in taps and region_taps ==
          [TICKET_GET_REGION, CONGRATS_REGION, REWARD_TAP_COORDS, CLOSE_MENU_COORDS])

    # -- X. Mystery-box text gate (OPEN_BOX) -------------------------------- #
    print("\n-- X. mystery-box text gate (OCR 'Mystery Box') --")
    o = build()
    o._mystery_box_present = lambda shot: True
    taps.clear()
    st = Orchestrator.handle_open_box(o)
    check("Mystery Box present -> opens + dismisses (2 taps) -> LEVEL_UP",
          st is State.LEVEL_UP and taps.count("open_all_button") == 2)

    o = build()
    o._mystery_box_present = lambda shot: False
    taps.clear()
    st = Orchestrator.handle_open_box(o)
    check("no Mystery Box -> skips box phase (0 taps) -> LEVEL_UP",
          st is State.LEVEL_UP and "open_all_button" not in taps)

    # -- R. Macro-watchdog relay/revive (OCR banner, toggle + once per run) -- #
    print("\n-- R. macro watchdog relay/revive (OCR banner gate) --")

    class WDProc:                       # poll() returns None a few times, then dies
        def __init__(s): s.n = 0
        def poll(s): s.n += 1; return None if s.n <= 6 else 0
        def terminate(s): pass
        def wait(s, timeout=None): return 0
        def kill(s): pass

    def run_wd(relay_enabled, banner, captcha=False):
        o = build("macro")
        o.long_run_relay_enabled = relay_enabled
        o._relay_used = False
        o._watchdog_detected = None
        o._captcha_active_cached = lambda shot: captcha
        o._captcha_confirm = lambda: False
        o._region_color_ratio = lambda *a, **k: 0.0        # RESULT never fires
        o._relay_prompt_present = lambda shot: banner
        o._purge_adb_input_buffer = lambda: None
        o._solve_captcha_inline = lambda: None
        local: list = []
        o._activate_relay = lambda: local.append("relay")
        ev = threading.Event(); ev.wait = lambda t=None: None
        o._background_watchdog_loop(WDProc(), ev)
        return local, o._watchdog_detected

    # Relay activation (one-shot + toggle gate)
    check("relay ON + banner -> activates relay exactly once (one-shot)",
          run_wd(True, True) == (["relay"], None))
    check("relay OFF + banner -> no relay activation (toggle gate)",
          run_wd(False, True) == ([], None))
    check("relay ON + no banner -> no relay activation",
          run_wd(True, False) == ([], None))
    # PHASE gating: captcha/game-over deferred until the relay fires
    check("PHASE 1: captcha up but relay not yet fired -> DEFERRED (not detected)",
          run_wd(True, False, captcha=True) == ([], None))
    check("relay disabled -> PHASE 2 armed immediately -> captcha detected",
          run_wd(False, False, captcha=True) == ([], State.CAPTCHA))
    check("PHASE 2: relay fires, then captcha armed -> relay + captcha detected",
          run_wd(True, True, captcha=True) == (["relay"], State.CAPTCHA))

    ok = all(results)
    print("\n" + "=" * 64)
    print(f" SELF-CHECK RESULT: {'ALL PASS' if ok else 'FAILURES DETECTED'} "
          f"({sum(results)}/{len(results)} checks)")
    print("=" * 64)
    return 0 if ok else 1


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="CookieRun automation orchestrator")
    ap.add_argument("--self-check", action="store_true",
                    help="dry-run the state machine on a mock device (no emulator) and exit")
    args = ap.parse_args()
    if args.self_check:
        raise SystemExit(_self_check())
    Orchestrator(MODE).run()
