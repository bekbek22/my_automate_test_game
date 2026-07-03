
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, List, Optional



@dataclass
class Config:

    adb_host: str = "127.0.0.1"
    adb_port: int = 16384

    jitter_px: int = 3
    delay_jitter_ms: int = 75
    tap_below_ms: int = 60

    poll_interval_s: float = 0.5
    pause_timeout_s: float = 120.0
    guard_interval_s: float = 1.0
    debounce_reads: int = 2

    @property
    def serial(self) -> str:
        return f"{self.adb_host}:{self.adb_port}"



@dataclass
class Gesture:

    t: float
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int

    @property
    def is_tap(self) -> bool:
        return self.x1 == self.x2 and self.y1 == self.y2


@dataclass
class Session:

    width: int
    height: int
    gestures: List[Gesture] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "width": self.width,
                "height": self.height,
                "gestures": [asdict(g) for g in self.gestures],
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> "Session":
        raw = json.loads(text)
        return cls(
            width=raw["width"],
            height=raw["height"],
            gestures=[Gesture(**g) for g in raw["gestures"]],
        )



@dataclass
class Screenshot:

    width: int
    height: int
    data: bytes
    offset: int

    @classmethod
    def from_raw(cls, raw: bytes) -> "Screenshot":
        w = int.from_bytes(raw[0:4], "little")
        h = int.from_bytes(raw[4:8], "little")
        offset = len(raw) - (w * h * 4)
        if w <= 0 or h <= 0 or offset < 0:
            raise RuntimeError("Unrecognized screencap buffer (bad dimensions).")
        return cls(width=w, height=h, data=raw, offset=offset)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        x = max(0, min(self.width - 1, x))
        y = max(0, min(self.height - 1, y))
        i = self.offset + (y * self.width + x) * 4
        return self.data[i], self.data[i + 1], self.data[i + 2]

    def region_avg(self, x: int, y: int, w: int, h: int,
                   step: int = 8) -> tuple[int, int, int]:
        rs = gs = bs = n = 0
        for yy in range(y, min(y + h, self.height), step):
            for xx in range(x, min(x + w, self.width), step):
                r, g, b = self.pixel(xx, yy)
                rs += r; gs += g; bs += b; n += 1
        if n == 0:
            return (0, 0, 0)
        return (rs // n, gs // n, bs // n)


def color_close(c1: tuple[int, int, int], c2: tuple[int, int, int],
                tol: int) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(c1, c2))



USE_PERSISTENT_ADB = True


