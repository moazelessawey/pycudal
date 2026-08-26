"""
cudal_gui.py

A Tkinter GUI front end for the `cudal` package (see cudal/*.py),
covering the same four scenarios and three analysis modes as the CLI
(cudal/cli.py):

Content Uniformity - Plan 1   (cudal.cusp1)
Content Uniformity - Plan 2   (cudal.cusp2)
Dissolution        - Plan 1   (cudal.disp1)
Dissolution        - Plan 2   (cudal.disp2)

Features
--------
* Threaded calculations with a REAL (determinate) progress bar and status
  messages; acceptance tables are memoized so "evaluate" reuses them.
* Scrollable parameters panel (shared, correct mouse-wheel dispatch).
* Results Treeview: visible text on all Tk builds, click-to-sort headers,
  zebra striping, conditional coloring of P(pass) rows, Ctrl+C copy,
  CSV export, modal matplotlib plot dialog (lines+spline AND heatmap with
  80/90% threshold contours), Save PNG.
* Settings persistence (parameters, mode, active tab, window geometry) in
  cudal_gui_settings.json; Reset-defaults button.
* Live input validation (red entry style) + tooltips; keyboard shortcuts
  (Ctrl+R run, Ctrl+E export CSV, Ctrl+P plot, F1 help); About dialog.
* Graceful startup when `cudal`/optional deps are missing; Windows DPI
  awareness; `--selftest` runs quick unit checks of the pure helpers.

Optional dependencies:
    pip install matplotlib scipy openpyxl

Run:
    python cudal_gui.py            # normal start
    python cudal_gui.py --selftest # quick unit tests, no GUI
"""

from __future__ import annotations

import csv
import json
import os
import math
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Optional dependencies (the app degrades gracefully without them)
# ---------------------------------------------------------------------------
try:
    from cudal import cusp1, cusp2, disp1, disp2
    HAVE_CUDAL = True
except Exception:  # pragma: no cover
    HAVE_CUDAL = False

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    HAVE_MPL = True
except Exception:  # pragma: no cover
    HAVE_MPL = False

try:
    from scipy.interpolate import make_interp_spline
    HAVE_SPLINE = True
except Exception:  # pragma: no cover
    HAVE_SPLINE = False

try:
    import openpyxl  # noqa: F401  (Excel export)
    HAVE_XLSX = True
except Exception:  # pragma: no cover
    HAVE_XLSX = False

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import letter, landscape
    HAVE_PDF = True
except Exception:  # pragma: no cover - reportlab is optional
    HAVE_PDF = False

# ---------------------------------------------------------------------------
# Visual style / constants
# ---------------------------------------------------------------------------
VERSION = "1.3.0"

BG = "#f4f6f9"
PANEL_BG = "#ffffff"
ACCENT = "#2f6fed"
ACCENT_DARK = "#204ea6"
TEXT = "#1c2733"
MUTED = "#64748b"
BORDER = "#e2e8f0"
OK_GREEN = "#1a8754"
ERR_RED = "#c0392b"
FONT_FAMILY = "helvetica"

TABLE_FONT_SIZE = 12  # integer on purpose (fractional sizes break some Tk builds)

SERIES_COLORS = [ACCENT, OK_GREEN, ERR_RED, "#8e44ad",
                 "#e67e22", "#16a085", "#c2417d", "#5b6470"]

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "cudal_gui_settings.json")


def setup_style(root: tk.Tk) -> None:
    root.configure(bg=BG)
    style = ttk.Style(root)

    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=BG, foreground=TEXT, font=(FONT_FAMILY, 10))
    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL_BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Panel.TLabel", background=PANEL_BG, foreground=TEXT)
    style.configure("Muted.TLabel", background=PANEL_BG, foreground=MUTED, font=(FONT_FAMILY, 9))
    style.configure("Header.TLabel", background=BG, foreground=TEXT, font=(FONT_FAMILY, 16, "bold"))
    style.configure("SubHeader.TLabel", background=BG, foreground=MUTED, font=(FONT_FAMILY, 10))
    style.configure("SectionTitle.TLabel", background=PANEL_BG, foreground=ACCENT_DARK,
                    font=(FONT_FAMILY, 11, "bold"))
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(8, 8, 8, 0))
    style.configure("TNotebook.Tab", padding=(16, 8), font=(FONT_FAMILY, 10, "bold"))
    style.map("TNotebook.Tab",
              background=[("selected", PANEL_BG), ("!selected", "#dde3ea")],
              foreground=[("selected", ACCENT_DARK), ("!selected", MUTED)])
    style.configure("TRadiobutton", background=PANEL_BG, foreground=TEXT, font=(FONT_FAMILY, 10))
    style.map("TRadiobutton", background=[("active", PANEL_BG)])
    style.configure("TEntry", fieldbackground="white", padding=4)
    style.configure("Invalid.TEntry", fieldbackground="#fdecea", foreground=ERR_RED, padding=4)
    style.configure("TLabelframe", background=PANEL_BG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=PANEL_BG, foreground=ACCENT_DARK,
                    font=(FONT_FAMILY, 10, "bold"))
    style.configure("Accent.TButton", background=ACCENT, foreground="white",
                    font=(FONT_FAMILY, 10, "bold"), padding=(14, 8), borderwidth=0)
    style.map("Accent.TButton",
              background=[("active", ACCENT_DARK), ("disabled", "#9db4e8")],
              foreground=[("disabled", "white")])
    style.configure("Secondary.TButton", background="#eef1f6", foreground=TEXT,
                    font=(FONT_FAMILY, 9), padding=(10, 6), borderwidth=0)
    style.map("Secondary.TButton", background=[("active", "#dfe4ec")])

    style.configure("Treeview", background=PANEL_BG, fieldbackground=PANEL_BG,
                    foreground=TEXT, rowheight=24,
                    font=(FONT_FAMILY, TABLE_FONT_SIZE), borderwidth=0)
    style.configure("Treeview.Heading", background="#eef1f6", foreground=TEXT,
                    font=(FONT_FAMILY, TABLE_FONT_SIZE, "bold"))
    style.map("Treeview",
              background=[("selected", "#d7e3fc")],
              fieldbackground=[("selected", "#d7e3fc")],
              foreground=[("selected", "#0b1b3d")])
    style.map("Treeview.Heading",
              background=[("active", "#e2e8f0")], foreground=[("active", TEXT)])

    style.configure("Status.TLabel", background=BG, foreground=MUTED, font=(FONT_FAMILY, 9))
    style.configure("green.Horizontal.TProgressbar", troughcolor="#e5e9f0", background=ACCENT, thickness=28)

