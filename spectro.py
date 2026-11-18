"""Spectrometer core: device access, spectral processing, kinetic runs, saving.

Hardware-free with ``MockSpectrometer`` so the app and tests run anywhere.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    import h5py
except ImportError:  # HDF5 output is optional
    h5py = None

SKIP_PIXELS = 2          # Flame-S: pixel 1 is a hot pixel; exclude from saturation checks
SATURATION_FRACTION = 0.98
MIN_REF_COUNTS = 50.0    # below this the reference has no usable light -> absorbance = NaN


# ---------------------------------------------------------------- devices

class MockSpectrometer:
    """Stands in for seabreeze.spectrometers.Spectrometer (same method names).

    scene "absorbance": a halogen-like lamp through a sample whose 520 nm band
    bleaches with a 30 s lifetime. scene "fluorescence": 405 nm laser scatter
    plus a 600 nm emission band that photobleaches with a 20 s lifetime.
    """
    model = "MOCK"
    serial_number = "MOCK0001"
    pixels = 2048
    max_intensity = 65535.0
    integration_time_micros_limits = (1000, 655_350_000)

    def __init__(self, seed: int = 0):
        self._wl = np.linspace(180.3, 881.1, self.pixels)
        self._it_s = 0.01
        self._t0 = time.perf_counter()
        self._rng = np.random.default_rng(seed)
        self.sample_in = True
        self.scene = "absorbance"

    def wavelengths(self):
        return self._wl.copy()

    def integration_time_micros(self, us):
        self._it_s = us / 1e6

    def intensities(self, correct_dark_counts=False, correct_nonlinearity=False):
        time.sleep(self._it_s)
        t = time.perf_counter() - self._t0
        if self.scene == "fluorescence":
            laser = 5.0e6 * self._it_s * np.exp(-(((self._wl - 405.0) / 1.5) ** 2))
            emission = (4.0e5 * self._it_s * math.exp(-t / 20.0)
                        * np.exp(-(((self._wl - 600.0) / 40.0) ** 2)))
            raw = 1500.0 + laser + (emission if self.sample_in else 0)
            return np.clip(raw + self._rng.normal(0, 12, self.pixels), 0, self.max_intensity)
        lamp = 3.0e6 * self._it_s * np.exp(-(((self._wl - 620.0) / 160.0) ** 2))
        a = 0.8 * math.exp(-t / 30.0) * np.exp(-(((self._wl - 520.0) / 25.0) ** 2))
        signal = lamp * 10 ** (-a) if self.sample_in else lamp
        raw = 1500.0 + signal + self._rng.normal(0, 12, self.pixels)
        return np.clip(raw, 0, self.max_intensity)

    def close(self):
        pass


def open_device(mock: bool = False):
    if mock:
        return MockSpectrometer()
    import seabreeze.spectrometers as sb
    devices = sb.list_devices()
    if not devices:
        raise RuntimeError("No spectrometer found. Check the USB cable and drivers "
                           "(Windows: run `seabreeze_os_setup` once as administrator).")
    return sb.Spectrometer(devices[0])


class Device:
    """Thread-safe wrapper: every USB call goes through one lock."""

    def __init__(self, spec):
        self.spec = spec
        self.lock = threading.Lock()
        self.wavelengths = np.asarray(spec.wavelengths(), dtype=float)
        lo, hi = spec.integration_time_micros_limits
        self.it_limits_s = (lo / 1e6, hi / 1e6)
        self.max_counts = float(spec.max_intensity)
        self.integration_s = 0.0
        self.n_avg = 1
        self.set_integration(0.1)

    @property
    def info(self):
        return {"model": self.spec.model, "serial": self.spec.serial_number,
                "pixels": len(self.wavelengths),
                "wl_range": [float(self.wavelengths[0]), float(self.wavelengths[-1])],
                "it_limits_s": list(self.it_limits_s), "max_counts": self.max_counts}

    def set_integration(self, seconds: float):
        lo, hi = self.it_limits_s
        seconds = min(max(float(seconds), lo), hi)
        with self.lock:
            self.spec.integration_time_micros(int(round(seconds * 1e6)))
            self.integration_s = seconds
            # The detector free-runs: the next frame may have started under the old
            # setting, so throw one away.
            self._read_raw()
        return seconds

    def _read_raw(self):
        try:
            return np.asarray(self.spec.intensities(correct_dark_counts=True,
                                                    correct_nonlinearity=True), dtype=float)
        except TypeError:  # backends without correction kwargs
            return np.asarray(self.spec.intensities(), dtype=float)

    def read(self, n_avg: int | None = None):
        """Average ``n_avg`` frames. Returns (counts, t_center) with t_center on the
        perf_counter clock at the middle of the integration window(s)."""
        n = max(1, int(n_avg or self.n_avg))
        with self.lock:
            acc = self._read_raw()
            for _ in range(n - 1):
                acc += self._read_raw()
            t_end = time.perf_counter()
            span = n * self.integration_s
        return acc / n, t_end - span / 2

    def is_saturated(self, raw):
        return bool(raw[SKIP_PIXELS:].max() >= SATURATION_FRACTION * self.max_counts)

    def saturated_ranges(self, raw):
        """[[start, end] nm, ...] for each saturated region, e.g. a laser scatter line."""
        hit = np.flatnonzero(raw[SKIP_PIXELS:] >= SATURATION_FRACTION * self.max_counts)
        wl = self.wavelengths[SKIP_PIXELS:]
        runs = np.split(hit, np.flatnonzero(np.diff(hit) > 1) + 1) if hit.size else []
        return [[round(float(wl[r[0]]), 1), round(float(wl[r[-1]]), 1)] for r in runs]

    def close(self):
        with self.lock:
            try:
                self.spec.close()
            except Exception:
                pass


# ---------------------------------------------------------------- processing

@dataclass
class Background:
    """A stored dark or reference, valid only for the settings it was taken with."""
    counts: np.ndarray
    integration_s: float
    n_avg: int
    taken: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def matches(self, dev: Device) -> bool:
        return math.isclose(self.integration_s, dev.integration_s, rel_tol=1e-6)

    def summary(self, dev: Device):
        return {"taken": self.taken, "integration_s": self.integration_s,
                "n_avg": self.n_avg, "valid": self.matches(dev)}


def process(raw, dark: np.ndarray | None, ref: np.ndarray | None):
    """Dark-correct and, if a reference exists, compute absorbance.

    ``raw`` may be one spectrum or a (frames, pixels) block.

    Absorbance is NaN wherever the reference or sample has no usable light,
    rather than clipped to an artificial ceiling.
    """
    counts = raw - dark if dark is not None else raw.copy()
    absorbance = None
    if ref is not None:
        ref_c = np.broadcast_to(ref - dark if dark is not None else ref, counts.shape)
        ok = (ref_c > MIN_REF_COUNTS) & (counts > 0)
        absorbance = np.full_like(counts, np.nan)
        absorbance[ok] = -np.log10(counts[ok] / ref_c[ok])
    return counts, absorbance


def band_average(wl, y, center, half_width):
    if y is None:
        return float("nan")
    m = np.abs(wl - center) <= half_width
    if not m.any():
        m = np.zeros_like(wl, dtype=bool)
        m[np.argmin(np.abs(wl - center))] = True
    vals = y[m]
    vals = vals[np.isfinite(vals)]
    return float(vals.mean()) if vals.size else float("nan")


def for_display(a):
    """JSON list for plotting, with the non-optical edge pixels blanked."""
    out = jsonable(a)
    if out is not None:
        out[:SKIP_PIXELS] = [None] * SKIP_PIXELS
    return out


def jsonable(a):
    """ndarray -> list with NaN/inf as None (JSON has no NaN)."""
    if a is None:
        return None
    a = np.round(np.asarray(a, dtype=float), 5)
    if np.isfinite(a).all():
        return a.tolist()                     # fast path: all in C
    return [v if math.isfinite(v) else None for v in a.tolist()]


# ---------------------------------------------------------------- saving

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def safe_name(name: str) -> str:
    """Filename-safe on Windows, macOS and Linux."""
    name = _BAD.sub("_", (name or "").strip()).strip(" ._")
    name = re.sub(r"[\s_]+", "_", name)
    return name[:80] or "untitled"


def stamped_path(folder: Path, name: str, suffix: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{datetime.now():%Y-%m-%d_%H%M%S}_{safe_name(name)}"
    p, k = folder / f"{base}{suffix}", 2
    while p.exists():
        p, k = folder / f"{base}_{k}{suffix}", k + 1
    return p


def save_spectrum(folder: Path, name: str, notes: str, wl, raw, dark, ref, meta: dict,
                  dark_label: str = "dark_counts"):
    counts, absorbance = process(raw, dark, ref)
    cols = {"wavelength_nm": wl, "raw_counts": raw}
    if dark is not None:
        cols[dark_label] = dark
    if ref is not None:
        cols["reference_counts"] = ref
    cols["corrected_counts"] = counts
    if absorbance is not None:
        cols["absorbance"] = absorbance
    path = stamped_path(folder, name, ".csv")
    np.savetxt(path, np.column_stack(list(cols.values())), delimiter=",",
               header=",".join(cols), comments="", fmt="%.6g")
    meta = {**meta, "name": name, "notes": notes, "file": path.name, "columns": list(cols)}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return path


# ---------------------------------------------------------------- kinetics

@dataclass
class RunConfig:
    name: str = "kinetics"
    notes: str = ""
    delay_s: float = 0.0          # countdown before t = 0
    duration_s: float = 60.0      # 0 = until stopped
    interval_s: float = 0.0       # 0 = back-to-back frames
    n_avg: int = 1
    traces_nm: list = field(default_factory=lambda: [])
    half_width_nm: float = 2.0
    save_hdf5: bool = False
    measurement: str = "absorbance"   # or "fluorescence" (set by the server)
    excitation_nm: float | None = None

    @classmethod
    def from_dict(cls, d: dict):
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        cfg = cls(**known)
        cfg.delay_s = max(0.0, float(cfg.delay_s))
        cfg.duration_s = max(0.0, float(cfg.duration_s))
        cfg.interval_s = max(0.0, float(cfg.interval_s))
        cfg.n_avg = max(1, int(cfg.n_avg))
        cfg.half_width_nm = max(0.0, float(cfg.half_width_nm))
        cfg.traces_nm = [float(x) for x in cfg.traces_nm][:8]
        return cfg


class KineticRun(threading.Thread):
    """Countdown, then acquire spectra on a schedule.

    During the run each frame is appended to ``frames.f32`` (raw binary, crash
    safe, microseconds per frame) so Python work cannot delay the next read.
    When the run ends the folder is finalized into:
      counts.csv      time_s + dark-corrected counts at every wavelength
      absorbance.csv  same layout, only if a valid reference was set
      traces.csv      time_s + band-averaged signal at each trace wavelength
      run.json        settings, dark/reference spectra, events, timing stats
      run.h5          all of the above in one file (optional)
    Spectra are timestamped at the centre of their integration window.
    """

    def __init__(self, dev: Device, cfg: RunConfig, dark, ref, data_dir: Path):
        super().__init__(daemon=True)
        self.dev, self.cfg, self.dark, self.ref = dev, cfg, dark, ref
        self.folder = stamped_path(Path(data_dir) / "kinetics", cfg.name)
        self.folder.mkdir(parents=True)
        self.state = "countdown"      # countdown -> running -> saving -> done/aborted/error
        self.error = None
        self.events: list[dict] = []
        self.t_zero = None            # perf_counter time of t = 0
        self.t_start = time.perf_counter()
        self.trace_t: list[float] = []
        self.trace_y: list[list] = []
        self.latest = None
        self.n = 0
        self.saturated_frames = 0
        self._halt = threading.Event()
        self._lock = threading.Lock()

    # -- control
    def stop(self):
        self._halt.set()

    def mark(self, label: str):
        planned_zero = self.t_start + self.cfg.delay_s
        t = time.perf_counter() - (self.t_zero if self.t_zero is not None else planned_zero)
        ev = {"t_s": round(t, 4), "label": label or "event",
              "wall": datetime.now().isoformat(timespec="milliseconds")}
        with self._lock:
            self.events.append(ev)
        return ev

    # -- status for the UI
    def status(self, since: int = 0):
        now = time.perf_counter()
        with self._lock:
            if self.state == "running":
                elapsed = now - self.t_zero
            else:
                elapsed = self.trace_t[-1] if self.trace_t else 0.0
            out = {
                "state": self.state, "error": self.error, "folder": str(self.folder),
                "n": self.n, "saturated_frames": self.saturated_frames,
                "countdown_s": max(0.0, self.t_start + self.cfg.delay_s - now)
                if self.state == "countdown" else 0.0,
                "elapsed_s": elapsed, "traces_nm": self.cfg.traces_nm, "since": since,
                "t": self.trace_t[since:], "y": self.trace_y[since:],
                "events": list(self.events), "config": asdict(self.cfg),
            }
            if since == 0:  # first poll: give a freshly opened page the wavelength axis
                out["wavelengths"] = jsonable(self.dev.wavelengths)
            latest = self.latest
        if latest is not None:  # convert outside the lock; send only the plotted curve
            counts, absorbance = process(latest["raw"], self.dark, self.ref)
            out["latest"] = {"t": latest["t"], "saturated": latest["saturated"],
                             "saturated_nm": self.dev.saturated_ranges(latest["raw"]),
                             "kind": "counts" if absorbance is None else "absorbance",
                             "y": for_display(counts if absorbance is None else absorbance)}
        return out

    # -- worker
    def run(self):
        try:
            if self._halt.wait(self.cfg.delay_s):
                self.state = "aborted"
                return
            self.t_zero = time.perf_counter()
            self.state = "running"
            self._acquire()
            final = "aborted" if self._halt.is_set() else "done"
            self.state = "saving"
            self._finalize()
            self.state = final
        except Exception as e:  # keep frames.f32 so nothing is lost
            self.state, self.error = "error", f"{type(e).__name__}: {e}"
        finally:
            self._write_meta()

    def _acquire(self):
        cfg, wl = self.cfg, self.dev.wavelengths
        bands = [np.abs(wl - c) <= cfg.half_width_nm for c in cfg.traces_nm]
        bands = [m if m.any() else (np.arange(len(wl)) == np.argmin(np.abs(wl - c)))
                 for m, c in zip(bands, cfg.traces_nm)]
        dark = self.dark if self.dark is not None else 0.0
        ref_c = None if self.ref is None else self.ref - dark
        k = 0
        with open(self.folder / "frames.f32", "wb") as fb:
            while not self._halt.is_set():
                if cfg.interval_s > 0:  # wait for the k-th scheduled slot
                    wait = self.t_zero + k * cfg.interval_s - time.perf_counter()
                    if wait > 0 and self._halt.wait(wait):
                        break
                raw, t_mid = self.dev.read(cfg.n_avg)
                t = t_mid - self.t_zero
                if cfg.duration_s and t > cfg.duration_s:
                    break
                raw.astype(np.float32).tofile(fb)
                counts = raw - dark
                ys = []
                for m in bands:  # a few small numpy ops: well under a millisecond
                    c = counts[m].mean()
                    if ref_c is None:
                        ys.append(round(float(c), 2))
                    else:
                        r = ref_c[m].mean()
                        ys.append(round(float(-np.log10(c / r)), 6)
                                  if c > 0 and r > MIN_REF_COUNTS else None)
                sat = self.dev.is_saturated(raw)
                with self._lock:
                    self.n += 1
                    self.saturated_frames += sat
                    self.trace_t.append(round(t, 5))
                    self.trace_y.append(ys)
                    self.latest = {"t": t, "saturated": sat, "raw": raw}
                k += 1
                if cfg.interval_s > 0:  # skip slots already missed rather than bursting
                    k = max(k, int((time.perf_counter() - self.t_zero) / cfg.interval_s) + 1)

    def _finalize(self, chunk: int = 2000):
        """Turn frames.f32 into CSV (and HDF5), chunk by chunk to bound memory."""
        f, wl, cfg = self.folder, self.dev.wavelengths, self.cfg
        n_px, n = len(wl), self.n
        frames = np.memmap(f / "frames.f32", dtype=np.float32, mode="r", shape=(n, n_px)) \
            if n else np.zeros((0, n_px), np.float32)
        t = np.asarray(self.trace_t[:n], dtype=float)
        has_abs = self.ref is not None
        hdr = "time_s," + ",".join(f"{w:.3f}" for w in wl)
        h5 = None
        if cfg.save_hdf5 and h5py is not None:
            h5 = h5py.File(f / "run.h5", "w")
            h5["wavelength_nm"], h5["time_s"] = wl, t
            opts = dict(dtype="f4", chunks=(min(max(n, 1), 256), n_px), compression="gzip")
            h5.create_dataset("counts", (n, n_px), **opts)
            if has_abs:
                h5.create_dataset("absorbance", (n, n_px), **opts)
            for key, arr in (("dark_counts", self.dark), ("reference_counts", self.ref)):
                if arr is not None:
                    h5[key] = arr
            h5.attrs["config"] = json.dumps(asdict(cfg))
            h5.attrs["integration_s"] = self.dev.integration_s
            h5.attrs["events"] = json.dumps(self.events)
        files = {"counts": open(f / "counts.csv", "w", newline="")}
        if has_abs:
            files["absorbance"] = open(f / "absorbance.csv", "w", newline="")
        try:
            for fh in files.values():
                fh.write(hdr + "\n")
            for i in range(0, n, chunk):
                raw = np.asarray(frames[i:i + chunk], dtype=float)
                counts, absorbance = process(raw, self.dark, self.ref)
                tt = t[i:i + chunk, None]
                np.savetxt(files["counts"], np.hstack([tt, counts]), delimiter=",",
                           fmt=["%.5f"] + ["%.1f"] * n_px)
                if has_abs:
                    np.savetxt(files["absorbance"], np.hstack([tt, absorbance]),
                               delimiter=",", fmt=["%.5f"] + ["%.5f"] * n_px)
                if h5 is not None:
                    h5["counts"][i:i + len(raw)] = counts
                    if has_abs:
                        h5["absorbance"][i:i + len(raw)] = absorbance
        finally:
            for fh in files.values():
                fh.close()
            if h5 is not None:
                h5.close()
        with open(f / "traces.csv", "w", newline="") as ft:
            ft.write("time_s," + ",".join(f"{c:g}nm" for c in cfg.traces_nm) + "\n")
            for ti, ys in zip(self.trace_t, self.trace_y):
                ft.write(f"{ti:.5f}," + ",".join("" if y is None else f"{y:.6g}" for y in ys)
                         + "\n")
        del frames
        (f / "frames.f32").unlink()

    def _write_meta(self):
        dt = np.diff(self.trace_t) if len(self.trace_t) > 1 else np.array([])
        meta = {
            "name": self.cfg.name, "notes": self.cfg.notes, "state": self.state,
            "error": self.error, "config": asdict(self.cfg), "device": self.dev.info,
            "integration_s": self.dev.integration_s, "n_spectra": self.n,
            "saturated_frames": self.saturated_frames,
            "detector_corrections": ["electric_dark", "nonlinearity"],
            "time_reference": "t = 0 at end of countdown; spectra stamped at centre of "
                              "integration window",
            "mean_period_s": float(dt.mean()) if dt.size else None,
            "max_period_s": float(dt.max()) if dt.size else None,
            "events": self.events,
            "files": sorted(p.name for p in self.folder.iterdir()) + ["run.json"],
            "dark_counts": None if self.dark is None else self.dark.tolist(),
            "reference_counts": None if self.ref is None else self.ref.tolist(),
            "wavelength_nm": self.dev.wavelengths.tolist(),
        }
        if "frames.f32" in meta["files"]:
            meta["frames_f32_note"] = (f"Unfinalized raw frames: float32, shape "
                                       f"({self.n}, {len(self.dev.wavelengths)}), row-major")
        (self.folder / "run.json").write_text(json.dumps(meta, indent=1))
