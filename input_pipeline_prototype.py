#!/usr/bin/env python3
"""
Non-root ADB input pipeline prototype  (Step 1 of the production sequence).

Isolated, self-contained proof-of-concept that measures whether a persistent
`adb shell` channel + a bounded fire-and-forget worker pool beats the current
inline `subprocess.run(["adb","shell","input","tap",...])` model.

Everything here runs strictly under the ADB shell UID (2000). No root, no
`/dev/input`, no `sendevent`. We are only trying to kill the *host-side*
overhead (adb.exe spawn + TCP hop + shell-service open + `sh` fork). The
on-device JVM cold-start inside /system/bin/input remains the hard floor --
this prototype exists to quantify exactly how much of the 30-80ms is host-side
and therefore recoverable without the resident-injector milestone.

Three pieces, as specified:
  1. PersistentShell / SyncShell / FireShell -- long-lived `adb shell` pipes.
  2. InputPipeline -- bounded queue drained by a small worker pool, each worker
     owning its OWN persistent shell (a single stdin pipe is serial and would
     corrupt if multiple workers wrote to it concurrently). Fire-and-forget:
     workers never block on stdout, and drop events whose absolute deadline is
     already stale (emulator-lag guardrail).
  3. bench() -- prints a hard before/after microsecond delta.

Safety: default benchmark command is a benign no-op (`true`) so it measures the
pipeline itself without injecting taps. Pass `--real X Y` to measure a genuine
`input tap X Y` (this WILL tap the device at that coordinate).

Usage:
    python input_pipeline_prototype.py                    # safe, pipeline-only
    python input_pipeline_prototype.py --real 540 1200    # real input tap @ (540,1200)
    python input_pipeline_prototype.py --serial 127.0.0.1:7555 --workers 3
    python input_pipeline_prototype.py --simulate-lag-ms 120   # demo drop-if-stale
"""

from __future__ import annotations

import argparse
import queue
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Optional


# --------------------------------------------------------------------------- #
# ADB base command
# --------------------------------------------------------------------------- #
def adb_base(serial: Optional[str]) -> List[str]:
    return ["adb"] + (["-s", serial] if serial else [])


def inline_shell(serial: Optional[str], cmd: str) -> None:
    """Baseline: one fresh `adb shell <cmd>` process per call (the status quo)."""
    subprocess.run(
        adb_base(serial) + ["shell", cmd],
        capture_output=True, text=True, check=False,
    )


