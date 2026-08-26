"""
cudal.disp2
===========

Translation of ``Disp2.sas`` -- Dissolution, Sampling Plan 2
(multiple locations, variance-components model, USP <711>).

Unlike the content-uniformity Sampling Plan 2 (:mod:`cudal.cusp2`), the
dissolution test only has a *lower* bound (Q value), so there is a single
``MEANL`` boundary per (SE, SM) combination, not a [MEANL, MEANU] pair.

Three analyses:

  * :func:`acceptance_limit_table`  (``CALDISP2``, A1DISP2=Y)
  * :func:`probability_of_passing`  (``EVDISP2`` / ``SIGDISP2``, A2DISP2=Y)
  * :func:`sample_probability`      (``SMPDISP2``, A3DISP2=Y)

Performance: as in :mod:`cudal.cusp2`, the whole (SE, SM) grid is
flattened and solved for MEANL in one vectorized batch via
:func:`cudal.core.batched_root_find`, instead of a per-cell scalar search.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import probit, cinv, probnorm, probchi, dissolution_bound, batched_root_find
from .cusp2 import _variance_components


def acceptance_limit_table(
    num: int,
    loc: int,
    q: float,
    lbound: float,
    cilevel: float,
    se_values,
    sm_values,
    meanadj_search_range=(-20.0, 100.0),
) -> pd.DataFrame:
    """
    SAS: ``%CALDISP2`` (A1DISP2=Y).

    For each (SE, SM) combination, finds the smallest acceptable sample
    mean (MEAN = MEANL + Q) such that the probability of passing USP
    <711> is still at least ``lbound``%. The whole SE/SM grid is solved
    in one vectorized batch (see module docstring).

    Returns
    -------
    pandas.DataFrame with columns ["SE", "SM", "MEAN"] (NaN MEAN where no
    acceptable mean exists in the search range for that SE/SM).
    """
    nn, l = num, loc
    n = nn * l
    lim = 100 - q
    z = probit(np.sqrt(cilevel / 100))
    chierr = cinv(1 - np.sqrt(cilevel / 100), l * (nn - 1))
    chiloc = cinv(1 - np.sqrt(cilevel / 100), l - 1)
    target_prob = lbound / 100
    lo, hi = meanadj_search_range
    hi = min(hi, lim)

    se_grid, sm_grid = np.meshgrid(np.asarray(se_values, dtype=float),
                                    np.asarray(sm_values, dtype=float), indexing="ij")
    se_flat = se_grid.ravel()
    sm_flat = sm_grid.ravel()

    var, mvar = _variance_components(se_flat, sm_flat, nn, l, chierr, chiloc)
    sigma = np.sqrt(var)
    se_of_mean = np.sqrt(mvar / n)

    def func(meanadj):
        llu = meanadj - z * se_of_mean
        return dissolution_bound(llu, sigma) - target_prob

    meanl, found = batched_root_find(func, lo, hi, which="first")
    mean = np.where(found, meanl + q, np.nan)

    return pd.DataFrame({"SE": se_flat, "SM": sm_flat, "MEAN": mean})


def probability_of_passing(
    table: pd.DataFrame,
    num: int,
    loc: int,
    dse: float,
    dsm: float,
    u_values,
    sigse_values,
    sigsm_values,
) -> pd.DataFrame:
    """
    SAS: ``%EVDISP2`` / ``%SIGDISP2`` (A2DISP2=Y).

    One-sided analogue of :func:`cudal.cusp2.probability_of_passing`:
    ``PMEAN = 1 - PROBNORM((MEAN - U) * SQRT(N / EXPSM2))`` since there is
    only a lower acceptance bound on the mean. The full grid is evaluated
    as one broadcasted array.

    Returns
    -------
    pandas.DataFrame with columns ["U", "SIGSE", "SIGSM", "PSUM"].
    """
    t = table.dropna(subset=["MEAN"])
    nn, l = num, loc
    n = nn * l

    se = t["SE"].to_numpy()[:, None, None, None]
    sm = t["SM"].to_numpy()[:, None, None, None]
    mean = t["MEAN"].to_numpy()[:, None, None, None]

    u = np.asarray(u_values, dtype=float)[None, :, None, None]
    sigse = np.asarray(sigse_values, dtype=float)[None, None, :, None]
    sigsm = np.asarray(sigsm_values, dtype=float)[None, None, None, :]

    expse2 = sigse ** 2
    expsm2 = expse2 + nn * sigsm ** 2

    pmean = 1 - probnorm((mean - u) * np.sqrt(n / expsm2))
    pse = probchi(l * (nn - 1) * se ** 2 / expse2, l * (nn - 1)) - probchi(
        l * (nn - 1) * (se - dse) ** 2 / expse2, l * (nn - 1)
    )
    psm = probchi((l - 1) * nn * sm ** 2 / expsm2, l - 1) - probchi(
        (l - 1) * nn * (sm - dsm) ** 2 / expsm2, l - 1
    )

    psum = np.sum(pmean * pse * psm, axis=0)  # (U, SIGSE, SIGSM)

    uu, ee, mm = np.meshgrid(np.asarray(u_values, dtype=float),
                              np.asarray(sigse_values, dtype=float),
                              np.asarray(sigsm_values, dtype=float), indexing="ij")
    return pd.DataFrame({
        "U": uu.ravel(), "SIGSE": ee.ravel(), "SIGSM": mm.ravel(), "PSUM": psum.ravel(),
    })


def sample_probability(
    mean: float,
    se: float,
    sm: float,
    num: int,
    loc: int,
    q: float,
    cilevel: float,
) -> dict:
    """
    SAS: ``%SMPDISP2`` (A3DISP2=Y).

    Given an observed sample MEAN, within-location SD (SE) and
    between-location SD (SM), computes the probability ("OVERBD") that
    future samples pass USP <711>.
    """
    nn, l = num, loc
    n = nn * l
    z = probit(np.sqrt(cilevel / 100))
    chierr = cinv(1 - np.sqrt(cilevel / 100), l * (nn - 1))
    chiloc = cinv(1 - np.sqrt(cilevel / 100), l - 1)

    var, mvar = _variance_components(se, sm, nn, l, chierr, chiloc)
    sigma = np.sqrt(var)
    se_of_mean = np.sqrt(mvar / n)

    meanadj = mean - q
    llu = meanadj - z * se_of_mean
    overbd = dissolution_bound(llu, sigma)

    return {
        "MEAN": mean, "SE": se, "SM": sm,
        "VAR": var, "MVAR": mvar, "SIGMA": sigma,
        "OVERBD": overbd,
    }
