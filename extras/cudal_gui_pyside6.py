"""
cudal_gui_pyside6.py  --  FINAL integrated PySide6 version

CuDAL GUI: 4 tabs (CU Plan 1/2, Dissolution Plan 1/2) x 3 modes
(table / evaluate / sample), with:

* modern flat "card" design, strict column-aligned parameter forms
* background-thread calculations with real progress bar + status text
* scrollable parameters, live validation, tooltips, Reset defaults
* results table: sorting, zebra stripes, conditional P(pass) coloring,
  Ctrl+C copy, CSV export, modal matplotlib dialog (lines+spline and
  heatmap with 80/90% contours), Save PNG
* settings persistence (parameters, mode, tab, window geometry)
* logo.png + fonts/ (TTF) support on Windows AND Linux
* menu, shortcuts (Ctrl+R/E/P, F1), About dialog, --selftest

Requirements:
    pip install PySide6 numpy pandas scipy matplotlib openpyxl

Run:
    python cudal_gui_pyside6.py            # GUI
    python cudal_gui_pyside6.py --selftest # quick unit checks
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import traceback

import numpy as np
import pandas as pd

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QDialog,
    QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel, QLineEdit,
    QRadioButton, QButtonGroup, QPushButton, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QScrollArea, QFrame, QFileDialog,
    QMessageBox, QComboBox, QSizePolicy, QAbstractItemView,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import (
    QAction, QIcon, QColor, QBrush, QPixmap, QFont, QFontDatabase, QKeySequence, QShortcut
)

# ---------------------------------------------------------------------------
# Optional dependencies
# ---------------------------------------------------------------------------
try:
    from cudal import cusp1, cusp2, disp1, disp2
    HAVE_CUDAL = True
except Exception:  # pragma: no cover
    HAVE_CUDAL = False

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
    HAVE_MPL = True
except Exception:  # pragma: no cover
    HAVE_MPL = False

try:
    from scipy.interpolate import make_interp_spline
    HAVE_SPLINE = True
except Exception:  # pragma: no cover
    HAVE_SPLINE = False

try:
    import openpyxl  # noqa: F401
    HAVE_XLSX = True
except Exception:  # pragma: no cover
    HAVE_XLSX = False

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import letter, landscape
    HAVE_PDF = True
except Exception:  # pragma: no cover
    HAVE_PDF = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VERSION = "2.1.0 (PySide6, modern UI)"

BG = "#f4f6f9"
PANEL_BG = "#ffffff"
ACCENT = "#2f6fed"
ACCENT_DARK = "#204ea6"
TEXT = "#1c2733"
MUTED = "#64748b"
BORDER = "#e2e8f0"
OK_GREEN = "#1a8754"
ERR_RED = "#c0392b"

SERIES_COLORS = [ACCENT, OK_GREEN, ERR_RED, "#8e44ad",
                 "#e67e22", "#16a085", "#c2417d", "#5b6470"]

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "cudal_gui_settings.json")

# ---------------------------------------------------------------------------
# SAS-style PDF listing export (reportlab, Courier, column wrapping)
# ---------------------------------------------------------------------------
_PDF_FONT = "Courier"
_PDF_FS = 8.0
_PDF_LEAD = 11.0
_PDF_CHAR = 0.6 * _PDF_FS


def _fmt_num(v):
    """Format a numeric value to 2 decimal places; '*' for NaN/Inf."""
    try:
        if isinstance(v, float) and math.isnan(v):
            return "*"
        if pd.isna(v):
            return "*"
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return "*"
        return f"{f:.2f}"
    except Exception:
        return str(v)


def _cell(v):
    return _fmt_num(v)


def write_sas_pdf(path, df, title_lines):
    """Write `df` to `path` as a SAS-listing-style PDF (Courier, wrapped).

    The report title block AND the table header are repeated on every page.
    """
    page_w, page_h = landscape(letter)
    margin = 36.0
    usable = int((page_w - 2 * margin) / _PDF_CHAR)

    c = rl_canvas.Canvas(path, pagesize=landscape(letter))
    c.setTitle("CuDAL results")
    st = {"y": page_h - margin, "table_header_fn": None}

    # -- low-level drawing (no page checks, used inside new_page) ------------
    def raw(text, indent=0):
        c.setFont(_PDF_FONT, _PDF_FS)
        c.drawString(margin + indent * _PDF_CHAR, st["y"], text)
        st["y"] -= _PDF_LEAD

    def raw_centered(text):
        raw(text, max(0, (usable - len(text)) // 2))

    def draw_title():
        for t in title_lines:
            raw_centered(t)
        raw("")

    def new_page():
        c.showPage()
        st["y"] = page_h - margin
        draw_title()                                   # title on every page
        if st["table_header_fn"] is not None:          # table header on every page
            st["table_header_fn"]()

    # -- page-checking drawing -------------------------------------------------
    def put(text, indent=0):
        if st["y"] < margin:
            new_page()
        raw(text, indent)

    def centered(text):
        put(text, max(0, (usable - len(text)) // 2))

    def blank(n=1):
        for _ in range(n):
            put("")

    def need(n):
        """Force a page break unless `n` more lines fit on this page."""
        if st["y"] - n * _PDF_LEAD < margin:
            new_page()

    draw_title()                                       # first-page title

    cols = [str(x) for x in df.columns]
    low = {cl.lower(): cl for cl in cols}

    # ------------ Plan-2 style matrix: SE rows x SM groups of LL/UL --------
    if {"se", "sm", "ll", "ul"} <= set(low):
        se_c, sm_c, ll_c, ul_c = low["se"], low["sm"], low["ll"], low["ul"]
        tmp = df.copy()
        tmp["_se"] = pd.to_numeric(tmp[se_c], errors="coerce")
        tmp["_sm"] = pd.to_numeric(tmp[sm_c], errors="coerce")
        ses = sorted(tmp["_se"].dropna().unique())
        sms = sorted(tmp["_sm"].dropna().unique())

        get = {}
        for r in tmp.itertuples():
            if pd.notna(r._se) and pd.notna(r._sm):
                get[(r._se, r._sm)] = (_fmt_num(r[ll_c]), _fmt_num(r[ul_c]))

        ll_w = max([2] + [len(v[0]) for v in get.values()])
        ul_w = max([2] + [len(v[1]) for v in get.values()])
        grp_w = ll_w + 1 + ul_w
        se_w = max([2] + [len(_fmt_num(s)) for s in ses])
        gap = 3
        per_page = max(1, (usable - se_w + gap) // (grp_w + gap))

        def header(seg):
            centered("STANDARD DEVIATION OF LOCATION MEANS")
            blank()
            line = " " * se_w
            for sm in seg:
                line += (" " * gap) + f"{_fmt_num(sm):>{grp_w}}"
            put(line)
            line = f"{'SE':>{se_w}}"
            for _ in seg:
                line += (" " * gap) + f"{'LL':>{ll_w}} {'UL':>{ul_w}}"
            put(line)
            blank()

        HDR_LINES = 5   # banner + blank + SM row + LL/UL row + blank

        for start in range(0, len(sms), per_page):      # column wrapping
            seg = sms[start:start + per_page]
            st["table_header_fn"] = None                # don't repeat old header
            need(HDR_LINES + 1)
            header(seg)
            st["table_header_fn"] = lambda seg=seg: header(seg)
            for se in ses:
                line = f"{_fmt_num(se):>{se_w}}"
                for sm in seg:
                    ll, ul = get.get((se, sm), ("*", "*"))
                    line += (" " * gap) + f"{ll:>{ll_w}} {ul:>{ul_w}}"
                put(line)                               # auto page-break repeats
            blank()                                     # title + segment header
        st["table_header_fn"] = None
        c.save()
        return

    # ------------ Plan-1 style: long rows wrapped into side-by-side blocks --
    body = [[_cell(v) for v in row] for _, row in df.iterrows()]
    widths = [max(len(cols[j]), max((len(r[j]) for r in body), default=0))
              for j in range(len(cols))]

    hdr = []
    for j, h in enumerate(cols):
        parts = h.split(" ", 1)
        if len(parts) == 2 and len(parts[0]) <= widths[j] and len(parts[1]) <= widths[j]:
            hdr.append((parts[0], parts[1]))
        else:
            hdr.append((h, ""))
    hdr_lines = 2 if any(b for _a, b in hdr) else 1

    gap, block_gap = 3, 4
    block_w = sum(widths) + gap * (len(widths) - 1)
    n_blocks = max(1, (usable + block_gap) // (block_w + block_gap))
    rpb = max(1, -(-len(body) // n_blocks))                 # rows per block
    chunks = [body[i:i + rpb] for i in range(0, len(body), rpb)]

    def header_line(li):
        return (" " * gap).join(f"{hdr[j][li]:^{widths[j]}}" for j in range(len(cols)))

    def block_line(chunk, i):
        parts = []
        for j in range(len(cols)):
            val = chunk[i][j] if i < len(chunk) else ""
            parts.append(f"{val:>{widths[j]}}")
        return (" " * gap).join(parts)

    for p in range(0, len(chunks), n_blocks):
        page_chunks = chunks[p:p + n_blocks]

        def draw_hdr(_pc=page_chunks):
            for li in range(hdr_lines):
                put((" " * block_gap).join(header_line(li) for _ in _pc))
            blank()

        st["table_header_fn"] = None                    # don't repeat old header
        need(hdr_lines + 2)
        draw_hdr()
        st["table_header_fn"] = draw_hdr                # repeat on page breaks
        for i in range(rpb):
            put((" " * block_gap).join(block_line(ch, i) for ch in page_chunks))
        blank()
    st["table_header_fn"] = None

    c.save()

def resource_path(relative: str) -> str:
    """Resolve bundled files both from source and from a PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _register_local_fonts() -> str | None:
    """Load every TTF/OTF in fonts/ into the Qt application font database."""
    font_dir = resource_path("fonts")
    if not os.path.isdir(font_dir):
        return None
    family = None
    for f in sorted(os.listdir(font_dir)):
        if f.lower().endswith((".ttf", ".otf")):
            fid = QFontDatabase.addApplicationFont(os.path.join(font_dir, f))
            if fid != -1 and family is None:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    family = fams[0]
    return family

