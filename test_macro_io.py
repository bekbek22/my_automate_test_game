
from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import datetime

from adb_macro_manager import Adb, Config

# Pause/resume control files (shared with the orchestrator, cwd-relative). When
# the relay banner appears the game FREEZES, so the orchestrator raises the flag,
# the macro stops + freezes its timeline, the relay is tapped, then the flag is
# cleared and the macro resumes exactly where it left off (no desync, no ADB
# contention fighting the relay tap).
PAUSE_FLAG_FILE = "macro_pause.flag"
PAUSE_ACK_FILE = "macro_paused.ack"


def _wait_if_paused(done) -> float:
    """If the pause flag is raised, freeze here until it clears. Returns the
    paused duration (s) so the caller shifts its timeline baseline forward."""
    if not os.path.exists(PAUSE_FLAG_FILE):
        return 0.0
    t0 = time.monotonic()
    try:
        open(PAUSE_ACK_FILE, "w").close()          # ack: macro has stopped
    except OSError:
        pass
    print("  [macro] PAUSED for relay...", flush=True)
    while os.path.exists(PAUSE_FLAG_FILE) and not done():
        time.sleep(0.02)
    try:
        os.remove(PAUSE_ACK_FILE)
    except OSError:
        pass
    paused = time.monotonic() - t0
    print(f"  [macro] RESUMED (+{paused:.2f}s)", flush=True)
    return paused



KEY_ACTIONS: dict[str, str] = {
    "j": "jump",
    "z": "jump",
    "s": "slide",
    "/": "slide",
    "b": "boost_relay",
    ".": "boost_relay",
}

ACTION_TARGETS: dict[str, list[tuple]] = {
    "jump":         [(203, 773)],
    "slide":        [(1393, 778)],
    "boost_relay":  [(816, 428), (860, 620)],
}

ACTION_INPUT_REGIONS: dict[str, tuple] = {
    "jump":  (44, 260, 314, 603),
    "slide": (1232, 239, 311, 635),
}

DUAL_TAP_GAP_S = 0.05

OUTPUT_FILE = "macro_output.json"



