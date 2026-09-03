#!/usr/bin/env bash
set -euo pipefail

uv pip install --system .[all,qt] pyinstaller || pip install .[all,qt] pyinstaller

pyinstaller --onefile --noconsole --name PyCuDAL \
  --paths . \
  --collect-all cudal --collect-all scipy --collect-all pandas --collect-all numpy \
  --add-data "assets/logo.png:." \
  --hidden-import matplotlib.backends.backend_tkagg \
  --hidden-import=PIL._tkinter_finder --hidden-import=PIL._imagingtk \
  cudal_gui.py

pyinstaller --onefile --noconsole --name PyCuDAL-Qt \
  --paths . \
  --collect-all cudal --collect-all scipy --collect-all pandas --collect-all numpy \
  --add-data "assets/logo.png:." \
  --hidden-import matplotlib.backends.backend_qtagg \
  extras/cudal_gui_pyside6.py

echo "Done: dist/CuDAL and dist/CuDAL-Qt"