# --------------------------------------------------------------------------- #
# Persistent shells
# --------------------------------------------------------------------------- #
class SyncShell:
    """Long-lived `adb shell` used for *synchronous* round-trip measurement.

    Writes `<cmd>; echo <marker>` and reads stdout until the marker appears, so
    timing captures full device-side completion (including the input JVM) --
    apples-to-apples with the blocking inline baseline.
    """

    def __init__(self, serial: Optional[str]):
        self.proc = subprocess.Popen(
            adb_base(serial) + ["shell"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        self._seq = 0

    def run(self, cmd: str) -> None:
        assert self.proc.stdin and self.proc.stdout
        self._seq += 1
        marker = f"__done_{self._seq}__"
        self.proc.stdin.write(f"{cmd}; echo {marker}\n")
        self.proc.stdin.flush()
        for line in self.proc.stdout:
            if marker in line:
                return
        raise RuntimeError("persistent shell closed before marker")

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.write("exit\n")
                self.proc.stdin.flush()
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


class FireShell:
    """Long-lived `adb shell` for *fire-and-forget* dispatch.

    A daemon reader silently drains stdout so the device-side pipe buffer can
    never fill and stall the shell. `fire()` only writes -- it never waits for a
    result, which is what keeps the scheduler unblocked.
    """

    def __init__(self, serial: Optional[str]):
        self.proc = subprocess.Popen(
            adb_base(serial) + ["shell"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        self._alive = True
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

    def _drain(self) -> None:
        assert self.proc.stdout
        try:
            for _ in self.proc.stdout:      # discard everything
                if not self._alive:
                    break
        except Exception:
            pass

    def fire(self, cmd: str) -> None:
        assert self.proc.stdin
        try:
            self.proc.stdin.write(cmd + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            self._alive = False

    def close(self) -> None:
        self._alive = False
        try:
            if self.proc.stdin:
                self.proc.stdin.write("exit\n")
                self.proc.stdin.flush()
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


# --------------------------------------------------------------------------- #
# Bounded fire-and-forget pipeline
# --------------------------------------------------------------------------- #
@dataclass
class InputEvent:
    deadline: float      # time.monotonic() by which this should have fired
    cmd: str             # device-side shell command, e.g. "input tap 540 1200"


class InputPipeline:
    """Scheduler -> bounded queue -> small worker pool, each worker on its own
    persistent shell. Fire-and-forget with a drop-if-stale guardrail."""

    def __init__(self, serial: Optional[str], workers: int = 3,
                 stale_ms: float = 250.0, maxsize: int = 256,
                 simulate_lag_ms: float = 0.0):
        self.q: "queue.Queue[Optional[InputEvent]]" = queue.Queue(maxsize=maxsize)
        self.stale_s = stale_ms / 1000.0
        self.simulate_lag_s = simulate_lag_ms / 1000.0
        self.shells = [FireShell(serial) for _ in range(workers)]
        self.fired = 0
        self.dropped_stale = 0
        self.dropped_full = 0
        self._lock = threading.Lock()
        self._threads = [
            threading.Thread(target=self._worker, args=(i,), daemon=True)
            for i in range(workers)
        ]
        for t in self._threads:
            t.start()

    def _worker(self, idx: int) -> None:
        shell = self.shells[idx]
        while True:
            ev = self.q.get()
            try:
                if ev is None:                        # shutdown sentinel
                    return
                if self.simulate_lag_s:               # emulate an emulator stall
                    time.sleep(self.simulate_lag_s)
                lateness = time.monotonic() - ev.deadline
                if lateness > self.stale_s:           # guardrail: don't fire the past
                    with self._lock:
                        self.dropped_stale += 1
                    continue
                shell.fire(ev.cmd)
                with self._lock:
                    self.fired += 1
            finally:
                self.q.task_done()

    def submit(self, ev: InputEvent) -> bool:
        """Non-blocking hand-off. Returns False if the queue is saturated
        (back-pressure) -- the scheduler is never blocked by a slow device."""
        try:
            self.q.put_nowait(ev)
            return True
        except queue.Full:
            with self._lock:
                self.dropped_full += 1
            return False

    def drain(self) -> None:
        self.q.join()

    def close(self) -> None:
        for _ in self.shells:
            self.q.put(None)
        for t in self._threads:
            t.join(timeout=2)
        for s in self.shells:
            s.close()


# --------------------------------------------------------------------------- #
# Stats helpers
# --------------------------------------------------------------------------- #
def _summ(name: str, samples_s: List[float]) -> dict:
    us = [s * 1_000_000 for s in samples_s]
    us.sort()
    p95 = us[min(len(us) - 1, int(round(0.95 * (len(us) - 1))))]
    return {
        "name": name,
        "n": len(us),
        "mean_us": statistics.mean(us),
        "median_us": statistics.median(us),
        "p95_us": p95,
        "min_us": us[0],
        "max_us": us[-1],
    }


def _row(s: dict) -> str:
    return (f"  {s['name']:<28} n={s['n']:<4} "
            f"median={s['median_us']/1000:8.2f}ms  "
            f"mean={s['mean_us']/1000:8.2f}ms  "
            f"p95={s['p95_us']/1000:8.2f}ms")


# --------------------------------------------------------------------------- #
# Benchmark
# --------------------------------------------------------------------------- #
def bench(serial: Optional[str], count: int, cmd: str, workers: int,
          stale_ms: float, simulate_lag_ms: float) -> None:
    print("=" * 78)
    print("Non-root ADB input pipeline -- latency benchmark")
    print(f"  serial     : {serial or '<default device>'}")
    print(f"  command    : {cmd!r}")
    print(f"  count      : {count}   workers: {workers}   stale: {stale_ms:.0f}ms")
    print("=" * 78)

    # sanity: is adb present and a device reachable?
    try:
        chk = subprocess.run(adb_base(serial) + ["get-state"],
                             capture_output=True, text=True)
    except FileNotFoundError:
        print("[!] `adb` not found on PATH. Add platform-tools to PATH "
              "(or run from a shell where `adb devices` works) and retry.")
        return
    if "device" not in chk.stdout:
        print(f"[!] no device in 'device' state (adb get-state -> "
              f"{chk.stdout.strip()!r} {chk.stderr.strip()!r}).")
        print("    Start MuMu / check `adb devices` and retry.")
        return

    # --- A) inline baseline: fresh `adb shell` per call ---------------------- #
    a_samples: List[float] = []
    inline_shell(serial, "true")                       # warm adb server
    for _ in range(count):
        t0 = time.perf_counter()
        inline_shell(serial, cmd)
        a_samples.append(time.perf_counter() - t0)
    A = _summ("A) inline adb shell", a_samples)

    # --- B) persistent shell, synchronous round-trip ------------------------ #
    sh = SyncShell(serial)
    b_samples: List[float] = []
    try:
        sh.run("true")                                 # warm: pays shell startup once
        for _ in range(count):
            t0 = time.perf_counter()
            sh.run(cmd)
            b_samples.append(time.perf_counter() - t0)
    finally:
        sh.close()
    B = _summ("B) persistent shell (sync)", b_samples)

    # --- C) fire-and-forget hand-off latency (scheduler release) ------------ #
    pipe = InputPipeline(serial, workers=workers, stale_ms=stale_ms,
                         simulate_lag_ms=simulate_lag_ms)
    c_samples: List[float] = []
    t_wall0 = time.perf_counter()
    for _ in range(count):
        t0 = time.perf_counter()
        pipe.submit(InputEvent(deadline=time.monotonic(), cmd=cmd))
        c_samples.append(time.perf_counter() - t0)
    submit_wall = time.perf_counter() - t_wall0
    pipe.drain()
    drain_wall = time.perf_counter() - t_wall0
    fired, dstale, dfull = pipe.fired, pipe.dropped_stale, pipe.dropped_full
    pipe.close()
    C = _summ("C) fire-and-forget submit", c_samples)

    # --- report -------------------------------------------------------------- #
    print("\nPer-call latency (lower is better):")
    print(_row(A))
    print(_row(B))
    print(_row(C) + "   <- scheduler release, NOT input completion")

    host_saved = A["median_us"] - B["median_us"]
    print("\n" + "-" * 78)
    print("BEFORE / AFTER  (median):")
    print(f"  inline  adb shell      : {A['median_us']:10.1f} us  "
          f"({A['median_us']/1000:.2f} ms)")
    print(f"  persistent shell (sync): {B['median_us']:10.1f} us  "
          f"({B['median_us']/1000:.2f} ms)")
    print(f"  >> host-side saved     : {host_saved:10.1f} us  "
          f"({host_saved/1000:.2f} ms, {100*host_saved/A['median_us']:.0f}% faster)")
    print(f"     (remaining {B['median_us']/1000:.2f} ms is the on-device input "
          f"JVM floor -- only the resident injector crosses it)")
    print(f"  scheduler release      : {C['median_us']:10.1f} us  "
          f"({C['median_us']/1000:.3f} ms)  "
          f"= {A['median_us']/max(C['median_us'],1e-6):.0f}x faster to unblock")
    print("-" * 78)
    print(f"Fire-and-forget throughput: submitted {count} in "
          f"{submit_wall*1000:.1f}ms, fully drained in {drain_wall*1000:.1f}ms")
    print(f"  fired={fired}  dropped_stale={dstale}  dropped_full={dfull}")
    if simulate_lag_ms:
        print(f"  (simulate-lag {simulate_lag_ms:.0f}ms > stale {stale_ms:.0f}ms "
              f"-> drop-if-stale guardrail should trip)")
    print("=" * 78)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--serial", default=None,
                   help="adb device serial (e.g. 127.0.0.1:7555 for MuMu). "
                        "Omit if only one device is attached.")
    p.add_argument("--count", type=int, default=30, help="samples per method")
    p.add_argument("--workers", type=int, default=3, help="fire-and-forget workers")
    p.add_argument("--stale-ms", type=float, default=250.0,
                   help="drop events later than this past their deadline")
    p.add_argument("--real", nargs=2, type=int, metavar=("X", "Y"), default=None,
                   help="benchmark a REAL `input tap X Y` (taps the device!). "
                        "Default is a benign no-op that measures pipeline only.")
    p.add_argument("--simulate-lag-ms", type=float, default=0.0,
                   help="inject artificial per-worker delay to demo drop-if-stale")
    args = p.parse_args(argv)

    if args.real:
        cmd = f"input tap {args.real[0]} {args.real[1]}"
    else:
        cmd = "true"     # benign: exercises the full pipeline, injects nothing

    bench(args.serial, args.count, cmd, args.workers,
          args.stale_ms, args.simulate_lag_ms)
    return 0


if __name__ == "__main__":
    sys.exit(main())
