#!/usr/bin/env bash


uv pip install .[all,qt] pyinstaller

uv run pyinstaller --onefile --noconsole --name CuDAL --add-data "cudal/logo.png:cudal" cudal_gui.py
uv run pyinstaller --onefile --noconsole --name CuDAL-Qt --add-data "cudal/logo.png:cudal" extras/cudal_gui_pyside6.py

echo "Done: dist/CuDAL and dist/CuDAL-Qt"