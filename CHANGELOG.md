# Changelog

All notable changes to this project are documented here.
Dates live on the GitHub Releases page.

## [Unreleased]
### Added
- Ruff lint/format configuration + pre-commit hooks + CI lint job.
- Repo hygiene: CITATION.cff, CONTRIBUTING.md, SECURITY.md, issue/PR templates.
- Comprehensive menu bar + toolbar in both GUIs; footer developer credit; richer About.
- `utils/cudal.r` — independent R reference implementation for cross-checks.

### Removed
- `.github/workflows/publish.yml` (PyPI publishing not required).

## [1.0.8]
### Added
- Splash screen with real loading progress and developer credit.
- Descriptive default export filenames (e.g. `CUSP2-95x95-10Lx6N.pdf`).

## [1.0.5]
### Added
- OC-curve dialog in both GUIs (computed plan vs USP <905>/<711> Monte-Carlo).

## [1.0.4]
### Fixed
- Heatmap NaN holes interpolated; Plan-2 PDF matrix header repeated per page.

## [1.0.3]
### Fixed
- `PIL._tkinter_finder` hidden import; Windows+Linux exe CI builds.

## [1.0.2]
### Added
- SAS-style PDF listings (repeated title/headers); Qt GUI feature parity.

## [1.0.1]
### Added
- Optional PySide6 GUI (extras/); spline + heatmap plotting.

## [1.0.0]
### Added
- Initial release: `cudal` package, interactive CLI, Tkinter GUI, packaging, CI/CD.
