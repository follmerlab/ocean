"""Ocean Optics Flame browser interface: spectra and kinetics.

    python app.py                 # real spectrometer, http://127.0.0.1:5001
    python app.py --mock          # simulated spectrometer (no hardware)
    python app.py --data-dir D:/data --host 0.0.0.0   # serve to the lab network
"""
from __future__ import annotations

import argparse
import logging
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import spectro
from spectro import Background, Device, KineticRun, RunConfig, for_display, jsonable, process

__version__ = "2.0.0"


class Station:
    """All instrument state for one spectrometer."""

    def __init__(self, data_dir: Path, mock: bool = False):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.mock = mock
        self.dev: Device | None = None
        self.dark: Background | None = None
        self.ref: Background | None = None
        self.last = None            # last captured spectrum, for "Save"
        self.live = False
        self.live_frame = None
        self.run: KineticRun | None = None
        self.connect_error = None
        self.measurement = "absorbance"   # "fluorescence": no reference, emission counts
        self.excitation_nm: float | None = None

    def connect(self):
        if self.busy:
            raise RuntimeError("Stop the kinetic run first.")
        self.stop_live()
        if self.dev:
            self.dev.close()
        self.dev = None
        try:
            self.dev = Device(spectro.open_device(self.mock))
            self.connect_error = None
        except Exception as e:
            self.connect_error = str(e)
            raise

    @property
    def busy(self):
        return self.run is not None and self.run.is_alive()

    def require(self):
        if self.dev is None:
            raise RuntimeError(self.connect_error or "Spectrometer not connected.")
        return self.dev

    def valid(self, bg: Background | None):
        return bg.counts if bg is not None and bg.matches(self.dev) else None

    @property
    def fluorescence(self):
        return self.measurement == "fluorescence"

    def active_ref(self):
        """The reference in use: none in fluorescence (emission is not ratioed)."""
        return None if self.fluorescence else self.valid(self.ref)

    def mode_meta(self):
        meta = {"measurement": self.measurement}
        if self.fluorescence:
            meta["excitation_nm"] = self.excitation_nm
            meta["background"] = "dark_counts slot = background (blank or excitation off)"
        return meta

    def frame(self, raw, sat, t=None):
        dev = self.dev
        counts, absorbance = process(raw, self.valid(self.dark), self.active_ref())
        return {"wavelengths": jsonable(dev.wavelengths), "counts": for_display(counts),
                "absorbance": for_display(absorbance), "saturated": dev.is_saturated(sat),
                "saturated_nm": dev.saturated_ranges(sat), "integration_s": dev.integration_s,
                "max_counts": float(raw[spectro.SKIP_PIXELS:].max()),
                "time": t or time.time()}

    # live view
    def start_live(self):
        self.require()
        if self.busy:
            raise RuntimeError("A kinetic run is using the spectrometer.")
        if not self.live:
            self.live = True
            threading.Thread(target=self._live_loop, daemon=True).start()

    def stop_live(self):
        self.live = False

    def _live_loop(self):
        while self.live and self.dev is not None:
            try:
                raw, _, sat = self.dev.read()
                self.live_frame = self.frame(raw, sat)
            except Exception as e:
                self.live_frame = {"error": str(e)}
                time.sleep(0.5)
            # Short integrations would otherwise hog the lock and the CPU
            time.sleep(max(0.0, 0.1 - self.dev.integration_s) if self.dev else 0.1)


