"""Check a real spectrometer: connection, a spectrum, and timing.

    python scripts/hardware_check.py          # run on any new machine (e.g. Windows) first

Reports frame rate and dropped frames at a few integration times, which tells
you how fast kinetics can run on this computer.
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spectro import Device, open_device  # noqa: E402

dev = Device(open_device())
info = dev.info
print(f"Device     : {info['model']}  S/N {info['serial']}")
print(f"Pixels     : {info['pixels']}  ({info['wl_range'][0]:.1f}-{info['wl_range'][1]:.1f} nm)")
print(f"Integration: {info['it_limits_s'][0]*1e3:g} ms - {info['it_limits_s'][1]:g} s")

dev.set_integration(0.1)
raw, _ = dev.read()
print(f"100 ms read: min {raw.min():.0f}, median {np.median(raw):.0f}, max {raw.max():.0f} counts"
      f"{'  (SATURATED)' if dev.is_saturated(raw) else ''}")

print("\nTiming (5 s at each integration time):")
for ms in (2, 5, 20, 100):
    dev.set_integration(ms / 1000)
    t, t_end = [], time.perf_counter() + 5
    while time.perf_counter() < t_end:
        t.append(dev.read()[1])
    dt = np.diff(t)
    drops = int((dt > 1.5 * ms / 1000).sum())
    print(f"  {ms:>4} ms: {len(t):5d} frames, mean period {dt.mean()*1e3:7.3f} ms, "
          f"max {dt.max()*1e3:6.2f} ms, dropped {drops} ({100*drops/len(dt):.2f}%)")
dev.close()
