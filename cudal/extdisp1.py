"""
cudal.extdisp1
==============

USP <711> Extended-Release Dissolution, Sampling Plan 1 (single location).

.. note::
   Unlike ``cusp1``/``cusp2``/``disp1``/``disp2``, this module is **not**
   a translation of an original SAS CuDAL macro -- USP <711>'s Extended-
   Release requirements (Acceptance Table 2) were not part of the legacy
   CuDAL system. It is a new derivation, built on exactly the same
   parametric-tolerance-interval methodology and Bonferroni-bound
   technique used throughout the rest of this package. See
   :func:`cudal.core.extended_release_bound` for the full derivation.

Because Extended-Release is a *two-sided range* criterion (dissolved
amount must fall within [QL, QU], not just exceed a single Q), this
module's structure mirrors :mod:`cudal.cusp1` (which is also two-sided)
rather than :mod:`cudal.disp1` (one-sided): a two-sided confidence
adjustment on the sample mean (LLU/ULU) is evaluated against
``extended_release_bound``, and the batch is credited with whichever
confidence-bound extreme is more restrictive (the ``min`` of the two).

Three analyses, matching the pattern of every other module:

  * :func:`acceptance_limit_table`
  * :func:`probability_of_passing`
  * :func:`sample_probability`
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import (
    batched_root_find,
    cinv,
    extended_release_bound,
    probchi,
    probit,
    probnorm,
)


def acceptance_limit_table(
    number: int,
    ql: float,
    qu: float,
    lbound: float,
    cilevel: float,
    mean_low: float = None,
    mean_high: float = None,
    mean_step: float = 0.5,
) -> pd.DataFrame:
    """
    For each candidate sample MEAN, finds the largest sample %CV for which
    the probability of passing the USP <711> Extended-Release test
    (Acceptance Table 2) still meets the required lower bound at the given
    confidence level.

    Parameters
    ----------
    number : int
        Sample size N.
    ql, qu : float
        Lower and upper ends of the stated acceptance range (% of label
        claim) at the evaluated time point.
    lbound : float
        Required lower bound on pass probability (%).
    cilevel : float
        Confidence level (%).
    mean_low, mean_high : float, optional
        Range of the candidate MEAN grid. Defaults to a range spanning
        the stated acceptance range with a margin on each side
        (``ql - 10`` to ``qu + 10``), since -- unlike Immediate-Release --
        there is no fixed compendial default range.
    mean_step : float, default 0.5
        Step size of the candidate MEAN grid.

    Returns
    -------
    pandas.DataFrame with columns ["MEAN", "CV"]. A CV of 0.0 marks a
    mean where even a (near) zero standard deviation fails to meet the
    bound.
    """
    if mean_low is None:
        mean_low = ql - 10
    if mean_high is None:
        mean_high = qu + 10

    z = probit((1 + np.sqrt(cilevel / 100)) / 2)
    n = number
    chi = cinv(1 - np.sqrt(cilevel / 100), n - 1)
    target_prob = lbound / 100

    means = np.round(np.arange(mean_low, mean_high + mean_step / 2, mean_step), 6)

    def overbd_of_sd(sampsd):
        sigma = np.sqrt((n - 1) * sampsd**2 / chi)
        llu = means - z * sigma / np.sqrt(n)
        ulu = means + z * sigma / np.sqrt(n)
        overlbd = extended_release_bound(llu, sigma, ql, qu)
        overubd = extended_release_bound(ulu, sigma, ql, qu)
        return np.minimum(overlbd, overubd) - target_prob

    sd_lo, sd_hi = 0.01, (qu - ql) / 2 + 10
    root, found = batched_root_find(overbd_of_sd, sd_lo, sd_hi)

    floor_fail = overbd_of_sd(np.full_like(means, sd_lo)) < 0
    sd = np.where(floor_fail, sd_lo, np.where(found, root, sd_hi))
    # Create an array of zeros with the same shape to store the results
    cv = np.zeros_like(means)

    # Perform division only where means is NOT zero (or where floor_fail is False)
    # Assuming floor_fail indicates where the mean is too low or zero:
    np.divide(100 * sd, means, out=cv, where=~floor_fail)

    return pd.DataFrame({"MEAN": means, "CV": cv})


def probability_of_passing(
    table: pd.DataFrame,
    number: int,
    u_values,
    cv_values,
) -> pd.DataFrame:
    """
    Given the acceptance-limit table, evaluates -- for every combination of
    assumed true population mean (U) and true population CV -- the
    probability that a sample of size ``number`` lands inside the
    acceptance region traced out by the table. Same trapezoidal-style
    accumulation as :func:`cudal.cusp1.probability_of_passing`.

    Returns
    -------
    pandas.DataFrame with columns ["U", "CV", "PTRAP"].
    """
    t = table.sort_values("MEAN").reset_index(drop=True)
    x = t["MEAN"].to_numpy()
    std = (t["MEAN"] * t["CV"] / 100).to_numpy()
    n = number

    u = np.asarray(u_values, dtype=float)[None, :, None]
    cv = np.asarray(cv_values, dtype=float)[None, None, :]
    sigma = u * cv / 100

    x_hi, x_lo = x[1:, None, None], x[:-1, None, None]
    std_hi, std_lo = std[1:, None, None], std[:-1, None, None]
    pmean = probnorm((x_hi - u) * np.sqrt(n) / sigma) - probnorm((x_lo - u) * np.sqrt(n) / sigma)
    aveht = (std_hi + std_lo) / 2
    pstd = probchi((n - 1) * aveht**2 / sigma**2, n - 1)
    ptrap = np.sum(pmean * pstd, axis=0)

    u_flat = np.asarray(u_values, dtype=float)
    cv_flat = np.asarray(cv_values, dtype=float)
    uu, cc = np.meshgrid(u_flat, cv_flat, indexing="ij")
    return pd.DataFrame({"U": uu.ravel(), "CV": cc.ravel(), "PTRAP": ptrap.ravel()})


def sample_probability(
    mean: float,
    cv: float,
    number: int,
    ql: float,
    qu: float,
    lbound: float,
    cilevel: float,
) -> dict:
    """
    Given an observed sample mean and %CV, computes the probability that
    future samples from that population will pass the USP <711>
    Extended-Release test.

    Returns
    -------
    dict with keys: MEAN, CV, SAMPSD, OVERBD
    """
    z = probit((1 + np.sqrt(cilevel / 100)) / 2)
    n = number
    chi = cinv(1 - np.sqrt(cilevel / 100), n - 1)

    sampsd = mean * cv / 100
    sigma = np.sqrt((n - 1) * sampsd**2 / chi)
    llu = mean - z * sigma / np.sqrt(n)
    ulu = mean + z * sigma / np.sqrt(n)

    overlbd = extended_release_bound(llu, sigma, ql, qu)
    overubd = extended_release_bound(ulu, sigma, ql, qu)
    overbd = min(overlbd, overubd)

    return {"MEAN": mean, "CV": cv, "SAMPSD": sampsd, "OVERBD": overbd}