# ---------------------------------------------------------------------------
# SAS-style PDF listing export (reportlab, Courier, column wrapping)
# ---------------------------------------------------------------------------
_PDF_FONT = "Courier"
_PDF_FS = 8.0
_PDF_LEAD = 11.0
_PDF_CHAR = 0.6 * _PDF_FS          # Courier advance width = 60% of font size


def _fmt_num(v):
    """Format a numeric value to 2 decimal places, right-aligned later.
    Returns '*' for NaN/Inf."""
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


# ---------------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------------
class ToolTip:
    """Tiny hover tooltip; attach to any widget."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, event=None):
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.configure(bg="#2b3648")
        tk.Label(self._tip, text=self.text, bg="#2b3648", fg="white",
                 font=(FONT_FAMILY, 9), justify="left", padx=8, pady=4).pack()
        self._tip.geometry(f"+{x}+{y}")

    def _hide(self, event=None):
        if self._tip:
            self._tip.destroy()
            self._tip = None


# ---------------------------------------------------------------------------
# Small reusable widgets
# ---------------------------------------------------------------------------
class LabeledField:
    """One label + entry row with live validation, tooltip and reset()."""

    def __init__(self, parent, row, key, label, default, width=12, cast=float, tip=None):
        self.key = key
        self.default = default
        self.cast = cast
        self.var = tk.StringVar(value=str(default))

        ttk.Label(parent, text=label, style="Panel.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        self.entry = ttk.Entry(parent, textvariable=self.var, width=width)
        self.entry.grid(row=row, column=1, sticky="w", pady=4)

        self.var.trace_add("write", self._on_change)
        ToolTip(self.entry, tip or f"{label}\nDefault: {default}")

    def _on_change(self, *_):
        raw = self.var.get().strip()
        ok = bool(raw)
        if ok:
            try:
                self.cast(raw)
            except ValueError:
                ok = False
        try:
            self.entry.configure(style="TEntry" if ok else "Invalid.TEntry")
        except tk.TclError:
            pass

    def reset(self):
        self.var.set(str(self.default))

    def get(self, cast=None):
        cast = cast or self.cast
        raw = self.var.get().strip()
        if raw == "":
            raise ValueError(f"'{self.key}' cannot be empty")
        try:
            return cast(raw)
        except ValueError:
            raise ValueError(f"'{self.key}' must be a number, got {raw!r}")


def build_form(parent, specs, start_row=0, registry=None):
    """
    specs: list of (key, label, default)
    Returns dict[key] -> LabeledField; optionally records them in `registry`
    (used for settings persistence and Reset-defaults).
    """
    fields = {}
    for i, (key, label, default) in enumerate(specs):
        fields[key] = LabeledField(parent, start_row + i, key, label, default)
    if registry is not None:
        registry.update(fields)
    return fields


class ScrollableFrame(ttk.Frame):
    """Vertically scrollable container; children go into ``self.inner``.

    ONE application-level wheel handler is shared by all instances and
    routes events to the instance under the pointer (repeated bind_all
    calls would otherwise replace each other).
    """

    _wheel_installed = False

    def __init__(self, parent):
        super().__init__(parent, style="Panel.TFrame")

        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0,
                                takefocus=0, background=PANEL_BG)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_yscroll)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.inner = ttk.Frame(self.canvas, style="Panel.TFrame")
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        if not ScrollableFrame._wheel_installed:
            ScrollableFrame._wheel_installed = True
            self.bind_all("<MouseWheel>", ScrollableFrame._dispatch_mousewheel)
            self.bind_all("<Button-4>", ScrollableFrame._dispatch_button4)
            self.bind_all("<Button-5>", ScrollableFrame._dispatch_button5)

    def _on_yscroll(self, *args):
        self.vsb.set(*args)
        lo, hi = float(args[0]), float(args[1])
        if lo <= 0.0 and hi >= 1.0:
            self.vsb.grid_remove()
        else:
            self.vsb.grid()

    def _on_inner_configure(self, event):
        canvas_h = self.canvas.winfo_height()
        if canvas_h > 1 and event.height < canvas_h:
            self.canvas.itemconfig(self._window, height=canvas_h)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(
            self._window,
            width=event.width,
            height=max(event.height, self.inner.winfo_reqheight()),
        )

    def _scroll_units(self, units: int):
        if self.canvas.yview() == (0.0, 1.0):
            return False
        self.canvas.yview_scroll(units, "units")
        return True

    @staticmethod
    def _owner_of(widget):
        while widget is not None:
            if isinstance(widget, ScrollableFrame):
                return widget
            widget = getattr(widget, "master", None)
        return None

    @staticmethod
    def _dispatch_mousewheel(event):
        owner = ScrollableFrame._owner_of(event.widget)
        if owner is None:
            return
        steps = int(-1 * (event.delta / 120)) or (-1 if event.delta < 0 else 1)
        if owner._scroll_units(steps * 3):
            return "break"

    @staticmethod
    def _dispatch_button4(event):
        owner = ScrollableFrame._owner_of(event.widget)
        if owner is not None and owner._scroll_units(-3):
            return "break"

    @staticmethod
    def _dispatch_button5(event):
        owner = ScrollableFrame._owner_of(event.widget)
        if owner is not None and owner._scroll_units(3):
            return "break"


# ---------------------------------------------------------------------------
# Plot helpers (matplotlib embedded in Tk)
# ---------------------------------------------------------------------------
def _spline_xy(xs, ys, samples=300):
    """Smooth cubic spline through (xs, ys); linear fallback w/o scipy."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)

    ux, inv = np.unique(xs, return_inverse=True)
    if ux.size != xs.size:
        uy = np.array([ys[inv == i].mean() for i in range(ux.size)])
    else:
        uy = ys

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


