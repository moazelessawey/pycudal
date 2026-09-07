#!/usr/bin/env bash
set -euo pipefail

uv pip install --system .[all,qt] pyinstaller || pip install .[all,qt] pyinstaller

pyinstaller --onefile --noconsole --name PyCuDAL \
  --paths . \
  --collect-all cudal --collect-all scipy --collect-all pandas --collect-all numpy \
  --add-data "assets/logo.png:." \
  --hidden-import matplotlib.backends.backend_qtagg \
  cudal_gui.py

echo "Done: dist/PyCuDAL"
