# Flame Spectrometer: spectra and kinetics

Browser interface for an Ocean Optics / Ocean Insight Flame (USB2000+ protocol) via
[python-seabreeze](https://github.com/ap--/python-seabreeze). Take named absorbance or
fluorescence spectra, or run time-resolved kinetics with a start countdown, live
single-wavelength traces, and event markers. Runs on Windows, macOS and Linux.

The original v1 interface is preserved at tag `v1.0.0` (`git checkout v1.0.0`).

## Install and start

Needs Python 3.11 or newer.

**Windows:** double-click `start.bat`. The first run creates a `.venv` folder and installs
packages. USB drivers, once per computer, from an **administrator** prompt:

```bat
.venv\Scripts\seabreeze_os_setup
```

If OceanView/OceanDirect is installed it may own the USB driver; if the Flame is not
found, close OceanView, re-run `seabreeze_os_setup`, and replug.

**macOS / Linux:** `./start.sh` (Linux: also run `.venv/bin/seabreeze_os_setup` once for udev rules).

**By hand:**

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip ...
.venv/bin/python app.py
```

The browser opens at <http://127.0.0.1:5001>. Options:

| flag | meaning |
|---|---|
| `--mock` | simulated spectrometer (no hardware) for practice and testing |
| `--data-dir PATH` | where files are saved (default `./data`) |
| `--host 0.0.0.0` | allow other computers on the network to connect (default: this computer only) |
| `--port N` | default 5001 |

On a new computer, `python scripts/hardware_check.py` confirms the connection and reports how
fast that machine can acquire.

## Measurement: absorbance or fluorescence

Choose at the top of the sidebar.

- **Absorbance:** dark + reference, shown as counts, absorbance or %T.
- **Fluorescence:** emission counts, with no reference (any stored reference is ignored and
  absorbance is never computed). *Dark* becomes **Background**. Use the blank with excitation on
  to remove scatter and Raman lines, or excitation off for a plain dark. Enter the **excitation
  wavelength**: it is marked on the plots and saved with every file. The display offers
  **Counts/s** (counts ÷ integration time) for comparing spectra taken at different
  integration times. Saved spectra name the column `background_counts`.

Both modes work the same way for single spectra and for kinetics. A fluorescence kinetic
run records emission versus time (photobleaching, binding, quenching, reaction progress).

**Time resolution:** one spectrum per integration time, 1 ms at the fastest (about 2–5 ms
in practice). The Flame cannot measure fluorescence lifetimes (ns–µs); those need TCSPC or a
gated detector. Millisecond-scale decays after a pulsed source (e.g. lanthanide emission)
would need the Flame's external trigger, which this version does not use.

When the detector saturates, the readout says where (e.g. *SATURATED at 403.5–406.6 nm*). In
fluorescence that is often just the excitation line and harmless to the emission band; a
long-pass filter removes it.

## Axis limits

Each plot has x and y boxes above it. A blank box means auto, and either end can be set alone.
Setting only the x window fits the y range to the data inside that window. **Lock view**
freezes whatever you have zoomed to with the mouse, and **Auto** clears the limits. y
limits are kept separately for counts, absorbance, etc., and the browser remembers them all.

## Taking spectra

1. Set **Integration (ms)** and **Averages**. Use **Start live** to adjust the sample and
   watch for the red *SATURATED* readout.
2. **Dark:** block the light, then click Take. **Reference:** put the blank in the beam, then click Take.
   Both are tied to the integration time they were taken at: change the integration time and they
   are flagged *stale* (red) and not applied until you retake them or change back.
3. **Capture**, type a name and optional notes, then click **Save last capture**.

Saved to `data/spectra/2026-11-18_143012_<name>.csv`, with columns
`wavelength_nm, raw_counts, dark_counts, reference_counts, corrected_counts, absorbance`,
plus a `.json` sidecar holding the settings and notes.

Absorbance is left blank (NaN) wherever the reference has no usable light, instead
of the false spikes clipping used to produce.

## Kinetics

On the **Kinetics** tab:

| field | meaning |
|---|---|
| Delay before t = 0 | countdown after Start; use it to get to the sample. Acquisition begins at t = 0 |
| Duration | seconds after t = 0 (0 = until you press Stop) |
| Interval | time between spectra (0 = as fast as the integration time allows) |
| Averages per point | frames averaged into each saved spectrum |
| Trace wavelengths | up to 8, plotted live as absorbance (or counts) vs time. Click the spectrum on the Spectrum tab to add one |
| Band ± | each trace averages wavelength ± this many nm |

The checklist shows whether dark and reference are set and valid, and estimates the number of
spectra and file size. During a run, **Mark** (or the **M** key) records a labeled event,
such as *inject*, at the current time. Events marked during the countdown get negative times.
Reloading the page during a run is safe: the run continues and the page catches up.

**Every full spectrum is saved**, whatever trace wavelengths you choose, so you can extract
any wavelength later. Each run gets its own folder, `data/kinetics/<date>_<time>_<name>/`:

| file | contents |
|---|---|
| `counts.csv` | first column `time_s`, then one column per wavelength: dark-corrected counts |
| `absorbance.csv` | same layout, if a reference was set |
| `traces.csv` | `time_s` + the live trace wavelengths (small; quick to plot) |
| `run.json` | settings, notes, events, timing statistics, dark and reference spectra, wavelength axis |
| `run.h5` | everything above in one HDF5 file (tick *Also save HDF5*) |

Timing: t = 0 is the end of the countdown, and each spectrum is stamped at the centre of its
integration window, measured on a high-resolution clock. The detector free-runs, so a
timestamp is accurate to about ±½ integration time. During a run, frames stream to
disk as raw binary; the CSV and HDF5 files are written when the run ends (*writing files…*
in the UI). If the program is interrupted mid-run, the raw `frames.f32` and `run.json` are
kept and `run.json` explains the format.

**Measured on Flame-S FLMS00863 (MacBook, with the UI polling):**

| integration | rate | dropped frames |
|---|---|---|
| 2 ms | 500 Hz | ~0.3–0.8 % |
| 5 ms | 200 Hz | ~0.1–0.4 % |
| ≥ 20 ms | 1 / integration | ~0 |

A dropped frame is only a gap; each spectrum keeps its own true timestamp.
File sizes are about 16 kB per spectrum per CSV, so 10 min at 200 Hz is ~2 GB of CSV.
Use HDF5 or a non-zero interval for long fast runs.

## Detector corrections and saturation

Every read applies the Flame's electric-dark and nonlinearity corrections (stored in its
EEPROM; the same calculation seabreeze and OceanView use). Corrected counts can be slightly
negative in the masked edge pixels.

Saturation is judged on the **uncorrected** ADC values, at 95 % of 65,535. The corrections lower
the ceiling: on FLMS00863 a fully saturated detector reads only ~62,000–63,700 corrected
counts, so a threshold on corrected counts never fires. A saturated spectrum minus a saturated
background is a flat line, so trust the SATURATED warning.

Known pixels on this unit: pixel 1 is hot (hidden in plots, kept in files), and the pixel at
463.4 nm accumulates dark current and saturates by itself at ~8 s integration. Single isolated
saturated pixels are ignored, since real light always spans several pixels. Dark/background
subtraction removes both.

## Development

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest          # runs against the simulated spectrometer
```

GitHub Actions (`.github/workflows/ci.yml`) runs the tests and a SeaBreeze import check on
Windows, macOS and Ubuntu with Python 3.11–3.13 on every push.

```
app.py                     Flask server, routes, CLI
spectro.py                 device access, processing, kinetic runs, saving, mock spectrometer
templates/index.html       page
static/app.js, style.css   UI (plain JS, no build step)
static/plotly-basic.min.js Plotly 2.35.2, bundled so it works offline
scripts/hardware_check.py  connection + timing check on real hardware
tests/test_app.py          tests (no hardware needed)
```

### HTTP API

All POST bodies are JSON; responses carry `success` and `error`.

| endpoint | |
|---|---|
| `GET /api/status` | device, settings, dark/reference validity, run state |
| `POST /api/connect` | (re)connect |
| `POST /api/settings` | `{integration_ms, n_avg, measurement: "absorbance"|"fluorescence", excitation_nm}` |
| `POST /api/dark`, `/api/reference` | take background; `/api/clear/dark`, `/api/clear/reference` |
| `POST /api/capture` | one spectrum; `POST /api/save` `{name, notes}` saves it |
| `POST /api/live/start`, `/api/live/stop`; `GET /api/live` | live view |
| `POST /api/run/start` | `{name, notes, delay_s, duration_s, interval_s, n_avg, traces_nm, half_width_nm, save_hdf5}` |
| `POST /api/run/stop`, `/api/run/mark` `{label}`; `GET /api/run/status?since=N` | run control and incremental data |

## Changes from v1

- Kinetics: countdown, scheduled or continuous acquisition, live traces, event markers, CSV/JSON/HDF5 output
- Fluorescence mode (emission spectra and emission kinetics) alongside absorbance
- Fixed or partial axis limits on every plot; saturation reported by wavelength
- Named spectra saved with notes and full provenance (raw, dark, reference, settings)
- One lock around all USB access (v1 could read from two threads at once)
- Dark/reference invalidated when the integration time changes; integration range is the
  device's own (1 ms – 655 s) instead of 1 ms – 10 s
- Absorbance is NaN where there is no light, instead of clipped to A = 10
- Electric-dark and nonlinearity corrections enabled
- Server listens on this computer only by default, with the debugger off (v1 exposed the
  Werkzeug debugger, which allows remote code execution, to the network)
- Plotly bundled locally (works offline); Flask-CORS dropped (not needed)
- Simulated spectrometer, tests, and Windows/macOS/Linux CI
