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
import time
import traceback

from PySide6.QtCore import QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.pdfgen import canvas as rl_canvas

    HAVE_PDF = True
except Exception:  # pragma: no cover
    HAVE_PDF = False

# Heavy / optional dependencies load in stages after the splash appears.
np = pd = None
cusp1 = cusp2 = disp1 = disp2 = None
Figure = FigureCanvas = NavigationToolbar = None
make_interp_spline = None
HAVE_CUDAL = HAVE_MPL = HAVE_SPLINE = HAVE_XLSX = False

REPO_URL = "https://github.com/moazelessawey/pycudal"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VERSION = "1.0.8 (PySide6, modern UI)"

BG = "#f4f6f9"
PANEL_BG = "#ffffff"
ACCENT = "#2f6fed"
ACCENT_DARK = "#204ea6"
TEXT = "#1c2733"
MUTED = "#64748b"
BORDER = "#e2e8f0"
OK_GREEN = "#1a8754"
ERR_RED = "#c0392b"

SERIES_COLORS = [ACCENT, OK_GREEN, ERR_RED, "#8e44ad", "#e67e22", "#16a085", "#c2417d", "#5b6470"]

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cudal_gui_settings.json")

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
        draw_title()  # title on every page
        if st["table_header_fn"] is not None:  # table header on every page
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

    draw_title()  # first-page title

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

        HDR_LINES = 5  # banner + blank + SM row + LL/UL row + blank

        for start in range(0, len(sms), per_page):  # column wrapping
            seg = sms[start : start + per_page]
            st["table_header_fn"] = None  # don't repeat old header
            need(HDR_LINES + 1)
            header(seg)
            st["table_header_fn"] = lambda seg=seg: header(seg)
            for se in ses:
                line = f"{_fmt_num(se):>{se_w}}"
                for sm in seg:
                    ll, ul = get.get((se, sm), ("*", "*"))
                    line += (" " * gap) + f"{ll:>{ll_w}} {ul:>{ul_w}}"
                put(line)  # auto page-break repeats
            blank()  # title + segment header
        st["table_header_fn"] = None
        c.save()
        return

    # ------------ Plan-1 style: long rows wrapped into side-by-side blocks --
    body = [[_cell(v) for v in row] for _, row in df.iterrows()]
    widths = [
        max(len(cols[j]), max((len(r[j]) for r in body), default=0)) for j in range(len(cols))
    ]

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
    rpb = max(1, -(-len(body) // n_blocks))  # rows per block
    chunks = [body[i : i + rpb] for i in range(0, len(body), rpb)]

    def header_line(li):
        return (" " * gap).join(f"{hdr[j][li]:^{widths[j]}}" for j in range(len(cols)))

    def block_line(chunk, i):
        parts = []
        for j in range(len(cols)):
            val = chunk[i][j] if i < len(chunk) else ""
            parts.append(f"{val:>{widths[j]}}")
        return (" " * gap).join(parts)

    for p in range(0, len(chunks), n_blocks):
        page_chunks = chunks[p : p + n_blocks]

        def draw_hdr(_pc=page_chunks):
            for li in range(hdr_lines):
                put((" " * block_gap).join(header_line(li) for _ in _pc))
            blank()

        st["table_header_fn"] = None  # don't repeat old header
        need(hdr_lines + 2)
        draw_hdr()
        st["table_header_fn"] = draw_hdr  # repeat on page breaks
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
    QToolBar {{ background: #eef1f6; border: 0; border-bottom: 1px solid #cfd8e3;
               spacing: 4px; padding: 4px; }}
    QToolBar QToolButton {{ background: transparent; border: 1px solid transparent;
                           border-radius: 4px; padding: 4px 8px; color: #2f3a4d; }}
    QToolBar QToolButton:hover {{ background: #dfe8f7; border-color: #aeb9c8; }}
    QToolBar QToolButton:pressed {{ background: #cfdffc; }}
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
    axes = sorted(
        (c for c in num.columns if c != zcol), key=lambda c: num[c].nunique(), reverse=True
    )

    # sanity check: the surface must vary more than either axis
    if num[zcol].nunique() <= max(num[axes[0]].nunique(), num[axes[1]].nunique()):
        return None

    return str(axes[0]), str(axes[1]), str(zcol)


def _is_plan2_table(df):
    """Detect a Plan 2 acceptance limit table (SE, SM, and >=2 value columns)."""
    cols = [str(c).lower() for c in df.columns]
    return "se" in cols and "sm" in cols and len(df.columns) >= 4


def _get_plan2_axes_and_z(df):
    """Return (x_col, y_col, [z_cols]) for Plan 2 tables."""
    cols = [str(c) for c in df.columns]
    lower_cols = [c.lower() for c in cols]
    x_col = cols[lower_cols.index("se")] if "se" in lower_cols else cols[0]
    y_col = cols[lower_cols.index("sm")] if "sm" in lower_cols else cols[1]
    z_cols = [
        c
        for c, lc in zip(cols, lower_cols)
        if lc not in ("se", "sm") and pd.api.types.is_numeric_dtype(df[c])
    ]
    return x_col, y_col, z_cols


def _plan2_eval_columns(df):
    """Detect a Plan-2 probability-of-passing grid (U x within-SD x between-SD -> P).

    Returns (u_col, se_col, sm_col, p_col) or None.
    """
    num = df.select_dtypes(include=[np.number])
    if num.shape[1] != 4:
        return None
    cols = [str(c) for c in num.columns]
    low = [c.lower() for c in cols]

    def find(*keys):
        for k in keys:
            for c, lc in zip(cols, low):
                if k in lc:
                    return c
        return None

    p_col = find("prob", "pass", "psum")
    se_col = find("within", "sigse") or next((c for c, lc in zip(cols, low) if lc == "se"), None)
    sm_col = find("between", "sigsm") or next((c for c, lc in zip(cols, low) if lc == "sm"), None)
    if None in (p_col, se_col, sm_col):
        return None
    rest = [c for c in cols if c not in (p_col, se_col, sm_col)]
    if len(rest) != 1:
        return None
    return rest[0], se_col, sm_col, p_col


def build_plan2_eval_plot(fig, df, u_col, se_col, sm_col, p_col):
    """Faceted view of the Plan-2 probability-of-passing surface.

    One panel per between-location SD (SM); inside each panel one spline
    curve per within-location SD (SE):  P(pass) vs true mean U.
    Dashed lines mark the usual 80 % / 90 % coverage levels.
    """
    work = pd.DataFrame(
        {
            "u": pd.to_numeric(df[u_col], errors="coerce"),
            "se": pd.to_numeric(df[se_col], errors="coerce"),
            "sm": pd.to_numeric(df[sm_col], errors="coerce"),
            "p": pd.to_numeric(df[p_col], errors="coerce"),
        }
    ).dropna()

    if work.empty:
        fig.text(0.5, 0.5, "Not enough numeric data to plot.", ha="center", va="center")
        fig.tight_layout()
        return

    sm_vals = sorted(work["sm"].unique())
    se_vals = sorted(work["se"].unique())
    n = len(sm_vals)
    ncols = min(3, n)
    nrows = -(-n // ncols)  # ceil without importing math
    axes = fig.subplots(nrows, ncols, squeeze=False, sharex=True, sharey=True)

    for i, smv in enumerate(sm_vals):
        ax = axes[i // ncols][i % ncols]
        panel = work[work["sm"] == smv]
        for color, sev in zip(SERIES_COLORS, se_vals):
            sub = panel[panel["se"] == sev].sort_values("u")
            xs = sub["u"].to_numpy(dtype=float)
            ys = sub["p"].to_numpy(dtype=float)
            if xs.size == 0:
                continue
            ax.plot(xs, ys, "o", color=color, ms=3, alpha=0.7)
            xx, yy = _spline_xy(xs, ys)
            ax.plot(xx, yy, "-", color=color, lw=1.6, label=f"{se_col} = {sev:g}")
        for t in (0.8, 0.9):
            ax.axhline(t, ls="--", lw=0.8, color="0.5")
        ax.set_title(f"{sm_col} = {smv:g}", fontsize=9)
        ax.grid(True, alpha=0.3)
        if i // ncols == nrows - 1:
            ax.set_xlabel(u_col, fontsize=9)
        if i % ncols == 0:
            ax.set_ylabel(p_col, fontsize=9)

    for j in range(n, nrows * ncols):  # hide unused panels
        axes[j // ncols][j % ncols].set_axis_off()

    handles, labels = axes[0][0].get_legend_handles_labels()
    if handles:
        fig.legend(
            handles, labels, loc="lower center", ncol=min(len(labels), 4), fontsize=8, frameon=False
        )
    fig.suptitle(
        f"Probability of passing vs {u_col}  (panels: {sm_col}, curves: {se_col})", fontsize=10
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))


def build_results_plot_plan2(fig, df):
    """Family of curves for Plan 2 tables: LL/UL vs SE, grouped by SM."""
    x_col, y_col, z_cols = _get_plan2_axes_and_z(df)
    if not z_cols:
        fig.text(0.5, 0.5, "Not enough data to plot.", ha="center", va="center")
        return

    n_z = len(z_cols)
    axes = fig.subplots(1, n_z, squeeze=False)

    for idx, z_col in enumerate(z_cols):
        ax = axes[0, idx]
        grouped = df.groupby(y_col, sort=True)
        for color, (sm_val, sub) in zip(SERIES_COLORS, grouped):
            xs = sub[x_col].to_numpy(dtype=float)
            ys = sub[z_col].to_numpy(dtype=float)
            order = np.argsort(xs)
            xs, ys = xs[order], ys[order]

            xx, yy = _spline_xy(xs, ys)
            ax.plot(xx, yy, "-", color=color, lw=1.6, label=f"{y_col}={sm_val:g}")
            ax.plot(xs, ys, "o", color=color, ms=3, alpha=0.7)

        ax.set_xlabel(x_col)
        ax.set_ylabel(z_col)
        ax.set_title(f"{z_col} vs {x_col}")
        ncol = 2 if len(grouped) > 6 else 1
        ax.legend(fontsize=7, loc="best", ncol=ncol)
        ax.grid(True, alpha=0.3)

    fig.tight_layout()


def build_heatmap_plan2(fig, df, z_col, thresholds=(0.8, 0.9)):
    """Contour-filled heatmap for Plan 2 tables (SE x SM -> Z)."""
    x_col, y_col, z_cols = _get_plan2_axes_and_z(df)
    if not z_cols:
        fig.text(0.5, 0.5, "Not enough data to plot.", ha="center", va="center")
        return
    if z_col not in z_cols:
        z_col = z_cols[0]

    work = df[[x_col, y_col, z_col]].copy()
    work = work.apply(pd.to_numeric, errors="coerce").dropna()
    piv = work.pivot_table(index=y_col, columns=x_col, values=z_col, aggfunc="mean")
    piv = piv.sort_index(axis=0).sort_index(axis=1)

    X = piv.columns.to_numpy(dtype=float)
    Y = piv.index.to_numpy(dtype=float)
    Z = np.ma.masked_invalid(piv.to_numpy(dtype=float))

    ax = fig.add_subplot(111)
    if Z.count() == 0 or X.size < 2 or Y.size < 2:
        ax.text(0.5, 0.5, "Not enough grid points for a heatmap.", ha="center", va="center")
        fig.tight_layout()
        return

    cs = ax.contourf(X, Y, Z, levels=min(24, max(6, X.size + Y.size)), cmap="viridis")
    fig.colorbar(cs, ax=ax, label=z_col)

    if X.size <= 15:
        ax.set_xticks(X)
    if Y.size <= 15:
        ax.set_yticks(Y)

    if float(Z.max()) <= 1.01 and float(Z.min()) >= -0.01:
        for i, t in enumerate(thresholds):
            if float(Z.min()) <= t <= float(Z.max()):
                ax.contour(X, Y, Z, levels=[t], colors="white", linewidths=1.2)
                ax.text(
                    0.02,
                    0.98 - 0.06 * i,
                    f"white line = {t:.0%}",
                    transform=ax.transAxes,
                    fontsize=8,
                    color="white",
                    va="top",
                )

    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)
    ax.set_title(f"{z_col} over {x_col} / {y_col}", fontsize=10)
    fig.tight_layout()


def build_results_plot(fig, df):
    """Points + spline curves for the results DataFrame."""
    p2 = _plan2_eval_columns(df)
    if p2 is not None:
        build_plan2_eval_plot(fig, df, *p2)
        return

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
    Z = np.ma.masked_invalid(piv.to_numpy(dtype=float))  # holes -> masked, not artifacts

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
                ax.text(
                    0.02,
                    0.98 - 0.06 * i,
                    f"white line = {t:.0%}",
                    transform=ax.transAxes,
                    fontsize=8,
                    color="white",
                    va="top",
                )

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
    def __init__(self, df, parent=None, save_base=None):
        super().__init__(parent)
        self.setWindowTitle("Results plot")
        self.resize(880, 640)
        self.setMinimumSize(520, 380)
        self.setModal(True)
        self._df = df
        self._save_base = save_base or "results"

        self._is_plan2 = _is_plan2_table(df)
        self._can_heat = self._is_plan2 or _grid_columns(df) is not None

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Plot style:"))

        self.style_cb = QComboBox()
        self.style_cb.addItems(["Lines + spline"] + (["Heatmap (grid)"] if self._can_heat else []))
        top.addWidget(self.style_cb)

        # Z-axis selector for Plan 2 tables
        self.z_cb = None
        if self._is_plan2:
            _, _, z_cols = _get_plan2_axes_and_z(df)
            if len(z_cols) > 1:
                top.addWidget(QLabel("Z-axis:"))
                self.z_cb = QComboBox()
                self.z_cb.addItems([str(c) for c in z_cols])
                top.addWidget(self.z_cb)
                self.z_cb.currentIndexChanged.connect(self._redraw)

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
        style = self.style_cb.currentText()
        if self._is_plan2:
            if style == "Heatmap (grid)" and self._can_heat:
                z_col = self.z_cb.currentText() if self.z_cb else None
                build_heatmap_plan2(self._fig, self._df, z_col)
            else:
                build_results_plot_plan2(self._fig, self._df)
        else:
            if style == "Heatmap (grid)" and self._can_heat:
                build_heatmap(self._fig, self._df)
            else:
                build_results_plot(self._fig, self._df)
        self._canvas.draw()

    def _save_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save figure", self._save_base + ".png", "PNG image (*.png)"
        )
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
        self.plot_btn.setEnabled(False)

        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setEnabled(False)

        self.pdf_btn = QPushButton("Export PDF")
        self.pdf_btn.setEnabled(False)

        self.oc_btn = QPushButton("OC Curve")
        # self.oc_btn.setObjectName("outline")
        self.oc_btn.setEnabled(False)
        self.oc_btn.setToolTip("OC curve: computed plan vs USP <905> (CU tabs)")

        toolbar.addWidget(title)
        toolbar.addStretch(1)
        toolbar.addWidget(self.row_count)
        toolbar.addWidget(self.plot_btn)
        toolbar.addWidget(self.oc_btn)
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
            lines.append(
                "\t".join(
                    self.table.item(r, c).text() if self.table.item(r, c) else ""
                    for c in range(self.table.columnCount())
                )
            )
        QApplication.clipboard().setText("\n".join(lines))

    def _show_plot(self):
        if not HAVE_MPL:
            QMessageBox.critical(
                self,
                "Plot unavailable",
                "matplotlib is required for plotting.\nInstall it with:  pip install matplotlib",
            )
            return
        if self._df is None:
            return
        PlotDialog(self._df, self, save_base=self._default_name(suffix="-plot")).exec()

    def _export_csv(self):
        if self._df is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", self._default_name(ext=".csv"), "CSV files (*.csv)"
        )
        if not path:
            return
        self._df.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
        QMessageBox.information(self, "Exported", f"Saved to {path}")

    def _export_pdf(self):
        if not HAVE_PDF:
            QMessageBox.critical(
                self,
                "PDF export unavailable",
                "reportlab is required.\nInstall it with:  pip install reportlab",
            )
            return
        if self._df is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PDF", self._default_name(ext=".pdf"), "PDF files (*.pdf)"
        )
        if not path:
            return
        meta = self.report_meta or {"title": ["CuDAL RESULTS"]}
        try:
            write_sas_pdf(path, self._df, meta["title"])
            QMessageBox.information(self, "Exported", f"Saved to {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "PDF export failed", str(exc))

    def _default_name(self, suffix="", ext=""):
        tab = getattr(self, "tab", None)
        try:
            base = tab._export_base_name() if tab is not None else "results"
        except Exception:
            base = "results"

        return base + suffix + ext


# ---------------------------------------------------------------------------
# Base tab
# ---------------------------------------------------------------------------
class BaseTab(QWidget):
    MODES = [
        ("table", "Acceptance limit table"),
        ("evaluate", "Probability of passing"),
        ("sample", "Sample probability"),
    ]

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
            g.setContentsMargins(14, 20, 14, 14)  # strict, uniform card padding
            g.setHorizontalSpacing(12)
            g.setVerticalSpacing(8)
            g.setColumnStretch(0, 1)  # labels fill col 0...
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
        # self.results.tab = self
        self.results.tab = self
        body.addWidget(self.results, 1)
        self.results.oc_btn.clicked.connect(self._show_oc)

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
            "fields": {
                mode: {k: f.edit.text() for k, f in reg.items()}
                for mode, reg in self.field_registry.items()
            },
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
            job = {
                "table": self._run_table,
                "evaluate": self._run_evaluate,
                "sample": self._run_sample,
            }[self._current_mode()]()
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

        # in _on_done, after showing the results:
        self.results.oc_btn.setEnabled(self._oc_available())

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
            lines.append(
                f"(MEETING LIMITS GUARANTEES, WITH {cilevel:.1f}% ASSURANCE, THAT AT LEAST"
            )
            lines.append(f"{lbound:.1f}% OF SAMPLES TESTED FOR {dom} WILL PASS THE USP TEST)")
        else:
            lines.append(f"ACCEPTANCE LIMITS FOR {dom}")
            lines.append("SAMPLING PLAN 2")
            base = f"TARGET={target:.1f}" if target is not None else f"Q={q:.1f}"
            lines.append(f"{base}, LOWER BOUND = {lbound:.1f}, CONFIDENCE LEVEL = {cilevel:.1f}")
            lines.append("TABLE ENTRIES ARE LOWER(LL) AND UPPER(UL) LIMITS ON THE MEAN")
            if n is not None and loc is not None:
                lines.append(
                    f"OF {int(n * loc)} ASSAYS:  {int(n)} ASSAYS AT EACH OF "
                    f"{int(loc)} DIFFERENT LOCATIONS"
                )
            lines.append("SE IS THE POOLED WITHIN LOCATION STANDARD DEVIATION")
            lines.append("STANDARD DEVIATIONS AND MEANS ARE EXPRESSED IN % CLAIM")
        if self._current_mode() != "table":
            lines.append(f"MODE: {dict(self.MODES)[self._current_mode()].upper()}")
        return {"title": lines}

    def _export_base_name(self):
        name = type(self).__name__
        dom = "DISSOLUTION" if name.startswith("Disp") else "CONTENT UNIFORMITY"
        plan = 2 if name.endswith("2Tab") else 1
        method = ("CUSP" if "CONTENT" in dom else "DISP") + str(plan)
        v = getattr(self, "table_fields", {})

        def g(key):
            try:
                return float(v[key].get(float))
            except Exception:
                return None

        toks = [method]
        q = g("q")
        if q is not None:
            toks.append(f"Q{q:g}")
        lb, ci = g("lbound"), g("cilevel")
        if lb is not None and ci is not None:
            toks.append(f"{lb:g}x{ci:g}")
        if plan == 1:
            n = g("number")
            if n is not None:
                toks.append(f"{n:g}N")
        else:
            loc, num = g("loc"), g("num")
            if loc is not None and num is not None:
                toks.append(f"{loc:g}Lx{num:g}N")
        base = "-".join(toks)
        mode = self._current_mode()
        if mode == "evaluate":
            base += "-EVAL"
        elif mode == "sample":
            base += "-SAMPLE"
        return base

    # new methods:
    def _oc_available(self):
        return False

    def _oc_context(self):
        return None

    def _show_oc(self):
        if not HAVE_MPL:
            QMessageBox.critical(
                self, "Plot unavailable", "matplotlib is required.\npip install matplotlib"
            )
            return
        ctx = self._oc_context()
        if ctx is None:
            QMessageBox.information(self, "OC curve", "Not available for this scenario.")
            return
        OCDialog(ctx, self, save_base=self._export_base_name() + "-OC").exec()


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
        super().__init__(
            "Content Uniformity -- Sampling Plan 1", "Single composite sample (USP <905>).", parent
        )
        self._last_table = None

    def _build_mode_frames(self):
        self.table_fields = build_form(
            self.mode_frames["table"].layout(),
            [
                ("number", "Number of units (N)", 10),
                ("target", "Target / label claim (%)", 100.0),
                ("lbound", "Lower bound (%)", 95.0),
                ("cilevel", "Confidence level (%)", 95.0),
                ("mean_low", "Mean grid low", 85.1),
                ("mean_high", "Mean grid high", 114.9),
                ("mean_step", "Mean grid step", 0.5),
            ],
            registry=self.field_registry["table"],
        )

        lay = self.mode_frames["evaluate"].layout()
        desc = QLabel("Builds the table above, then evaluates:")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        lay.addWidget(desc, 0, 0, 1, 2)
        self.eval_fields = build_form(
            lay,
            [
                ("u_low", "True mean U -- low", 95.0),
                ("u_high", "True mean U -- high", 105.0),
                ("u_step", "True mean U -- step", 2.5),
                ("cv_low", "True CV(%) -- low", 1.0),
                ("cv_high", "True CV(%) -- high", 4.0),
                ("cv_step", "True CV(%) -- step", 1.0),
            ],
            start_row=1,
            registry=self.field_registry["evaluate"],
        )
        for k in ("number", "target", "lbound", "cilevel"):
            self.eval_fields[k] = self.table_fields[k]

        self.sample_fields = build_form(
            self.mode_frames["sample"].layout(),
            [
                ("mean", "Sample mean (%)", 100.0),
                ("cv", "Sample CV (%)", 2.0),
                ("number", "Number of units (N)", 10),
                ("target", "Target / label claim (%)", 100.0),
                ("lbound", "Lower bound (%)", 95.0),
                ("cilevel", "Confidence level (%)", 95.0),
            ],
            registry=self.field_registry["sample"],
        )

    def _run_table(self):
        v = self.table_fields
        number = v["number"].get(int)
        target = v["target"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        mean_low = v["mean_low"].get(float)
        mean_high = v["mean_high"].get(float)
        mean_step = v["mean_step"].get(float)
        key = self._cache_key(number, target, lbound, cilevel, mean_low, mean_high, mean_step)

        def job(progress):
            hit = self._table_cache.get(key)
            if hit is not None:
                progress(0.5, "Using cached table...")
                return hit
            progress(0.2, "Computing acceptance table...")
            table = cusp1.acceptance_limit_table(
                number, target, lbound, cilevel, mean_low, mean_high, mean_step
            )
            self._table_cache[key] = table
            self._last_table = table
            progress(1.0, "Table complete.")
            return table

        return job

    def _run_evaluate(self):
        v = self.table_fields
        number = v["number"].get(int)
        target = v["target"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        u_vals = make_grid(
            self.eval_fields["u_low"].get(float),
            self.eval_fields["u_high"].get(float),
            self.eval_fields["u_step"].get(float),
            "U",
        )
        cv_vals = make_grid(
            self.eval_fields["cv_low"].get(float),
            self.eval_fields["cv_high"].get(float),
            self.eval_fields["cv_step"].get(float),
            "CV",
        )
        key = self._cache_key(number, target, lbound, cilevel)

        def job(progress):
            table = self._table_cache.get(key)
            if table is None:
                progress(0.2, "Building acceptance table...")
                table = cusp1.acceptance_limit_table(number, target, lbound, cilevel)
                self._table_cache[key] = table
                self._last_table = table
            else:
                progress(0.2, "Using cached table...")
            progress(0.6, "Evaluating probability grid...")
            return cusp1.probability_of_passing(table, number, u_vals, cv_vals)

        return job

    def _run_sample(self):
        v = self.sample_fields
        mean = v["mean"].get(float)
        cv = v["cv"].get(float)
        number = v["number"].get(int)
        target = v["target"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)

        def job(progress):
            progress(0.4, "Computing sample probability...")
            return cusp1.sample_probability(mean, cv, number, target, lbound, cilevel)

        return job

    def _oc_available(self):
        return True

    def _oc_context(self):
        v = self.table_fields
        number = v["number"].get(int)
        target = v["target"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        table = (
            self._last_table
            if self._last_table is not None
            else cusp1.acceptance_limit_table(number, target, lbound, cilevel)
        )

        def computed(xk, xs, fx):
            if xk == "cv":
                res = cusp1.probability_of_passing(table, number, [fx["U"]], [float(x) for x in xs])
            else:
                res = cusp1.probability_of_passing(
                    table, number, [float(x) for x in xs], [fx["CV"]]
                )
            return _prob_series(res)

        def make_units(xk, x, fx, rng, reps):
            U = x if xk == "u" else fx["U"]
            CV = x if xk == "cv" else fx["CV"]
            return rng.normal(U, U * CV / 100.0, (reps, 30))

        return make_oc_context(
            "cu",
            target,
            computed,
            make_units,
            [("cv", "True CV (%)  [U fixed]"), ("u", "True mean U (%)  [CV fixed]")],
            {"cv": (0.5, 10.0, 0.25), "u": (85.0, 115.0, 1.0)},
            {"cv": [("U", target)], "u": [("CV", 2.0)]},
        )


class Cusp2Tab(BaseTab):
    def __init__(self, parent=None):
        super().__init__(
            "Content Uniformity -- Sampling Plan 2",
            "Multiple locations, within/between-location variance components (USP <905>).",
            parent,
        )
        self._last_table = None

    def _build_mode_frames(self):
        self.table_fields = build_form(
            self.mode_frames["table"].layout(),
            [
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
            ],
            registry=self.field_registry["table"],
        )

        lay = self.mode_frames["evaluate"].layout()
        desc = QLabel("Builds the table above, then evaluates:")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        lay.addWidget(desc, 0, 0, 1, 2)
        self.eval_fields = build_form(
            lay,
            [
                ("u_low", "True mean U -- low", 95.0),
                ("u_high", "True mean U -- high", 105.0),
                ("u_step", "True mean U -- step", 2.5),
                ("sigse_low", "True within-loc SD -- low", 1.0),
                ("sigse_high", "True within-loc SD -- high", 3.0),
                ("sigse_step", "True within-loc SD -- step", 1.0),
                ("sigsm_low", "True between-loc SD -- low", 1.0),
                ("sigsm_high", "True between-loc SD -- high", 3.0),
                ("sigsm_step", "True between-loc SD -- step", 1.0),
            ],
            start_row=1,
            registry=self.field_registry["evaluate"],
        )

        self.sample_fields = build_form(
            self.mode_frames["sample"].layout(),
            [
                ("mean", "Sample mean (%)", 100.0),
                ("se", "Sample within-loc SD", 2.2),
                ("sm", "Sample between-loc SD", 2.46),
                ("num", "Units per location", 6),
                ("loc", "Number of locations", 10),
                ("target", "Target / label claim (%)", 100.0),
                ("cilevel", "Confidence level (%)", 95.0),
            ],
            registry=self.field_registry["sample"],
        )

    def _table_args(self):
        v = self.table_fields
        num = v["num"].get(int)
        loc = v["loc"].get(int)
        target = v["target"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        se_vals = make_grid(
            v["se_low"].get(float), v["se_high"].get(float), v["se_step"].get(float), "SE"
        )
        sm_vals = make_grid(
            v["sm_low"].get(float), v["sm_high"].get(float), v["sm_step"].get(float), "SM"
        )
        return num, loc, target, lbound, cilevel, se_vals, sm_vals

    def _run_table(self):
        num, loc, target, lbound, cilevel, se_vals, sm_vals = self._table_args()
        key = self._cache_key(num, loc, target, lbound, cilevel, se_vals, sm_vals)
        self._last_table = None

        def job(progress):
            hit = self._table_cache.get(key)
            if hit is not None:
                progress(0.5, "Using cached table...")
                return hit
            progress(0.2, "Computing acceptance table (Plan 2)...")
            table = cusp2.acceptance_limit_table(
                num, loc, target, lbound, cilevel, se_vals, sm_vals
            )
            self._table_cache[key] = table
            self._last_table = table
            progress(1.0, "Table complete.")
            return table

        return job

    def _run_evaluate(self):
        num, loc, target, lbound, cilevel, se_vals, sm_vals = self._table_args()
        u_vals = make_grid(
            self.eval_fields["u_low"].get(float),
            self.eval_fields["u_high"].get(float),
            self.eval_fields["u_step"].get(float),
            "U",
        )
        sigse_vals = make_grid(
            self.eval_fields["sigse_low"].get(float),
            self.eval_fields["sigse_high"].get(float),
            self.eval_fields["sigse_step"].get(float),
            "within-loc SD",
        )
        sigsm_vals = make_grid(
            self.eval_fields["sigsm_low"].get(float),
            self.eval_fields["sigsm_high"].get(float),
            self.eval_fields["sigsm_step"].get(float),
            "between-loc SD",
        )
        key = self._cache_key(num, loc, target, lbound, cilevel, se_vals, sm_vals)

        def job(progress):
            table = self._table_cache.get(key)
            if table is None:
                progress(0.2, "Building acceptance table (Plan 2)...")
                table = cusp2.acceptance_limit_table(
                    num, loc, target, lbound, cilevel, se_vals, sm_vals
                )
                self._last_table = table
                self._table_cache[key] = table
                self._last_table = table
            else:
                progress(0.2, "Using cached table...")
            d1 = se_vals[1] - se_vals[0] if len(se_vals) > 1 else 0.1
            progress(0.6, "Evaluating probability grid...")
            return cusp2.probability_of_passing(table, num, loc, d1, u_vals, sigse_vals, sigsm_vals)

        return job

    def _run_sample(self):
        v = self.sample_fields
        mean = v["mean"].get(float)
        se = v["se"].get(float)
        sm = v["sm"].get(float)
        num = v["num"].get(int)
        loc = v["loc"].get(int)
        target = v["target"].get(float)
        cilevel = v["cilevel"].get(float)

        def job(progress):
            progress(0.4, "Computing sample probability...")
            return cusp2.sample_probability(mean, se, sm, num, loc, target, cilevel)

        return job

    def _oc_available(self):
        return True

    def _oc_context(self):
        v = self.table_fields
        num, loc = v["num"].get(int), v["loc"].get(int)
        target = v["target"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        se_vals = make_grid(
            v["se_low"].get(float), v["se_high"].get(float), v["se_step"].get(float), "SE"
        )
        sm_vals = make_grid(
            v["sm_low"].get(float), v["sm_high"].get(float), v["sm_step"].get(float), "SM"
        )
        d1 = se_vals[1] - se_vals[0] if len(se_vals) > 1 else 0.1
        table = (
            self._last_table
            if self._last_table is not None
            else cusp2.acceptance_limit_table(num, loc, target, lbound, cilevel, se_vals, sm_vals)
        )

        def computed(xk, xs, fx):
            U = [float(x) for x in xs] if xk == "u" else [fx["U"]]
            SE = [float(x) for x in xs] if xk == "se" else [fx["SE"]]
            return _prob_series(
                cusp2.probability_of_passing(table, num, loc, d1, U, SE, [fx["SM"]])
            )

        def make_units(xk, x, fx, rng, reps):
            U = x if xk == "u" else fx["U"]
            SE = x if xk == "se" else fx["SE"]
            return U + rng.normal(0.0, fx["SM"], (reps, 1)) + rng.normal(0.0, SE, (reps, 30))

        return make_oc_context(
            "cu",
            target,
            computed,
            make_units,
            [("se", "True within-loc SD  [U, SM fixed]"), ("u", "True mean U  [SE, SM fixed]")],
            {"se": (0.5, 10.0, 0.25), "u": (85.0, 115.0, 1.0)},
            {"se": [("U", target), ("SM", 2.2)], "u": [("SE", 2.2), ("SM", 2.2)]},
        )


class Disp1Tab(BaseTab):
    def __init__(self, parent=None):
        super().__init__("Dissolution -- Sampling Plan 1", "Single location (USP <711>).", parent)
        self._last_table = None

    def _build_mode_frames(self):
        self.table_fields = build_form(
            self.mode_frames["table"].layout(),
            [
                ("number", "Number of units (N)", 6),
                ("q", "Q value (%)", 80.0),
                ("lbound", "Lower bound (%)", 95.0),
                ("cilevel", "Confidence level (%)", 95.0),
                ("meanadj_step", "Mean grid step", 1.0),
            ],
            registry=self.field_registry["table"],
        )

        lay = self.mode_frames["evaluate"].layout()
        desc = QLabel("Builds the table above, then evaluates:")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        lay.addWidget(desc, 0, 0, 1, 2)
        self.eval_fields = build_form(
            lay,
            [
                ("u_low", "True mean U -- low", 90.0),
                ("u_high", "True mean U -- high", 100.0),
                ("u_step", "True mean U -- step", 2.5),
                ("cv_low", "True CV(%) -- low", 1.0),
                ("cv_high", "True CV(%) -- high", 4.0),
                ("cv_step", "True CV(%) -- step", 1.0),
            ],
            start_row=1,
            registry=self.field_registry["evaluate"],
        )

        self.sample_fields = build_form(
            self.mode_frames["sample"].layout(),
            [
                ("mean", "Sample mean (%)", 90.0),
                ("cv", "Sample CV (%)", 3.0),
                ("number", "Number of units (N)", 6),
                ("q", "Q value (%)", 80.0),
                ("cilevel", "Confidence level (%)", 95.0),
            ],
            registry=self.field_registry["sample"],
        )

    def _run_table(self):
        v = self.table_fields
        number = v["number"].get(int)
        q = v["q"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
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
            self._last_table = table
            progress(1.0, "Table complete.")
            return table

        return job

    def _run_evaluate(self):
        v = self.table_fields
        number = v["number"].get(int)
        q = v["q"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        u_vals = make_grid(
            self.eval_fields["u_low"].get(float),
            self.eval_fields["u_high"].get(float),
            self.eval_fields["u_step"].get(float),
            "U",
        )
        cv_vals = make_grid(
            self.eval_fields["cv_low"].get(float),
            self.eval_fields["cv_high"].get(float),
            self.eval_fields["cv_step"].get(float),
            "CV",
        )
        key = self._cache_key(number, q, lbound, cilevel)

        def job(progress):
            table = self._table_cache.get(key)
            if table is None:
                progress(0.2, "Building acceptance table...")
                table = disp1.acceptance_limit_table(number, q, lbound, cilevel)
                self._table_cache[key] = table
                self._last_table = table
            else:
                progress(0.2, "Using cached table...")
            progress(0.6, "Evaluating probability grid...")
            return disp1.probability_of_passing(table, number, u_vals, cv_vals)

        return job

    def _run_sample(self):
        v = self.sample_fields
        mean = v["mean"].get(float)
        cv = v["cv"].get(float)
        number = v["number"].get(int)
        q = v["q"].get(float)
        cilevel = v["cilevel"].get(float)

        def job(progress):
            progress(0.4, "Computing sample probability...")
            return disp1.sample_probability(mean, cv, number, q, cilevel)

        return job

    def _oc_available(self):
        return True

    def _oc_context(self):
        v = self.table_fields
        number = v["number"].get(int)
        q = v["q"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        table = (
            self._last_table
            if self._last_table is not None
            else disp1.acceptance_limit_table(number, q, lbound, cilevel)
        )

        def computed(xk, xs, fx):
            if xk == "cv":
                res = disp1.probability_of_passing(table, number, [fx["U"]], [float(x) for x in xs])
            else:
                res = disp1.probability_of_passing(
                    table, number, [float(x) for x in xs], [fx["CV"]]
                )
            return _prob_series(res)

        def make_units(xk, x, fx, rng, reps):
            U = x if xk == "u" else fx["U"]
            CV = x if xk == "cv" else fx["CV"]
            return rng.normal(U, U * CV / 100.0, (reps, 24))

        return make_oc_context(
            "disp",
            q,
            computed,
            make_units,
            [("cv", "True CV (%)  [U fixed]"), ("u", "True mean U (%)  [CV fixed]")],
            {"cv": (0.5, 25.0, 0.5), "u": (70.0, 120.0, 1.0)},
            {"cv": [("U", 100.0)], "u": [("CV", 3.0)]},
        )


class Disp2Tab(BaseTab):
    def __init__(self, parent=None):
        super().__init__(
            "Dissolution -- Sampling Plan 2",
            "Multiple locations, within/between-location variance components (USP <711>).",
            parent,
        )
        self._last_table = None

    def _build_mode_frames(self):
        self.table_fields = build_form(
            self.mode_frames["table"].layout(),
            [
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
            ],
            registry=self.field_registry["table"],
        )

        lay = self.mode_frames["evaluate"].layout()
        desc = QLabel("Builds the table above, then evaluates:")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        lay.addWidget(desc, 0, 0, 1, 2)
        self.eval_fields = build_form(
            lay,
            [
                ("u_low", "True mean U -- low", 90.0),
                ("u_high", "True mean U -- high", 100.0),
                ("u_step", "True mean U -- step", 2.5),
                ("sigse_low", "True within-loc SD -- low", 1.0),
                ("sigse_high", "True within-loc SD -- high", 3.0),
                ("sigse_step", "True within-loc SD -- step", 1.0),
                ("sigsm_low", "True between-loc SD -- low", 1.0),
                ("sigsm_high", "True between-loc SD -- high", 3.0),
                ("sigsm_step", "True between-loc SD -- step", 1.0),
            ],
            start_row=1,
            registry=self.field_registry["evaluate"],
        )

        self.sample_fields = build_form(
            self.mode_frames["sample"].layout(),
            [
                ("mean", "Sample mean (%)", 90.0),
                ("se", "Sample within-loc SD", 2.2),
                ("sm", "Sample between-loc SD", 2.46),
                ("num", "Units per location", 6),
                ("loc", "Number of locations", 5),
                ("q", "Q value (%)", 80.0),
                ("cilevel", "Confidence level (%)", 95.0),
            ],
            registry=self.field_registry["sample"],
        )

    def _table_args(self):
        v = self.table_fields
        num = v["num"].get(int)
        loc = v["loc"].get(int)
        q = v["q"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        se_vals = make_grid(
            v["se_low"].get(float), v["se_high"].get(float), v["se_step"].get(float), "SE"
        )
        sm_vals = make_grid(
            v["sm_low"].get(float), v["sm_high"].get(float), v["sm_step"].get(float), "SM"
        )
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
            self._last_table = table
            self._table_cache[key] = table
            progress(1.0, "Table complete.")
            return table

        return job

    def _run_evaluate(self):
        num, loc, q, lbound, cilevel, se_vals, sm_vals = self._table_args()
        dse = se_vals[1] - se_vals[0] if len(se_vals) > 1 else 1.0
        dsm = sm_vals[1] - sm_vals[0] if len(sm_vals) > 1 else 1.0
        u_vals = make_grid(
            self.eval_fields["u_low"].get(float),
            self.eval_fields["u_high"].get(float),
            self.eval_fields["u_step"].get(float),
            "U",
        )
        sigse_vals = make_grid(
            self.eval_fields["sigse_low"].get(float),
            self.eval_fields["sigse_high"].get(float),
            self.eval_fields["sigse_step"].get(float),
            "within-loc SD",
        )
        sigsm_vals = make_grid(
            self.eval_fields["sigsm_low"].get(float),
            self.eval_fields["sigsm_high"].get(float),
            self.eval_fields["sigsm_step"].get(float),
            "between-loc SD",
        )
        key = self._cache_key(num, loc, q, lbound, cilevel, se_vals, sm_vals)

        def job(progress):
            table = self._table_cache.get(key)
            if table is None:
                progress(0.2, "Building acceptance table (Plan 2)...")
                table = disp2.acceptance_limit_table(num, loc, q, lbound, cilevel, se_vals, sm_vals)
                self._table_cache[key] = table
                self._last_table = table
            else:
                progress(0.2, "Using cached table...")
            progress(0.6, "Evaluating probability grid...")
            return disp2.probability_of_passing(
                table, num, loc, dse, dsm, u_vals, sigse_vals, sigsm_vals
            )

        return job

    def _run_sample(self):
        v = self.sample_fields
        mean = v["mean"].get(float)
        se = v["se"].get(float)
        sm = v["sm"].get(float)
        num = v["num"].get(int)
        loc = v["loc"].get(int)
        q = v["q"].get(float)
        cilevel = v["cilevel"].get(float)

        def job(progress):
            progress(0.4, "Computing sample probability...")
            return disp2.sample_probability(mean, se, sm, num, loc, q, cilevel)

        return job

    def _oc_available(self):
        return True

    def _oc_context(self):
        v = self.table_fields
        num, loc = v["num"].get(int), v["loc"].get(int)
        q = v["q"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        se_vals = make_grid(
            v["se_low"].get(float), v["se_high"].get(float), v["se_step"].get(float), "SE"
        )
        sm_vals = make_grid(
            v["sm_low"].get(float), v["sm_high"].get(float), v["sm_step"].get(float), "SM"
        )
        dse = se_vals[1] - se_vals[0] if len(se_vals) > 1 else 1.0
        dsm = sm_vals[1] - sm_vals[0] if len(sm_vals) > 1 else 1.0
        table = (
            self._last_table
            if self._last_table is not None
            else disp2.acceptance_limit_table(num, loc, q, lbound, cilevel, se_vals, sm_vals)
        )

        def computed(xk, xs, fx):
            U = [float(x) for x in xs] if xk == "u" else [fx["U"]]
            SE = [float(x) for x in xs] if xk == "se" else [fx["SE"]]
            return _prob_series(
                disp2.probability_of_passing(table, num, loc, dse, dsm, U, SE, [fx["SM"]])
            )

        def make_units(xk, x, fx, rng, reps):
            U = x if xk == "u" else fx["U"]
            SE = x if xk == "se" else fx["SE"]
            return U + rng.normal(0.0, fx["SM"], (reps, 1)) + rng.normal(0.0, SE, (reps, 24))

        return make_oc_context(
            "disp",
            q,
            computed,
            make_units,
            [("se", "True within-loc SD  [U, SM fixed]"), ("u", "True mean U  [SE, SM fixed]")],
            {"se": (0.5, 25.0, 0.5), "u": (70.0, 120.0, 2.0)},
            {"se": [("U", 100.0), ("SM", 2.2)], "u": [("SE", 2.2), ("SM", 2.2)]},
        )


# ---------------------------------------------------------------------------
# OC-curve engine (unified): Monte-Carlo probability of passing the
# compendial test itself -- USP <905> (2 stages) or USP <711> (3 stages).
# ---------------------------------------------------------------------------
def _oc_cu_pass(units: np.ndarray, target: float) -> float:
    """Two-stage USP <905> decision. units: (reps, 30) -> P(pass)."""
    """
    This checks for an absolute shift of 25.0 units rather than 25% of $M$.
     - If $M = 98.5$, the lower bound should be $73.875$ ($98.5 \times 0.75$), meaning a deviation of at most $24.625$.
     - code allows a deviation up to $25.0$ (down to $73.5$), falsely passing extreme outliers.
     - If $M = 101.5$, the upper bound should be $126.875$, meaning a deviation up to $25.375$.
     - code caps it strictly at $25.0$ ($126.5$), falsely failing valid units.
    """
    passed = np.zeros(units.shape[0], dtype=bool)
    hi = target if target > 101.5 else 101.5

    def M(m):
        return np.where(m <= 100.0, np.maximum(98.5, m), np.minimum(hi, m))

    # --- Stage 1 (10 units) ---
    x1 = units[:, :10]
    m1, s1 = x1.mean(axis=1), x1.std(axis=1, ddof=1)

    p1 = (np.abs(M(m1) - m1) + 2.4 * s1) <= 15.0
    passed |= p1

    # --- Stage 2 (30 units) ---
    live = np.where(~p1)[0]
    if live.size:
        x30 = units[live]
        m2, s2 = x30.mean(axis=1), x30.std(axis=1, ddof=1)
        M2 = M(m2)

        av_ok = (np.abs(M2 - m2) + 2.0 * s2) <= 15.0
        # FIXED: 0.25 * M2 instead of hardcoded 25.0
        within_ok = np.abs(x30 - M2[:, None]).max(axis=1) <= (0.25 * M2)

        passed[live[av_ok & within_ok]] = True

    return float(passed.mean())


def _oc_disp_pass(units, q):
    """Three-stage USP <711> decision. units: (reps, 24) -> P(pass)."""
    passed = np.zeros(units.shape[0], dtype=bool)

    x6 = units[:, :6]  # Stage 1: all >= Q+5
    p = np.all(x6 >= q + 5.0, axis=1)
    passed |= p
    live = np.where(~p)[0]

    if live.size:  # Stage 2: 12 units
        x12 = units[live][:, :12]
        # FIXED: Changed > to >= for Q-15 boundary
        p = (x12.mean(axis=1) >= q) & np.all(x12 >= q - 15.0, axis=1)
        passed[live[p]] = True
        live = live[~p]

    if live.size:  # Stage 3: 24 units
        x24 = units[live][:, :24]
        ok_mean = x24.mean(axis=1) >= q
        # FIXED: Changed <= to < to match "less than Q-15%"
        n_l15 = (x24 < q - 15.0).sum(axis=1)
        # FIXED: Changed <= to < to match "less than Q-25%"
        any_l25 = (x24 < q - 25.0).any(axis=1)

        p = ok_mean & (n_l15 <= 2) & ~any_l25
        passed[live[p]] = True

    return float(passed.mean())


def _prob_series(df):
    for c in df.columns:
        if any(s in str(c).lower() for s in ("prob", "pass", "ptrap")):
            return pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
    return pd.to_numeric(df.iloc[:, -1], errors="coerce").to_numpy(dtype=float)


def make_oc_context(test, ref, computed, make_units, x_choices, grid, fixed_specs):
    """Single factory for every tab's OC context.

    test       : "cu"  -> USP <905> two-stage decision,  ref = target
                 "disp"-> USP <711> three-stage decision, ref = Q
    computed   : fn(xk, xs, fx) -> analytic P(pass table)   (per-tab)
    make_units : fn(xk, x, fx, rng, reps) -> (reps, n_units) simulated units
    """
    decision = _oc_cu_pass if test == "cu" else _oc_disp_pass

    def usp(xk, xs, fx, reps):
        out = []
        for x in xs:
            rng = np.random.default_rng(12345)  # seeded -> reproducible
            out.append(decision(make_units(xk, float(x), fx, rng, reps), ref))
        return np.array(out)

    return {
        "test": test,
        "x_choices": x_choices,
        "grid": grid,
        "fixed_specs": fixed_specs,
        "computed": computed,
        "usp": usp,
    }


class OCDialog(QDialog):
    """OC curve: computed acceptance-limit plan vs the USP <905> test itself."""

    def __init__(self, ctx, parent=None, save_base=None):
        super().__init__(parent)
        self._ctx = ctx
        self._usp_label = (
            "USP <905> two-stage test (Monte Carlo)"
            if ctx["test"] == "cu"
            else "USP <711> three-stage test (Monte Carlo)"
        )
        self._title = "OC Curve -- computed plan vs " + (
            "USP <905>" if ctx["test"] == "cu" else "USP <711>"
        )
        self.setWindowTitle(self._title)
        self.resize(900, 640)
        self.setModal(True)
        self._save_base = save_base or "oc"

        lay = QVBoxLayout(self)
        top = QGridLayout()
        top.addWidget(QLabel("X axis:"), 0, 0)
        self.x_cb = QComboBox()
        for key, label in ctx["x_choices"]:
            self.x_cb.addItem(label, key)
        top.addWidget(self.x_cb, 0, 1)
        top.addWidget(QLabel("low/high/step:"), 0, 2)
        self.g_lo, self.g_hi, self.g_st = (QLineEdit() for _ in range(3))
        for w in (self.g_lo, self.g_hi, self.g_st):
            w.setFixedWidth(70)
        row = QHBoxLayout()
        row.addWidget(self.g_lo)
        row.addWidget(self.g_hi)
        row.addWidget(self.g_st)
        top.addLayout(row, 0, 3)
        top.addWidget(QLabel("MC reps:"), 0, 4)
        self.rep_ed = QLineEdit("2000")
        self.rep_ed.setFixedWidth(70)
        top.addWidget(self.rep_ed, 0, 5)

        self.fixed_box = QWidget()
        self.fixed_layout = QHBoxLayout(self.fixed_box)
        self.fixed_layout.setContentsMargins(0, 0, 0, 0)
        redraw = QPushButton("Redraw")
        redraw.setObjectName("accent")
        redraw.clicked.connect(self._redraw)
        save = QPushButton("Save PNG")
        save.clicked.connect(self._save_png)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        wrap = QHBoxLayout()
        wrap.addWidget(self.fixed_box, 1)
        wrap.addWidget(redraw)
        wrap.addWidget(save)
        wrap.addWidget(close)
        top.addLayout(wrap, 1, 0, 1, 6)
        lay.addLayout(top)

        self._fig = Figure(dpi=100)
        self._canvas = FigureCanvas(self._fig)
        lay.addWidget(NavigationToolbar(self._canvas, self))
        lay.addWidget(self._canvas, 1)

        self.x_cb.currentIndexChanged.connect(lambda _i: (self._build_fixed(), self._redraw()))
        self._build_fixed()
        self._redraw()

    def _build_fixed(self):
        while self.fixed_layout.count():
            it = self.fixed_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._fixed_edits = {}
        xk = self.x_cb.currentData()
        lbl = QLabel("Fixed:")
        self.fixed_layout.addWidget(lbl)
        for name, d in self._ctx["fixed_specs"][xk]:
            self.fixed_layout.addWidget(QLabel(f"{name} ="))
            ed = QLineEdit(str(d))
            ed.setFixedWidth(70)
            self.fixed_layout.addWidget(ed)
            self._fixed_edits[name] = ed
        lo, hi, st = self._ctx["grid"][xk]
        self.g_lo.setText(str(lo))
        self.g_hi.setText(str(hi))
        self.g_st.setText(str(st))

    def _inputs(self):
        xk = self.x_cb.currentData()
        lo, hi, st = (float(w.text()) for w in (self.g_lo, self.g_hi, self.g_st))
        xs = np.arange(lo, hi + st / 2.0, st)
        fx = {n: float(w.text()) for n, w in self._fixed_edits.items()}
        reps = max(200, int(self.rep_ed.text() or 2000))
        return xk, xs, fx, reps

    def _redraw(self):
        xk, xs, fx, reps = self._inputs()
        p_comp = self._ctx["computed"](xk, xs, fx)
        p_usp = self._ctx["usp"](xk, xs, fx, reps)
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        ax.plot(
            xs,
            p_comp,
            "o-",
            color=SERIES_COLORS[0],
            lw=1.8,
            ms=4,
            label="Computed plan (acceptance-limit table)",
        )
        ax.plot(xs, p_usp, "s--", color=SERIES_COLORS[2], lw=1.8, ms=4, label=self._usp_label)
        for t in (0.8, 0.9):
            ax.axhline(t, ls=":", lw=0.8, color="0.5")
        ax.set_ylim(0.0, 1.05)
        ax.set_xlabel(self.x_cb.currentText())
        ax.set_ylabel("Probability of passing")
        ax.set_title(self._title)
        ax.legend(fontsize=9, loc="best")
        ax.grid(True, alpha=0.3)
        self._fig.tight_layout()
        self._canvas.draw()

    def _save_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save figure", self._save_base + ".png", "PNG image (*.png)"
        )
        if path:
            self._fig.savefig(path, dpi=150)
            QMessageBox.information(self, "Saved", f"Figure saved to {path}")


class SplashScreen(QDialog):
    """Frameless startup splash: logo, note, progress bar, developer footer."""

    def __init__(self):
        super().__init__(
            None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedSize(620, 400)
        self.setStyleSheet("""
            QDialog      { background:#0d2b55; }
            QLabel       { background:transparent; }
            #title { color:white; font-size:26px; font-weight:700; }
            #note  { color:#bcd4f5; font-size:10pt; }
            #status{ color:#9fc3f2; font-size:9pt; }
            #foot  { color:#bcd4f5; font-size:9pt; }
            #foot a{ color:#4da3ff; }
            QProgressBar { background:#123a6e; border:0; border-radius:5px;
                           height:10px; text-align: center; }
            QProgressBar::chunk { background:#4da3ff; border-radius:5px; }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 22, 30, 14)
        center = Qt.AlignmentFlag.AlignCenter

        logo_file = resource_path("logo.png")
        if os.path.exists(logo_file):
            pix = QPixmap(logo_file)
            if not pix.isNull():
                if pix.height() > 96:
                    pix = pix.scaledToHeight(96, Qt.TransformationMode.SmoothTransformation)
                ll = QLabel()
                ll.setPixmap(pix)
                ll.setAlignment(center)
                lay.addWidget(ll)

        t = QLabel("PyCuDAL")
        t.setObjectName("title")
        t.setAlignment(center)
        lay.addWidget(t)
        n = QLabel(
            "Parametric acceptance limits for USP <905> Content\n"
            "Uniformity and USP <711> Dissolution"
        )
        n.setObjectName("note")
        n.setAlignment(center)
        lay.addWidget(n)
        lay.addSpacing(14)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        lay.addWidget(self.bar)
        self.status = QLabel("Starting…")
        self.status.setObjectName("status")
        self.status.setAlignment(center)
        lay.addWidget(self.status)
        lay.addStretch(1)

        foot = QLabel(f'Program developed by: <a href="{REPO_URL}">Moaz El-Essawey</a>')
        foot.setObjectName("foot")
        foot.setOpenExternalLinks(True)  # click opens the GitHub repo
        foot.setAlignment(center)
        lay.addWidget(foot)

        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center() - self.rect().center())

    def set_progress(self, frac, msg):
        self.bar.setValue(int(frac * 100))
        self.status.setText(msg)
        QApplication.processEvents()
        time.sleep(0.08)


def _load_libraries(splash=None):
    global np, pd, cusp1, cusp2, disp1, disp2
    global Figure, FigureCanvas, NavigationToolbar, make_interp_spline
    global HAVE_CUDAL, HAVE_MPL, HAVE_SPLINE, HAVE_XLSX

    def step(frac, msg):
        if splash is not None:
            splash.set_progress(frac, msg)

    step(0.05, "Loading NumPy…")
    import numpy as _np

    np = _np

    step(0.20, "Loading Pandas…")
    import pandas as _pd

    pd = _pd

    step(0.40, "Loading CuDAL core…")
    try:
        from cudal import cusp1 as _a
        from cudal import cusp2 as _b
        from cudal import disp1 as _c
        from cudal import disp2 as _d

        cusp1, cusp2, disp1, disp2 = _a, _b, _c, _d
        HAVE_CUDAL = True
    except Exception:
        HAVE_CUDAL = False

    step(0.60, "Loading SciPy…")
    try:
        from scipy.interpolate import make_interp_spline as _mis

        make_interp_spline = _mis
        HAVE_SPLINE = True
    except Exception:
        HAVE_SPLINE = False

    step(0.75, "Loading Matplotlib…")
    try:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as _C
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as _T
        from matplotlib.figure import Figure as _F

        Figure, FigureCanvas, NavigationToolbar = _F, _C, _T
        HAVE_MPL = True
    except Exception:
        HAVE_MPL = False

    step(0.90, "Loading export engines…")
    try:
        import openpyxl  # noqa: F401

        HAVE_XLSX = True
    except Exception:
        HAVE_XLSX = False

    step(1.0, "Ready.")


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
                logo_lbl.setPixmap(
                    pix.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
                )
                header.addWidget(logo_lbl)
        else:
            t = QLabel("CuDAL")
            t.setObjectName("header")
        s = QLabel(
            "   Parametric acceptance limits for USP <905> Content Uniformity "
            "and USP <711> Dissolution"
        )
        s.setObjectName("subheader")
        if not logo_file:
            header.addWidget(t)
        header.addWidget(s)
        header.addStretch(1)
        outer.addLayout(header)

        # ---- tabs ---------------------------------------------------------------
        self.notebook = QTabWidget()
        self.tabs = [Cusp1Tab(), Cusp2Tab(), Disp1Tab(), Disp2Tab()]
        for tab, text in zip(
            self.tabs,
            [
                "Content Uniformity -- Plan 1",
                "Content Uniformity -- Plan 2",
                "Dissolution -- Plan 1",
                "Dissolution -- Plan 2",
            ],
        ):
            self.notebook.addTab(tab, text)
        outer.addWidget(self.notebook, 1)

        # ---- comprehensive menu bar ----------------------------------------
        menubar = self.menuBar()

        filem = menubar.addMenu("&File")
        a = filem.addAction("Export current results (CSV)")
        a.setShortcut(QKeySequence("Ctrl+E"))
        a.triggered.connect(self._export_current_csv)
        a = filem.addAction("Export current results (PDF)")
        a.triggered.connect(self._export_current_pdf)
        a = filem.addAction("Export all results (XLSX)")
        a.triggered.connect(self._export_all_xlsx)
        filem.addSeparator()
        a = filem.addAction("Save settings now")
        a.setShortcut(QKeySequence("Ctrl+S"))
        a.triggered.connect(self._save_settings_now)
        filem.addSeparator()
        a = filem.addAction("Exit")
        a.setShortcut(QKeySequence("Ctrl+Q"))
        a.triggered.connect(self.close)

        runm = menubar.addMenu("&Run")
        a = runm.addAction("Run analysis")
        a.setShortcut(QKeySequence("Ctrl+R"))
        a.triggered.connect(lambda: self._current_tab()._on_run())
        a = runm.addAction("Reset parameters")
        a.triggered.connect(lambda: self._current_tab()._reset_defaults())
        runm.addSeparator()
        a = runm.addAction("Plot results")
        a.setShortcut(QKeySequence("Ctrl+P"))
        a.triggered.connect(lambda: self._current_tab().results._show_plot())
        a = runm.addAction("OC curve\u2026")
        a.setShortcut(QKeySequence("Ctrl+O"))
        a.triggered.connect(self._show_oc_current)
        runm.addSeparator()
        a = runm.addAction("Copy selection")
        a.setShortcut(QKeySequence.Copy)
        a.triggered.connect(self._copy_current_selection)
        a = runm.addAction("Clear results")
        a.triggered.connect(lambda: self._current_tab().results.clear())

        viewm = menubar.addMenu("&View")
        for i, label in enumerate(
            (
                "Content Uniformity \u2013 Plan 1",
                "Content Uniformity \u2013 Plan 2",
                "Dissolution \u2013 Plan 1",
                "Dissolution \u2013 Plan 2",
            )
        ):
            a = viewm.addAction(label)
            a.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            a.triggered.connect(lambda _=False, i=i: self.notebook.setCurrentIndex(i))

        helpm = menubar.addMenu("&Help")
        a = helpm.addAction("Documentation (online)")
        a.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        a = helpm.addAction("Report an issue")
        a.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL + "/issues")))
        helpm.addSeparator()
        a = helpm.addAction("About / Help")
        a.setShortcut(QKeySequence("F1"))
        a.triggered.connect(self._show_about)

        # ---- action toolbar --------------------------------------------------
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(18, 18))

        def _glyph_icon(glyph, color=ACCENT_DARK):
            px = QPixmap(18, 18)
            px.fill(Qt.GlobalColor.transparent)
            p = QPainter(px)
            p.setPen(QColor(color))
            f = QFont("Segoe UI Symbol", 11)
            f.setBold(True)
            p.setFont(f)
            p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
            p.end()
            return QIcon(px)

        def add_tool(text, glyph, slot, tip):
            a = QAction(_glyph_icon(glyph), text, self)
            a.triggered.connect(slot)
            a.setToolTip(tip)
            toolbar.addAction(a)
            return a

        add_tool(
            "Run",
            "\u25b6",
            lambda: self._current_tab()._on_run(),
            "Run the selected analysis (Ctrl+R)",
        )
        add_tool(
            "Plot",
            "\u223f",
            lambda: self._current_tab().results._show_plot(),
            "Plot results (Ctrl+P)",
        )
        add_tool(
            "OC Curve",
            "\u2277",
            self._show_oc_current,
            "OC curve: computed plan vs USP test (Ctrl+O)",
        )
        add_tool(
            "CSV", "\u2913", self._export_current_csv, "Export current results to CSV (Ctrl+E)"
        )
        add_tool(
            "PDF", "\u2261", self._export_current_pdf, "Export current results to SAS-style PDF"
        )
        add_tool("XLSX", "\u25a6", self._export_all_xlsx, "Export all results to Excel")
        add_tool(
            "Reset",
            "\u21ba",
            lambda: self._current_tab()._reset_defaults(),
            "Reset parameters to defaults",
        )
        add_tool("About", "?", self._show_about, "About PyCuDAL (F1)")

        # # ---- shortcuts ------------------------------------------------------------
        # QShortcut(QKeySequence("Ctrl+R"), self, activated=lambda: self._current_tab()._on_run())
        # QShortcut(QKeySequence("Ctrl+P"), self,
        #           activated=lambda: self._current_tab().results._show_plot())

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

        # ---- footer / status bar ------------------------------------------------
        self.statusBar().showMessage("Ready.")
        credit_lbl = QLabel(
            'Created by <a href="https://github.com/moazelessawey/pycudal" '
            'style="color: #2f6fed; text-decoration: none;">Moaz El-Essawey</a>'
        )
        credit_lbl.setOpenExternalLinks(True)
        credit_lbl.setTextFormat(Qt.TextFormat.RichText)
        credit_lbl.setStyleSheet("margin-right: 10px; font-size: 9pt;")
        self.statusBar().addPermanentWidget(credit_lbl)

    # -- helpers ---------------------------------------------------------------------
    def _current_tab(self):
        return self.notebook.currentWidget()

    @staticmethod
    def _load_settings():
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as fh:
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
            QMessageBox.critical(
                self,
                "Excel export unavailable",
                "openpyxl is required.\nInstall it with:  pip install openpyxl",
            )
            return
        sheets = {
            tab.__class__.__name__: tab.results._df
            for tab in self.tabs
            if tab.results._df is not None
        }
        if not sheets:
            QMessageBox.information(self, "Nothing to export", "Run at least one analysis first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export all results",
            f"PyCuDAL-all-results-{time.strftime('%Y%m%d-%H%M')}.xlsx",
            "Excel workbook (*.xlsx)",
        )
        if not path:
            return
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for name, df in sheets.items():
                df.to_excel(writer, sheet_name=name[:31], index=False)
        QMessageBox.information(self, "Exported", f"Saved {len(sheets)} sheet(s) to {path}")

    # -- top-bar dispatchers (guarded for optional features) ------------------
    def _export_current_pdf(self):
        r = self._current_tab().results
        if hasattr(r, "_export_pdf"):
            r._export_pdf()
        else:
            QMessageBox.information(
                self, "Unavailable", "PDF export is not included in this build."
            )

    def _show_oc_current(self):
        t = self._current_tab()
        if hasattr(t, "_show_oc"):
            t._show_oc()
        else:
            QMessageBox.information(
                self, "Unavailable", "OC curves are not included in this build."
            )

    def _copy_current_selection(self):
        r = self._current_tab().results
        if hasattr(r, "_copy_selection"):
            r._copy_selection()

    def _save_settings_now(self):
        self._save_settings()
        self.statusBar().showMessage("Settings saved.", 3000)

    def _show_about(self):
        deps = (
            f"matplotlib: {'yes' if HAVE_MPL else 'no'}\n"
            f"scipy splines: {'yes' if HAVE_SPLINE else 'no'}\n"
            f"openpyxl (xlsx): {'yes' if HAVE_XLSX else 'no'}"
        )
        about_text = (
            f"PyCuDAL v{VERSION}\n\n"
            "Parametric acceptance limits for USP <905> Content Uniformity\n"
            "and USP <711> Dissolution.\n\n"
            "This tool mirrors the functionality of the original SAS programs\n"
            "(CALCUSPx/CALDISPx, EVCUSPx/EVDISPx, SMPCUSPx/SMPDISPx)\n"
            "developed by James Bergum, Ph.D.\n\n"
            "Created & Maintained by: Moaz El-Essawey\n"
            "GitHub: https://github.com/moazelessawey/pycudal\n\n"
            "Shortcuts:\n"
            "  Ctrl+R  run analysis\n"
            "  Ctrl+E  export current results (CSV)\n"
            "  Ctrl+P  plot results\n"
            "  Ctrl+C  copy selected table rows\n"
            "  F1      this dialog\n\n"
            f"Optional dependencies:\n{deps}"
        )
        QMessageBox.about(self, "About PyCuDAL", about_text)


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
        _load_libraries(None)
        run_selftest()
        return

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    splash = SplashScreen()
    splash.show()
    app.processEvents()
    _load_libraries(splash)

    if not HAVE_CUDAL:
        splash.close()
        QMessageBox.critical(
            None,
            "Missing dependency",
            "The `cudal` package could not be imported.\n"
            "Put this script next to the `cudal` package folder\n"
            "or install it, then restart the GUI.",
        )
        sys.exit(1)

    family = _register_local_fonts()
    if not family:
        family = "Segoe UI" if sys.platform.startswith("win") else "DejaVu Sans"
    app.setFont(QFont(family, 10))
    app.setStyleSheet(build_stylesheet(family))
    if HAVE_MPL:
        try:
            fdir = resource_path("fonts")
            if os.path.isdir(fdir):
                import matplotlib as mpl
                from matplotlib import font_manager as fm

                for f in os.listdir(fdir):
                    if f.lower().endswith((".ttf", ".otf")):
                        fm.fontManager.addfont(os.path.join(fdir, f))
                mpl.rcParams["font.family"] = family
        except Exception:
            pass

    win = CudalApp()
    win.show()
    splash.close()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
