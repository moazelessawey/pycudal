"""
cudal.core
==========

Shared statistical building blocks for the CuDAL (Content Uniformity and
Dissolution Acceptance Limits) system, translated from the original SAS
macros (CuDAL.sas, cusp1.sas, Cusp2.sas, Disp1.sas, Disp2.sas).

SAS -> Python function mapping
-------------------------------
    PROBNORM(x)        -> norm.cdf(x)
    PROBIT(p)          -> norm.ppf(p)
    PROBCHI(x, df)     -> chi2.cdf(x, df)
    CINV(p, df)        -> chi2.ppf(p, df)

Two probability "cores" appear repeatedly in the SAS code, always with the
exact same formulas (only the values fed into them differ):

  * ``c1calc`` (cusp1.sas) / ``cullu`` + ``cuulu`` (Cusp2.sas)
    -> :func:`content_uniformity_bound` here.
  * ``COMPUTE`` (Disp1.sas / Disp2.sas -- byte-for-byte identical formula
    in both files)
    -> :func:`dissolution_bound` here.

Both are implemented as **numpy ufunc-style, broadcastable** functions:
``mu``/``sigma`` (or ``llu``/``sigma``) may be scalars, or arrays of any
mutually-broadcastable shape, and the result has the broadcast shape.
This lets every acceptance-limit search evaluate an entire grid (e.g. all
300 rows of a MEAN table, or an 80x80 SE/SM grid) in a handful of numpy
calls instead of one Python-level call per grid point.

Performance notes
------------------
This module deliberately avoids two patterns that make the equivalent
SAS code (and a naive line-by-line port of it) slow:

1. **Per-point root finding.** The SAS code steps a candidate value
   (a standard deviation, or a mean) in tiny fixed increments, one
   value at a time, until a probability threshold is crossed. Doing
   this with a Python ``for`` loop -- even calling a fast vectorized
   probability function inside it -- pays the interpreter-loop
   overhead once per grid point. :func:`batched_root_find` instead
   solves *all* grid points' roots simultaneously with a vectorized
   bisection: every iteration is a single numpy expression over the
   whole grid, not a Python loop over the grid.

2. **Scalar broadcasting.** :func:`content_uniformity_bound` and
   :func:`dissolution_bound` accept arrays directly, so a table with
   ``M`` mean values, or a grid with ``G = len(SE) * len(SM)`` cells,
   is evaluated as one ``M``- or ``G``-length numpy computation rather
   than ``M`` (or ``G``) separate scalar calls.

Together, building e.g. the CUSP2 acceptance-limit table for an 80x80
SE/SM grid drops from tens of thousands of scalar probability
evaluations to a few dozen vectorized ones.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy.special import gammainc, gammaincinv, ndtr, ndtri

__all__ = [
    "acid_stage_bound",
    "batched_root_find",
    "batched_two_sided_bounds",
    "cinv",
    "content_uniformity_bound",
    "delayed_release_bound",
    "dissolution_bound",
    "extended_release_bound",
    "probchi",
    "probit",
    "probnorm",
    "sas_do_range",
]


# ---------------------------------------------------------------------------
# Direct SAS function equivalents (already numpy ufuncs -> broadcast for free)
# ---------------------------------------------------------------------------


def probnorm(x):
    """
    SAS PROBNORM(x): standard normal CDF.

    Implemented directly via ``scipy.special.ndtr`` rather than
    ``scipy.stats.norm.cdf`` -- numerically identical, but avoids the
    ~5-7x overhead of the generic frozen-distribution machinery, which
    matters a lot here since this is called on arrays with millions of
    elements during the acceptance-limit table searches.
    """
    return ndtr(x)


def probit(p):
    """SAS PROBIT(p): standard normal inverse CDF (quantile function)."""
    return ndtri(p)


def probchi(x, df):
    """
    SAS PROBCHI(x, df): chi-square CDF with `df` degrees of freedom.

    Implemented via the regularized lower incomplete gamma function
    (``chi2.cdf(x, df) == gammainc(df/2, x/2)``) rather than
    ``scipy.stats.chi2.cdf`` -- numerically identical, ~2.5x faster.
    """
    return gammainc(df / 2.0, x / 2.0)


def cinv(p, df):
    """
    SAS CINV(p, df): chi-square inverse CDF (quantile function).

    ``chi2.ppf(p, df) == 2 * gammaincinv(df/2, p)``.
    """
    return 2.0 * gammaincinv(df / 2.0, p)


def sas_do_range(start: float, stop: float, step: float) -> np.ndarray:
    """
    Reproduce the index values visited by a SAS ``DO start TO stop BY step;``
    loop (inclusive of `stop`, subject to floating point rounding the same
    way SAS handles it in practice for these fixed step sizes).
    """
    if step == 0:
        raise ValueError("step must be non-zero")
    n = int(round((stop - start) / step)) + 1
    if n <= 0:
        return np.array([])
    return start + step * np.arange(n)


# ---------------------------------------------------------------------------
# Content uniformity core  (c1calc / cullu / cuulu in the SAS source)
# ---------------------------------------------------------------------------


def _cu_stage_prob(mu: np.ndarray, sigma: np.ndarray, E, n: int, k: float) -> np.ndarray:
    """
    One "stage" of the content-uniformity probability calculation
    (n=10, k=2.4 for stage 1; n=30, k=2.0 for stage 2), reproducing the
    int1/int2/int3 (or iint1/iint2/iint3) block of the SAS macro exactly.

    ``mu``, ``sigma`` and ``E`` may be scalars or arrays of a common
    broadcast shape; the result has that broadcast shape.
    """
    h = 0.05
    L1 = 15.0

    mu = np.asarray(mu, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    E = np.asarray(E, dtype=float)

    z1 = (E - mu) * np.sqrt(n) / sigma
    z2 = (98.5 - mu) * np.sqrt(n) / sigma
    chi_a = probchi((n - 1) * L1**2 / (k * sigma) ** 2, n - 1)
    int1 = (probnorm(z1) - probnorm(z2)) * chi_a

    # Broadcast the fixed integration grid against mu/sigma/E by adding a
    # trailing axis to the (broadcast) parameter arrays and summing over it.
    mu_e, sigma_e, E_e = np.broadcast_arrays(mu, sigma, E)
    mu_e = mu_e[..., None]
    sigma_e = sigma_e[..., None]
    E_e = E_e[..., None]

    # int2 : do x = E to (E + 15 - h) by h;   (E varies per element, so we
    # build the grid relative to E_e directly rather than via sas_do_range)
    n_steps = int(round(15 / h))  # number of h-steps spanning the 15-unit window
    j = np.arange(n_steps)  # 0 .. n_steps-1
    xs = E_e + j * h
    x1 = (xs - mu_e) * np.sqrt(n) / sigma_e
    x2 = (xs + h - mu_e) * np.sqrt(n) / sigma_e
    chi_args = (n - 1) * (E_e + 15 - xs - h / 2) ** 2 / (k * sigma_e) ** 2
    int2 = np.sum((probnorm(x2) - probnorm(x1)) * probchi(chi_args, n - 1), axis=-1)

    # int3 : do x = (98.5 - 15) to (98.5 - h) by h;   (fixed grid, no E dependence)
    xs3 = sas_do_range(98.5 - 15, 98.5 - h, h)
    x1b = (xs3 - mu_e) * np.sqrt(n) / sigma_e
    x2b = (xs3 + h - mu_e) * np.sqrt(n) / sigma_e
    chi_args3 = (n - 1) * (15 - 98.5 + xs3 + h / 2) ** 2 / (k * sigma_e) ** 2
    int3 = np.sum((probnorm(x2b) - probnorm(x1b)) * probchi(chi_args3, n - 1), axis=-1)

    return int1 + int2 + int3


def content_uniformity_bound(mu, sigma, target):
    """
    Replicates the ``c1calc`` / ``cullu`` / ``cuulu`` SAS macro.

    Estimated probability that a batch with true (population) mean ``mu``
    and true standard deviation ``sigma`` passes the USP <905> Content
    Uniformity test, for a label claim / target of ``target`` (%).

    Fully broadcastable: ``mu``, ``sigma``, ``target`` may be Python
    scalars or numpy arrays of a common broadcast shape (e.g. evaluate an
    entire table of candidate means in one call). The return value has
    that broadcast shape (a plain float is returned for scalar inputs).

    Parameters
    ----------
    mu : float or array_like
        True population mean (% of label claim), e.g. LLU or ULU.
    sigma : float or array_like
        True population standard deviation (% of label claim).
    target : float or array_like
        Target / label claim value used by the USP test (usually 100).

    Returns
    -------
    float or numpy.ndarray
        The "OVERBD" value: max(P1, P2), where P1 is the stage-1 (n=10)
        pass probability and P2 combines stage-2 (n=30) with an
        additional 30-unit compound tail term.
    """
    mu = np.asarray(mu, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    target = np.asarray(target, dtype=float)
    E = np.where(target <= 101.5, 101.5, target)

    # ---- stage 1 (n=10, k=2.4) -> P1 -------------------------------------
    P1 = _cu_stage_prob(mu, sigma, E, n=10, k=2.4)

    # ---- stage 2 (n=30, k=2.0) -> P2a + tail term P2b --------------------
    P2a = _cu_stage_prob(mu, sigma, E, n=30, k=2.0)

    zzz1 = (123.125 - mu) / sigma
    zzz2 = np.where(target <= 101.5, (101.5 - 24.625 - mu) / sigma, (target - 24.625 - mu) / sigma)
    P2b = (probnorm(zzz1) - probnorm(zzz2)) ** 30
    P2 = np.maximum(0.0, P2a + P2b - 1)

    result = np.maximum(P1, P2)
    return result if result.ndim else result.item()


# ---------------------------------------------------------------------------
# Dissolution core (COMPUTE macro in Disp1.sas / Disp2.sas -- identical)
# ---------------------------------------------------------------------------


def _dissolution_stage_probs(llu, sigma):
    """
    Internal helper returning the three individual USP <711> stage
    probabilities (F1, F2, F3) rather than their max. Factored out of
    :func:`dissolution_bound` so that :func:`delayed_release_bound` can
    reuse the exact same Buffer-Stage formulas (Acceptance Table 4 is
    structurally identical to Acceptance Table 1) on a per-level basis.
    """
    llu = np.asarray(llu, dtype=float)
    sigma = np.asarray(sigma, dtype=float)

    F1 = (1 - probnorm((5 - llu) / sigma)) ** 6

    sn2 = np.sqrt(12)
    pm2 = probnorm(sn2 * (-llu) / sigma)
    pb2 = 1 - probnorm((-15 - llu) / sigma)
    F2 = pb2**12 - pm2

    sn3 = np.sqrt(24)
    pm3 = probnorm(sn3 * (-llu) / sigma)
    p2 = probnorm((-15 - llu) / sigma) - probnorm((-25 - llu) / sigma)
    p3 = 1 - probnorm((-15 - llu) / sigma)
    F3 = p3**24 + 24 * p2 * p3**23 + 276 * p2**2 * p3**22 - pm3

    return F1, F2, F3


def dissolution_bound(llu, sigma):
    """
    Replicates the ``COMPUTE`` SAS macro (identical in Disp1.sas and
    Disp2.sas).

    Estimated probability of passing the USP <711> Dissolution test
    (stage 1: n=6, stage 2: n=12, stage 3: n=24), given a lower adjusted
    bound on the population mean (``llu``) and population standard
    deviation ``sigma``. Fully broadcastable, like
    :func:`content_uniformity_bound`.

    Returns
    -------
    float or numpy.ndarray
        The "OVERBD" value: max(F1, F2, F3) across the three USP <711>
        stages.
    """
    F1, F2, F3 = _dissolution_stage_probs(llu, sigma)
    result = np.maximum(np.maximum(F1, F2), F3)
    return result if result.ndim else result.item()


# ---------------------------------------------------------------------------
# Extended-release / delayed-release dissolution (USP <711>, Acceptance
# Tables 2, 3 and 4) -- NOT part of the original SAS CuDAL system. These are
# new derivations, added on top of the same parametric-tolerance-interval
# methodology and the same Bonferroni-bound technique used throughout this
# module, extended to cover the additional dosage-form categories USP <711>
# defines. See each function's docstring for the specific derivation.
#
# Modeling assumptions common to all three functions below (stated once
# here rather than repeated):
#   * Individual unit measurements are i.i.d. Normal(mu, sigma^2), exactly
#     as assumed everywhere else in this module (Part 0 of the underlying
#     statistical derivation).
#   * Where a single-point (single test time) abstraction is required
#     (Extended-Release), the "final test time" individual-unit check in
#     USP <711> is treated as coinciding with the lower end of the stated
#     range at that time point -- consistent with how the rest of CuDAL
#     already reduces multi-faceted compendial rules to one evaluated
#     point per module, rather than a full dissolution profile.
#   * Where a compound (average-and-individual) criterion has no explicit
#     USP inclusion-exclusion formula, the Fréchet/Bonferroni inequality
#     P(A ∩ B) >= P(A) + P(B) - 1 is used, exactly as in
#     :func:`content_uniformity_bound` (P2) and :func:`dissolution_bound`
#     (F2, F3) above -- giving a guaranteed conservative lower bound, never
#     an overestimate.
# ---------------------------------------------------------------------------


def extended_release_bound(mu, sigma, ql, qu):
    """
    USP <711> Extended-Release Dosage Forms, Acceptance Table 2 (L1/L2/L3).

    Unlike Immediate-Release (a one-sided "at least Q" criterion),
    Extended-Release requires the dissolved amount to fall *within* a
    stated range [ql, qu] at the evaluated time point.

    Derivation
    ----------
    L1 (n=6): every unit in [ql, qu] -- an i.i.d. product, exact::

        F1 = [Phi((qu-mu)/sigma) - Phi((ql-mu)/sigma)]^6

    L2 (n=12, +/-10% margin): the average of 12 units must lie in
    [ql, qu], AND no individual unit may be more than 10% outside either
    side of the range. Let::

        p_ok12 = Phi((qu+10-mu)/sigma) - Phi((ql-10-mu)/sigma)   (all 12 within the +/-10% margin)
        avg_fail12 = Phi((ql-mu)*sqrt(12)/sigma) + [1 - Phi((qu-mu)*sqrt(12)/sigma)]  (avg outside [ql,qu])

    Bonferroni: F2 = p_ok12^12 - avg_fail12

    L3 (n=24, +/-10%/+/-20% margins): average of 24 in [ql, qu]; NMT 2
    of 24 units more than 10% outside the range (either side, combined);
    no unit ever more than 20% outside the range. This is the same exact
    multinomial counting device used in Disp1's Stage 3 (see
    :func:`_dissolution_stage_probs`), just applied symmetrically to both
    tails::

        p_ok24     = Phi((qu+10-mu)/sigma) - Phi((ql-10-mu)/sigma)
        p_border24 = [Phi((ql-10-mu)/sigma) - Phi((ql-20-mu)/sigma)]
                     + [Phi((qu+20-mu)/sigma) - Phi((qu+10-mu)/sigma)]
        F3 = p_ok24^24 + 24*p_border24*p_ok24^23 + 276*p_border24^2*p_ok24^22
             - [Phi((ql-mu)*sqrt(24)/sigma) + (1 - Phi((qu-mu)*sqrt(24)/sigma))]

    Parameters
    ----------
    mu, sigma : float or array_like
        True population mean and standard deviation (% of label claim).
    ql, qu : float
        Lower and upper ends of the stated acceptance range (% of label
        claim) at the evaluated time point.

    Returns
    -------
    float or numpy.ndarray
        max(F1, F2, F3).
    """
    mu = np.asarray(mu, dtype=float)
    sigma = np.asarray(sigma, dtype=float)

    F1 = (probnorm((qu - mu) / sigma) - probnorm((ql - mu) / sigma)) ** 6

    p_ok12 = probnorm((qu + 10 - mu) / sigma) - probnorm((ql - 10 - mu) / sigma)
    avg_fail12 = probnorm((ql - mu) * np.sqrt(12) / sigma) + (
        1 - probnorm((qu - mu) * np.sqrt(12) / sigma)
    )
    F2 = p_ok12**12 - avg_fail12

    p_ok24 = probnorm((qu + 10 - mu) / sigma) - probnorm((ql - 10 - mu) / sigma)
    p_border24 = (probnorm((ql - 10 - mu) / sigma) - probnorm((ql - 20 - mu) / sigma)) + (
        probnorm((qu + 20 - mu) / sigma) - probnorm((qu + 10 - mu) / sigma)
    )
    avg_fail24 = probnorm((ql - mu) * np.sqrt(24) / sigma) + (
        1 - probnorm((qu - mu) * np.sqrt(24) / sigma)
    )
    F3 = p_ok24**24 + 24 * p_border24 * p_ok24**23 + 276 * p_border24**2 * p_ok24**22 - avg_fail24

    result = np.maximum(np.maximum(F1, F2), F3)
    return result if result.ndim else result.item()


def acid_stage_bound(mu, sigma):
    """
    USP <711> Delayed-Release Dosage Forms, Acid Stage, Acceptance Table 3
    (A1/A2/A3).

    Unlike every other criterion in this module, the Acid Stage is an
    *upper*-bound test: the drug should resist dissolving in acid, so the
    criterion caps how much may dissolve, rather than requiring a minimum.
    The 10% and 25% limits are fixed compendial constants (not
    monograph-specific, unlike Q elsewhere).

    Derivation
    ----------
    A1 (n=6): every unit <= 10% dissolved -- exact i.i.d. product::

        A1 = [Phi((10-mu)/sigma)]^6

    A2 (n=12) and A3 (n=24) both require (average <= 10%) AND (every
    individual unit <= 25%) -- structurally simpler than the Immediate-
    Release Stage 3 case, since USP <711> places no "NMT 2 units" relaxed
    band here. Via Bonferroni::

        A2 = [Phi((25-mu)/sigma)]^12 - [1 - Phi((10-mu)*sqrt(12)/sigma)]
        A3 = [Phi((25-mu)/sigma)]^24 - [1 - Phi((10-mu)*sqrt(24)/sigma)]

    Parameters
    ----------
    mu, sigma : float or array_like
        True population mean and standard deviation of % dissolved in the
        Acid Stage.

    Returns
    -------
    float or numpy.ndarray
        max(A1, A2, A3).
    """
    mu = np.asarray(mu, dtype=float)
    sigma = np.asarray(sigma, dtype=float)

    A1 = probnorm((10 - mu) / sigma) ** 6
    A2 = probnorm((25 - mu) / sigma) ** 12 - (1 - probnorm((10 - mu) * np.sqrt(12) / sigma))
    A3 = probnorm((25 - mu) / sigma) ** 24 - (1 - probnorm((10 - mu) * np.sqrt(24) / sigma))

    result = np.maximum(np.maximum(A1, A2), A3)
    return result if result.ndim else result.item()


def delayed_release_bound(mu_acid, sigma_acid, mu_buffer, sigma_buffer, q_buffer=75.0):
    """
    USP <711> Delayed-Release Dosage Forms: combined Acid Stage
    (Acceptance Table 3) + Buffer Stage (Acceptance Table 4).

    Acceptance Table 4 (Buffer Stage) is structurally identical to
    Acceptance Table 1 (Immediate-Release) -- same "NLT Q+5" / "avg >= Q,
    none < Q-15" / "avg >= Q, NMT 2 < Q-15, none < Q-25" structure -- so
    its per-level probabilities are obtained by reusing
    :func:`_dissolution_stage_probs` directly, just shifted by
    ``q_buffer`` (75% dissolved unless the monograph states otherwise).

    USP <711> stops testing only when *both* stages conform at the same
    level, so this models the level-i pass probability as the Acid-Stage
    and Buffer-Stage level-i probabilities occurring together. The Acid
    Stage (coating integrity) and Buffer Stage (matrix dissolution) are
    governed by different physicochemical mechanisms, so -- as a
    documented modeling simplification -- they are treated as
    statistically independent, and the two probabilities are multiplied
    at each level::

        Level i combined = Acid_i * Buffer_i,   i = 1, 2, 3

    with the overall bound taken as the best of the three levels, matching
    the max(...) convention used everywhere else in this module.

    Parameters
    ----------
    mu_acid, sigma_acid : float or array_like
        True population mean and standard deviation of % dissolved in the
        Acid Stage.
    mu_buffer, sigma_buffer : float or array_like
        True population mean and standard deviation of cumulative %
        dissolved (Acid Stage + Buffer Stage) at the Buffer Stage
        evaluation.
    q_buffer : float, default 75.0
        The Buffer Stage's Q value (% dissolved); 75% unless the
        individual monograph specifies otherwise.

    Returns
    -------
    float or numpy.ndarray
        max over the three levels of (Acid_i * Buffer_i).
    """
    mu_acid = np.asarray(mu_acid, dtype=float)
    sigma_acid = np.asarray(sigma_acid, dtype=float)

    A1 = probnorm((10 - mu_acid) / sigma_acid) ** 6
    A2 = probnorm((25 - mu_acid) / sigma_acid) ** 12 - (
        1 - probnorm((10 - mu_acid) * np.sqrt(12) / sigma_acid)
    )
    A3 = probnorm((25 - mu_acid) / sigma_acid) ** 24 - (
        1 - probnorm((10 - mu_acid) * np.sqrt(24) / sigma_acid)
    )

    llu_buffer = np.asarray(mu_buffer, dtype=float) - q_buffer
    B1, B2, B3 = _dissolution_stage_probs(llu_buffer, sigma_buffer)

    level1 = A1 * B1
    level2 = A2 * B2
    level3 = A3 * B3

    result = np.maximum(np.maximum(level1, level2), level3)
    return result if result.ndim else result.item()


# ---------------------------------------------------------------------------
# Vectorized batch root finding -- replaces per-point brentq/GOTO search
# ---------------------------------------------------------------------------


def batched_root_find(
    func: Callable[[np.ndarray], np.ndarray],
    lo,
    hi,
    scan_points: int = 12,
    bisect_iters: int = 22,
    which: str = "first",
) -> tuple[np.ndarray, np.ndarray]:
    """
    Solve ``func(x) == 0`` independently for every element of a grid, in
    one vectorized pass, instead of one root-find per grid point.

    ``func`` must accept an array of shape ``(S, 1)`` (or any shape that
    broadcasts against the grid's own parameter arrays baked into the
    closure) and return an array of shape ``(S, G)``, and must also
    accept a shape-``(G,)`` array (during bisection refinement) and
    return shape ``(G,)``. This is automatic for anything built from
    :func:`content_uniformity_bound` / :func:`dissolution_bound` plus
    elementwise arithmetic -- see cudal.cusp1/cusp2/disp1/disp2 for the
    closures passed in.

    Parameters
    ----------
    func : callable
        Elementwise function; ``func(x)`` broadcasts ``x`` against the
        grid parameters captured in the closure.
    lo, hi : float
        Scalar bounds of the search interval (the same interval is
        scanned for every grid point -- pass a wide-enough range).
    scan_points : int
        Number of points used to bracket the root before refining. The
        function is assumed to have exactly one sign crossing of
        interest between ``lo`` and ``hi`` at this resolution (this
        mirrors the same monotonicity assumption the original SAS
        stepped search relies on).
    bisect_iters : int
        Number of vectorized bisection halving steps used to refine each
        bracket. The SAS code this replaces used a fixed step of
        0.001-0.2 depending on macro; matching that resolution needs on
        the order of log2((hi-lo)/step) ~= 13-20 iterations, so the
        default of 22 already has comfortable headroom while staying
        cheap (each extra iteration re-evaluates the full probability
        integral for the whole grid).
    which : {"first", "last"}
        If the scanned curve has more than one sign crossing (e.g. the
        content-uniformity bound is bump-shaped in the mean), "first"
        finds the lowest-x crossing and "last" finds the highest-x one.
        This mirrors the SAS code's two opposite-direction searches
        (scan up from the low end vs. scan down from the high end).

    Returns
    -------
    (root, found) : (numpy.ndarray, numpy.ndarray[bool])
        ``root`` has shape ``(G,)`` -- the last scanned/bisected value is
        returned even where no sign change was found (caller decides how
        to interpret that; ``found`` flags which entries actually
        bracketed a root).
    """
    xs = np.linspace(lo, hi, scan_points)  # shape (S,)
    xs_col = xs[:, None]  # (S, 1) -- broadcasts against the grid inside func
    vals = np.asarray(func(xs_col))  # shape (S, G)

    sign = np.sign(vals)
    changes = np.diff(sign, axis=0) != 0  # (S-1, G)
    found = changes.any(axis=0)

    if which == "first":
        idx = np.argmax(changes, axis=0)
    else:
        idx = changes.shape[0] - 1 - np.argmax(changes[::-1, :], axis=0)

    g = vals.shape[-1]
    cols = np.arange(g)
    lo_x = np.where(found, xs[idx], lo)
    hi_x = np.where(found, xs[idx + 1], hi)
    lo_val = np.where(found, vals[idx, cols], vals[0, cols])

    # Vectorized bisection refinement of every bracket simultaneously.
    cur_lo, cur_hi, cur_lo_val = lo_x.copy(), hi_x.copy(), lo_val.copy()
    for _ in range(bisect_iters):
        mid = (cur_lo + cur_hi) / 2.0
        f_mid = np.asarray(func(mid))
        same_sign_as_lo = np.sign(f_mid) == np.sign(cur_lo_val)
        cur_lo = np.where(same_sign_as_lo, mid, cur_lo)
        cur_hi = np.where(same_sign_as_lo, cur_hi, mid)
        cur_lo_val = np.where(same_sign_as_lo, f_mid, cur_lo_val)

    root = (cur_lo + cur_hi) / 2.0
    return root, found


def batched_two_sided_bounds(
    func_lower: Callable[[np.ndarray], np.ndarray],
    func_upper: Callable[[np.ndarray], np.ndarray],
    lo,
    hi,
    scan_points: int = 24,
    bisect_iters: int = 22,
):
    """
    Convenience wrapper for the CUSP2-style pattern of two searches over
    the same grid: the lower boundary found scanning low->high (first
    crossing) and the upper boundary found scanning high->low (last
    crossing). See :func:`batched_root_find`.

    Returns
    -------
    (lower, lower_found, upper, upper_found)
    """
    lower, lower_found = batched_root_find(
        func_lower, lo, hi, scan_points, bisect_iters, which="first"
    )
    upper, upper_found = batched_root_find(
        func_upper, lo, hi, scan_points, bisect_iters, which="last"
    )
    return lower, lower_found, upper, upper_found