def record_session(out_path: str = OUTPUT_FILE,
                   macro_name: str = "test_run_macro",
                   stop_check=None) -> dict:
    try:
        from pynput import keyboard
    except ImportError:
        raise RuntimeError(
            "Global-hook recording needs pynput. Install it with: "
            "pip install pynput")

    special_actions = {keyboard.Key.space: "jump", keyboard.Key.down: "slide"}
    stop_specials = {keyboard.Key.esc}
    stop_chars = {"q"}

    events: list[dict] = []
    state = {"start": None}
    currently_pressed: set = set()

    def key_token(key):
        ch = getattr(key, "char", None)
        return ch.lower() if ch is not None else key

    def action_for(key):
        ch = getattr(key, "char", None)
        if ch is not None:
            return KEY_ACTIONS.get(ch.lower())
        return special_actions.get(key)

    def is_stop(key):
        ch = getattr(key, "char", None)
        if ch is not None:
            return ch.lower() in stop_chars
        return key in stop_specials

    def _log(action: str, kind: str, token) -> None:
        if state["start"] is None:
            state["start"] = time.monotonic()
        t_ms = int((time.monotonic() - state["start"]) * 1000)
        events.append({
            "time_ms": t_ms,
            "action": action,
            "state": kind,
            "comment": f"{action} {kind} (key '{token}')",
        })
        print(f"  [{t_ms:>6}ms] {action} ({kind}) @ key '{token}'", flush=True)

    def on_press(key):
        if is_stop(key):
            print("\n[STOP] stop key pressed -- saving...", flush=True)
            return False
        action = action_for(key)
        if action is None:
            return
        token = key_token(key)
        if token in currently_pressed:
            return
        currently_pressed.add(token)
        _log(action, "down", token)

    def on_release(key):
        action = action_for(key)
        if action is None:
            return
        token = key_token(key)
        if token in currently_pressed:
            currently_pressed.discard(token)
            _log(action, "up", token)

    print("[INIT] Global keyboard recorder ACTIVE -- focus the MuMu window and "
          "play normally.")
    print("       J/Z/Space=jump   S///Down=slide   B/.=boost_relay   |   "
          "Q/Esc=stop & save   (HOLD a key to record a long press)")

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    try:
        while listener.running:
            if stop_check and stop_check():
                print("\n[STOP] external stop -- saving...", flush=True)
                break
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C received -- saving...")
    finally:
        listener.stop()

    data = {
        "macro_name": macro_name,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "events": events,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    downs = sum(1 for e in events if e.get("state") == "down")
    print(f"Saved {len(events)} event(s) = {downs} move(s) (down+up pairs) "
          f"-> {out_path}")
    return data



DEFAULT_TAP_MS = 100


def _build_moves(events: list) -> list:
    ordered = sorted(enumerate(events), key=lambda p: (p[1]["time_ms"], p[0]))
    consumed_up: set = set()
    moves = []
    for pos, (idx, ev) in enumerate(ordered):
        st = ev.get("state")
        if st == "up":
            continue
        action = ev["action"]
        t = ev["time_ms"]
        if st == "down":
            duration = DEFAULT_TAP_MS
            for jpos in range(pos + 1, len(ordered)):
                jidx, jev = ordered[jpos]
                if (jev.get("state") == "up" and jev["action"] == action
                        and jidx not in consumed_up):
                    duration = max(1, jev["time_ms"] - t)
                    consumed_up.add(jidx)
                    break
            moves.append((t, action, duration))
        else:
            moves.append((t, action, DEFAULT_TAP_MS))
    moves.sort(key=lambda m: m[0])
    return moves


def playback_session(in_path: str = OUTPUT_FILE, adb=None,
                     stop_check=None, abort_check=None) -> None:
    if adb is None:
        adb = Adb(Config())
        adb.connect()

    def stop() -> bool:
        return bool(stop_check and stop_check())

    abort_state = {"t": -1.0, "hit": False}

    def aborted() -> bool:
        if abort_check is None:
            return False
        now = time.monotonic()
        if now - abort_state["t"] >= 1.0:
            abort_state["hit"] = bool(abort_check())
            abort_state["t"] = now
        return abort_state["hit"]

    def done() -> bool:
        if stop():
            return True
        if aborted():
            print("  [ABORT] captcha/game-over detected -- yielding to monitor.",
                  flush=True)
            return True
        return False

    with open(in_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    events = data.get("events", [])
    moves = _build_moves(events)
    print(f"Playing {len(moves)} move(s) [{len(events)} down/up events] from "
          f"{in_path} (macro={data.get('macro_name')!r}). t=0 starts now.")

    start = time.monotonic()
    for t_ms, action, duration in moves:
        if done():
            return

        target = start + t_ms / 1000.0
        while not done():
            paused = _wait_if_paused(done)         # freeze while relay is handled
            if paused:
                start += paused                    # shift baseline -> stay aligned
                target = start + t_ms / 1000.0
            remaining = target - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.02, remaining))
        if done():
            return

        targets = ACTION_TARGETS.get(action)
        if not targets:
            print(f"  [{t_ms:>6}ms] unknown action {action!r} -- skipped", flush=True)
            continue

        if action == "boost_relay":
            for i, (x, y) in enumerate(targets):
                adb.shell("input", "tap", str(x), str(y))
                print(f"  [{t_ms:>6}ms] {action:<12} -> tap ({x},{y})", flush=True)
                if i < len(targets) - 1:
                    time.sleep(DUAL_TAP_GAP_S)
        else:
            region = ACTION_INPUT_REGIONS.get(action)
            if region:
                rx, ry, rw, rh = region
                x = random.randint(rx, rx + rw)
                y = random.randint(ry, ry + rh)
            else:
                x, y = targets[0]

            if action == "slide":
                adb.shell("input", "swipe", str(x), str(y), str(x), str(y), str(duration))
                print(f"  [{t_ms:>6}ms] {action:<12} -> hold {duration}ms @ ({x},{y})",
                      flush=True)
            else:
                adb.shell("input", "tap", str(x), str(y))
                print(f"  [{t_ms:>6}ms] {action:<12} -> tap @ ({x},{y})", flush=True)

    print("Playback complete.")



def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Semantic macro record/playback test")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("record", help="record taps as actions until Ctrl+C")
    p_play = sub.add_parser("play", help=f"replay a macro json (default {OUTPUT_FILE})")
    p_play.add_argument("file", nargs="?", default=OUTPUT_FILE,
                        help="macro json to replay")

    args = parser.parse_args(argv)
    if args.cmd == "record":
        record_session()
    elif args.cmd == "play":
        playback_session(args.file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
