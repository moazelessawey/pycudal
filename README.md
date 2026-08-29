# PyCuDAL

Parametric acceptance limits for USP <905> Content Uniformity and USP <711> Dissolution.

PyCuDAL is a Python re-implementation of the CuDAL Version 2 SAS application
(Bergum, 2007). For a user-specified coverage *P* (lower bound) and confidence
level *C*, it constructs acceptance-limit tables such that meeting the limits
assures any future sample from the batch will pass the applicable USP test at
least *P* % of the time with *C* % confidence. It also evaluates those tables
and computes lower confidence bounds on the probability of passing for
observed samples.


[![CI](https://github.com/moazelessawey/pycudal/actions/workflows/ci.yml/badge.svg)](https://github.com/moazelessawey/pycudal/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pycudal.svg)](https://pypi.org/project/pycudal/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/moazelessawey/pycudal)](https://github.com/moazelessawey/pycudal/releases)

---

## Methods

Two sampling plans are supported for each test:

- **Plan 1** – one dosage unit per location (e.g. composite QC samples).
- **Plan 2** – an equal number of units (> 1) per location (e.g. process validation).

Three analyses are available per plan:

| Analysis | Description | SAS equivalent |
|---|---|---|
| Acceptance-limit table | Limits on the sample (mean/CV pairs, or LL/UL on the mean as a function of within- and between-location SD) | `CALCUSP1/2`, `CALDISP1/2` |
| Probability of passing | Probability that sample results fall inside a given table, for assumed true population parameters | `EVCUSP1/2`, `EVDISP1/2` |
| Sample probability | Lower confidence bound on the probability of passing, given observed sample results | `SMPCUSP1/2`, `SMPDISP1/2` |

Statistical details are given in [docs/USER_MANUAL.md](docs/USER_MANUAL.md) (Appendix B) and in the referenced publications.

## Components

| Component | Entry point | Notes |
|---|---|---|
| `cudal` library | `import cudal` | Modules `cusp1`, `cusp2`, `disp1`, `disp2` |
| CLI | `cudal`, `python -m cudal.cli` | Interactive (SAS-style) and sub-command interfaces |
| Tkinter GUI | `cudal-gui`, `python cudal_gui.py` | Standard-library UI; no extra dependencies |
| PySide6 GUI | `extras/cudal_gui_pyside6.py` | Optional Qt UI; not installed by default |

## Installation

Requires Python ≥ 3.9.

```bash
pip install .            # core: numpy, pandas, scipy + CLI + Tk GUI
pip install .[all]       # + matplotlib, reportlab, openpyxl
pip install .[qt]        # + PySide6 (optional Qt GUI)
pip install .[dev]       # + pytest, pyinstaller
```

## Usage

### Library

```python
from cudal import cusp1

table = cusp1.acceptance_limit_table(10, 100.0, 95.0, 95.0, 85.1, 114.9, 0.5)
prob = cusp1.probability_of_passing(table, 10, [95.0, 100.0], [1.0, 4.0])
bound = cusp1.sample_probability(100.0, 2.0, 10, 100.0, 95.0, 95.0)
```

### CLI

```bash
cudal                                  # interactive SAS-style menu
cudal cusp1 -m evaluate -o ev.csv      # sub-command mode
cudal disp2 -m sample --mean 90 --se 2.2 --sm 2.46
```

### GUI

```bash
cudal-gui                              # Tkinter
python extras/cudal_gui_pyside6.py     # PySide6 (requires pip install .[qt])
```

See [docs/USER_MANUAL.md](docs/USER_MANUAL.md) for a panel-by-panel guide.

## Outputs and exports

- Results tables (DataFrames) with sortable columns and conditional formatting.
- CSV per table; XLSX workbook with one sheet per scenario.
- PDF listings reproducing the SAS output format (Courier, wrapped column
  blocks, SE × SM LL/UL matrices, repeated page headers).
- Plots: points with cubic-spline interpolation, or contour heatmaps with
  80 %/90 % threshold contours; exportable as PNG.

## Repository layout

```
cudal/        library: computations, CLI, Tk GUI, package data
extras/       optional PySide6 GUI (excluded from the wheel)
docs/         user manual
tests/        pytest smoke tests
scripts/      executable build helper
.github/      CI, PyPI publishing, release workflows
```

## Testing

```bash
pip install -e .[all,dev]
pytest -q
python -m cudal.gui --selftest
```

## References

1. Bergum, J.S. (1990). *Constructing Acceptance Limits for Multiple Stage Tests.* Drug Development and Industrial Pharmacy, 16(14), 2153–2166.
2. Bergum, J., Utter, M. (2000). *Process Validation.* In: Encyclopedia of Biopharmaceutical Statistics, Marcel Dekker, 422–439.
3. Bergum, J.S., Utter, M.L. (2003). *Statistical Methods for Uniformity and Dissolution Testing.* In: Pharmaceutical Process Validation, Marcel Dekker, 667–697.
4. Bergum, J., Li, H. (2007). *Acceptance Limits for the New ICH USP 29 Content Uniformity Test.* Pharmaceutical Technology, October, 88–98.
5. Bergum, J. (2007). *CuDAL Version 2 Users Guide* and *Appendix E – Lower Bound Calculations.*

## Acknowledgments

This project is a re-implementation of the CuDAL application originally
designed, developed and validated in SAS by **Dr. James Bergum**. The
statistical methods, program structure and reference outputs used here are
due to his work; the original SAS programs and validation materials remain
the authoritative source.

## License

MIT. Provided as-is for research and informational use; it does not
constitute regulatory advice. Validate against your own reference
implementation before any GMP use.