class Adb:

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.serial = cfg.serial
        self._dev = None
        self._dev_tried = False

    def _device(self):
        if not USE_PERSISTENT_ADB:
            return None
        if self._dev is not None or self._dev_tried:
            return self._dev
        self._dev_tried = True
        try:
            from ppadb.client import Client
            self._dev = Client(host="127.0.0.1", port=5037).device(self.serial)
        except Exception:
            self._dev = None
        return self._dev

    def _drop_device(self) -> None:
        self._dev = None
        self._dev_tried = False

    def _base(self) -> List[str]:
        return ["adb", "-s", self.serial]

    def connect(self) -> None:
        subprocess.run(
            ["adb", "connect", self.serial],
            capture_output=True, text=True, check=False,
        )
        out = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, check=False
        ).stdout
        if self.serial not in out:
            raise RuntimeError(
                f"ADB device {self.serial} not found. Start MuMu, then run "
                f"`adb connect {self.serial}` and `adb devices` to verify."
            )

    def shell(self, *args: str) -> str:
        dev = self._device()
        if dev is not None:
            try:
                return dev.shell(" ".join(args))
            except Exception:
                self._drop_device()
        return subprocess.run(
            self._base() + ["shell", *args],
            capture_output=True, text=True, check=False,
        ).stdout

    def shell_stream(self, *args: str) -> subprocess.Popen:
        return subprocess.Popen(
            self._base() + ["shell", *args],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )


    def focused_window(self) -> str:
        out = self.shell("dumpsys", "window", "windows")
        for key in ("mCurrentFocus", "mFocusedApp"):
            m = re.search(rf"{key}=.*", out)
            if m:
                return m.group(0).strip()
        return ""

    def inspect(self) -> None:
        w, h = self.display_size()
        print(f"serial         : {self.serial}")
        print(f"display size   : {w}x{h}")
        print(f"focused window : {self.focused_window() or '<unknown>'}")
        try:
            dev, xm, ym = self.find_touch_device()
            print(f"touch device   : {dev} (panel {xm}x{ym})")
        except RuntimeError as exc:
            print(f"touch device   : <not found> ({exc})")

    def display_size(self) -> tuple[int, int]:
        out = self.shell("wm", "size")
        m = re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise RuntimeError(f"Could not parse `wm size` output: {out!r}")
        return int(m.group(1)), int(m.group(2))

    def exec_out(self, *args: str) -> bytes:
        return subprocess.run(
            self._base() + ["exec-out", *args],
            capture_output=True, check=False,
        ).stdout

    def screenshot(self) -> Screenshot:
        dev = self._device()
        if dev is not None:
            try:
                conn = dev.create_connection()
                with conn:
                    conn.send("exec:/system/bin/screencap")
                    raw = conn.read_all()
                if raw:
                    return Screenshot.from_raw(raw)
            except Exception:
                self._drop_device()
        raw = self.exec_out("screencap")
        if not raw:
            raise RuntimeError("screencap returned no data (device/connection?).")
        return Screenshot.from_raw(raw)

    def find_touch_device(self) -> tuple[str, int, int]:
        out = self.shell("getevent", "-pl")
        cur_dev: Optional[str] = None
        dev_x_max = dev_y_max = 0
        best: Optional[tuple[str, int, int]] = None

        for line in out.splitlines():
            dev_match = re.match(r"add device \d+: (.+)", line.strip())
            if dev_match:
                if cur_dev and dev_x_max and dev_y_max:
                    best = (cur_dev, dev_x_max, dev_y_max)
                cur_dev = dev_match.group(1).strip()
                dev_x_max = dev_y_max = 0
                continue

            ax = re.search(r"ABS_MT_POSITION_X.*max (\d+)", line)
            ay = re.search(r"ABS_MT_POSITION_Y.*max (\d+)", line)
            if ax:
                dev_x_max = int(ax.group(1))
            if ay:
                dev_y_max = int(ay.group(1))

        if cur_dev and dev_x_max and dev_y_max:
            best = (cur_dev, dev_x_max, dev_y_max)
        if best is None:
            raise RuntimeError("No multitouch input device found via getevent -pl.")
        return best



class Recorder:

    LINE_RE = re.compile(
        r"\[\s*([\d.]+)\]\s+\S+:\s+(\w+)\s+(\w+)\s+([0-9a-fA-F]+)"
    )

    def __init__(self, cfg: Config, adb: Adb):
        self.cfg = cfg
        self.adb = adb
        self._proc: Optional[subprocess.Popen] = None

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()

    def record(self) -> Session:
        device, x_max, y_max = self.adb.find_touch_device()
        width, height = self.adb.display_size()
        print(f"Recording from {device} (panel {x_max}x{y_max} -> "
              f"display {width}x{height}). Press Ctrl-C to stop.")

        sx = width / x_max
        sy = height / y_max

        proc = self.adb.shell_stream("getevent", "-lt", device)
        self._proc = proc
        gestures: List[Gesture] = []

        start_t: Optional[float] = None
        down_t: Optional[float] = None
        first_x = first_y = 0
        cur_x = cur_y = 0
        touching = False

        try:
            for line in proc.stdout:
                m = self.LINE_RE.search(line)
                if not m:
                    continue
                _kts, etype, code, value_hex = m.groups()
                value = int(value_hex, 16)
                now = time.monotonic()
                if start_t is None:
                    start_t = now

                if code == "ABS_MT_POSITION_X":
                    cur_x = int(value * sx)
                elif code == "ABS_MT_POSITION_Y":
                    cur_y = int(value * sy)
                elif code == "ABS_MT_TRACKING_ID":
                    if value == 0xFFFFFFFF:
                        if touching and down_t is not None:
                            gestures.append(Gesture(
                                t=round(down_t - start_t, 4),
                                x1=first_x, y1=first_y,
                                x2=cur_x, y2=cur_y,
                                duration_ms=int((now - down_t) * 1000),
                            ))
                        touching = False
                    else:
                        touching = True
                        down_t = now
                        first_x, first_y = cur_x, cur_y
        except KeyboardInterrupt:
            print("\nStopping recorder...")
        finally:
            proc.terminate()

        print(f"Captured {len(gestures)} gesture(s).")
        return Session(width=width, height=height, gestures=gestures)



