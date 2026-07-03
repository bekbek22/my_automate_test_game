
from __future__ import annotations

import argparse
import random
import time
from typing import Callable, Dict, List, Optional, Tuple

from adb_macro_manager import Adb, Config, Screenshot
from test_macro_io import ACTION_INPUT_REGIONS, ACTION_TARGETS, DUAL_TAP_GAP_S



JUMP_ZONE: Tuple[int, int, int, int]  = (470, 900, 40, 160)
SLIDE_ZONE: Tuple[int, int, int, int] = (470, 620, 40, 140)

TRIGGER_MAE = 28.0
SAMPLE_STEP = 3
COOLDOWN_S  = 0.45
SLIDE_HOLD_MS = 350

RESULT_COLOR_REGION = (669, 55, 262, 70)
RESULT_TARGET_RGB   = (255, 205, 0)
RESULT_TOLERANCE    = 15
RESULT_REQUIRED_RATIO = 0.15

CAPTCHA = "captcha"
GAME_OVER = "game_over"



Signature = List[Tuple[int, int, int]]


def strip_signature(shot: Screenshot, zone: Tuple[int, int, int, int],
                    step: int = SAMPLE_STEP) -> Signature:
    x, y, w, h = zone
    return [shot.pixel(xx, yy)
            for yy in range(y, y + h, step)
            for xx in range(x, x + w, step)]


def mae(a: Signature, b: Signature) -> float:
    if not a or len(a) != len(b):
        return 0.0
    total = 0
    for (r1, g1, b1), (r2, g2, b2) in zip(a, b):
        total += abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)
    return total / (len(a) * 3)


def region_color_ratio(shot: Screenshot, region: Tuple[int, int, int, int],
                       target_rgb: Tuple[int, int, int],
                       tolerance: int = RESULT_TOLERANCE, step: int = 4) -> float:
    x, y, w, h = region
    tr, tg, tb = target_rgb
    match = total = 0
    for yy in range(y, y + h, step):
        for xx in range(x, x + w, step):
            r, g, b = shot.pixel(xx, yy)
            total += 1
            if (abs(r - tr) <= tolerance and abs(g - tg) <= tolerance
                    and abs(b - tb) <= tolerance):
                match += 1
    return (match / total) if total else 0.0



def calibrate_baseline(adb: Adb) -> Dict[str, Signature]:
    shot = adb.screenshot()
    return {
        "jump":  strip_signature(shot, JUMP_ZONE),
        "slide": strip_signature(shot, SLIDE_ZONE),
    }


CAPTCHA_BANNER_REGION = (492, 43, 722, 71)
CAPTCHA_TARGET_RGB = (92, 131, 132)
CAPTCHA_TOLERANCE = 15
CAPTCHA_REQUIRED_RATIO = 0.10


def _color_gate(shot: Screenshot) -> float:
    return region_color_ratio(shot, CAPTCHA_BANNER_REGION, CAPTCHA_TARGET_RGB,
                              CAPTCHA_TOLERANCE)


def captcha_active(shot: Screenshot, throttle: bool = True) -> bool:
    if _color_gate(shot) < CAPTCHA_REQUIRED_RATIO:
        return False
    if region_color_ratio(shot, RESULT_COLOR_REGION, RESULT_TARGET_RGB,
                          RESULT_TOLERANCE) >= RESULT_REQUIRED_RATIO:
        return False
    return True


def detect_end(adb: Adb, shot: Screenshot) -> Optional[str]:
    if captcha_active(shot):
        return CAPTCHA
    if region_color_ratio(shot, RESULT_COLOR_REGION, RESULT_TARGET_RGB) \
            >= RESULT_REQUIRED_RATIO:
        return GAME_OVER
    return None



def _random_point(action: str) -> Tuple[int, int]:
    region = ACTION_INPUT_REGIONS.get(action)
    if region:
        rx, ry, rw, rh = region
        return random.randint(rx, rx + rw), random.randint(ry, ry + rh)
    return ACTION_TARGETS[action][0]


def fire_jump(adb: Adb) -> None:
    x, y = _random_point("jump")
    adb.shell("input", "tap", str(x), str(y))


def fire_slide(adb: Adb, hold_ms: int = SLIDE_HOLD_MS) -> None:
    x, y = _random_point("slide")
    adb.shell("input", "swipe", str(x), str(y), str(x), str(y), str(hold_ms))



