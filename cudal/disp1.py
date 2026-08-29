"""
cudal.disp1
===========

Translation of ``Disp1.sas`` -- Dissolution, Sampling Plan 1
(single location, USP <711>).

Three analyses, matching the three SAS entry points:

  * :func:`acceptance_limit_table`  (``CALDISP1`` / ``PRTDISP1``, A1DISP1=Y)
  * :func:`probability_of_passing`  (``EVDISP1`` / ``SIGDISP1``, A2DISP1=Y)
  * :func:`sample_probability`      (``SMPDISP1``, A3DISP1=Y)

Note the dissolution confidence multiplier is one-sided:
``Z = PROBIT(SQRT(CILEVEL/100))``, unlike the two-sided
``PROBIT((1+SQRT(CILEVEL/100))/2)`` used for content uniformity.

Performance: see :mod:`cudal.cusp1` -- the MEAN grid's boundary standard
deviations are all solved in one vectorized batch via
:func:`cudal.core.batched_root_find`, and ``probability_of_passing``
evaluates the full (U, CV) grid as one broadcasted array.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import batched_root_find, cinv, dissolution_bound, probchi, probit, probnorm


def acceptance_limit_table(
    number: int,
    q: float,
    lbound: float,
    cilevel: float,
    meanadj_step: float = 0.2,
) -> pd.DataFrame:
    """
    SAS: ``%CALDISP1`` (A1DISP1=Y or A2DISP1=Y).

    Parameters
    ----------
    number : int
        Sample size N (SAS &NUMBER).
    q : float
        USP <711> Q value (% dissolved), e.g. 80.
    lbound, cilevel : float
        Required lower bound (%) and confidence level (%).
    meanadj_step : float
        Step size for the internal MEANADJ = MEAN - Q grid (SAS D = 0.2).

    Returns
    -------
    pandas.DataFrame with columns ["MEAN", "CV"] where MEAN ranges from
    just above Q up to 100 (Q + LIM). CV = 0.0 marks a mean adjustment
    where even a (near) zero SD fails to meet the bound.
    """
    lim = 100 - q
    n = number
    z = probit(np.sqrt(cilevel / 100))
    chi = cinv(1 - np.sqrt(cilevel / 100), n - 1)
    target_prob = lbound / 100

    meanadjs = np.round(np.arange(meanadj_step, lim + meanadj_step / 2, meanadj_step), 6)

    def overbd_of_sd(sampsd):
        sigma = np.sqrt((n - 1) * sampsd**2 / chi)
        llu = meanadjs - z * sigma / np.sqrt(n)
        return dissolution_bound(llu, sigma) - target_prob

    sd_lo, sd_hi = 0.002, 60.0
    root, found = batched_root_find(overbd_of_sd, sd_lo, sd_hi)

    floor_fail = overbd_of_sd(np.full_like(meanadjs, sd_lo)) < 0
    sd = np.where(floor_fail, sd_lo, np.where(found, root, sd_hi))
    mean = meanadjs + q
    cv = np.where(floor_fail, 0.0, 100 * sd / mean)

    return pd.DataFrame({"MEAN": mean, "CV": cv})


def probability_of_passing(
    table: pd.DataFrame,
    number: int,
    u_values,
    cv_values,
) -> pd.DataFrame:
    """
    SAS: ``%EVDISP1`` / ``%SIGDISP1`` (A2DISP1=Y).

    Same trapezoidal-style accumulation as
    :func:`cudal.cusp1.probability_of_passing`, plus the SAS code's extra
    one-sided upper-tail correction applied to every table row whose mean
    exceeds 99.9 (% claim), using that row's own standard deviation rather
    than an average with its neighbour. The full (row, U, CV) grid is
    evaluated as one broadcasted array.

    Returns
    -------
    pandas.DataFrame with columns ["U", "CV", "PTRAP"].
    """
    t = table.sort_values("MEAN").reset_index(drop=True)
    x = t["MEAN"].to_numpy()
    std = (t["MEAN"] * t["CV"] / 100).to_numpy()
    n = number

    u = np.asarray(u_values, dtype=float)[None, :, None]  # (1, U, 1)
    cv = np.asarray(cv_values, dtype=float)[None, None, :]  # (1, 1, CV)
    sigma = u * cv / 100  # (1, U, CV)

    # main pairwise (trapezoid-style) term, rows 2..end
    x_hi, x_lo = x[1:, None, None], x[:-1, None, None]
    std_hi, std_lo = std[1:, None, None], std[:-1, None, None]
    pmean = probnorm((x_hi - u) * np.sqrt(n) / sigma) - probnorm((x_lo - u) * np.sqrt(n) / sigma)
    aveht = (std_hi + std_lo) / 2
    pstd = probchi((n - 1) * aveht**2 / sigma**2, n - 1)
    ptrap = np.sum(pmean * pstd, axis=0)  # (U, CV)

    # extra upper-tail correction for every row with X > 99.9
    tail_mask = x > 99.9
    if np.any(tail_mask):
        xt = x[tail_mask][:, None, None]
        stdt = std[tail_mask][:, None, None]
        pmean_t = 1 - probnorm((xt - u) * np.sqrt(n) / sigma)
        pstd_t = probchi((n - 1) * stdt**2 / sigma**2, n - 1)
        ptrap = ptrap + np.sum(pmean_t * pstd_t, axis=0)

    u_flat = np.asarray(u_values, dtype=float)
    cv_flat = np.asarray(cv_values, dtype=float)
    uu, cc = np.meshgrid(u_flat, cv_flat, indexing="ij")
    return pd.DataFrame({"U": uu.ravel(), "CV": cc.ravel(), "PTRAP": ptrap.ravel()})


def sample_probability(
    mean: float,
    cv: float,
    number: int,
    q: float,
    cilevel: float,
) -> dict:
    """
    SAS: ``%SMPDISP1`` (A3DISP1=Y).

    Given an observed sample mean (% dissolved) and CV (%), computes the
    probability ("OVERBD") that future samples pass USP <711>.
    """
    n = number
    z = probit(np.sqrt(cilevel / 100))
    chi = cinv(1 - np.sqrt(cilevel / 100), n - 1)

    meanadj = mean - q
    sampsd = mean * cv / 100
    sigma = np.sqrt((n - 1) * sampsd**2 / chi)
    llu = meanadj - z * sigma / np.sqrt(n)
    overbd = dissolution_bound(llu, sigma)

    return {"MEAN": mean, "CV": cv, "SAMPSD": sampsd, "OVERBD": overbd}