StateCheck = Callable[[], bool]


def default_state_check(adb: Adb) -> bool:
    return False


def throttled(check: StateCheck, interval_s: float) -> StateCheck:
    state = {"t": -1.0, "result": False}

    def wrapper() -> bool:
        now = time.monotonic()
        if now - state["t"] >= interval_s:
            state["result"] = check()
            state["t"] = now
        return state["result"]

    return wrapper


def screenshot_state_check(adb: Adb, screen: Screenshot) -> bool:
    return False


def debounced(check: StateCheck, reads: int) -> StateCheck:
    state: dict = {"committed": None, "streak": 0}

    def wrapper() -> bool:
        raw = check()
        if state["committed"] is None:
            state["committed"] = raw
        elif raw == state["committed"]:
            state["streak"] = 0
        else:
            state["streak"] += 1
            if state["streak"] >= reads:
                state["committed"] = raw
                state["streak"] = 0
        return state["committed"]

    return wrapper


def _raw_guard(strategy: str, adb: Adb) -> StateCheck:
    if strategy == "focus":
        return lambda: default_state_check(adb)
    if strategy == "screen":
        return lambda: screenshot_state_check(adb, adb.screenshot())
    raise ValueError(f"unknown guard strategy: {strategy!r}")


def make_guard(cfg: Config, adb: Adb, strategy: str) -> StateCheck:
    raw = _raw_guard(strategy, adb)
    return throttled(debounced(raw, cfg.debounce_reads), cfg.guard_interval_s)


def run_guard_test(cfg: Config, adb: Adb, strategy: str) -> None:
    check = debounced(_raw_guard(strategy, adb), cfg.debounce_reads)
    label = {False: "Screen Clear", True: "Pop-up Detected"}

    def stamp() -> str:
        return time.strftime("%H:%M:%S")

    print(f"Guard-test [{strategy}] -- evaluating every "
          f"{cfg.guard_interval_s:.1f}s, debounce={cfg.debounce_reads} "
          f"reads. Press Ctrl-C to stop.")

    prev: Optional[bool] = None
    try:
        while True:
            try:
                state = check()
            except RuntimeError as exc:
                print(f"[{stamp()}] guard error: {exc}")
                time.sleep(cfg.guard_interval_s)
                continue

            if prev is None:
                print(f"[{stamp()}] initial state: {label[state]}")
            elif state != prev:
                print(f"[{stamp()}] [STATE CHANGE] "
                      f"{label[prev]} -> {label[state]}")
            prev = state
            time.sleep(cfg.guard_interval_s)
    except KeyboardInterrupt:
        print(f"\n[{stamp()}] guard-test stopped.")



