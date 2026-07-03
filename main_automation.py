
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

BONUS_ICON_REGION = (725, 334, 183, 188)
REFLEX_TARGET_BLUE = (32, 74, 124)
REFLEX_TOLERANCE = 50
REFLEX_REQUIRED_RATIO = 0.05
BOOST_SLOT_CLICK = (816, 428)
RELAY_SLOT_CLICK = (860, 620)

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
    "relay_slot":       RELAY_SLOT_CLICK,
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
        self.long_run_boost = long_run_boost_enabled
        self.long_run_relay = long_run_relay_enabled
        self.adb_cfg = AdbConfig()
        self.adb = Adb(self.adb_cfg)
        self.running = True

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
        offset_x = random.randint(-8, 8)
        offset_y = random.randint(-8, 8)
        self.adb.shell("input", "tap", str(x + offset_x), str(y + offset_y))

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


    def handle_main_menu(self) -> State:
        self._throttle()
        self.log(State.MAIN_MENU, "clicking play button -> prep")
        self.tap("play_button")
        self.sleep_human(1.5)
        return State.BEFORE_START

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

    def _background_watchdog_loop(self, proc, stop_evt: "threading.Event") -> None:
        while (not stop_evt.is_set() and proc.poll() is None and self.running):
            try:
                shot = self.adb.screenshot()
                if self._captcha_active_cached(shot):
                    detected = State.CAPTCHA
                elif self._region_color_ratio(
                        RESULT_COLOR_REGION, RESULT_TARGET_RGB,
                        RESULT_COLOR_TOLERANCE, shot=shot) >= RESULT_REQUIRED_RATIO:
                    detected = (State.CAPTCHA if self._captcha_confirm()
                                else State.GAME_OVER)
                else:
                    detected = None
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
        self.log(State.OPEN_BOX, "awaiting Mystery Box screen")
        self._await_region_settled(MYSTERY_BOX_REGION, State.OPEN_BOX, "MYSTERY_BOX")

        self.log(State.OPEN_BOX, "opening all boxes")
        self.tap("open_all_button")

        wait = random.uniform(BOX_ANIM_MIN_S, BOX_ANIM_MAX_S)
        self.log(State.OPEN_BOX, f"waiting {wait:.1f}s for reward animation")
        self._sleep_responsive(wait)

        self.log(State.OPEN_BOX, "dismissing rewards")
        self.tap("open_all_button")
        self.sleep_human(1.5)
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
                if not (self.long_run_boost or self.long_run_relay):
                    continue
                reflex = self._region_color_ratio(BONUS_ICON_REGION,
                                                  REFLEX_TARGET_BLUE, REFLEX_TOLERANCE)
                self.log(State.PLAYING,
                         f"support-slot density={reflex * 100:.2f}% "
                         f"(need>={REFLEX_REQUIRED_RATIO * 100:.0f}%) "
                         f"[boost={self.long_run_boost} relay={self.long_run_relay}]")
                if reflex >= REFLEX_REQUIRED_RATIO:
                    fired = []
                    if self.long_run_boost:
                        self.tap("boost_slot")
                        fired.append("boost")
                    if self.long_run_relay:
                        if fired:
                            self._sleep_responsive(0.05)
                        self.tap("relay_slot")
                        fired.append("relay")
                    self.log(State.PLAYING,
                             f"Long Run Reflex: icon detected -> tapped {fired}")
                    continue
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
        for n in _await_names:
            if hasattr(o, n):
                setattr(o, n, lambda *a, **k: None)
        return o

    results: list = []
    def check(desc, cond):
        results.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")

    print("\n-- A. golden pipeline (long_run) --")
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