class PlotDialog(tk.Toplevel):
    """Modal dialog: lines+spline or heatmap, matplotlib toolbar, Save PNG."""

    def __init__(self, parent, df, title="Results plot"):
        super().__init__(parent)
        self.title(title)
        self.geometry("880x640")
        self.minsize(520, 380)
        self.configure(bg=BG)
        self.transient(parent)

        self._df = df
        self._can_heat = _grid_columns(df) is not None

        top = ttk.Frame(self, style="Panel.TFrame")
        top.pack(side="top", fill="x", padx=8, pady=8)

        ttk.Label(top, text="Plot style:", style="Panel.TLabel").pack(side="left", padx=(0, 6))
        self._style_var = tk.StringVar(value="Lines + spline")
        values = ["Lines + spline"] + (["Heatmap (grid)"] if self._can_heat else [])
        cb = ttk.Combobox(top, textvariable=self._style_var, state="readonly",
                          width=16, values=values)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._redraw())

        ttk.Button(top, text="Save PNG", style="Secondary.TButton",
                   command=self._save_png).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="Close", style="Accent.TButton",
                   command=self._close).pack(side="right")

        self._fig = Figure(dpi=100, facecolor=PANEL_BG)
        self._canvas = FigureCanvasTkAgg(self._fig, master=self)
        widget = self._canvas.get_tk_widget()
        widget.configure(background=PANEL_BG, highlightthickness=0)

        toolbar_frame = ttk.Frame(self, style="Panel.TFrame")
        toolbar_frame.pack(side="top", fill="x")
        self._mpl_toolbar = NavigationToolbar2Tk(self._canvas, toolbar_frame)
        self._mpl_toolbar.update()

        btn_space = ttk.Frame(self, style="TFrame")
        btn_space.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        widget.pack(fill="both", expand=True, padx=8)

        self._redraw()
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
            self.geometry(f"+{max(px, 0)}+{max(py, 0)}")
        except tk.TclError:
            pass

        self.grab_set()
        self.focus_set()

    def _redraw(self):
        self._fig.clear()
        if self._style_var.get() == "Heatmap (grid)" and self._can_heat:
            build_heatmap(self._fig, self._df)
        else:
            build_results_plot(self._fig, self._df)
        self._canvas.draw()

    def _save_png(self):
        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=[("PNG image", "*.png")])
        if path:
            self._fig.savefig(path, dpi=150)
            messagebox.showinfo("Saved", f"Figure saved to {path}")

    def _close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