def reflex_loop(adb: Adb, baseline: Dict[str, Signature],
                stop_check: Optional[Callable[[], bool]] = None,
                trigger_mae: float = TRIGGER_MAE,
                cooldown_s: float = COOLDOWN_S,
                on_event: Optional[Callable[[str, float, float], None]] = None,
                ) -> Optional[str]:
    cooldown_until = {"jump": 0.0, "slide": 0.0}
    while not (stop_check and stop_check()):
        now = time.monotonic()
        shot = adb.screenshot()

        end = detect_end(adb, shot)
        if end is not None:
            if on_event:
                on_event(end, 0.0, 0.0)
            return end

        jump_mae  = mae(strip_signature(shot, JUMP_ZONE),  baseline["jump"])
        slide_mae = mae(strip_signature(shot, SLIDE_ZONE), baseline["slide"])

        if (jump_mae >= trigger_mae and now >= cooldown_until["jump"]
                and jump_mae >= slide_mae):
            fire_jump(adb)
            cooldown_until["jump"] = now + cooldown_s
            if on_event:
                on_event("jump", jump_mae, slide_mae)
        elif slide_mae >= trigger_mae and now >= cooldown_until["slide"]:
            fire_slide(adb)
            cooldown_until["slide"] = now + cooldown_s
            if on_event:
                on_event("slide", jump_mae, slide_mae)
    return None



def _cli_calibrate(adb: Adb, interval_s: float = 0.2) -> None:
    print("[CALIBRATE] Capturing EMPTY-TRACK baseline NOW -- keep the lane clear.")
    baseline = calibrate_baseline(adb)
    print(f"[CALIBRATE] Baseline set. JUMP_ZONE={JUMP_ZONE}  SLIDE_ZONE={SLIDE_ZONE}")
    print(f"[CALIBRATE] TRIGGER_MAE={TRIGGER_MAE}  "
          f"CAPTCHA_BANNER_REGION={CAPTCHA_BANNER_REGION}")
    print(f"[CALIBRATE] To find the captcha signature: sit on the captcha screen "
          f"and read 'CAP rgb' / 'CAP ratio' below.")
    print(f"[CALIBRATE] Set CAPTCHA_TARGET_RGB to the CAP rgb you see there, and "
          f"CAPTCHA_REQUIRED_RATIO between its play-vs-captcha ratios.")
    print(f"[CALIBRATE] Watching live (Ctrl+C to stop)...\n")
    print(f"{'t(s)':>7} | {'JUMP mae':>9} | {'SLIDE mae':>9} | "
          f"{'CAP rgb':>15} | {'CAP ratio':>9} | end")
    print("-" * 74)
    t0 = time.monotonic()
    try:
        while True:
            shot = adb.screenshot()
            end = detect_end(adb, shot) or "-"
            jm = mae(strip_signature(shot, JUMP_ZONE),  baseline["jump"])
            sm = mae(strip_signature(shot, SLIDE_ZONE), baseline["slide"])
            jflag = "**" if jm >= TRIGGER_MAE else "  "
            sflag = "**" if sm >= TRIGGER_MAE else "  "
            cap_rgb = shot.region_avg(*CAPTCHA_BANNER_REGION)
            cap_ratio = region_color_ratio(shot, CAPTCHA_BANNER_REGION,
                                           CAPTCHA_TARGET_RGB, CAPTCHA_TOLERANCE)
            cflag = "**" if cap_ratio >= CAPTCHA_REQUIRED_RATIO else "  "
            rgb_str = f"{cap_rgb[0]:>3},{cap_rgb[1]:>3},{cap_rgb[2]:>3}"
            print(f"{time.monotonic() - t0:7.1f} | {jm:7.1f}{jflag} | "
                  f"{sm:7.1f}{sflag} | {rgb_str:>15} | {cap_ratio:7.2f}{cflag} | "
                  f"{end}", flush=True)
            time.sleep(interval_s)
    except KeyboardInterrupt:
        print("\n[CALIBRATE] stopped.")


def _cli_run(adb: Adb) -> None:
    print("[RUN] Capturing baseline (keep the lane clear), then reflex starts.")
    baseline = calibrate_baseline(adb)

    def _log(kind: str, jm: float, sm: float) -> None:
        if kind in (CAPTCHA, GAME_OVER):
            print(f"[RUN] end anchor: {kind} -> exiting", flush=True)
        else:
            print(f"[RUN] {kind:<5} fired  (jump={jm:.1f} slide={sm:.1f})", flush=True)

    result = reflex_loop(adb, baseline, on_event=_log)
    print(f"[RUN] reflex_loop returned: {result}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Vision-triggered reflex engine for a frame-tied runner")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("calibrate", help="live JUMP/SLIDE MAE readout for tuning")
    sub.add_parser("run", help="standalone reflex loop (calibrate + play)")
    args = parser.parse_args(argv)

    adb = Adb(Config())
    adb.connect()
    if args.cmd == "calibrate":
        _cli_calibrate(adb)
    elif args.cmd == "run":
        _cli_run(adb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
