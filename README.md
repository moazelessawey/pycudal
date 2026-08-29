# PyCuDAL

<p align="center">
  <img src="assets/logo.png" alt="PyCuDAL logo" width="120"/>
</p>

**Parametric acceptance limits for USP <905> Content Uniformity and USP <711> Dissolution.**

PyCuDAL is a pure‑Python re‑implementation of the **CuDAL Version 2** SAS™ system
written by **Dr. James Bergum** (`CALCUSP1/2`, `CALDISP1/2`, `EVCUSP1/2`,
`EVDISP1/2`, `SMPCUSP1/2`, `SMPDISP1/2`), with a library API, a command‑line
interface and two desktop GUIs (Tkinter and PySide6).

[![CI](https://github.com/moazelessawey/pycudal/actions/workflows/ci.yml/badge.svg)](https://github.com/moazelessawey/pycudal/actions)
[![PyPI](https://img.shields.io/pypi/v/pycudal.svg)](https://pypi.org/project/pycudal/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/moazelessawey/pycudal)](https://github.com/moazelessawey/pycudal/releases)

> 📘 Full operating instructions: **[docs/USER_MANUAL.md](docs/USER_MANUAL.md)**

---

## What it does

Routine USP testing only tells you whether *the current sample* passes.
PyCuDAL answers the question a quality system actually needs:

> *Which limits should I apply to my sample so that any **future** sample from
> the same batch passes the USP test at least **P %** of the time, with **C %**
> confidence?*

For each of the four scenarios — **CU Plan 1/2** and **Dissolution Plan 1/2** —
the system provides the same three analyses as the original SAS programs:

| Analysis | SAS equivalent | Output |
|---|---|---|
| Acceptance‑limit table | `CALCUSP1/2`, `CALDISP1/2` | Limits on the sample (mean/CV pairs, or LL/UL on the mean as a function of within/between‑location SD) |
| Probability of passing | `EVCUSP1/2`, `EVDISP1/2` | P(sample falls inside a given table) over grids of true population parameters |
| Sample probability | `SMPCUSP1/2`, `SMPDISP1/2` | Lower confidence bound on P(future samples pass USP) for an observed sample |

**Sampling plans**

- **Plan 1** – one unit per location (composite QC samples).
- **Plan 2** – `num` units at each of `loc` locations (process validation,
  variance‑components model).

## Features

- **`cudal` package** – faithful, *vectorized* translations of the SAS macros:
  broadcastable probability cores (`content_uniformity_bound`,
  `dissolution_bound`) and a batched scan‑and‑bisection root finder that solves
  whole MEAN or SE×SM grids in a handful of NumPy calls instead of thousands of
  scalar steps.
- **CLI** – `cudal` / `python -m cudal.cli`: interactive SAS‑style sessions
  with the original prompts and defaults.
- **Tkinter GUI** (`cudal-gui`, stdlib‑only) and **PySide6 GUI**
  (`extras/cudal_gui_pyside6.py`, modern theme): 4 tabs × 3 modes, splash
  screen with real loading progress, background threads with determinate
  progress, scrollable validated parameter forms, sortable results tables with
  conditional P(pass) coloring, tooltips, settings persistence.
- **Plots** – points + cubic spline, contour heatmaps with 80/90 % threshold
  contours, Plan‑2 faceted/heatmap views with Z‑axis selector, and **OC‑curve
  dialogs** comparing your computed plan against the raw USP <905>/<711>
  multi‑stage test (seeded Monte‑Carlo).
- **Exports** – CSV per table, XLSX workbook (one sheet per scenario), and
  SAS‑listing‑style **PDF** (Courier, wrapped column blocks, SE×SM LL/UL
  matrices, 2 dp right‑aligned values, `*` for missing, title + headers
  repeated on every page) with descriptive default filenames
  (e.g. `CUSP2-95x95-10Lx6N.pdf`, `DISP1-Q80-95x95-6N-EVAL.csv`).
- **Cross‑validation** – an independent R implementation (`utils/cudal.r`)
  reproduces every entry point for output checking.
- **Packaging** – PyPI wheel, standalone Windows/Linux executables via
  PyInstaller + GitHub Actions, `--selftest` smoke checks.

## Repository layout

```
cudal/            library: core.py, cusp1/2, disp1/2, cli.py, Tk GUI, logo
extras/           optional PySide6 GUI (not installed by pip)
utils/cudal.r     independent R reference implementation (cross-checks)
docs/             USER_MANUAL.md
tests/            pytest smoke tests
scripts/          build_exe.sh (Linux/Windows exe build helper)
.github/          CI, exe-release workflows
```

## Installation

Requires Python ≥ 3.9.

```bash
# from GitHub / PyPI / source
pip install git+https://github.com/moazelessawey/pycudal.git
pip install pycudal
pip install .                 # source checkout

# extras
pip install .[all]            # matplotlib + openpyxl + reportlab (plots/exports)
pip install .[qt]             # + PySide6 for the optional Qt GUI
pip install .[dev]            # + pytest, pyinstaller
```

| Extra | Adds |
|---|---|
| `plot` | matplotlib (plots, OC curves) |
| `xlsx` | openpyxl (Excel export) |
| `pdf` | reportlab (SAS‑style PDF listings) |
| `qt` | PySide6 (+matplotlib) optional Qt GUI |
| `all` | plot + xlsx + pdf |
| `dev` | pytest + pyinstaller |

Standalone executables (`CuDAL`, `CuDAL-Qt`) are attached to every
[GitHub Release](https://github.com/moazelessawey/pycudal/releases).

## Quick start

### Library

```python
from cudal import cusp1, cusp2, disp1, disp2

# acceptance-limit table (CU Plan 1): N=10, target=100, P=95, C=95
table = cusp1.acceptance_limit_table(10, 100.0, 95.0, 95.0, 85.1, 114.9, 0.5)

# probability of passing that table for true (U, CV) grids
ev = cusp1.probability_of_passing(table, 10, [95.0, 100.0], [1.0, 4.0])

# lower bound for an observed sample (mean=100, CV=4) -> 0.98003
sb = cusp1.sample_probability(100.0, 4.0, 10, 100.0, 95.0, 95.0)
```

### CLI

```bash
cudal                    # or: python -m cudal.cli
```

Interactive SAS‑style session: test type (CU/dissolution) → sampling plan →
analysis mode → parameters (original defaults, e.g. U grid 950–1000×50 ÷10).

### GUIs

```bash
cudal-gui                              # Tkinter (installed, stdlib-only)
python cudal_gui.py                    # Tkinter from source
pip install .[qt]
python extras/cudal_gui_pyside6.py     # PySide6 (splash, toolbar, OC curves)
```

See the [User Manual](docs/USER_MANUAL.md) for a screen‑by‑screen guide.

## Validation & cross-checks

- `pytest -q` and `python cudal_gui.py --selftest` run smoke tests.
- The shipped tables reproduce the published SAS Version 2 reference output
  (e.g. CUSP1 `100.0 → 4.18`, CUSP2 `SE 0.1/SM 0.1 → 84.8/115.2`,
  DISP1 `100.0 → 4.97`, sample bounds `0.98003 / 0.98750 / 0.99824 / 1`).
- `utils/cudal.r` is an **independent R implementation** of the same formulas:

```r
source("utils/cudal.r")
cusp1_sample_probability(100, 4, 10, 100, 95, 95)$OVERBD        # 0.98003
disp1_sample_probability(100, 4, 6, 80, 95)$OVERBD              # 0.99824
t2 <- cusp2_acceptance_limit_table(4, 10, 100, 95, 95,
       seq(0.1, 5.2, 0.1), seq(0.1, 3.7, 0.1))
```

## Building executables & releasing

```bash
scripts/build_exe.sh     # or scripts\build_exe.bat on Windows
# = pip install .[all,qt] pyinstaller
#   pyinstaller --onefile --noconsole --name CuDAL    ... cudal_gui.py
#   pyinstaller --onefile --noconsole --name CuDAL-Qt ... extras/cudal_gui_pyside6.py
```

Tagging a release (`git tag v1.0.8 && git push --tags`) builds and attaches the
executables automatically via `.github/workflows/build-exe.yml`.

## References

1. Bergum, J.S. (1990), *Constructing Acceptance Limits for Multiple Stage Tests*, Drug Dev. Ind. Pharm. 16(14), 2153–2166.
2. Bergum, J., Utter, M. (2000), *Process Validation*, Encycl. Biopharm. Stat., Marcel Dekker, 422–439.
3. Bergum, J.S., Utter, M.L. (2003), *Statistical Methods for Uniformity and Dissolution Testing*, Pharm. Process Validation, Marcel Dekker, 667–697.
4. Bergum, J., Li, H. (2007), *Acceptance Limits for the New ICH USP 29 Content Uniformity Test*, Pharm. Tech., Oct, 88–98.
5. Bergum, J. (2007), *CuDAL Version 2 Users Guide* and *Appendix E – Lower Bound Calculations*.

## Acknowledgments

The statistical methodology and the original SAS implementation are due to
**Dr. James Bergum**; this project exists to carry that work into the modern
Python ecosystem.

## Author & license

Created and maintained by **Moaz El‑Essawey** —
[github.com/moazelessawey/pycudal](https://github.com/moazelessawey/pycudal).

MIT — see [LICENSE](LICENSE). Provided AS‑IS for research/informational use; it
does not constitute regulatory advice. Validate against your own reference
implementation before any GMP use.