# ---------------------------------------------------------------------------
# Results panel
# ---------------------------------------------------------------------------
class ResultsPanel(ttk.Frame):
    """Treeview + scrollbars + CSV export + plot dialog + sorting/copy."""

    def __init__(self, parent):
        super().__init__(parent, style="Panel.TFrame")
        self._df = None
        self._sort_col = None
        self._sort_asc = True
        self._prob_col = None

        toolbar = ttk.Frame(self, style="Panel.TFrame")
        toolbar.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Label(toolbar, text="Results", style="SectionTitle.TLabel").pack(side="left")

        self.export_btn = ttk.Button(toolbar, text="Export CSV", style="Secondary.TButton",
                                     command=self._export_csv, state="disabled")
        self.export_btn.pack(side="right")

        self.plot_btn = ttk.Button(toolbar, text="Plot", style="Secondary.TButton",
                                   command=self._show_plot, state="disabled")
        self.plot_btn.pack(side="right", padx=(0, 6))
        
        self.pdf_btn = ttk.Button(toolbar, text="Export PDF", style="Secondary.TButton",
                                  command=self._export_pdf, state="disabled")
        self.pdf_btn.pack(side="right", padx=(0, 6))
        self.report_meta = None

        self.row_count_label = ttk.Label(toolbar, text="", style="Muted.TLabel")
        self.row_count_label.pack(side="right", padx=(0, 10))
        ToolTip(self.row_count_label, "Tip: click a column header to sort;\nCtrl+C copies selected rows.")

        body = ttk.Frame(self, style="Panel.TFrame")
        body.pack(fill="both", expand=True, padx=10, pady=10)

        self.tree = ttk.Treeview(body, show="headings")
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        # visibility hardening (some Tk builds ignore style-level colors)
        try:
            self.tree.configure(background=PANEL_BG, fieldbackground=PANEL_BG,
                                foreground=TEXT, font=(FONT_FAMILY, TABLE_FONT_SIZE))
            self.tree.configure(selectbackground="#d7e3fc", selectforeground="#0b1b3d")
        except tk.TclError:
            pass

        self.tree.tag_configure("data", foreground=TEXT, background=PANEL_BG,
                                font=(FONT_FAMILY, TABLE_FONT_SIZE))
        self.tree.tag_configure("even", background="#f6f8fb")
        self.tree.tag_configure("low", foreground=ERR_RED)
        self.tree.tag_configure("high", foreground=OK_GREEN)

        self.tree.bind("<Control-c>", lambda _e: self._copy_selection())
        ToolTip(self.tree, "Click header = sort | Ctrl+C = copy selection")

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

    # -- formatting / helpers -------------------------------------------------
    @staticmethod
    def _fmt(v, digits=4):
        try:
            if pd.isna(v):
                return ""
        except Exception:
            pass
        if isinstance(v, (float, np.floating)):
            return f"{v:,.{digits}f}"
        return str(v)

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = ()
        self._df = None
        self._prob_col = None
        self._sort_col = None
        self.export_btn["state"] = "disabled"
        self.plot_btn["state"] = "disabled"
        self.pdf_btn["state"] = "disabled"
        self.row_count_label["text"] = ""

    # -- population -----------------------------------------------------------
    def show_dataframe(self, df: pd.DataFrame):
        self.clear()
        self._df = df

        cols = [str(c) for c in df.columns]
        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=str(c), command=lambda c=c: self._sort_by(c))
            self.tree.column(c, width=110, anchor="center")

        # detect a probability-like column for conditional coloring
        for c in df.columns:
            if any(s in str(c).lower() for s in ("prob", "pass")):
                ser = pd.to_numeric(df[c], errors="coerce").dropna()
                if len(ser) and ser.max() <= 1.0:
                    self._prob_col = c
                    break

        self._populate_rows(df)

        self.export_btn["state"] = "normal"
        can_plot = HAVE_MPL and len(df) >= 2 and df.select_dtypes(include=[np.number]).shape[1] >= 2
        self.plot_btn["state"] = "normal" if can_plot else "disabled"
        self.pdf_btn["state"] = "normal" if HAVE_PDF else "disabled"
        self.row_count_label["text"] = f"{len(df)} rows"

    def _populate_rows(self, df):
        self.tree.delete(*self.tree.get_children())
        for i, (_, row) in enumerate(df.iterrows()):
            vals = [self._fmt(v, 4) for v in row]
            tags = ["data", "even" if i % 2 else "odd"]
            if self._prob_col is not None:
                try:
                    pv = float(row[self._prob_col])
                except Exception:
                    pv = None
                if pv is not None:
                    if pv < 0.8:
                        tags.append("low")
                    elif pv >= 0.9:
                        tags.append("high")
            self.tree.insert("", "end", values=vals, tags=tuple(tags))

    def _sort_by(self, col):
        if self._df is None:
            return
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col, self._sort_asc = col, True
        try:
            df = self._df.sort_values(by=col, ascending=self._sort_asc, kind="mergesort")
        except Exception:
            return
        for c in [str(x) for x in self._df.columns]:
            arrow = ""
            if c == str(col):
                arrow = " \u25b2" if self._sort_asc else " \u25bc"
            self.tree.heading(c, text=c + arrow)
        self._populate_rows(df)

    def _copy_selection(self):
        sel = self.tree.selection()
        if not sel:
            return
        lines = ["\t".join(str(x) for x in self.tree.item(iid, "values")) for iid in sel]
        top = self.winfo_toplevel()
        top.clipboard_clear()
        top.clipboard_append("\n".join(lines))

    # -- single-result view -----------------------------------------------------
    def show_dict(self, d: dict):
        self.clear()
        self._df = pd.DataFrame([d])
        self.tree["columns"] = ("Field", "Value")
        self.tree.heading("Field", text="Field")
        self.tree.heading("Value", text="Value")
        self.tree.column("Field", width=160, anchor="w")
        self.tree.column("Value", width=200, anchor="center")
        for k, v in d.items():
            self.tree.insert("", "end", values=(str(k), self._fmt(v, 6)), tags=("data",))
        self.export_btn["state"] = "normal"
        self.pdf_btn["state"] = "normal" if HAVE_PDF else "disabled"
        self.plot_btn["state"] = "disabled"
        self.row_count_label["text"] = "1 result"

    # -- actions ------------------------------------------------------------------
    def _show_plot(self):
        if not HAVE_MPL:
            messagebox.showerror("Plot unavailable",
                                 "matplotlib is required for plotting.\n"
                                 "Install it with:  pip install matplotlib")
            return
        if self._df is None:
            return
        PlotDialog(self, self._df, title="Results plot")

    def _export_csv(self):
        if self._df is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        self._df.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
        messagebox.showinfo("Exported", f"Saved to {path}")

    def _export_pdf(self):
        if not HAVE_PDF:
            messagebox.showerror("PDF export unavailable",
                                 "reportlab is required.\nInstall it with:  pip install reportlab")
            return
        if self._df is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                            filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        meta = self.report_meta or {"title": ["CuDAL RESULTS"]}
        try:
            write_sas_pdf(path, self._df, meta["title"])
            messagebox.showinfo("Exported", f"Saved to {path}")
        except Exception as exc:
            messagebox.showerror("PDF export failed", str(exc))


