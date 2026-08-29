"""
cudal.cli

Command-line front end for the `cudal` package, mirroring the original
SAS/AF application (CuDAL.sas):

Test type    : Content Uniformity (CUSP) | Dissolution (DISP)
Sampling plan: 1 (single location) | 2 (multiple locations)
Analysis     : table   (A1) acceptance-limit table
               evaluate (A2) probability-of-passing evaluation
               sample  (A3) probability for an observed sample

Usage
-----
# interactive (SAS-style) menu -- same prompts/defaults as before:
python -m cudal.cli

# non-interactive subcommands (same defaults, overridable via options):
python -m cudal.cli cusp1                       # CU Plan 1 acceptance table
python -m cudal.cli cusp1 -m evaluate -o ev.csv # probability of passing + CSV
python -m cudal.cli disp2 -m sample --mean 90 --se 2.2 --sm 2.46
python -m cudal.cli cusp2 --num 6 --loc 10 --se-high 4 --sm-high 4

Run with:  python -m cudal.cli
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from . import cusp1, cusp2, disp1, disp2

pd.set_option("display.width", 120)
pd.set_option("display.float_format", lambda v: f"{v:,.4f}")

_MODE_ALIASES = {
    "1": "table",
    "a1": "table",
    "table": "table",
    "2": "evaluate",
    "a2": "evaluate",
    "evaluate": "evaluate",
    "3": "sample",
    "a3": "sample",
    "sample": "sample",
}


def _mode(text: str) -> str:
    key = str(text).strip().lower()
    if key not in _MODE_ALIASES:
        raise argparse.ArgumentTypeError(
            f"invalid mode {text!r} (use table/evaluate/sample or 1/2/3)"
        )
    return _MODE_ALIASES[key]


def grid(low: float, high: float, step: float, div: float = 1.0):
    """Inclusive low..high grid with `step`, optionally divided by `div`."""
    if step <= 0:
        raise ValueError("grid step must be positive")
    if high < low:
        raise ValueError("grid high must be >= grid low")
    n = int(round((high - low) / step)) + 1
    return [(low + i * step) / div for i in range(n)]


# ---------------------------------------------------------------------------
# scenario runners (one source of truth for the math; used by CLI + interactive)
# ---------------------------------------------------------------------------
def run_cusp1(a):
    if a.mode in ("table", "evaluate"):
        if None not in (a.mean_low, a.mean_high, a.mean_step):
            table = cusp1.acceptance_limit_table(
                a.number, a.target, a.lbound, a.cilevel, a.mean_low, a.mean_high, a.mean_step
            )
        else:
            table = cusp1.acceptance_limit_table(a.number, a.target, a.lbound, a.cilevel)
        if a.mode == "table":
            return table
        u_vals = grid(a.u_low, a.u_high, a.u_step)
        cv_vals = grid(a.cv_low, a.cv_high, a.cv_step)
        return cusp1.probability_of_passing(table, a.number, u_vals, cv_vals)
    return cusp1.sample_probability(a.mean, a.cv, a.number, a.target, a.lbound, a.cilevel)


def run_cusp2(a):
    se_vals = grid(a.se_low, a.se_high, a.se_step)
    sm_vals = grid(a.sm_low, a.sm_high, a.sm_step)
    if a.mode in ("table", "evaluate"):
        table = cusp2.acceptance_limit_table(
            a.num, a.loc, a.target, a.lbound, a.cilevel, se_vals, sm_vals
        )
        if a.mode == "table":
            return table
        u_vals = grid(a.u_low, a.u_high, a.u_step)
        sigse_vals = grid(a.sigse_low, a.sigse_high, a.sigse_step)
        sigsm_vals = grid(a.sigsm_low, a.sigsm_high, a.sigsm_step)
        return cusp2.probability_of_passing(
            table, a.num, a.loc, a.d1, u_vals, sigse_vals, sigsm_vals
        )
    return cusp2.sample_probability(a.mean, a.se, a.sm, a.num, a.loc, a.target, a.cilevel)


def run_disp1(a):
    if a.mode in ("table", "evaluate"):
        table = disp1.acceptance_limit_table(a.number, a.q, a.lbound, a.cilevel)
        if a.mode == "table":
            return table
        u_vals = grid(a.u_low, a.u_high, a.u_step)
        cv_vals = grid(a.cv_low, a.cv_high, a.cv_step)
        return disp1.probability_of_passing(table, a.number, u_vals, cv_vals)
    return disp1.sample_probability(a.mean, a.cv, a.number, a.q, a.cilevel)


def run_disp2(a):
    se_vals = grid(a.se_low, a.se_high, a.se_step)
    sm_vals = grid(a.sm_low, a.sm_high, a.sm_step)
    if a.mode in ("table", "evaluate"):
        table = disp2.acceptance_limit_table(
            a.num, a.loc, a.q, a.lbound, a.cilevel, se_vals, sm_vals
        )
        if a.mode == "table":
            return table
        u_vals = grid(a.u_low, a.u_high, a.u_step)
        sigse_vals = grid(a.sigse_low, a.sigse_high, a.sigse_step)
        sigsm_vals = grid(a.sigsm_low, a.sigsm_high, a.sigsm_step)
        return disp2.probability_of_passing(
            table, a.num, a.loc, a.dse, a.dsm, u_vals, sigse_vals, sigsm_vals
        )
    return disp2.sample_probability(a.mean, a.se, a.sm, a.num, a.loc, a.q, a.cilevel)


# ---------------------------------------------------------------------------
# argument parser
# ---------------------------------------------------------------------------
def _add_common(p):
    p.add_argument(
        "-m",
        "--mode",
        type=_mode,
        default="table",
        metavar="{table,evaluate,sample|1,2,3}",
        help="Mode (1=table, 2=evaluate, 3=sample) [default: table]",
    )
    p.add_argument("-o", "--output", metavar="CSV", help="also write the result to this CSV file")


def _add_u_grid(p, low=95.0, high=100.0, step=5.0):
    p.add_argument("--u-low", type=float, default=low, help="true mean U grid low [%(default)s]")
    p.add_argument("--u-high", type=float, default=high, help="true mean U grid high [%(default)s]")
    p.add_argument("--u-step", type=float, default=step, help="true mean U grid step [%(default)s]")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cudal",
        description="CuDAL -- Content Uniformity and Dissolution Acceptance Limits "
        "(USP <905> / <711>, mirrors the SAS CALCUSPx/CALDISPx/EV*/SMP* programs).",
        epilog="Run without a subcommand to use the interactive menu. "
        "Examples:  cudal cusp1 | cudal disp2 -m evaluate -o ev.csv | "
        "cudal cusp2 --num 6 --loc 10",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {getattr(__import__('cudal'), '__version__', '1.0.0')}",
    )

    sub = parser.add_subparsers(dest="command", metavar="SCENARIO")
    registry = {}

    # ---------------- Content Uniformity, Plan 1 ----------------
    p = sub.add_parser(
        "cusp1",
        help="Content Uniformity, Sampling Plan 1",
        description="Single composite sample (USP <905>).",
    )
    _add_common(p)
    p.add_argument("--number", type=int, default=10, help="number of units (N) [%(default)s]")
    p.add_argument("--target", type=float, default=100.0, help="target / label claim [%(default)s]")
    p.add_argument("--lbound", type=float, default=95.0, help="lower bound (%%) [%(default)s]")
    p.add_argument(
        "--cilevel", type=float, default=95.0, help="confidence level (%%) [%(default)s]"
    )
    p.add_argument(
        "--mean-low", type=float, default=None, help="optional mean grid low (table mode)"
    )
    p.add_argument(
        "--mean-high", type=float, default=None, help="optional mean grid high (table mode)"
    )
    p.add_argument(
        "--mean-step", type=float, default=None, help="optional mean grid step (table mode)"
    )
    _add_u_grid(p)
    p.add_argument("--cv-low", type=float, default=1.0, help="true CV grid low [%(default)s]")
    p.add_argument("--cv-high", type=float, default=4.0, help="true CV grid high [%(default)s]")
    p.add_argument("--cv-step", type=float, default=3.0, help="true CV grid step [%(default)s]")
    p.add_argument(
        "--mean", type=float, default=100.0, help="sample mode: sample mean [%(default)s]"
    )
    p.add_argument(
        "--cv", type=float, default=4.0, help="sample mode: sample CV (%%) [%(default)s]"
    )
    p.set_defaults(func=run_cusp1, title="Content Uniformity, Sampling Plan 1")
    registry["cusp1"] = p

    # ---------------- Content Uniformity, Plan 2 ----------------
    p = sub.add_parser(
        "cusp2",
        help="Content Uniformity, Sampling Plan 2",
        description="Multiple locations (USP <905>).",
    )
    _add_common(p)
    p.add_argument("--num", type=int, default=10, help="units per location [%(default)s]")
    p.add_argument("--loc", type=int, default=3, help="number of locations [%(default)s]")
    p.add_argument("--target", type=float, default=100.0, help="target / label claim [%(default)s]")
    p.add_argument("--lbound", type=float, default=95.0, help="lower bound (%%) [%(default)s]")
    p.add_argument(
        "--cilevel", type=float, default=95.0, help="confidence level (%%) [%(default)s]"
    )
    p.add_argument("--se-low", type=float, default=0.1, help="within-loc SD grid low [%(default)s]")
    p.add_argument(
        "--se-high", type=float, default=9.2, help="within-loc SD grid high [%(default)s]"
    )
    p.add_argument(
        "--se-step", type=float, default=0.1, help="within-loc SD grid step [%(default)s]"
    )
    p.add_argument(
        "--sm-low", type=float, default=0.1, help="between-loc SD grid low [%(default)s]"
    )
    p.add_argument(
        "--sm-high", type=float, default=9.2, help="between-loc SD grid high [%(default)s]"
    )
    p.add_argument(
        "--sm-step", type=float, default=0.1, help="between-loc SD grid step [%(default)s]"
    )
    _add_u_grid(p)
    p.add_argument(
        "--sigse-low", type=float, default=2.2, help="true within-loc SD grid low [%(default)s]"
    )
    p.add_argument(
        "--sigse-high", type=float, default=2.2, help="true within-loc SD grid high [%(default)s]"
    )
    p.add_argument(
        "--sigse-step", type=float, default=1.0, help="true within-loc SD grid step [%(default)s]"
    )
    p.add_argument(
        "--sigsm-low", type=float, default=2.2, help="true between-loc SD grid low [%(default)s]"
    )
    p.add_argument(
        "--sigsm-high", type=float, default=2.2, help="true between-loc SD grid high [%(default)s]"
    )
    p.add_argument(
        "--sigsm-step", type=float, default=1.0, help="true between-loc SD grid step [%(default)s]"
    )
    p.add_argument(
        "--d1", type=float, default=0.1, help="SE grid step passed to evaluation [%(default)s]"
    )
    p.add_argument(
        "--mean", type=float, default=100.0, help="sample mode: sample mean [%(default)s]"
    )
    p.add_argument("--se", type=float, default=2.2, help="sample mode: within-loc SD [%(default)s]")
    p.add_argument(
        "--sm", type=float, default=2.46, help="sample mode: between-loc SD [%(default)s]"
    )
    p.set_defaults(func=run_cusp2, title="Content Uniformity, Sampling Plan 2")
    registry["cusp2"] = p

    # ---------------- Dissolution, Plan 1 ----------------
    p = sub.add_parser(
        "disp1", help="Dissolution, Sampling Plan 1", description="Single location (USP <711>)."
    )
    _add_common(p)
    p.add_argument("--number", type=int, default=6, help="number of units (N) [%(default)s]")
    p.add_argument("--q", type=float, default=80.0, help="Q value [%(default)s]")
    p.add_argument("--lbound", type=float, default=95.0, help="lower bound (%%) [%(default)s]")
    p.add_argument(
        "--cilevel", type=float, default=95.0, help="confidence level (%%) [%(default)s]"
    )
    _add_u_grid(p)
    p.add_argument("--cv-low", type=float, default=1.0, help="true CV grid low [%(default)s]")
    p.add_argument("--cv-high", type=float, default=4.0, help="true CV grid high [%(default)s]")
    p.add_argument("--cv-step", type=float, default=3.0, help="true CV grid step [%(default)s]")
    p.add_argument(
        "--mean", type=float, default=90.0, help="sample mode: sample mean [%(default)s]"
    )
    p.add_argument(
        "--cv", type=float, default=4.0, help="sample mode: sample CV (%%) [%(default)s]"
    )
    p.set_defaults(func=run_disp1, title="Dissolution, Sampling Plan 1")
    registry["disp1"] = p

    # ---------------- Dissolution, Plan 2 ----------------
    p = sub.add_parser(
        "disp2", help="Dissolution, Sampling Plan 2", description="Multiple locations (USP <711>)."
    )
    _add_common(p)
    p.add_argument("--num", type=int, default=6, help="units per location [%(default)s]")
    p.add_argument("--loc", type=int, default=5, help="number of locations [%(default)s]")
    p.add_argument("--q", type=float, default=80.0, help="Q value [%(default)s]")
    p.add_argument("--lbound", type=float, default=95.0, help="lower bound (%%) [%(default)s]")
    p.add_argument(
        "--cilevel", type=float, default=95.0, help="confidence level (%%) [%(default)s]"
    )
    p.add_argument("--se-low", type=float, default=2.2, help="within-loc SD grid low [%(default)s]")
    p.add_argument(
        "--se-high", type=float, default=60.0, help="within-loc SD grid high [%(default)s]"
    )
    p.add_argument(
        "--se-step", type=float, default=2.2, help="within-loc SD grid step [%(default)s]"
    )
    p.add_argument(
        "--sm-low", type=float, default=2.2, help="between-loc SD grid low [%(default)s]"
    )
    p.add_argument(
        "--sm-high", type=float, default=60.0, help="between-loc SD grid high [%(default)s]"
    )
    p.add_argument(
        "--sm-step", type=float, default=2.2, help="between-loc SD grid step [%(default)s]"
    )
    _add_u_grid(p)
    p.add_argument(
        "--sigse-low", type=float, default=2.2, help="true within-loc SD grid low [%(default)s]"
    )
    p.add_argument(
        "--sigse-high", type=float, default=2.2, help="true within-loc SD grid high [%(default)s]"
    )
    p.add_argument(
        "--sigse-step", type=float, default=1.0, help="true within-loc SD grid step [%(default)s]"
    )
    p.add_argument(
        "--sigsm-low", type=float, default=2.2, help="true between-loc SD grid low [%(default)s]"
    )
    p.add_argument(
        "--sigsm-high", type=float, default=2.2, help="true between-loc SD grid high [%(default)s]"
    )
    p.add_argument(
        "--sigsm-step", type=float, default=1.0, help="true between-loc SD grid step [%(default)s]"
    )
    p.add_argument(
        "--dse", type=float, default=2.2, help="SE grid step passed to evaluation [%(default)s]"
    )
    p.add_argument(
        "--dsm", type=float, default=2.2, help="SM grid step passed to evaluation [%(default)s]"
    )
    p.add_argument(
        "--mean", type=float, default=90.0, help="sample mode: sample mean [%(default)s]"
    )
    p.add_argument("--se", type=float, default=2.2, help="sample mode: within-loc SD [%(default)s]")
    p.add_argument(
        "--sm", type=float, default=2.46, help="sample mode: between-loc SD [%(default)s]"
    )
    p.set_defaults(func=run_disp2, title="Dissolution, Sampling Plan 2")
    registry["disp2"] = p

    return parser, registry


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------
def _emit(result, args, title):
    print(f"\n--- {title} ---")
    if isinstance(result, pd.DataFrame):
        print(result.to_string(index=False))
        if getattr(args, "output", None):
            result.to_csv(args.output, index=False)
            print(f"\nSaved CSV -> {args.output}")
    elif isinstance(result, dict):
        for k, v in result.items():
            print(f"{k}: {v}")
        if getattr(args, "output", None):
            pd.DataFrame([result]).to_csv(args.output, index=False)
            print(f"\nSaved CSV -> {args.output}")
    else:
        print(result)
        if getattr(args, "output", None):
            pd.DataFrame([{"result": result}]).to_csv(args.output, index=False)
            print(f"\nSaved CSV -> {args.output}")


# ---------------------------------------------------------------------------
# interactive fallback (same prompts/defaults as the original SAS-style menu)
# ---------------------------------------------------------------------------
def _ask(prompt: str, cast=float, default=None):
    suffix = f" [{default}]" if default is not None else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    if raw == "" and default is not None:
        return default
    return cast(raw)


def _fill_interactively(subparser):
    """Prompt for every option of the chosen subparser, using its defaults."""
    ns = argparse.Namespace()
    # Preserve the runner function and title from the subparser defaults
    ns.func = subparser.get_default("func")
    ns.title = subparser.get_default("title")

    for action in subparser._actions:
        if action.dest in ("help",) or isinstance(action, argparse._HelpAction):
            continue
        default = action.default
        # Extract a clean label from the help text (strips the "[default: ...]" suffix)
        help_text = action.help or action.dest
        label = help_text.split("[")[0].strip()
        cast = action.type or str

        while True:
            raw = input(f"{label} [{default}]: ").strip()
            if raw == "":
                setattr(ns, action.dest, default)
                break
            try:
                setattr(ns, action.dest, cast(raw))
                break
            except (ValueError, argparse.ArgumentTypeError) as exc:
                print(f"  invalid value: {exc}")
    return ns


def interactive(registry):
    print("CuDAL -- Content Uniformity and Dissolution Acceptance Limits")
    test = _ask("Test type (1=Content Uniformity, 2=Dissolution)", int, 1)
    plan = _ask("Sampling plan (1=single location, 2=multiple locations)", int, 1)
    name = {(1, 1): "cusp1", (1, 2): "cusp2", (2, 1): "disp1", (2, 2): "disp2"}.get((test, plan))
    if name is None:
        print("Invalid selection.")
        return 1
    args = _fill_interactively(registry[name])
    try:
        result = args.func(args)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    _emit(result, args, args.title)
    return 0


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def main(argv=None):
    parser, registry = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        return interactive(registry) or 0

    try:
        # Check if 'func' exists in the namespace
        if hasattr(args, "func"):
            args.func(args)
        else:
            parser.print_help()  # Show help if no subcommand was provided
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    _emit(result, args, args.title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