def create_app(station: Station) -> Flask:
    app = Flask(__name__)
    st = station

    def ok(**kw):
        return jsonify(success=True, **kw)

    @app.errorhandler(Exception)
    def on_error(e):
        code = getattr(e, "code", 400)
        return jsonify(success=False, error=str(e)), code if isinstance(code, int) else 400

    @app.get("/")
    def index():
        return render_template("index.html", version=__version__)

    @app.get("/api/status")
    def status():
        dev = st.dev
        return ok(
            version=__version__, connected=dev is not None, error=st.connect_error,
            device=dev.info if dev else None, mock=st.mock,
            integration_s=dev.integration_s if dev else None,
            n_avg=dev.n_avg if dev else 1, live=st.live, busy=st.busy,
            measurement=st.measurement, excitation_nm=st.excitation_nm,
            dark=st.dark.summary(dev) if st.dark and dev else None,
            reference=st.ref.summary(dev) if st.ref and dev else None,
            run_state=st.run.state if st.run else None,
            data_dir=str(st.data_dir), hdf5_available=spectro.h5py is not None,
            has_last=st.last is not None)

    @app.post("/api/connect")
    def connect():
        st.connect()
        return ok(device=st.dev.info)

    @app.post("/api/settings")
    def settings():
        dev = st.require()
        if st.busy:
            raise RuntimeError("Settings are locked during a kinetic run.")
        body = request.get_json(force=True)
        if "integration_ms" in body:
            dev.set_integration(float(body["integration_ms"]) / 1000)
        if "n_avg" in body:
            dev.n_avg = min(max(int(body["n_avg"]), 1), 1000)
        if "measurement" in body:
            if body["measurement"] not in ("absorbance", "fluorescence"):
                raise ValueError("measurement must be absorbance or fluorescence")
            st.measurement = body["measurement"]
            if st.mock:
                dev.spec.scene = st.measurement
        if "excitation_nm" in body:
            ex = body["excitation_nm"]
            st.excitation_nm = float(ex) if ex not in (None, "") else None
        return ok(integration_s=dev.integration_s, n_avg=dev.n_avg,
                  measurement=st.measurement, excitation_nm=st.excitation_nm)

    def capture_background(kind):
        dev = st.require()
        if st.busy:
            raise RuntimeError("A kinetic run is using the spectrometer.")
        raw, _, sat = dev.read()
        bg = Background(raw, dev.integration_s, dev.n_avg)
        setattr(st, kind, bg)
        return ok(**{kind: bg.summary(dev)}, saturated=dev.is_saturated(sat),
                  counts=jsonable(raw))

    @app.post("/api/dark")
    def dark():
        return capture_background("dark")

    @app.post("/api/reference")
    def reference():
        return capture_background("ref")

    @app.post("/api/clear/<kind>")
    def clear(kind):
        if kind not in ("dark", "reference"):
            raise ValueError("kind must be dark or reference")
        setattr(st, "dark" if kind == "dark" else "ref", None)
        return ok()

    @app.post("/api/capture")
    def capture():
        dev = st.require()
        if st.busy:
            raise RuntimeError("A kinetic run is using the spectrometer.")
        raw, _, sat = dev.read()
        st.last = {"raw": raw, "dark": st.valid(st.dark), "ref": st.active_ref(),
                   "mode": st.mode_meta(),
                   "integration_s": dev.integration_s, "n_avg": dev.n_avg,
                   "taken": datetime.now().isoformat(timespec="seconds")}
        return ok(data=st.frame(raw, sat))

    @app.post("/api/save")
    def save():
        if st.last is None:
            raise RuntimeError("Capture a spectrum first.")
        body = request.get_json(force=True)
        name = body.get("name") or "spectrum"
        L = st.last
        meta = {"taken": L["taken"], "integration_s": L["integration_s"],
                "n_avg": L["n_avg"], "device": st.dev.info, **L["mode"],
                "detector_corrections": ["electric_dark", "nonlinearity"]}
        fluo = L["mode"]["measurement"] == "fluorescence"
        path = spectro.save_spectrum(st.data_dir / "spectra", name, body.get("notes", ""),
                                     st.dev.wavelengths, L["raw"], L["dark"], L["ref"], meta,
                                     "background_counts" if fluo else "dark_counts")
        return ok(file=str(path))

    @app.post("/api/live/<action>")
    def live(action):
        st.start_live() if action == "start" else st.stop_live()
        return ok(live=st.live)

    @app.get("/api/live")
    def live_frame():
        return ok(data=st.live_frame)

    @app.post("/api/run/start")
    def run_start():
        dev = st.require()
        if st.busy:
            raise RuntimeError("A run is already in progress.")
        cfg = RunConfig.from_dict(request.get_json(force=True))
        cfg.measurement, cfg.excitation_nm = st.measurement, st.excitation_nm
        checks = [(st.dark, "background" if st.fluorescence else "dark")]
        if not st.fluorescence:
            checks.append((st.ref, "reference"))
        for bg, label in checks:
            if bg is not None and not bg.matches(dev):
                raise RuntimeError(f"The {label} was taken at {bg.integration_s*1000:g} ms "
                                   f"but the integration time is now "
                                   f"{dev.integration_s*1000:g} ms. Retake or clear it.")
        if cfg.save_hdf5 and spectro.h5py is None:
            raise RuntimeError("HDF5 needs h5py: pip install h5py")
        st.stop_live()
        time.sleep(dev.integration_s + 0.05)  # let the live loop release the device
        st.run = KineticRun(dev, cfg, st.valid(st.dark), st.active_ref(), st.data_dir)
        st.run.start()
        return ok(folder=str(st.run.folder))

    @app.post("/api/run/stop")
    def run_stop():
        if st.run:
            st.run.stop()
        return ok()

    @app.post("/api/run/mark")
    def run_mark():
        if not st.busy:
            raise RuntimeError("No run in progress.")
        return ok(event=st.run.mark(request.get_json(force=True).get("label", "")))

    @app.get("/api/run/status")
    def run_status():
        if st.run is None:
            return ok(run=None)
        return ok(run=st.run.status(int(request.args.get("since", 0))))

    return app


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="use a simulated spectrometer")
    ap.add_argument("--data-dir", default=Path(__file__).resolve().parent / "data",
                    help="where spectra and runs are saved (default: ./data)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 = this computer only; 0.0.0.0 = lab network")
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    station = Station(args.data_dir, mock=args.mock)
    try:
        station.connect()
        print(f"Connected: {station.dev.info['model']} {station.dev.info['serial']}")
    except Exception as e:
        print(f"Spectrometer not connected ({e}). Use Connect in the browser.")

    url = f"http://127.0.0.1:{args.port}"
    print(f"Data folder: {station.data_dir}\nOpen {url}  (Ctrl+C to quit)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, (url,)).start()
    # Single-user instrument app: hide Flask's "development server" banner and the
    # per-request log lines from the UI polling several times a second.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    import flask.cli
    flask.cli.show_server_banner = lambda *a, **k: None
    try:
        create_app(station).run(host=args.host, port=args.port, threaded=True)
    finally:
        if station.run:
            station.run.stop()
            station.run.join(timeout=5)
        if station.dev:
            station.dev.close()


if __name__ == "__main__":
    main()