class Player:

    def __init__(self, cfg: Config, adb: Adb,
                 state_check: Optional[StateCheck] = None):
        self.cfg = cfg
        self.adb = adb
        self.state_check: StateCheck = state_check or (lambda: False)

    def _wait_until_clear(self) -> None:
        if not self.state_check():
            return
        print("[pause] interrupting event detected -- waiting for screen to clear...")
        waited = 0.0
        while self.state_check():
            if waited >= self.cfg.pause_timeout_s:
                print(f"[pause] timed out after {self.cfg.pause_timeout_s:.0f}s; "
                      f"resuming anyway.")
                return
            time.sleep(self.cfg.poll_interval_s)
            waited += self.cfg.poll_interval_s
        print(f"[resume] screen clear after {waited:.1f}s; continuing.")

    def _jitter(self, v: int, lo: int, hi: int) -> int:
        j = random.randint(-self.cfg.jitter_px, self.cfg.jitter_px)
        return max(lo, min(hi, v + j))

    def play(self, session: Session, loops: int = 1,
             stop_check: Optional[Callable[[], bool]] = None) -> None:
        w, h = session.width, session.height

        def stop() -> bool:
            return bool(stop_check and stop_check())

        def sleep_until(target: float) -> None:
            while not stop():
                remaining = target - time.monotonic()
                if remaining <= 0.0:
                    return
                time.sleep(min(0.02, remaining))

        i = 0
        while (loops <= 0 or i < loops) and not stop():
            if loops > 1 or loops <= 0:
                total = "inf" if loops <= 0 else str(loops)
                print(f"--- loop {i + 1}/{total} ---")

            macro_start = time.monotonic()
            for g in session.gestures:
                if stop():
                    return

                pause_t0 = time.monotonic()
                self._wait_until_clear()
                paused = time.monotonic() - pause_t0
                if paused > 0.0:
                    macro_start += paused

                jitter = random.uniform(
                    -self.cfg.delay_jitter_ms, self.cfg.delay_jitter_ms
                ) / 1000.0
                sleep_until(macro_start + g.t + jitter)
                if stop():
                    return

                x1 = self._jitter(g.x1, 0, w - 1)
                y1 = self._jitter(g.y1, 0, h - 1)
                stationary = (g.x1 == g.x2 and g.y1 == g.y2)

                if g.duration_ms > 0:
                    if stationary:
                        x2, y2 = x1, y1
                    else:
                        x2 = self._jitter(g.x2, 0, w - 1)
                        y2 = self._jitter(g.y2, 0, h - 1)
                    self.adb.shell("input", "swipe", str(x1), str(y1),
                                   str(x2), str(y2), str(g.duration_ms))
                    kind = "hold" if stationary else "swipe"
                    print(f"{kind} ({x1},{y1})->({x2},{y2}) {g.duration_ms}ms")
                elif stationary:
                    self.adb.shell("input", "tap", str(x1), str(y1))
                    print(f"tap ({x1},{y1})")
                else:
                    x2 = self._jitter(g.x2, 0, w - 1)
                    y2 = self._jitter(g.y2, 0, h - 1)
                    dur = max(1, g.duration_ms)
                    self.adb.shell("input", "swipe", str(x1), str(y1),
                                   str(x2), str(y2), str(dur))
                    print(f"swipe ({x1},{y1})->({x2},{y2}) {dur}ms")
            i += 1



def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[3])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="record a new macro session")
    p_rec.add_argument("file", help="output JSON session file")

    p_play = sub.add_parser("play", help="replay a recorded session")
    p_play.add_argument("file", help="input JSON session file")
    p_play.add_argument("--loops", type=int, default=1, help="repeat count")
    p_play.add_argument(
        "--guard", choices=["none", "focus", "screen"], default="none",
        help="pause/resume guard: 'focus' (dumpsys window) or 'screen' "
             "(screenshot pixel/color check); default none",
    )

    sub.add_parser("inspect", help="print current on-screen state")

    p_gt = sub.add_parser(
        "guard-test", help="evaluate a guard in isolation and log transitions")
    p_gt.add_argument(
        "--guard", choices=["focus", "screen"], default="screen",
        help="which guard strategy to test (default screen)")

    p_px = sub.add_parser("pixel", help="print the color at a screen coordinate")
    p_px.add_argument("x", type=int)
    p_px.add_argument("y", type=int)

    args = parser.parse_args(argv)

    cfg = Config()
    adb = Adb(cfg)
    adb.connect()

    if args.cmd == "record":
        session = Recorder(cfg, adb).record()
        with open(args.file, "w", encoding="utf-8") as fh:
            fh.write(session.to_json())
        print(f"Saved -> {args.file}")
    elif args.cmd == "play":
        with open(args.file, "r", encoding="utf-8") as fh:
            session = Session.from_json(fh.read())
        guard: Optional[StateCheck] = (
            None if args.guard == "none" else make_guard(cfg, adb, args.guard)
        )
        Player(cfg, adb, state_check=guard).play(session, loops=args.loops)
    elif args.cmd == "inspect":
        adb.inspect()
    elif args.cmd == "guard-test":
        run_guard_test(cfg, adb, args.guard)
    elif args.cmd == "pixel":
        r, g, b = adb.screenshot().pixel(args.x, args.y)
        print(f"({args.x},{args.y}) -> RGB ({r},{g},{b})  hex #{r:02x}{g:02x}{b:02x}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
