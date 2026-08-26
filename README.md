# PyCuDAL

<p align="center">
  <img src="assets/logo.png" alt="PyCuDAL logo" width="120"/>
</p>

**Parametric acceptance limits for USP <905> Content Uniformity and USP <711> Dissolution** —
a Python re-implementation of the SAS programs `CALCUSP1/2`, `CALDISP1/2`,
`EVCUSP1/2`, `EVDISP1/2`, `SMPCUSP1/2`, `SMPDISP1/2`, with a CLI and two GUIs.

[![CI](https://github.com/moazelessawey/pycudal/actions/workflows/ci.yml/badge.svg)](https://github.com/moazelessawey/pycudal/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pycudal.svg)](https://pypi.org/project/pycudal/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/moazelessawey/pycudal)](https://github.com/moazelessawey/pycudal/releases)

---

## Features

- **Computations (`cudal` package)**
  - Content Uniformity – Sampling Plans 1 & 2 (`cusp1`, `cusp2`)
  - Dissolution – Sampling Plans 1 & 2 (`disp1`, `disp2`)
  - Three analysis modes each: acceptance-limit table, probability of passing, sample probability
- **CLI** – `python -m cudal.cli` (or installed command `cudal`)
- **Tkinter GUI** (`cudal-gui`, stdlib-only → tiny install): 4 tabs × 3 modes,
  background threads with progress, scrollable parameters, live validation,
  sortable/colored results table, CSV export, modal matplotlib plots
  (lines + cubic spline, heatmap with 80/90 % contours), SAS-style **PDF listings**
  (Courier, column wrapping, repeated page headers), XLSX export, settings persistence
- **Optional PySide6 GUI** (`extras/cudal_gui_pyside6.py`) – modern Qt theme,
  kept *outside* the package so the pip install stays small

## Repository layout

```
cudal/            library: computations + CLI + Tk GUI (+ logo package data)
extras/           optional PySide6 GUI (not installed)
tests/            pytest smoke tests
scripts/          local exe build helper
.github/          CI, PyPI publish, exe release workflows
```

## Installation

Requires Python ≥ 3.9.

```bash
# from GitHub
pip install git+https://github.com/moazelessawey/cudal.git

# from a source checkout
pip install .            # core (numpy/pandas/scipy) + CLI + Tk GUI
pip install .[all]       # + matplotlib, openpyxl, reportlab (plots/exports)
pip install .[qt]        # + PySide6 for the optional Qt GUI
pip install .[dev]       # + pytest, pyinstaller
```

| Extra   | Adds                          |
|---------|-------------------------------|
| `plot`  | matplotlib (plots)            |
| `xlsx`  | openpyxl (Excel export)       |
| `pdf`   | reportlab (PDF listings)      |
| `qt`    | PySide6 (+matplotlib) Qt GUI  |
| `all`   | plot + xlsx + pdf             |
| `dev`   | pytest + pyinstaller          |

## Quick start

### Python API

```python
from cudal import cusp1

table = cusp1.acceptance_limit_table(10, 100.0, 95.0, 95.0, 85.1, 114.9, 0.5)
print(table)
```

### CLI

```bash
cudal --help                 # installed console script
python -m cudal.cli --help   # module form
python -m cudal --help       # package __main__
```

The CLI covers the same four scenarios × three modes as the GUIs
(see `--help` for the exact option names).

### Tkinter GUI (included, stdlib-only)

```bash
cudal-gui                 # after pip install
python cudal_gui.py       # from a source checkout
```

### Optional PySide6 GUI (extra file, not installed)

```bash
pip install .[qt]
python extras/cudal_gui_pyside6.py
```

## Result exports

- **CSV** – one click per table
- **XLSX** – File → *Export all results* (one sheet per tab)
- **PDF** – SAS-listing style: Courier, centered title block, Plan‑1 row-wrapped
  blocks, Plan‑2 SE×SM LL/UL matrix, 2 dp right-aligned numbers, `*` for NaN,
  **title + table headers repeated on every page**
- **Plots** – lines + cubic spline, or heatmap with 80/90 % threshold contours; Save PNG

## Building standalone executables

Locally (Windows):

```bat
scripts\build_exe.bat
```

or manually:

```bat
pip install .[all,qt] pyinstaller
pyinstaller --onefile --noconsole --name CuDAL    --add-data "cudal\logo.png;cudal" cudal_gui.py
pyinstaller --onefile --noconsole --name CuDAL-Qt --add-data "cudal\logo.png;cudal" extras\cudal_gui_pyside6.py
```

On every **GitHub Release**, the `build-exe.yml` workflow builds
`CuDAL.exe` and `CuDAL-Qt.exe` and attaches them to the release automatically.

## Releasing & publishing

1. Bump `cudal/__version__` and commit.
2. Create a tag & GitHub release: `git tag v1.0.0 && git push origin v1.0.0`
   (or use *Releases → Draft new release* in the UI).
3. Actions then:
   - build & attach the Windows executables to the release,
   - build the wheel/sdist and publish to PyPI (`publish.yml`).

## Development

```bash
pip install -e .[all,dev]
pytest -q
python -m cudal.gui --selftest
```

## License & disclaimer

MIT — see [LICENSE](LICENSE).

This software is provided for research/informational use. It does **not**
constitute regulatory advice; validate any output against your own
reference implementation before use in a GMP environment.
