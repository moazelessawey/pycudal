## What's new in v1.0.4

### OC (Operating Characteristic) curves
- New **OC Curve** dialog in **both** GUIs (Tkinter & PySide6), on all four tabs.
- Overlays two curves on one axes:
  - **Computed plan** – analytic OC of your acceptance-limit table.
  - **USP sampling plan** – Monte-Carlo OC of the raw compendial test
    (USP <905> two-stage / USP <711> three-stage rules, Appendix E).
- Selectable x-axis, editable fixed parameters, MC-reps control, seeded RNG.

### Reporting & plotting
- Plan-2 SAS-style PDF matrix header (SM / LL-UL / SE rows) repeated on every page.
- Heatmap NaN holes interpolated so surfaces render complete.

### Packaging / CI
- `build-exe.yml` builds Windows **and** Linux executables for both GUIs and
  attaches them to this release; `publish.yml` publishes the wheel to PyPI.
