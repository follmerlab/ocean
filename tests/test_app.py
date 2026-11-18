"""Tests against the simulated spectrometer: no hardware needed (runs in CI)."""
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import spectro  # noqa: E402
from app import Station, create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    st = Station(tmp_path, mock=True)
    st.connect()
    app = create_app(st)
    app.testing = True
    c = app.test_client()
    c.station = st
    yield c
    if st.run:
        st.run.stop()
        st.run.join(5)


def post(c, url, body=None):
    r = c.post(url, json=body or {})
    return r.get_json()


def wait_run(c, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        run = c.get("/api/run/status").get_json()["run"]
        if run["state"] in ("done", "aborted", "error"):
            time.sleep(0.1)
            return run
        time.sleep(0.05)
    raise TimeoutError


# ---- processing -----------------------------------------------------------

def test_absorbance_is_nan_without_light_not_clipped():
    raw = np.array([1000.0, 50.0, 600.0])
    dark = np.array([100.0, 100.0, 100.0])
    ref = np.array([1100.0, 110.0, 1100.0])     # middle pixel: ref has ~no light
    counts, a = spectro.process(raw, dark, ref)
    assert np.allclose(counts, [900, -50, 500])
    assert a[0] == pytest.approx(-np.log10(0.9))
    assert np.isnan(a[1])
    assert a[2] == pytest.approx(-np.log10(0.5))


def test_safe_name_is_windows_safe():
    assert spectro.safe_name('my:sample/<1>?') == "my_sample_1"
    assert spectro.safe_name("  ") == "untitled"
    assert spectro.safe_name("Fe(II) + O2 run 3") == "Fe(II)_+_O2_run_3"
    assert spectro.safe_name("ambient test: room light") == "ambient_test_room_light"


def test_band_average():
    wl = np.linspace(400, 600, 201)
    assert spectro.band_average(wl, wl, 500, 2) == pytest.approx(500)


# ---- API ------------------------------------------------------------------

def test_status_and_settings(client):
    s = client.get("/api/status").get_json()
    assert s["connected"] and s["mock"]
    r = post(client, "/api/settings", {"integration_ms": 0.01})   # below 1 ms floor
    assert r["integration_s"] == pytest.approx(0.001)
    r = post(client, "/api/settings", {"integration_ms": 5, "n_avg": 3})
    assert r["integration_s"] == pytest.approx(0.005) and r["n_avg"] == 3


def test_dark_invalidated_by_integration_change(client):
    post(client, "/api/settings", {"integration_ms": 5})
    assert post(client, "/api/dark")["success"]
    assert client.get("/api/status").get_json()["dark"]["valid"]
    post(client, "/api/settings", {"integration_ms": 6})
    assert not client.get("/api/status").get_json()["dark"]["valid"]
    r = post(client, "/api/run/start", {"duration_s": 1})
    assert not r["success"] and "dark" in r["error"]


def test_capture_and_save_spectrum(client, tmp_path):
    post(client, "/api/settings", {"integration_ms": 5})
    client.station.dev.spec.sample_in = False
    post(client, "/api/dark")          # mock dark still contains the lamp; fine for test
    post(client, "/api/reference")
    client.station.dev.spec.sample_in = True
    d = post(client, "/api/capture")["data"]
    assert len(d["wavelengths"]) == 2048 and d["absorbance"] is not None
    json.dumps(d, allow_nan=False)      # strict JSON: no NaN leaks
    r = post(client, "/api/save", {"name": "test: sample 1", "notes": "hello"})
    path = Path(r["file"])
    assert path.exists() and path.with_suffix(".json").exists()
    assert path.name.endswith("_test_sample_1.csv")
    header = path.read_text().splitlines()[0].split(",")
    assert header[0] == "wavelength_nm" and "absorbance" in header


def test_kinetic_run_with_delay_and_events(client):
    post(client, "/api/settings", {"integration_ms": 5})
    client.station.dev.spec.sample_in = False
    post(client, "/api/reference")
    client.station.dev.spec.sample_in = True
    r = post(client, "/api/run/start", {
        "name": "bleach", "delay_s": 0.5, "duration_s": 1.0, "interval_s": 0,
        "traces_nm": [520, 700], "save_hdf5": spectro.h5py is not None})
    assert r["success"], r
    time.sleep(0.2)
    st = client.get("/api/run/status").get_json()["run"]
    assert st["state"] == "countdown" and st["countdown_s"] > 0
    ev = post(client, "/api/run/mark", {"label": "inject"})["event"]
    assert ev["t_s"] < 0                        # marked before t = 0
    run = wait_run(client)
    # Rate on hardware is checked by scripts/hardware_check.py; CI runners have
    # coarse, jittery timers, so only require that the pipeline produced data.
    assert run["state"] == "done" and run["n"] >= 20

    folder = Path(run["folder"])
    meta = json.loads((folder / "run.json").read_text())
    assert meta["events"][0]["label"] == "inject"
    rows = list(csv.reader(open(folder / "absorbance.csv")))
    assert rows[0][0] == "time_s" and len(rows[0]) == 2049
    times = [float(r[0]) for r in rows[1:]]
    assert times == sorted(times) and 0 <= times[0] < 0.05 and times[-1] <= 1.0
    tr = list(csv.reader(open(folder / "traces.csv")))
    assert tr[0] == ["time_s", "520nm", "700nm"]
    a520 = float(tr[1][1])
    assert 0.3 < a520 < 1.0                     # mock band is ~0.8 * exp(-t/30)
    assert abs(float(tr[1][2])) < 0.05          # no absorber at 700 nm
    if spectro.h5py is not None:
        with spectro.h5py.File(folder / "run.h5") as h:
            assert h["absorbance"].shape == (len(times), 2048)


def test_interval_scheduling_and_stop(client):
    post(client, "/api/settings", {"integration_ms": 10})
    post(client, "/api/run/start", {"duration_s": 0, "interval_s": 0.25})
    time.sleep(1.2)
    post(client, "/api/run/stop")
    run = wait_run(client)
    assert run["state"] == "aborted"
    t = np.array(run["t"])
    assert 3 <= len(t) <= 6
    dt = np.diff(t)
    assert dt.min() > 0.15                      # late slots are skipped, never burst
    assert abs(dt.mean() - 0.25) < 0.06         # stays on the schedule on average


def test_settings_locked_during_run(client):
    post(client, "/api/run/start", {"duration_s": 0, "delay_s": 5})
    r = post(client, "/api/settings", {"integration_ms": 20})
    assert not r["success"]
    post(client, "/api/run/stop")
    assert wait_run(client)["state"] == "aborted"


def test_process_block_matches_rows():
    rng = np.random.default_rng(1)
    raw = rng.uniform(200, 5000, (5, 16)); dark = np.full(16, 100.0); ref = np.full(16, 6000.0)
    c, a = spectro.process(raw, dark, ref)
    for i in range(5):
        ci, ai = spectro.process(raw[i], dark, ref)
        assert np.allclose(c[i], ci) and np.allclose(a[i], ai, equal_nan=True)


def test_fluorescence_mode(client):
    # A reference left over from absorbance work must be ignored, even when stale.
    post(client, "/api/settings", {"integration_ms": 10})
    post(client, "/api/reference")
    r = post(client, "/api/settings", {"measurement": "fluorescence", "excitation_nm": 405,
                                       "integration_ms": 20})
    assert r["measurement"] == "fluorescence" and r["excitation_nm"] == 405
    client.station.dev.spec.sample_in = False          # blank: scatter only
    post(client, "/api/dark")
    client.station.dev.spec.sample_in = True
    d = post(client, "/api/capture")["data"]
    assert d["absorbance"] is None
    wl = np.array(d["wavelengths"]); c = np.array(d["counts"], dtype=float)
    assert c[np.argmin(abs(wl - 600))] > 20 * abs(c[np.argmin(abs(wl - 405))])  # scatter removed

    path = Path(post(client, "/api/save", {"name": "emission"})["file"])
    header = path.read_text().splitlines()[0].split(",")
    assert "background_counts" in header and "absorbance" not in header
    meta = json.loads(path.with_suffix(".json").read_text())
    assert meta["measurement"] == "fluorescence" and meta["excitation_nm"] == 405

    r = post(client, "/api/run/start", {"duration_s": 0.5, "traces_nm": [600]})
    assert r["success"], r                               # stale reference does not block
    run = wait_run(client)
    folder = Path(run["folder"])
    assert not (folder / "absorbance.csv").exists() and (folder / "counts.csv").exists()
    cfg = json.loads((folder / "run.json").read_text())["config"]
    assert cfg["measurement"] == "fluorescence" and cfg["excitation_nm"] == 405
    assert run["y"][0][0] > 1000                         # emission counts at 600 nm


def test_saturation_reports_where(client):
    post(client, "/api/settings", {"measurement": "fluorescence", "integration_ms": 50})
    d = post(client, "/api/capture")["data"]             # only the 405 nm scatter saturates
    assert d["saturated"] and len(d["saturated_nm"]) == 1
    lo, hi = d["saturated_nm"][0]
    assert 400 < lo <= hi < 410
    post(client, "/api/settings", {"integration_ms": 200})
    d = post(client, "/api/capture")["data"]             # scatter and emission: two regions
    assert len(d["saturated_nm"]) == 2 and d["saturated_nm"][1][0] > 500
