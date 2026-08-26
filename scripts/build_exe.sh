#!/usr/bin/env bash


uv pip install .[all,qt] pyinstaller

pyinstaller --onefile --noconsole --name CuDAL-Qt \
  --paths . \
  --collect-all cudal \
  --collect-all scipy \
  --collect-all pandas \
  --collect-all numpy \
  --add-data "assets/logo.png:." \
  --hidden-import matplotlib.backends.backend_qtagg \
  extras/cudal_gui_pyside6.py

echo "Done: dist/CuDAL-Qt"