# ---------------------------------------------------------------------------
# Base tab
# ---------------------------------------------------------------------------
class BaseTab(ttk.Frame):
    MODES = [("table", "Acceptance limit table"),
             ("evaluate", "Probability of passing"),
             ("sample", "Sample probability")]
    DOMAIN = "CONTENT UNIFORMITY"   # overridden per tab
    PLAN = 1                        # overridden per tab


    def __init__(self, parent, title, subtitle):
        super().__init__(parent, style="TFrame")
        self._task_queue = queue.Queue()
        self._running = False
        self._table_cache = {}
        self.field_registry = {mode: {} for mode, _ in self.MODES}

        header = ttk.Frame(self, style="TFrame")
        header.pack(fill="x", padx=16, pady=(14, 6))
        ttk.Label(header, text=title, style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text=subtitle, style="SubHeader.TLabel").pack(anchor="w")

        body = ttk.Frame(self, style="TFrame")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        controls = ttk.Frame(body, style="Panel.TFrame")
        controls.grid(row=0, column=0, sticky="ns", padx=(0, 14))

        mode_box = ttk.LabelFrame(controls, text="Analysis mode")
        mode_box.pack(fill="x", padx=10, pady=(10, 8))
        self.mode_var = tk.StringVar(value="table")
        for val, label in self.MODES:
            ttk.Radiobutton(mode_box, text=label, value=val, variable=self.mode_var,
                            command=self._switch_mode).pack(anchor="w", padx=8, pady=3)

        self.mode_frames = {}
        self.stack = ScrollableFrame(controls)
        self.stack.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        for val, _ in self.MODES:
            self.mode_frames[val] = ttk.LabelFrame(self.stack.inner, text="Parameters")

        self._build_mode_frames()
        self.mode_frames["table"].pack(fill="both", expand=True)

        run_row = ttk.Frame(controls, style="Panel.TFrame")
        run_row.pack(fill="x", padx=10, pady=(4, 12))
        self.run_btn = ttk.Button(run_row, text="Run", style="Accent.TButton", command=self._on_run)
        self.run_btn.pack(side="left")
        ToolTip(self.run_btn, "Run the selected analysis (Ctrl+R)")
        ttk.Button(run_row, text="Reset", style="Secondary.TButton",
                   command=self._reset_defaults).pack(side="left", padx=(8, 0))
        self.progress = ttk.Progressbar(run_row, mode="determinate", length=120, maximum=100,
                                        style="green.Horizontal.TProgressbar")
        self.progress.pack(side="left", padx=10)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(controls, textvariable=self.status_var, style="Muted.TLabel",
                  wraplength=260, justify="left").pack(fill="x", padx=10, pady=(0, 10))

        self.results = ResultsPanel(body)
        self.results.grid(row=0, column=1, sticky="nsew")

    # -- subclass hooks -----------------------------------------------------
    def _build_mode_frames(self):
        raise NotImplementedError

    def _run_table(self):
        raise NotImplementedError

    def _run_evaluate(self):
        raise NotImplementedError

    def _run_sample(self):
        raise NotImplementedError

    # -- caching helper -------------------------------------------------------
    @staticmethod
    def _cache_key(*args):
        norm = []
        for a in args:
            if isinstance(a, (list, tuple)):
                norm.append(tuple(round(float(x), 12) for x in a))
            else:
                norm.append(a)
        return tuple(norm)

    # -- settings persistence ---------------------------------------------------
    def collect_state(self):
        return {
            "mode": self.mode_var.get(),
            "fields": {mode: {k: f.var.get() for k, f in reg.items()}
                       for mode, reg in self.field_registry.items()},
        }

    def apply_state(self, state):
        if not isinstance(state, dict):
            return
        for mode, reg in self.field_registry.items():
            for k, field in reg.items():
                val = state.get("fields", {}).get(mode, {}).get(k)
                if val is not None:
                    field.var.set(str(val))
        mode = state.get("mode")
        if mode in self.mode_frames:
            self.mode_var.set(mode)
            self._switch_mode()

    def _reset_defaults(self):
        for reg in self.field_registry.values():
            for field in reg.values():
                field.reset()
        self.status_var.set("Parameters reset to defaults.")

    # -- shared plumbing ------------------------------------------------------
    def _switch_mode(self):
        for frame in self.mode_frames.values():
            frame.pack_forget()
        self.mode_frames[self.mode_var.get()].pack(fill="both", expand=True)

    def _on_run(self):
        if self._running:
            return
        job = {"table": self._run_table,
               "evaluate": self._run_evaluate,
               "sample": self._run_sample}[self.mode_var.get()]()

        self._running = True
        self.run_btn["state"] = "disabled"
        self.progress["value"] = 0
        self.status_var.set("Calculating...")

        def worker():
            def report(frac, msg=""):
                self._task_queue.put(("progress", float(frac), str(msg)))
            try:
                result = job(report)
                self._task_queue.put(("ok", result))
            except Exception:  # noqa: BLE001
                self._task_queue.put(("error", traceback.format_exc()))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_queue)

    def _poll_queue(self):
        try:
            payload = self._task_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_queue)
            return

        status = payload[0]
        if status == "progress":
            _, frac, msg = payload
            self.progress["value"] = min(100.0, frac * 100)
            if msg:
                self.status_var.set(msg)
            self.after(100, self._poll_queue)
            return

        self._running = False
        self.run_btn["state"] = "normal"
        if status == "ok":
            self.progress["value"] = 100
            result = payload[1]
            if isinstance(result, pd.DataFrame):
                self.results.show_dataframe(result)
                self.status_var.set(f"Done -- {len(result)} row(s) computed.")
            else:
                self.results.show_dict(result)
                self.status_var.set("Done.")
            self.results.report_meta = self._report_meta()
        else:
            self.progress["value"] = 0
            self.status_var.set("Calculation failed -- see error dialog.")
            messagebox.showerror("Calculation error", payload[1])

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
        n = self._fv("number", "num")
        loc = self._fv("loc")
        target = self._fv("target")
        q = self._fv("q")
        lbound = self._fv("lbound")
        cilevel = self._fv("cilevel")
        lines = []
        if self.PLAN == 1:
            key = f"TARGET = {target:.1f}" if target is not None else f"Q = {q:.1f}"
            lines.append(f"ACCEPTANCE LIMITS FOR {self.DOMAIN}(N= {n:.0f}, {key})")
            lines.append("SAMPLING PLAN 1")
            lines.append(f"(MEETING LIMITS GUARANTEES, WITH {cilevel:.1f}% ASSURANCE, THAT AT LEAST")
            lines.append(f"{lbound:.1f}% OF SAMPLES TESTED FOR {self.DOMAIN} WILL PASS THE USP TEST)")
        else:
            lines.append(f"ACCEPTANCE LIMITS FOR {self.DOMAIN}")
            lines.append("SAMPLING PLAN 2")
            base = f"TARGET={target:.1f}" if target is not None else f"Q={q:.1f}"
            lines.append(f"{base}, LOWER BOUND = {lbound:.1f}, CONFIDENCE LEVEL = {cilevel:.1f}")
            lines.append("TABLE ENTRIES ARE LOWER(LL) AND UPPER(UL) LIMITS ON THE MEAN")
            if n is not None and loc is not None:
                lines.append(f"OF {int(n * loc)} ASSAYS:  {int(n)} ASSAYS AT EACH OF "
                             f"{int(loc)} DIFFERENT LOCATIONS")
            lines.append("SE IS THE POOLED WITHIN LOCATION STANDARD DEVIATION")
            lines.append("STANDARD DEVIATIONS AND MEANS ARE EXPRESSED IN % CLAIM")
        if self.mode_var.get() != "table":
            lines.append(f"MODE: {dict(self.MODES)[self.mode_var.get()].upper()}")
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
    DOMAIN = "CONTENT UNIFORMITY"
    PLAN = 1
    def __init__(self, parent):
        super().__init__(parent, "Content Uniformity -- Sampling Plan 1",
                         "Single composite sample (USP <905>).")

    def _build_mode_frames(self):
        f = self.mode_frames["table"]
        self.table_fields = build_form(f, [
            ("number", "Number of units (N)", 10),
            ("target", "Target / label claim (%)", 100.0),
            ("lbound", "Lower bound (%)", 95.0),
            ("cilevel", "Confidence level (%)", 95.0),
            ("mean_low", "Mean grid low", 85.1),
            ("mean_high", "Mean grid high", 114.9),
            ("mean_step", "Mean grid step", 0.5),
        ], registry=self.field_registry["table"])

        f = self.mode_frames["evaluate"]
        ttk.Label(f, text="Builds the table above, then evaluates:", style="Muted.TLabel",
                  wraplength=230).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.eval_fields = build_form(f, [
            ("u_low", "True mean U -- low", 95.0),
            ("u_high", "True mean U -- high", 105.0),
            ("u_step", "True mean U -- step", 2.5),
            ("cv_low", "True CV(%) -- low", 1.0),
            ("cv_high", "True CV(%) -- high", 4.0),
            ("cv_step", "True CV(%) -- step", 1.0),
        ], start_row=1, registry=self.field_registry["evaluate"])
        for k in ("number", "target", "lbound", "cilevel"):
            self.eval_fields[k] = self.table_fields[k]

        f = self.mode_frames["sample"]
        self.sample_fields = build_form(f, [
            ("mean", "Sample mean (%)", 100.0),
            ("cv", "Sample CV (%)", 2.0),
            ("number", "Number of units (N)", 10),
            ("target", "Target / label claim (%)", 100.0),
            ("lbound", "Lower bound (%)", 95.0),
            ("cilevel", "Confidence level (%)", 95.0),
        ], registry=self.field_registry["sample"])

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
            table = cusp1.acceptance_limit_table(number, target, lbound, cilevel,
                                                 mean_low, mean_high, mean_step)
            self._table_cache[key] = table
            progress(1.0, "Table complete.")
            return table
        return job

    def _run_evaluate(self):
        v = self.table_fields
        number = v["number"].get(int)
        target = v["target"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
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
        mean = v["mean"].get(float)
        cv = v["cv"].get(float)
        number = v["number"].get(int)
        target = v["target"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
        return lambda progress: (progress(0.4, "Computing sample probability..."),
                                 cusp1.sample_probability(mean, cv, number, target, lbound, cilevel))[1]


class Cusp2Tab(BaseTab):
    DOMAIN = "CONTENT UNIFORMITY"
    PLAN = 2
    def __init__(self, parent):
        super().__init__(parent, "Content Uniformity -- Sampling Plan 2",
                         "Multiple locations, within/between-location variance components (USP <905>).")

    def _build_mode_frames(self):
        f = self.mode_frames["table"]
        self.table_fields = build_form(f, [
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

        f = self.mode_frames["evaluate"]
        ttk.Label(f, text="Builds the table above, then evaluates:", style="Muted.TLabel",
                  wraplength=230).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.eval_fields = build_form(f, [
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

        f = self.mode_frames["sample"]
        self.sample_fields = build_form(f, [
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
        num = v["num"].get(int)
        loc = v["loc"].get(int)
        target = v["target"].get(float)
        lbound = v["lbound"].get(float)
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
        mean = v["mean"].get(float)
        se = v["se"].get(float)
        sm = v["sm"].get(float)
        num = v["num"].get(int)
        loc = v["loc"].get(int)
        target = v["target"].get(float)
        cilevel = v["cilevel"].get(float)
        return lambda progress: (progress(0.4, "Computing sample probability..."),
                                 cusp2.sample_probability(mean, se, sm, num, loc, target, cilevel))[1]


class Disp1Tab(BaseTab):
    DOMAIN = "DISSOLUTION"
    PLAN = 1
    def __init__(self, parent):
        super().__init__(parent, "Dissolution -- Sampling Plan 1", "Single location (USP <711>).")

    def _build_mode_frames(self):
        f = self.mode_frames["table"]
        self.table_fields = build_form(f, [
            ("number", "Number of units (N)", 6),
            ("q", "Q value (%)", 80.0),
            ("lbound", "Lower bound (%)", 95.0),
            ("cilevel", "Confidence level (%)", 95.0),
            ("meanadj_step", "Mean grid step", 1.0),
        ], registry=self.field_registry["table"])

        f = self.mode_frames["evaluate"]
        ttk.Label(f, text="Builds the table above, then evaluates:", style="Muted.TLabel",
                  wraplength=230).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.eval_fields = build_form(f, [
            ("u_low", "True mean U -- low", 90.0),
            ("u_high", "True mean U -- high", 100.0),
            ("u_step", "True mean U -- step", 2.5),
            ("cv_low", "True CV(%) -- low", 1.0),
            ("cv_high", "True CV(%) -- high", 4.0),
            ("cv_step", "True CV(%) -- step", 1.0),
        ], start_row=1, registry=self.field_registry["evaluate"])

        f = self.mode_frames["sample"]
        self.sample_fields = build_form(f, [
            ("mean", "Sample mean (%)", 90.0),
            ("cv", "Sample CV (%)", 3.0),
            ("number", "Number of units (N)", 6),
            ("q", "Q value (%)", 80.0),
            ("cilevel", "Confidence level (%)", 95.0),
        ], registry=self.field_registry["sample"])

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
            progress(1.0, "Table complete.")
            return table
        return job

    def _run_evaluate(self):
        v = self.table_fields
        number = v["number"].get(int)
        q = v["q"].get(float)
        lbound = v["lbound"].get(float)
        cilevel = v["cilevel"].get(float)
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
        mean = v["mean"].get(float)
        cv = v["cv"].get(float)
        number = v["number"].get(int)
        q = v["q"].get(float)
        cilevel = v["cilevel"].get(float)
        return lambda progress: (progress(0.4, "Computing sample probability..."),
                                 disp1.sample_probability(mean, cv, number, q, cilevel))[1]


class Disp2Tab(BaseTab):
    DOMAIN = "DISSOLUTION"
    PLAN = 2
    def __init__(self, parent):
        super().__init__(parent, "Dissolution -- Sampling Plan 2",
                         "Multiple locations, within/between-location variance components (USP <711>).")

    def _build_mode_frames(self):
        f = self.mode_frames["table"]
        self.table_fields = build_form(f, [
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

        f = self.mode_frames["evaluate"]
        ttk.Label(f, text="Builds the table above, then evaluates:", style="Muted.TLabel",
                  wraplength=230).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.eval_fields = build_form(f, [
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

        f = self.mode_frames["sample"]
        self.sample_fields = build_form(f, [
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
        num = v["num"].get(int)
        loc = v["loc"].get(int)
        q = v["q"].get(float)
        lbound = v["lbound"].get(float)
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
        mean = v["mean"].get(float)
        se = v["se"].get(float)
        sm = v["sm"].get(float)
        num = v["num"].get(int)
        loc = v["loc"].get(int)
        q = v["q"].get(float)
        cilevel = v["cilevel"].get(float)
        return lambda progress: (progress(0.4, "Computing sample probability..."),
                                 disp2.sample_probability(mean, se, sm, num, loc, q, cilevel))[1]


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------
class CudalApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CuDAL -- Content Uniformity & Dissolution Acceptance Limits")
        self.geometry("1180x720")
        self.minsize(980, 600)
        setup_style(self)

        # ---- logo / window icon ----------------------------------------------
        self._logo_img = None
        logo_file = resource_path("cudal.jpeg")
        if os.path.exists(logo_file):
            try:
                self._logo_img = tk.PhotoImage(file=logo_file)
                self.iconphoto(True, self._logo_img)  # also applies to dialogs (Plot, etc.)
            except tk.TclError:
                self._logo_img = None

        self._settings = self._load_settings()

        # ---- menu bar -------------------------------------------------------
        menubar = tk.Menu(self)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Export current results (CSV)", accelerator="Ctrl+E",
                          command=self._export_current_csv)
        filem.add_command(label="Export all results (XLSX)", command=self._export_all_xlsx)
        filem.add_separator()
        filem.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=filem)
        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="About / Help", accelerator="F1", command=self._show_about)
        menubar.add_cascade(label="Help", menu=helpm)
        self.config(menu=menubar)

        # ---- header ---------------------------------------------------------
        top = ttk.Frame(self, style="TFrame")
        top.pack(fill="x", padx=18, pady=(14, 0))
        if self._logo_img is not None:
            try:  # keep the header compact if the PNG is large
                h = self._logo_img.height()
                if h > 48:
                    self._logo_img = self._logo_img.subsample(max(1, h // 48))
            except tk.TclError:
                pass
            ttk.Label(top, image=self._logo_img).pack(side="left", padx=(0, 10))
        ttk.Label(top, text="CuDAL", style="Header.TLabel").pack(side="left")

        ttk.Label(top, text="   Parametric acceptance limits for USP <905> Content Uniformity "
                             "and USP <711> Dissolution", style="SubHeader.TLabel").pack(side="left")

        # ---- tabs -----------------------------------------------------------
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=14)
        self.tabs = [Cusp1Tab(self.notebook), Cusp2Tab(self.notebook),
                     Disp1Tab(self.notebook), Disp2Tab(self.notebook)]
        for tab, text in zip(self.tabs,
                             ["  Content Uniformity -- Plan 1  ", "  Content Uniformity -- Plan 2  ",
                              "  Dissolution -- Plan 1  ", "  Dissolution -- Plan 2  "]):
            self.notebook.add(tab, text=text)

        self.status_bar = ttk.Label(self, text=f"Ready. (Tk {tk.TkVersion})",
                                    style="Status.TLabel", anchor="w")
        self.status_bar.pack(fill="x", side="bottom", padx=14, pady=(0, 8))

        # ---- restore persisted state -----------------------------------------
        for tab in self.tabs:
            tab.apply_state(self._settings.get("tabs", {}).get(tab.__class__.__name__))
        try:
            idx = int(self._settings.get("tab_index", 0))
            self.notebook.select(self.notebook.tabs()[max(0, min(idx, 3))])
        except Exception:
            pass
        geom = self._settings.get("geometry")
        if geom:
            try:
                self.geometry(geom)
            except tk.TclError:
                pass

        # ---- global shortcuts -------------------------------------------------
        self.bind("<Control-r>", lambda _e: self._current_tab()._on_run())
        self.bind("<Control-e>", lambda _e: self._export_current_csv())
        self.bind("<Control-p>", lambda _e: self._current_tab().results._show_plot())
        self.bind("<F1>", lambda _e: self._show_about())

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- helpers -----------------------------------------------------------------
    def _current_tab(self):
        return self.nametowidget(self.notebook.select())

    @staticmethod
    def _load_settings():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _save_settings(self):
        data = {
            "geometry": self.geometry(),
            "tab_index": self.notebook.index(self.notebook.select()),
            "tabs": {tab.__class__.__name__: tab.collect_state() for tab in self.tabs},
        }
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception:
            pass

    def _on_close(self):
        self._save_settings()
        self.destroy()

    # -- menu actions ---------------------------------------------------------
    def _export_current_csv(self):
        self._current_tab().results._export_csv()

    def _export_all_xlsx(self):
        if not HAVE_XLSX:
            messagebox.showerror("Excel export unavailable",
                                 "openpyxl is required.\nInstall it with:  pip install openpyxl")
            return
        sheets = {tab.__class__.__name__: tab.results._df
                  for tab in self.tabs if tab.results._df is not None}
        if not sheets:
            messagebox.showinfo("Nothing to export", "Run at least one analysis first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for name, df in sheets.items():
                df.to_excel(writer, sheet_name=name[:31], index=False)
        messagebox.showinfo("Exported", f"Saved {len(sheets)} sheet(s) to {path}")

    def _show_about(self):
        deps = (f"matplotlib: {'yes' if HAVE_MPL else 'no'}\n"
                f"scipy splines: {'yes' if HAVE_SPLINE else 'no'}\n"
                f"openpyxl (xlsx): {'yes' if HAVE_XLSX else 'no'}")
        messagebox.showinfo(
            "About CuDAL",
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
            f"Optional dependencies:\n{deps}\n\nTk version: {tk.TkVersion}")


# ---------------------------------------------------------------------------
# Self-test (tiny unit tests for the pure helpers)
# ---------------------------------------------------------------------------
def run_selftest():
    assert make_grid(1.0, 2.0, 0.5, "x") == [1.0, 1.5, 2.0]
    try:
        make_grid(2.0, 1.0, 1.0, "x")
        raise AssertionError("make_grid should reject high < low")
    except ValueError:
        pass
    assert ResultsPanel._fmt(1234.56789) == "1,234.5679"
    assert ResultsPanel._fmt("abc") == "abc"
    xx, yy = _spline_xy([1, 2, 3, 4], [1, 4, 9, 16])
    assert len(xx) == len(yy) == 300
    print("selftest OK")


def main():
    if "--selftest" in sys.argv:
        run_selftest()
        return

    try:  # Windows: render at native DPI (sharper fonts)
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    if not HAVE_CUDAL:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Missing dependency",
            "The `cudal` package could not be imported.\n"
            "Put cudal_gui.py next to the `cudal` package folder\n"
            "or install it, then restart the GUI.")
        sys.exit(1)

    app = CudalApp()
    app.mainloop()


if __name__ == "__main__":
    main()