def build_stylesheet(family: str) -> str:
    """Balanced 'classic-modern' theme: familiar desktop look, clean palette."""
    return f"""
    QMainWindow, QDialog {{ background: {BG}; }}
    QWidget {{ background: {BG}; color: #1f2937; font-family: "{family}"; }}

    QLabel {{ background: transparent; }}
    QLabel#header {{ font-size: 17px; font-weight: 700; }}
    QLabel#subheader {{ color: {MUTED}; }}
    QLabel#muted {{ color: {MUTED}; font-size: 9pt; }}
    QLabel#section {{ color: {ACCENT_DARK}; font-weight: 700; }}
    QLabel#fieldlabel {{ color: #2f3a4d; }}

    /* panels & group boxes: light cards with a classic frame */
    QFrame#panel, QGroupBox#card {{
        background: {PANEL_BG};
        border: 1px solid #cfd8e3;
        border-radius: 6px;
    }}
    QGroupBox#card {{ margin-top: 12px; font-weight: 600; color: #2f3a4d; }}
    QGroupBox#card::title {{
        subcontrol-origin: margin; left: 10px; padding: 0 4px;
        color: {ACCENT_DARK};
    }}

    /* radio buttons: classic circle + dot, accent colour */
    QRadioButton {{ spacing: 7px; padding: 3px; background: transparent; }}
    QRadioButton::indicator {{
        width: 15px; height: 15px;
        border: 1px solid #8b97a8; border-radius: 8px; background: white;
    }}
    QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
    QRadioButton::indicator:checked {{
        border: 1px solid {ACCENT_DARK};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.45, fx:0.5, fy:0.5,
                    stop:0 {ACCENT}, stop:0.55 {ACCENT},
                    stop:0.56 white, stop:1 white);
    }}

    /* inputs: white with a firm border */
    QLineEdit {{
        background: white; border: 1px solid #aeb9c8; border-radius: 3px;
        padding: 4px 8px; selection-background-color: {ACCENT};
    }}
    QLineEdit:hover {{ border-color: #8b97a8; }}
    QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
    QLineEdit[invalid="true"] {{ background: #fdf1f1; border: 1px solid {ERR_RED}; color: {ERR_RED}; }}

    /* buttons: subtle gradient like classic toolkits */
    QPushButton {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fdfefe, stop:1 #e7ebf2);
        color: #2f3a4d; border: 1px solid #aeb9c8; border-radius: 4px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f4f8ff, stop:1 #dfe8f7);
        border-color: {ACCENT}; color: {ACCENT_DARK};
    }}
    QPushButton:pressed {{ background: #dfe4ec; border-color: #8b97a8; }}
    QPushButton:disabled {{ background: #eef1f5; color: #9aa7b8; border-color: #d5dce6; }}
    QPushButton#accent {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5a8ff2, stop:1 {ACCENT});
        border: 1px solid {ACCENT_DARK}; color: white; padding: 8px 20px;
    }}
    QPushButton#accent:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4c82f3, stop:1 {ACCENT_DARK});
    }}
    QPushButton#accent:disabled {{ background: #b6c6ea; border-color: #9db1dd; color: #f8fafc; }}
    QPushButton#outline {{ background: white; border: 1px solid {ACCENT}; color: {ACCENT_DARK}; }}
    QPushButton#outline:hover {{ background: #eaf1fe; }}

    /* progress: framed bar with accent fill, same height as the Run button */
    QProgressBar {{
        background: white;
        border: 1px solid #aeb9c8;
        border-radius: 4px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6ea0f5, stop:1 {ACCENT});
        border-radius: 3px;
    }}

    /* scrollbars: classic width, soft colours, no arrows */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: #eef1f5; width: 12px; border: 1px solid #dfe4ec; }}
    QScrollBar::handle:vertical {{ background: #c3ccd8; border-radius: 6px; min-height: 24px; margin: 1px; }}
    QScrollBar::handle:vertical:hover {{ background: #a9b4c4; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: #eef1f5; height: 12px; border: 1px solid #dfe4ec; }}
    QScrollBar::handle:horizontal {{ background: #c3ccd8; border-radius: 6px; min-width: 24px; margin: 1px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* tabs: classic raised tabs on a framed pane */
    QTabWidget::pane {{
        border: 1px solid #cfd8e3; background: {PANEL_BG}; border-radius: 4px;
    }}
    QTabBar::tab {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f2f5f9, stop:1 #e2e7ee);
        color: {MUTED};
        border: 1px solid #cfd8e3; border-bottom: none;
        border-top-left-radius: 5px; border-top-right-radius: 5px;
        padding: 7px 16px; margin-right: 2px;
    }}
    QTabBar::tab:hover {{ color: #2f3a4d; background: #eef3fa; }}
    QTabBar::tab:selected {{ background: {PANEL_BG}; color: {ACCENT_DARK}; font-weight: 600; }}

    /* table: classic grid with soft header */
    QTableWidget {{
        background: white; alternate-background-color: #f4f7fb;
        border: 1px solid #cfd8e3; border-radius: 4px;
        gridline-color: #dde3ec;
        selection-background-color: #cfdffc; selection-color: #101828;
    }}
    QHeaderView::section {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fbfcfe, stop:1 #edf0f5);
        color: #334155; border: none;
        border-right: 1px solid #dde3ec; border-bottom: 1px solid #cfd8e3;
        padding: 5px; font-weight: 600;
    }}

    QComboBox {{
        background: white; border: 1px solid #aeb9c8; border-radius: 3px;
        padding: 4px 8px; min-width: 140px;
    }}
    QComboBox:hover {{ border-color: {ACCENT}; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: center right;
        width: 20px; border: none;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f6f8fb, stop:1 #e2e7ee);
    }}
    QComboBox QAbstractItemView {{
        background: white; border: 1px solid #aeb9c8;
        selection-background-color: #cfdffc;
    }}

    QMenuBar {{ background: #eef1f6; border-bottom: 1px solid #cfd8e3; }}
    QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
    QMenuBar::item:selected {{ background: #d7e3fc; border-radius: 3px; }}
    QMenu {{ background: {PANEL_BG}; border: 1px solid #aeb9c8; padding: 4px; }}
    QMenu::item {{ padding: 5px 24px; border-radius: 3px; }}
    QMenu::item:selected {{ background: #cfdffc; }}
    QMenu::separator {{ height: 1px; background: #dde3ec; margin: 4px 8px; }}

    QStatusBar {{ background: #eef1f6; color: {MUTED}; border-top: 1px solid #cfd8e3; }}

    /* classic pale-yellow tooltip */
    QToolTip {{
        background: #ffffe1; color: #333333; border: 1px solid #767676; padding: 4px;
    }}
    """

# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------
def _spline_xy(xs, ys, samples=300):
    """Smooth cubic spline through (xs, ys); linear fallback w/o scipy."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    ux, inv = np.unique(xs, return_inverse=True)
    uy = np.array([ys[inv == i].mean() for i in range(ux.size)]) if ux.size != xs.size else ys
    order = np.argsort(ux)
    ux, uy = ux[order], uy[order]
    if ux.size < 2:
        return ux, uy
    if HAVE_SPLINE:
        k = min(3, ux.size - 1)
        try:
            spl = make_interp_spline(ux, uy, k=k)
            xx = np.linspace(ux[0], ux[-1], samples)
            return xx, spl(xx)
        except Exception:
            pass
    xx = np.linspace(ux[0], ux[-1], samples)
    return xx, np.interp(xx, ux, uy)


def _grid_columns(df):
    """Detect a 3-column grid and return (x, y, z) column *names*.

    The surface value (z) is the column with the most distinct values
    (it changes on nearly every row); the two axis columns are the rest,
    with x = the axis having more distinct values.  Returns None when the
    DataFrame is not a proper 3-column grid (e.g. the acceptance-limit or
    probability tables in a different column order are still handled).
    """
    num = df.select_dtypes(include=[np.number]).dropna()
    if num.shape[1] != 3 or len(num) < 4:
        return None

    uniq = [num[c].nunique() for c in num.columns]
    if min(uniq) < 2:
        return None

    zcol = num.columns[int(np.argmax(uniq))]
    axes = sorted((c for c in num.columns if c != zcol),
                  key=lambda c: num[c].nunique(), reverse=True)

    # sanity check: the surface must vary more than either axis
    if num[zcol].nunique() <= max(num[axes[0]].nunique(), num[axes[1]].nunique()):
        return None

    return str(axes[0]), str(axes[1]), str(zcol)


def build_results_plot(fig, df):
    """Points + spline curves for the results DataFrame."""
    ax = fig.add_subplot(111)
    num = df.select_dtypes(include=[np.number]).replace([np.inf, -np.inf], np.nan).dropna()
    num = num.copy()
    num.columns = [str(c) for c in num.columns]
    cols = list(num.columns)

    if num.shape[1] >= 2 and len(num) >= 2:
        grid = _grid_columns(df)
        if grid:
            xcol, gcol, ycol = grid
            for color, (g, sub) in zip(SERIES_COLORS, num.groupby(gcol, sort=True)):
                xs = sub[xcol].to_numpy(dtype=float)
                ys = sub[ycol].to_numpy(dtype=float)
                order = np.argsort(xs)
                xs, ys = xs[order], ys[order]
                ax.plot(xs, ys, "o", color=color, ms=3, alpha=0.7, label=f"{gcol} = {g:g}")
                xx, yy = _spline_xy(xs, ys)
                ax.plot(xx, yy, "-", color=color, lw=1.6)
            ax.set_xlabel(xcol)
            ax.set_ylabel(ycol)
            ax.legend(fontsize=8, loc="best")
        else:
            xcol = cols[0]
            xs_all = num[cols[0]].to_numpy(dtype=float)
            for color, ycol in zip(SERIES_COLORS, cols[1:]):
                ys = num[ycol].to_numpy(dtype=float)
                ax.plot(xs_all, ys, "o", color=color, ms=3, alpha=0.7, label=ycol)
                xx, yy = _spline_xy(xs_all, ys)
                ax.plot(xx, yy, "-", color=color, lw=1.6)
            ax.set_xlabel(xcol)
            ax.legend(fontsize=8, loc="best")

        kind = "cubic spline" if HAVE_SPLINE else "linear interpolation"
        ax.set_title(f"Results with {kind}", fontsize=10)
    else:
        ax.text(0.5, 0.5, "Not enough numeric data to plot.", ha="center", va="center")

    ax.grid(True, alpha=0.3)
    ax.set_facecolor("#fbfcfe")
    fig.tight_layout()


def build_heatmap(fig, df, thresholds=(0.8, 0.9)):
    """Contour-filled heatmap for 3-column grids (x, y, z) with correct axes."""
    ax = fig.add_subplot(111)
    grid = _grid_columns(df)
    if grid is None:
        ax.text(0.5, 0.5, "Data is not a 3-column grid.", ha="center", va="center")
        fig.tight_layout()
        return

    xcol, ycol, zcol = grid
    work = df[[c for c in df.columns if str(c) in grid]].copy()
    work.columns = [str(c) for c in work.columns]
    work = work.apply(pd.to_numeric, errors="coerce").dropna()

    piv = work.pivot_table(index=ycol, columns=xcol, values=zcol, aggfunc="mean")
    piv = piv.sort_index(axis=0).sort_index(axis=1)

    X = piv.columns.to_numpy(dtype=float)
    Y = piv.index.to_numpy(dtype=float)
    Z = np.ma.masked_invalid(piv.to_numpy(dtype=float))   # holes -> masked, not artifacts

    if Z.count() == 0 or X.size < 2 or Y.size < 2:
        ax.text(0.5, 0.5, "Not enough grid points for a heatmap.", ha="center", va="center")
        fig.tight_layout()
        return

    cs = ax.contourf(X, Y, Z, levels=min(24, max(6, X.size + Y.size)), cmap="viridis")
    fig.colorbar(cs, ax=ax, label=zcol)

    if X.size <= 12:
        ax.set_xticks(X)
    if Y.size <= 12:
        ax.set_yticks(Y)

    if float(Z.max()) <= 1.01:  # probability-scale surface -> draw 80/90% contours
        for i, t in enumerate(thresholds):
            if float(Z.min()) <= t <= float(Z.max()):
                ax.contour(X, Y, Z, levels=[t], colors="white", linewidths=1.2)
                ax.text(0.02, 0.98 - 0.06 * i, f"white line = {t:.0%}",
                        transform=ax.transAxes, fontsize=8, color="white", va="top")

    ax.set_xlabel(xcol)
    ax.set_ylabel(ycol)
    ax.set_title(f"{zcol} over {xcol} / {ycol}", fontsize=10)
    fig.tight_layout()


# ---------------------------------------------------------------------------
# Form fields (strict column alignment)
# ---------------------------------------------------------------------------
class LabeledField:
    """Label + line-edit pair placed into a SHARED grid so every input sits in
    one strict, perfectly aligned column.  Live validation via a dynamic Qt
    property styled in QSS."""

    EDIT_WIDTH = 120
    EDIT_HEIGHT = 30

    def __init__(self, layout, row, key, label, default, cast=float, tip=None):
        self.key = key
        self.default = default
        self.cast = cast

        self.label = QLabel(label)
        self.label.setObjectName("fieldlabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.edit = QLineEdit(str(default))
        self.edit.setFixedWidth(self.EDIT_WIDTH)
        self.edit.setFixedHeight(self.EDIT_HEIGHT)
        self.edit.setToolTip(tip or f"{label}\nDefault: {default}")

        layout.addWidget(self.label, row, 0)
        layout.addWidget(self.edit, row, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        self.edit.textChanged.connect(self._validate)
        self._validate()

    def _validate(self, *_):
        raw = self.edit.text().strip()
        ok = bool(raw)
        if ok:
            try:
                self.cast(raw)
            except ValueError:
                ok = False
        self.edit.setProperty("invalid", "false" if ok else "true")
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)

    def reset(self):
        self.edit.setText(str(self.default))

    def get(self, cast=None):
        cast = cast or self.cast
        raw = self.edit.text().strip()
        if raw == "":
            raise ValueError(f"'{self.key}' cannot be empty")
        try:
            return cast(raw)
        except ValueError:
            raise ValueError(f"'{self.key}' must be a number, got {raw!r}")


def build_form(layout, specs, start_row=0, registry=None):
    """Fill a shared QGridLayout; returns dict[key] -> LabeledField."""
    fields = {}
    for i, (key, label, default) in enumerate(specs):
        fields[key] = LabeledField(layout, start_row + i, key, label, default)
    if registry is not None:
        registry.update(fields)
    return fields


class NumItem(QTableWidgetItem):
    """Table item that sorts numerically instead of lexicographically."""

    def __lt__(self, other):
        a = self.data(Qt.ItemDataRole.UserRole)
        b = other.data(Qt.ItemDataRole.UserRole)
        try:
            return float(a) < float(b)
        except Exception:
            return super().__lt__(other)


def fmt_num(v, digits=4):
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    if isinstance(v, (float, np.floating)):
        return f"{v:,.{digits}f}"
    return str(v)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------
class Worker(QThread):
    progress = Signal(float, str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self._job = job

    def run(self):
        try:
            result = self._job(self.progress.emit)
            self.finished_ok.emit(result)
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc())


# ---------------------------------------------------------------------------
# Plot dialog (modal)
# ---------------------------------------------------------------------------
class PlotDialog(QDialog):
    def __init__(self, df, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Results plot")
        self.resize(880, 640)
        self.setMinimumSize(520, 380)
        self.setModal(True)
        self._df = df
        self._can_heat = _grid_columns(df) is not None

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Plot style:"))
        self.style_cb = QComboBox()
        self.style_cb.addItems(["Lines + spline"] + (["Heatmap (grid)"] if self._can_heat else []))
        top.addWidget(self.style_cb)
        top.addStretch(1)
        save_btn = QPushButton("Save PNG")
        save_btn.clicked.connect(self._save_png)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        top.addWidget(save_btn)
        top.addWidget(close_btn)
        lay.addLayout(top)

        self._fig = Figure(dpi=100)
        self._canvas = FigureCanvas(self._fig)
        self._toolbar = NavigationToolbar(self._canvas, self)
        lay.addWidget(self._toolbar)
        lay.addWidget(self._canvas, 1)

        self.style_cb.currentIndexChanged.connect(self._redraw)
        self._redraw()

    def _redraw(self):
        self._fig.clear()
        if self.style_cb.currentText() == "Heatmap (grid)" and self._can_heat:
            build_heatmap(self._fig, self._df)
        else:
            build_results_plot(self._fig, self._df)
        self._canvas.draw()

    def _save_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save figure", "results.png",
                                              "PNG image (*.png)")
        if path:
            self._fig.savefig(path, dpi=150)
            QMessageBox.information(self, "Saved", f"Figure saved to {path}")


# ---------------------------------------------------------------------------
# Results panel
# ---------------------------------------------------------------------------
class ResultsPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._df = None
        self._prob_col = None

        lay = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        title = QLabel("Results")
        title.setObjectName("section")
        self.row_count = QLabel("")
        self.row_count.setObjectName("muted")
        self.plot_btn = QPushButton("Plot")
        self.plot_btn.setObjectName("outline")
        self.plot_btn.setEnabled(False)
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setEnabled(False)
        self.pdf_btn = QPushButton("Export PDF")
        self.pdf_btn.setEnabled(False)

        toolbar.addWidget(title)
        toolbar.addStretch(1)
        toolbar.addWidget(self.row_count)
        toolbar.addWidget(self.plot_btn)
        toolbar.addWidget(self.export_btn)
        toolbar.addWidget(self.pdf_btn)
        lay.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.setToolTip("Click a header to sort | Ctrl+C copies selected rows")
        lay.addWidget(self.table, 1)

        self.export_btn.clicked.connect(self._export_csv)
        self.plot_btn.clicked.connect(self._show_plot)
        self.pdf_btn.clicked.connect(self._export_pdf)
        self.report_meta = None
        QShortcut(QKeySequence.Copy, self.table, activated=self._copy_selection)

    # -- population -----------------------------------------------------------
    def clear(self):
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self._df = None
        self._prob_col = None
        self.export_btn.setEnabled(False)
        self.plot_btn.setEnabled(False)
        self.pdf_btn.setEnabled(False)
        self.row_count.setText("")

    def show_dataframe(self, df: pd.DataFrame):
        self.clear()
        self._df = df
        cols = [str(c) for c in df.columns]

        self._prob_col = None
        for c in df.columns:
            if any(s in str(c).lower() for s in ("prob", "pass")):
                ser = pd.to_numeric(df[c], errors="coerce").dropna()
                if len(ser) and ser.max() <= 1.0:
                    self._prob_col = c
                    break

        self.table.setSortingEnabled(False)
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(df))

        for r, (_, row) in enumerate(df.iterrows()):
            for ci, c in enumerate(df.columns):
                v = row[c]
                item = NumItem(fmt_num(v, 4))
                if isinstance(v, (float, np.floating)):
                    item.setData(Qt.ItemDataRole.UserRole, float(v))
                if self._prob_col is not None and c == self._prob_col:
                    try:
                        pv = float(v)
                        if pv < 0.8:
                            item.setForeground(QBrush(QColor(ERR_RED)))
                        elif pv >= 0.9:
                            item.setForeground(QBrush(QColor(OK_GREEN)))
                    except Exception:
                        pass
                self.table.setItem(r, ci, item)

        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()

        self.export_btn.setEnabled(True)
        can_plot = HAVE_MPL and len(df) >= 2 and df.select_dtypes(include=[np.number]).shape[1] >= 2
        self.plot_btn.setEnabled(bool(can_plot))
        self.pdf_btn.setEnabled(bool(HAVE_PDF))
        self.row_count.setText(f"{len(df)} rows")

    def show_dict(self, d: dict):
        self.clear()
        self._df = pd.DataFrame([d])
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Field", "Value"])
        self.table.setRowCount(len(d))
        for r, (k, v) in enumerate(d.items()):
            self.table.setItem(r, 0, QTableWidgetItem(str(k)))
            self.table.setItem(r, 1, QTableWidgetItem(fmt_num(v, 6)))
        self.table.resizeColumnsToContents()
        self.export_btn.setEnabled(True)
        self.plot_btn.setEnabled(False)
        self.pdf_btn.setEnabled(bool(HAVE_PDF))
        self.row_count.setText("1 result")

    # -- actions -----------------------------------------------------------------
    def _copy_selection(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if not rows:
            return
        lines = []
        for r in rows:
            lines.append("\t".join(
                self.table.item(r, c).text() if self.table.item(r, c) else ""
                for c in range(self.table.columnCount())))
        QApplication.clipboard().setText("\n".join(lines))

    def _show_plot(self):
        if not HAVE_MPL:
            QMessageBox.critical(self, "Plot unavailable",
                                 "matplotlib is required for plotting.\n"
                                 "Install it with:  pip install matplotlib")
            return
        if self._df is None:
            return
        PlotDialog(self._df, self).exec()

    def _export_csv(self):
        if self._df is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "results.csv",
                                              "CSV files (*.csv)")
        if not path:
            return
        self._df.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
        QMessageBox.information(self, "Exported", f"Saved to {path}")

    def _export_pdf(self):
        if not HAVE_PDF:
            QMessageBox.critical(self, "PDF export unavailable",
                                 "reportlab is required.\nInstall it with:  pip install reportlab")
            return
        if self._df is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", "results.pdf",
                                              "PDF files (*.pdf)")
        if not path:
            return
        meta = self.report_meta or {"title": ["CuDAL RESULTS"]}
        try:
            write_sas_pdf(path, self._df, meta["title"])
            QMessageBox.information(self, "Exported", f"Saved to {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "PDF export failed", str(exc))

# ---------------------------------------------------------------------------
# Base tab
# ---------------------------------------------------------------------------
class BaseTab(QWidget):
    MODES = [("table", "Acceptance limit table"),
             ("evaluate", "Probability of passing"),
             ("sample", "Sample probability")]

    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self._worker = None
        self._table_cache = {}
        self.field_registry = {m: {} for m, _ in self.MODES}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)

        hdr = QLabel(title)
        hdr.setObjectName("header")
        sub = QLabel(subtitle)
        sub.setObjectName("subheader")
        outer.addWidget(hdr)
        outer.addWidget(sub)

        body = QHBoxLayout()
        outer.addLayout(body, 1)

        # --- left: controls -----------------------------------------------------
        controls = QFrame()
        controls.setObjectName("panel")
        controls.setFixedWidth(360)
        cl = QVBoxLayout(controls)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(10)

        mode_box = QGroupBox("Analysis mode")
        mode_box.setObjectName("card")
        ml = QVBoxLayout(mode_box)
        ml.setContentsMargins(14, 16, 14, 12)
        ml.setSpacing(2)
        self.mode_group = QButtonGroup(self)
        self._mode_buttons = {}
        for val, label in self.MODES:
            rb = QRadioButton(label)
            rb.setProperty("mode", val)
            rb.setFixedHeight(26)
            self.mode_group.addButton(rb)
            self._mode_buttons[val] = rb
            ml.addWidget(rb)
        self._mode_buttons["table"].setChecked(True)
        self.mode_group.buttonClicked.connect(self._switch_mode)
        cl.addWidget(mode_box)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(12)
        self.mode_frames = {}
        for val, _ in self.MODES:
            gb = QGroupBox("Parameters")
            gb.setObjectName("card")
            g = QGridLayout()
            g.setContentsMargins(14, 20, 14, 14)   # strict, uniform card padding
            g.setHorizontalSpacing(12)
            g.setVerticalSpacing(8)
            g.setColumnStretch(0, 1)               # labels fill col 0...
            g.setColumnMinimumWidth(1, LabeledField.EDIT_WIDTH)  # inputs align in col 1
            gb.setLayout(g)
            self.mode_frames[val] = gb
            self._content_layout.addWidget(gb)
        self._content_layout.addStretch(1)
        self.scroll.setWidget(content)
        cl.addWidget(self.scroll, 1)

        self._build_mode_frames()

        run_row = QHBoxLayout()

        self.run_btn = QPushButton("Run")
        self.run_btn.setObjectName("accent")
        self.run_btn.setToolTip("Run the selected analysis (Ctrl+R)")
        self.reset_btn = QPushButton("Reset")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        # uniform run row: progress bar as tall as the Run button
        for w in (self.run_btn, self.reset_btn, self.progress):
            w.setFixedHeight(34)

        run_row.addWidget(self.run_btn)
        run_row.addWidget(self.reset_btn)
        run_row.addWidget(self.progress, 1)
        cl.addLayout(run_row)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        cl.addWidget(self.status_label)

        body.addWidget(controls)

        # --- right: results -----------------------------------------------------
        self.results = ResultsPanel()
        body.addWidget(self.results, 1)

        self.run_btn.clicked.connect(self._on_run)
        self.reset_btn.clicked.connect(self._reset_defaults)
        self._switch_mode()

    # -- subclass hooks -----------------------------------------------------------
    def _build_mode_frames(self):
        raise NotImplementedError

    def _run_table(self):
        raise NotImplementedError

    def _run_evaluate(self):
        raise NotImplementedError

    def _run_sample(self):
        raise NotImplementedError

    @staticmethod
    def _cache_key(*args):
        norm = []
        for a in args:
            if isinstance(a, (list, tuple)):
                norm.append(tuple(round(float(x), 12) for x in a))
            else:
                norm.append(a)
        return tuple(norm)

    # -- settings -------------------------------------------------------------------
    def collect_state(self):
        return {
            "mode": self._current_mode(),
            "fields": {mode: {k: f.edit.text() for k, f in reg.items()}
                       for mode, reg in self.field_registry.items()},
        }

    def apply_state(self, state):
        if not isinstance(state, dict):
            return
        for mode, reg in self.field_registry.items():
            for k, field in reg.items():
                val = state.get("fields", {}).get(mode, {}).get(k)
                if val is not None:
                    field.edit.setText(str(val))
        mode = state.get("mode")
        if mode in self._mode_buttons:
            self._mode_buttons[mode].setChecked(True)
            self._switch_mode()

    def _reset_defaults(self):
        for reg in self.field_registry.values():
            for field in reg.values():
                field.reset()
        self.status_label.setText("Parameters reset to defaults.")

    # -- plumbing -------------------------------------------------------------------
    def _current_mode(self):
        return self.mode_group.checkedButton().property("mode")

    def _switch_mode(self, *_):
        mode = self._current_mode()
        for val, gb in self.mode_frames.items():
            gb.setVisible(val == mode)

    def _on_run(self):
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            job = {"table": self._run_table,
                   "evaluate": self._run_evaluate,
                   "sample": self._run_sample}[self._current_mode()]()
        except ValueError as exc:
            QMessageBox.critical(self, "Invalid input", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Invalid input", str(exc))
            return

        self.run_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status_label.setText("Calculating...")

        self._worker = Worker(job, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.finished.connect(self._worker_finished)
        self._worker.start()

    def _on_progress(self, frac, msg):
        self.progress.setValue(int(min(100.0, frac * 100)))
        if msg:
            self.status_label.setText(msg)

    def _on_done(self, result):
        self.progress.setValue(100)
        if isinstance(result, pd.DataFrame):
            self.results.show_dataframe(result)
            self.status_label.setText(f"Done -- {len(result)} row(s) computed.")
        else:
            self.results.show_dict(result)
            self.status_label.setText("Done.")
        self.results.report_meta = self._report_meta()

    def _on_fail(self, tb):
        self.progress.setValue(0)
        self.status_label.setText("Calculation failed -- see error dialog.")
        QMessageBox.critical(self, "Calculation error", tb)

    def _worker_finished(self):
        self.run_btn.setEnabled(True)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    # -- SAS-style PDF title block --------------------------------------------
    def _fv(self, *keys):
        for d in (getattr(self, "table_fields", {}), getattr(self, "sample_fields", {})):
            for k in keys:
                if k in d:
                    try:
                        return d[k].get(float)
                    except Exception:
                        return None
        return None

    def _report_meta(self):
        name = type(self).__name__
        dom = "DISSOLUTION" if name.startswith("Disp") else "CONTENT UNIFORMITY"
        plan = 2 if name.endswith("2Tab") else 1
        n = self._fv("number", "num")
        loc = self._fv("loc")
        target = self._fv("target")
        q = self._fv("q")
        lbound = self._fv("lbound")
        cilevel = self._fv("cilevel")
        lines = []
        if plan == 1:
            key = f"TARGET = {target:.1f}" if target is not None else f"Q = {q:.1f}"
            lines.append(f"ACCEPTANCE LIMITS FOR {dom}(N= {n:.0f}, {key})")
            lines.append("SAMPLING PLAN 1")
            lines.append(f"(MEETING LIMITS GUARANTEES, WITH {cilevel:.1f}% ASSURANCE, THAT AT LEAST")
            lines.append(f"{lbound:.1f}% OF SAMPLES TESTED FOR {dom} WILL PASS THE USP TEST)")
        else:
            lines.append(f"ACCEPTANCE LIMITS FOR {dom}")
            lines.append("SAMPLING PLAN 2")
            base = f"TARGET={target:.1f}" if target is not None else f"Q={q:.1f}"
            lines.append(f"{base}, LOWER BOUND = {lbound:.1f}, CONFIDENCE LEVEL = {cilevel:.1f}")
            lines.append("TABLE ENTRIES ARE LOWER(LL) AND UPPER(UL) LIMITS ON THE MEAN")
            if n is not None and loc is not None:
                lines.append(f"OF {int(n * loc)} ASSAYS:  {int(n)} ASSAYS AT EACH OF "
                             f"{int(loc)} DIFFERENT LOCATIONS")
            lines.append("SE IS THE POOLED WITHIN LOCATION STANDARD DEVIATION")
            lines.append("STANDARD DEVIATIONS AND MEANS ARE EXPRESSED IN % CLAIM")
        if self._current_mode() != "table":
            lines.append(f"MODE: {dict(self.MODES)[self._current_mode()].upper()}")
        return {"title": lines}


def make_grid(low: float, high: float, step: float, name: str):
    if step <= 0:
        raise ValueError(f"{name} step must be positive")
    if high < low:
        raise ValueError(f"{name} high must be >= {name} low")
    n = int(round((high - low) / step)) + 1
    return [low + i * step for i in range(n)]


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
class Cusp1Tab(BaseTab):
    def __init__(self, parent=None):
        super().__init__("Content Uniformity -- Sampling Plan 1",
                         "Single composite sample (USP <905>).", parent)

    def _build_mode_frames(self):
        self.table_fields = build_form(self.mode_frames["table"].layout(), [
            ("number", "Number of units (N)", 10),
            ("target", "Target / label claim (%)", 100.0),
            ("lbound", "Lower bound (%)", 95.0),
            ("cilevel", "Confidence level (%)", 95.0),
            ("mean_low", "Mean grid low", 85.1),
            ("mean_high", "Mean grid high", 114.9),
            ("mean_step", "Mean grid step", 0.5),
        ], registry=self.field_registry["table"])

        lay = self.mode_frames["evaluate"].layout()
        desc = QLabel("Builds the table above, then evaluates:")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        lay.addWidget(desc, 0, 0, 1, 2)
        self.eval_fields = build_form(lay, [
            ("u_low", "True mean U -- low", 95.0),
            ("u_high", "True mean U -- high", 105.0),
            ("u_step", "True mean U -- step", 2.5),
            ("cv_low", "True CV(%) -- low", 1.0),
            ("cv_high", "True CV(%) -- high", 4.0),
            ("cv_step", "True CV(%) -- step", 1.0),
        ], start_row=1, registry=self.field_registry["evaluate"])
        for k in ("number", "target", "lbound", "cilevel"):
            self.eval_fields[k] = self.table_fields[k]

        self.sample_fields = build_form(self.mode_frames["sample"].layout(), [
            ("mean", "Sample mean (%)", 100.0),
            ("cv", "Sample CV (%)", 2.0),
            ("number", "Number of units (N)", 10),
            ("target", "Target / label claim (%)", 100.0),
            ("lbound", "Lower bound (%)", 95.0),
            ("cilevel", "Confidence level (%)", 95.0),
        ], registry=self.field_registry["sample"])

    def _run_table(self):
        v = self.table_fields
        number = v["number"].get(int); target = v["target"].get(float)
        lbound = v["lbound"].get(float); cilevel = v["cilevel"].get(float)
        mean_low = v["mean_low"].get(float); mean_high = v["mean_high"].get(float)
        mean_step = v["mean_step"].get(float)
        key = self._cache_key(number, target, lbound, cilevel, mean_low, mean_high, mean_step)

        def job(progress):
            hit = self._table_cache.get(key)
            if hit is not None:
                progress(0.5, "Using cached table...")
                return hit
            progress(0.2, "Computing acceptance table...")
            table = cusp1.acceptance_limit_table(number, target, lbound, cilevel,
                                                 mean_low, mean_high, mean_step)
            self._table_cache[key] = table
            progress(1.0, "Table complete.")
            return table
        return job

    def _run_evaluate(self):
        v = self.table_fields
        number = v["number"].get(int); target = v["target"].get(float)
        lbound = v["lbound"].get(float); cilevel = v["cilevel"].get(float)
        u_vals = make_grid(self.eval_fields["u_low"].get(float),
                           self.eval_fields["u_high"].get(float),
                           self.eval_fields["u_step"].get(float), "U")
        cv_vals = make_grid(self.eval_fields["cv_low"].get(float),
                            self.eval_fields["cv_high"].get(float),
                            self.eval_fields["cv_step"].get(float), "CV")
        key = self._cache_key(number, target, lbound, cilevel)

        def job(progress):
            table = self._table_cache.get(key)
            if table is None:
                progress(0.2, "Building acceptance table...")
                table = cusp1.acceptance_limit_table(number, target, lbound, cilevel)
                self._table_cache[key] = table
            else:
                progress(0.2, "Using cached table...")
            progress(0.6, "Evaluating probability grid...")
            return cusp1.probability_of_passing(table, number, u_vals, cv_vals)
        return job

    def _run_sample(self):
        v = self.sample_fields
        mean = v["mean"].get(float); cv = v["cv"].get(float)
        number = v["number"].get(int); target = v["target"].get(float)
        lbound = v["lbound"].get(float); cilevel = v["cilevel"].get(float)

        def job(progress):
            progress(0.4, "Computing sample probability...")
            return cusp1.sample_probability(mean, cv, number, target, lbound, cilevel)
        return job


class Cusp2Tab(BaseTab):
    def __init__(self, parent=None):
        super().__init__("Content Uniformity -- Sampling Plan 2",
                         "Multiple locations, within/between-location variance components (USP <905>).",
                         parent)

    def _build_mode_frames(self):
        self.table_fields = build_form(self.mode_frames["table"].layout(), [
            ("num", "Units per location", 6),
            ("loc", "Number of locations", 10),
            ("target", "Target / label claim (%)", 100.0),
            ("lbound", "Lower bound (%)", 95.0),
            ("cilevel", "Confidence level (%)", 95.0),
            ("se_low", "Within-loc SD -- low", 0.5),
            ("se_high", "Within-loc SD -- high", 4.0),
            ("se_step", "Within-loc SD -- step", 0.5),
            ("sm_low", "Between-loc SD -- low", 0.5),
            ("sm_high", "Between-loc SD -- high", 4.0),
            ("sm_step", "Between-loc SD -- step", 0.5),
        ], registry=self.field_registry["table"])

        lay = self.mode_frames["evaluate"].layout()
        desc = QLabel("Builds the table above, then evaluates:")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        lay.addWidget(desc, 0, 0, 1, 2)
        self.eval_fields = build_form(lay, [
            ("u_low", "True mean U -- low", 95.0),
            ("u_high", "True mean U -- high", 105.0),
            ("u_step", "True mean U -- step", 2.5),
            ("sigse_low", "True within-loc SD -- low", 1.0),
            ("sigse_high", "True within-loc SD -- high", 3.0),
            ("sigse_step", "True within-loc SD -- step", 1.0),
            ("sigsm_low", "True between-loc SD -- low", 1.0),
            ("sigsm_high", "True between-loc SD -- high", 3.0),
            ("sigsm_step", "True between-loc SD -- step", 1.0),
        ], start_row=1, registry=self.field_registry["evaluate"])

        self.sample_fields = build_form(self.mode_frames["sample"].layout(), [
            ("mean", "Sample mean (%)", 100.0),
            ("se", "Sample within-loc SD", 2.2),
            ("sm", "Sample between-loc SD", 2.46),
            ("num", "Units per location", 6),
            ("loc", "Number of locations", 10),
            ("target", "Target / label claim (%)", 100.0),
            ("cilevel", "Confidence level (%)", 95.0),
        ], registry=self.field_registry["sample"])

    def _table_args(self):
        v = self.table_fields
        num = v["num"].get(int); loc = v["loc"].get(int)
        target = v["target"].get(float); lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        se_vals = make_grid(v["se_low"].get(float), v["se_high"].get(float), v["se_step"].get(float), "SE")
        sm_vals = make_grid(v["sm_low"].get(float), v["sm_high"].get(float), v["sm_step"].get(float), "SM")
        return num, loc, target, lbound, cilevel, se_vals, sm_vals

    def _run_table(self):
        num, loc, target, lbound, cilevel, se_vals, sm_vals = self._table_args()
        key = self._cache_key(num, loc, target, lbound, cilevel, se_vals, sm_vals)

        def job(progress):
            hit = self._table_cache.get(key)
            if hit is not None:
                progress(0.5, "Using cached table...")
                return hit
            progress(0.2, "Computing acceptance table (Plan 2)...")
            table = cusp2.acceptance_limit_table(num, loc, target, lbound, cilevel, se_vals, sm_vals)
            self._table_cache[key] = table
            progress(1.0, "Table complete.")
            return table
        return job

    def _run_evaluate(self):
        num, loc, target, lbound, cilevel, se_vals, sm_vals = self._table_args()
        u_vals = make_grid(self.eval_fields["u_low"].get(float), self.eval_fields["u_high"].get(float),
                           self.eval_fields["u_step"].get(float), "U")
        sigse_vals = make_grid(self.eval_fields["sigse_low"].get(float), self.eval_fields["sigse_high"].get(float),
                               self.eval_fields["sigse_step"].get(float), "within-loc SD")
        sigsm_vals = make_grid(self.eval_fields["sigsm_low"].get(float), self.eval_fields["sigsm_high"].get(float),
                               self.eval_fields["sigsm_step"].get(float), "between-loc SD")
        key = self._cache_key(num, loc, target, lbound, cilevel, se_vals, sm_vals)

        def job(progress):
            table = self._table_cache.get(key)
            if table is None:
                progress(0.2, "Building acceptance table (Plan 2)...")
                table = cusp2.acceptance_limit_table(num, loc, target, lbound, cilevel, se_vals, sm_vals)
                self._table_cache[key] = table
            else:
                progress(0.2, "Using cached table...")
            d1 = se_vals[1] - se_vals[0] if len(se_vals) > 1 else 0.1
            progress(0.6, "Evaluating probability grid...")
            return cusp2.probability_of_passing(table, num, loc, d1, u_vals, sigse_vals, sigsm_vals)
        return job

    def _run_sample(self):
        v = self.sample_fields
        mean = v["mean"].get(float); se = v["se"].get(float); sm = v["sm"].get(float)
        num = v["num"].get(int); loc = v["loc"].get(int)
        target = v["target"].get(float); cilevel = v["cilevel"].get(float)

        def job(progress):
            progress(0.4, "Computing sample probability...")
            return cusp2.sample_probability(mean, se, sm, num, loc, target, cilevel)
        return job


class Disp1Tab(BaseTab):
    def __init__(self, parent=None):
        super().__init__("Dissolution -- Sampling Plan 1", "Single location (USP <711>).", parent)

    def _build_mode_frames(self):
        self.table_fields = build_form(self.mode_frames["table"].layout(), [
            ("number", "Number of units (N)", 6),
            ("q", "Q value (%)", 80.0),
            ("lbound", "Lower bound (%)", 95.0),
            ("cilevel", "Confidence level (%)", 95.0),
            ("meanadj_step", "Mean grid step", 1.0),
        ], registry=self.field_registry["table"])

        lay = self.mode_frames["evaluate"].layout()
        desc = QLabel("Builds the table above, then evaluates:")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        lay.addWidget(desc, 0, 0, 1, 2)
        self.eval_fields = build_form(lay, [
            ("u_low", "True mean U -- low", 90.0),
            ("u_high", "True mean U -- high", 100.0),
            ("u_step", "True mean U -- step", 2.5),
            ("cv_low", "True CV(%) -- low", 1.0),
            ("cv_high", "True CV(%) -- high", 4.0),
            ("cv_step", "True CV(%) -- step", 1.0),
        ], start_row=1, registry=self.field_registry["evaluate"])

        self.sample_fields = build_form(self.mode_frames["sample"].layout(), [
            ("mean", "Sample mean (%)", 90.0),
            ("cv", "Sample CV (%)", 3.0),
            ("number", "Number of units (N)", 6),
            ("q", "Q value (%)", 80.0),
            ("cilevel", "Confidence level (%)", 95.0),
        ], registry=self.field_registry["sample"])

    def _run_table(self):
        v = self.table_fields
        number = v["number"].get(int); q = v["q"].get(float)
        lbound = v["lbound"].get(float); cilevel = v["cilevel"].get(float)
        meanadj_step = v["meanadj_step"].get(float)
        key = self._cache_key(number, q, lbound, cilevel, meanadj_step)

        def job(progress):
            hit = self._table_cache.get(key)
            if hit is not None:
                progress(0.5, "Using cached table...")
                return hit
            progress(0.2, "Computing acceptance table...")
            table = disp1.acceptance_limit_table(number, q, lbound, cilevel, meanadj_step)
            self._table_cache[key] = table
            progress(1.0, "Table complete.")
            return table
        return job

    def _run_evaluate(self):
        v = self.table_fields
        number = v["number"].get(int); q = v["q"].get(float)
        lbound = v["lbound"].get(float); cilevel = v["cilevel"].get(float)
        u_vals = make_grid(self.eval_fields["u_low"].get(float), self.eval_fields["u_high"].get(float),
                           self.eval_fields["u_step"].get(float), "U")
        cv_vals = make_grid(self.eval_fields["cv_low"].get(float), self.eval_fields["cv_high"].get(float),
                            self.eval_fields["cv_step"].get(float), "CV")
        key = self._cache_key(number, q, lbound, cilevel)

        def job(progress):
            table = self._table_cache.get(key)
            if table is None:
                progress(0.2, "Building acceptance table...")
                table = disp1.acceptance_limit_table(number, q, lbound, cilevel)
                self._table_cache[key] = table
            else:
                progress(0.2, "Using cached table...")
            progress(0.6, "Evaluating probability grid...")
            return disp1.probability_of_passing(table, number, u_vals, cv_vals)
        return job

    def _run_sample(self):
        v = self.sample_fields
        mean = v["mean"].get(float); cv = v["cv"].get(float)
        number = v["number"].get(int); q = v["q"].get(float)
        cilevel = v["cilevel"].get(float)

        def job(progress):
            progress(0.4, "Computing sample probability...")
            return disp1.sample_probability(mean, cv, number, q, cilevel)
        return job


class Disp2Tab(BaseTab):
    def __init__(self, parent=None):
        super().__init__("Dissolution -- Sampling Plan 2",
                         "Multiple locations, within/between-location variance components (USP <711>).",
                         parent)

    def _build_mode_frames(self):
        self.table_fields = build_form(self.mode_frames["table"].layout(), [
            ("num", "Units per location", 6),
            ("loc", "Number of locations", 5),
            ("q", "Q value (%)", 80.0),
            ("lbound", "Lower bound (%)", 95.0),
            ("cilevel", "Confidence level (%)", 95.0),
            ("se_low", "Within-loc SD -- low", 1.0),
            ("se_high", "Within-loc SD -- high", 5.0),
            ("se_step", "Within-loc SD -- step", 1.0),
            ("sm_low", "Between-loc SD -- low", 1.0),
            ("sm_high", "Between-loc SD -- high", 5.0),
            ("sm_step", "Between-loc SD -- step", 1.0),
        ], registry=self.field_registry["table"])

        lay = self.mode_frames["evaluate"].layout()
        desc = QLabel("Builds the table above, then evaluates:")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        lay.addWidget(desc, 0, 0, 1, 2)
        self.eval_fields = build_form(lay, [
            ("u_low", "True mean U -- low", 90.0),
            ("u_high", "True mean U -- high", 100.0),
            ("u_step", "True mean U -- step", 2.5),
            ("sigse_low", "True within-loc SD -- low", 1.0),
            ("sigse_high", "True within-loc SD -- high", 3.0),
            ("sigse_step", "True within-loc SD -- step", 1.0),
            ("sigsm_low", "True between-loc SD -- low", 1.0),
            ("sigsm_high", "True between-loc SD -- high", 3.0),
            ("sigsm_step", "True between-loc SD -- step", 1.0),
        ], start_row=1, registry=self.field_registry["evaluate"])

        self.sample_fields = build_form(self.mode_frames["sample"].layout(), [
            ("mean", "Sample mean (%)", 90.0),
            ("se", "Sample within-loc SD", 2.2),
            ("sm", "Sample between-loc SD", 2.46),
            ("num", "Units per location", 6),
            ("loc", "Number of locations", 5),
            ("q", "Q value (%)", 80.0),
            ("cilevel", "Confidence level (%)", 95.0),
        ], registry=self.field_registry["sample"])

    def _table_args(self):
        v = self.table_fields
        num = v["num"].get(int); loc = v["loc"].get(int)
        q = v["q"].get(float); lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        se_vals = make_grid(v["se_low"].get(float), v["se_high"].get(float), v["se_step"].get(float), "SE")
        sm_vals = make_grid(v["sm_low"].get(float), v["sm_high"].get(float), v["sm_step"].get(float), "SM")
        return num, loc, q, lbound, cilevel, se_vals, sm_vals

    def _run_table(self):
        num, loc, q, lbound, cilevel, se_vals, sm_vals = self._table_args()
        key = self._cache_key(num, loc, q, lbound, cilevel, se_vals, sm_vals)

        def job(progress):
            hit = self._table_cache.get(key)
            if hit is not None:
                progress(0.5, "Using cached table...")
                return hit
            progress(0.2, "Computing acceptance table (Plan 2)...")
            table = disp2.acceptance_limit_table(num, loc, q, lbound, cilevel, se_vals, sm_vals)
            self._table_cache[key] = table
            progress(1.0, "Table complete.")
            return table
        return job

    def _run_evaluate(self):
        num, loc, q, lbound, cilevel, se_vals, sm_vals = self._table_args()
        dse = se_vals[1] - se_vals[0] if len(se_vals) > 1 else 1.0
        dsm = sm_vals[1] - sm_vals[0] if len(sm_vals) > 1 else 1.0
        u_vals = make_grid(self.eval_fields["u_low"].get(float), self.eval_fields["u_high"].get(float),
                           self.eval_fields["u_step"].get(float), "U")
        sigse_vals = make_grid(self.eval_fields["sigse_low"].get(float), self.eval_fields["sigse_high"].get(float),
                               self.eval_fields["sigse_step"].get(float), "within-loc SD")
        sigsm_vals = make_grid(self.eval_fields["sigsm_low"].get(float), self.eval_fields["sigsm_high"].get(float),
                               self.eval_fields["sigsm_step"].get(float), "between-loc SD")
        key = self._cache_key(num, loc, q, lbound, cilevel, se_vals, sm_vals)

        def job(progress):
            table = self._table_cache.get(key)
            if table is None:
                progress(0.2, "Building acceptance table (Plan 2)...")
                table = disp2.acceptance_limit_table(num, loc, q, lbound, cilevel, se_vals, sm_vals)
                self._table_cache[key] = table
            else:
                progress(0.2, "Using cached table...")
            progress(0.6, "Evaluating probability grid...")
            return disp2.probability_of_passing(table, num, loc, dse, dsm, u_vals, sigse_vals, sigsm_vals)
        return job

    def _run_sample(self):
        v = self.sample_fields
        mean = v["mean"].get(float); se = v["se"].get(float); sm = v["sm"].get(float)
        num = v["num"].get(int); loc = v["loc"].get(int)
        q = v["q"].get(float); cilevel = v["cilevel"].get(float)

        def job(progress):
            progress(0.4, "Computing sample probability...")
            return disp2.sample_probability(mean, se, sm, num, loc, q, cilevel)
        return job


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class CudalApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyCuDAL -- Content Uniformity & Dissolution Acceptance Limits")
        self.resize(1180, 720)
        self.setMinimumSize(980, 600)

        self._settings = self._load_settings()

        # ---- logo -------------------------------------------------------------
        logo_file = resource_path("logo.png")
        if os.path.exists(logo_file):
            self.setWindowIcon(QIcon(logo_file))

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        header = QHBoxLayout()
        if os.path.exists(logo_file):
            pix = QPixmap(logo_file)
            if not pix.isNull():
                logo_lbl = QLabel()
                logo_lbl.setPixmap(pix.scaledToHeight(
                    40, Qt.TransformationMode.SmoothTransformation))
                header.addWidget(logo_lbl)
        else:
            t = QLabel("CuDAL")
            t.setObjectName("header")
        s = QLabel("   Parametric acceptance limits for USP <905> Content Uniformity "
                   "and USP <711> Dissolution")
        s.setObjectName("subheader")
        if not logo_file:
            header.addWidget(t)
        header.addWidget(s)
        header.addStretch(1)
        outer.addLayout(header)

        # ---- tabs ---------------------------------------------------------------
        self.notebook = QTabWidget()
        self.tabs = [Cusp1Tab(), Cusp2Tab(), Disp1Tab(), Disp2Tab()]
        for tab, text in zip(self.tabs,
                             ["Content Uniformity -- Plan 1", "Content Uniformity -- Plan 2",
                              "Dissolution -- Plan 1", "Dissolution -- Plan 2"]):
            self.notebook.addTab(tab, text)
        outer.addWidget(self.notebook, 1)

        # ---- menu ---------------------------------------------------------------
        menubar = self.menuBar()
        filem = menubar.addMenu("&File")
        a = QAction("Export current results (CSV)", self)
        a.setShortcut(QKeySequence("Ctrl+E"))
        a.triggered.connect(self._export_current_csv)
        filem.addAction(a)
        a = QAction("Export all results (XLSX)", self)
        a.triggered.connect(self._export_all_xlsx)
        filem.addAction(a)
        filem.addSeparator()
        a = QAction("Exit", self)
        a.triggered.connect(self.close)
        filem.addAction(a)
        helpm = menubar.addMenu("&Help")
        a = QAction("About / Help", self)
        a.setShortcut(QKeySequence("F1"))
        a.triggered.connect(self._show_about)
        helpm.addAction(a)

        # ---- shortcuts ------------------------------------------------------------
        QShortcut(QKeySequence("Ctrl+R"), self, activated=lambda: self._current_tab()._on_run())
        QShortcut(QKeySequence("Ctrl+P"), self,
                  activated=lambda: self._current_tab().results._show_plot())

        # ---- restore persisted state --------------------------------------------
        for tab in self.tabs:
            tab.apply_state(self._settings.get("tabs", {}).get(tab.__class__.__name__))
        try:
            idx = int(self._settings.get("tab_index", 0))
            self.notebook.setCurrentIndex(max(0, min(idx, 3)))
        except Exception:
            pass
        g = self._settings.get("geometry")
        if isinstance(g, (list, tuple)) and len(g) == 4:
            self.setGeometry(int(g[0]), int(g[1]), int(g[2]), int(g[3]))

        self.statusBar().showMessage("Ready.")

    # -- helpers ---------------------------------------------------------------------
    def _current_tab(self):
        return self.notebook.currentWidget()

    @staticmethod
    def _load_settings():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _save_settings(self):
        data = {
            "geometry": [self.x(), self.y(), self.width(), self.height()],
            "tab_index": self.notebook.currentIndex(),
            "tabs": {tab.__class__.__name__: tab.collect_state() for tab in self.tabs},
        }
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception:
            pass

    def closeEvent(self, event):
        self._save_settings()
        event.accept()

    # -- actions -----------------------------------------------------------------------
    def _export_current_csv(self):
        self._current_tab().results._export_csv()

    def _export_all_xlsx(self):
        if not HAVE_XLSX:
            QMessageBox.critical(self, "Excel export unavailable",
                                 "openpyxl is required.\nInstall it with:  pip install openpyxl")
            return
        sheets = {tab.__class__.__name__: tab.results._df
                  for tab in self.tabs if tab.results._df is not None}
        if not sheets:
            QMessageBox.information(self, "Nothing to export", "Run at least one analysis first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export all results", "cudal_results.xlsx",
                                              "Excel workbook (*.xlsx)")
        if not path:
            return
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for name, df in sheets.items():
                df.to_excel(writer, sheet_name=name[:31], index=False)
        QMessageBox.information(self, "Exported", f"Saved {len(sheets)} sheet(s) to {path}")

    def _show_about(self):
        deps = (f"matplotlib: {'yes' if HAVE_MPL else 'no'}\n"
                f"scipy splines: {'yes' if HAVE_SPLINE else 'no'}\n"
                f"openpyxl (xlsx): {'yes' if HAVE_XLSX else 'no'}")
        QMessageBox.about(
            self, "About CuDAL",
            f"CuDAL GUI {VERSION}\n\n"
            "Parametric acceptance limits for USP <905> Content Uniformity\n"
            "and USP <711> Dissolution (mirrors SAS CALCUSPx/CALDISPx,\n"
            "EVCUSPx/EVDISPx, SMPCUSPx/SMPDISPx).\n\n"
            "Shortcuts:\n"
            "  Ctrl+R  run analysis\n"
            "  Ctrl+E  export current results (CSV)\n"
            "  Ctrl+P  plot results\n"
            "  Ctrl+C  copy selected table rows\n"
            "  F1      this dialog\n\n"
            f"Optional dependencies:\n{deps}")


# ---------------------------------------------------------------------------
# Self-test & entry point
# ---------------------------------------------------------------------------
def run_selftest():
    assert make_grid(1.0, 2.0, 0.5) == [1.0, 1.5, 2.0]
    try:
        make_grid(2.0, 1.0, 1.0, "x")
        raise AssertionError("make_grid should reject high < low")
    except ValueError:
        pass
    assert fmt_num(1234.56789) == "1,234.5679"
    assert fmt_num("abc") == "abc"
    xx, yy = _spline_xy([1, 2, 3, 4], [1, 4, 9, 16])
    assert len(xx) == len(yy) == 300
    print("selftest OK")


def main():
    if "--selftest" in sys.argv:
        run_selftest()
        return

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    if not HAVE_CUDAL:
        QMessageBox.critical(
            None, "Missing dependency",
            "The `cudal` package could not be imported.\n"
            "Put this script next to the `cudal` package folder\n"
            "or install it, then restart the GUI.")
        sys.exit(1)

    # bundled fonts (Windows AND Linux via Qt font database)
    family = _register_local_fonts()
    if not family:
        family = "Segoe UI" if sys.platform.startswith("win") else "DejaVu Sans"
    app.setFont(QFont(family, 10))
    app.setStyleSheet(build_stylesheet(family))

    # let matplotlib use the bundled font too
    if HAVE_MPL:
        try:
            fdir = resource_path("fonts")
            if os.path.isdir(fdir):
                from matplotlib import font_manager as fm
                import matplotlib as mpl
                for f in os.listdir(fdir):
                    if f.lower().endswith((".ttf", ".otf")):
                        fm.fontManager.addfont(os.path.join(fdir, f))
                mpl.rcParams["font.family"] = family
        except Exception:
            pass

    win = CudalApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()