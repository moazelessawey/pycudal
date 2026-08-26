"""
cudal.cusp2
===========

Translation of ``Cusp2.sas`` -- Content Uniformity, Sampling Plan 2
(multiple locations, each with its own composite sample -- a
within-location / between-location variance-components model, USP <905>).

Three analyses, matching the three SAS entry points:

  * :func:`acceptance_limit_table`  (``CALCUSP2``, A1CUSP2=Y)
  * :func:`probability_of_passing`  (``EVCUSP2`` / ``SIGCUSP2``, A2CUSP2=Y)
  * :func:`sample_probability`      (``SMPCUSP2``, A3CUSP2=Y)

Variance-component notation (mirrors the SAS variable names)
--------------------------------------------------------------
    NN   -- number of units assayed per location (SAS &NUM)
    L    -- number of locations (SAS &LOC)
    N    = NN * L
    SE   -- pooled within-location standard deviation
    SM   -- between-location standard deviation
    VAR  -- total variance used as sigma^2 in the content-uniformity core
    MVAR -- upper confidence bound on the between-location variance
            component, used (via sqrt(MVAR/N)) as the standard error of
            the overall mean for the MEANL/MEANU confidence bound

Performance
-----------
The original SAS code (and a naive Python port) loops over every (SE, SM)
grid cell and, for each one, scans/steps a candidate MEAN up from below
(for MEANL) and down from above (for MEANU) one value at a time. Here the
*entire* SE/SM grid is flattened to a single array of length
``G = len(SE) * len(SM)``, and both boundaries for all G cells are solved
in one vectorized pass with :func:`cudal.core.batched_two_sided_bounds`
-- turning what would be thousands of scalar root searches (each costing
hundreds of probability evaluations) into a couple dozen array-wide
evaluations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import probit, cinv, probnorm, probchi, content_uniformity_bound, batched_two_sided_bounds


def _variance_components(se, sm, nn: int, l: int, chierr: float, chiloc: float):
    """
    Shared VAR / MVAR calculation used by all three CUSP2 analyses.
    Works elementwise on scalars or numpy arrays of any shape.
    """
    se2 = se * se
    h2 = l * (nn - 1) / chierr - 1
    sec = ((1 - 1 / nn) * h2 * se2) ** 2

    sl2 = sm * sm * nn
    sl2ub = (l - 1) * sl2 / chiloc
    h1 = (l - 1) / chiloc - 1
    first = ((1 / nn) * h1 * sl2) ** 2

    ptest = (1 / nn) * sl2 + (1 - 1 / nn) * se2
    var = ptest + np.sqrt(first + sec)
    mvar = sl2ub
    return var, mvar


def acceptance_limit_table(
    num: int,
    loc: int,
    target: float,
    lbound: float,
    cilevel: float,
    se_values,
    sm_values,
    mean_search_range=(80.0, 120.0),
) -> pd.DataFrame:
    """
    SAS: ``%CALCUSP2`` (A1CUSP2=Y).

    Parameters
    ----------
    num : int
        Units per location (SAS &NUM).
    loc : int
        Number of locations (SAS &LOC).
    target, lbound, cilevel : float
        Label claim / target, required lower bound (%), confidence
        level (%) -- same meaning as in :mod:`cudal.cusp1`.
    se_values, sm_values : iterable of float
        Grids of within-location (SE) and between-location (SM) standard
        deviations to evaluate (SAS steps these by D1=0.10).
    mean_search_range : (float, float)
        Range to scan for the MEANL/MEANU roots.

    Returns
    -------
    pandas.DataFrame with columns SE, SM, MEANL, MEANU (NaN where no
    acceptable mean range exists for that SE/SM combination -- i.e. the
    combined variability is too large to ever pass).
    """
    nn, l = num, loc
    n = nn * l
    z = probit((1 + np.sqrt(cilevel / 100)) / 2)
    chierr = cinv(1 - np.sqrt(cilevel / 100), l * (nn - 1))
    chiloc = cinv(1 - np.sqrt(cilevel / 100), l - 1)
    target_prob = lbound / 100
    lo, hi = mean_search_range

    se_grid, sm_grid = np.meshgrid(np.asarray(se_values, dtype=float),
                                    np.asarray(sm_values, dtype=float), indexing="ij")
    se_flat = se_grid.ravel()
    sm_flat = sm_grid.ravel()

    var, mvar = _variance_components(se_flat, sm_flat, nn, l, chierr, chiloc)
    sigma = np.sqrt(var)             # shape (G,)
    se_of_mean = np.sqrt(mvar / n)   # shape (G,)

    def func_lower(mean):
        llu = mean - z * se_of_mean
        return content_uniformity_bound(llu, sigma, target) - target_prob

    def func_upper(mean):
        ulu = mean + z * se_of_mean
        return content_uniformity_bound(ulu, sigma, target) - target_prob

    meanl, meanl_found, meanu, meanu_found = batched_two_sided_bounds(func_lower, func_upper, lo, hi)

    ok = meanl_found & meanu_found & (meanu > meanl)
    meanl_out = np.where(ok, meanl, np.nan)
    meanu_out = np.where(ok, meanu, np.nan)

    return pd.DataFrame({"SE": se_flat, "SM": sm_flat, "MEANL": meanl_out, "MEANU": meanu_out})


def probability_of_passing(
    table: pd.DataFrame,
    num: int,
    loc: int,
    d1: float,
    u_values,
    sigse_values,
    sigsm_values,
) -> pd.DataFrame:
    """
    SAS: ``%EVCUSP2`` / ``%SIGCUSP2`` (A2CUSP2=Y).

    Given the acceptance-limit ``table`` (columns SE, SM, MEANL, MEANU),
    sums, over every (SE, SM) grid cell, the probability that a batch with
    assumed true mean ``U`` and true within-/between-location standard
    deviations (``sigse``, ``sigsm``) both (a) lands its location means in
    [MEANL, MEANU], (b) has a within-location SD landing in the SE bin,
    and (c) has a between-location SD landing in the SM bin.

    The full (table row x U x SIGSE x SIGSM) computation is done as one
    broadcasted numpy array rather than nested Python loops.

    Returns
    -------
    pandas.DataFrame with columns ["U", "SIGSE", "SIGSM", "PSUM"].
    """
    t = table.dropna(subset=["MEANL", "MEANU"])
    nn, l = num, loc
    n = nn * l

    se = t["SE"].to_numpy()[:, None, None, None]
    sm = t["SM"].to_numpy()[:, None, None, None]
    meanl = t["MEANL"].to_numpy()[:, None, None, None]
    meanu = t["MEANU"].to_numpy()[:, None, None, None]

    u = np.asarray(u_values, dtype=float)[None, :, None, None]
    sigse = np.asarray(sigse_values, dtype=float)[None, None, :, None]
    sigsm = np.asarray(sigsm_values, dtype=float)[None, None, None, :]

    expse2 = sigse ** 2
    expsm2 = expse2 + nn * sigsm ** 2

    pmean = probnorm((meanu - u) * np.sqrt(n / expsm2)) - probnorm((meanl - u) * np.sqrt(n / expsm2))
    pse = probchi(l * (nn - 1) * se ** 2 / expse2, l * (nn - 1)) - probchi(
        l * (nn - 1) * (se - d1) ** 2 / expse2, l * (nn - 1)
    )
    psm = probchi((l - 1) * nn * sm ** 2 / expsm2, l - 1) - probchi(
        (l - 1) * nn * (sm - d1) ** 2 / expsm2, l - 1
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
    target: float,
    cilevel: float,
) -> dict:
    """
    SAS: ``%SMPCUSP2`` (A3CUSP2=Y).

    Given an observed sample MEAN, within-location SD (SE) and
    between-location SD (SM), computes the probability ("OVERBD") that
    future samples from that population pass USP <905>.
    """
    nn, l = num, loc
    n = nn * l
    z = probit((1 + np.sqrt(cilevel / 100)) / 2)
    chierr = cinv(1 - np.sqrt(cilevel / 100), l * (nn - 1))
    chiloc = cinv(1 - np.sqrt(cilevel / 100), l - 1)

    var, mvar = _variance_components(se, sm, nn, l, chierr, chiloc)
    sigma = np.sqrt(var)
    se_of_mean = np.sqrt(mvar / n)

    llu = mean - z * se_of_mean
    ulu = mean + z * se_of_mean

    overbdl = content_uniformity_bound(llu, sigma, target)
    overbdu = content_uniformity_bound(ulu, sigma, target)
    overbd = min(overbdl, overbdu)

    return {
        "MEAN": mean, "SE": se, "SM": sm,
        "VAR": var, "MVAR": mvar, "SIGMA": sigma,
        "OVERBDL": overbdl, "OVERBDU": overbdu, "OVERBD": overbd,
    }
