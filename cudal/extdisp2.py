"""
cudal.extdisp2
==============

USP <711> Extended-Release Dissolution, Sampling Plan 2 (multiple
locations, variance-components model).

.. note::
   As with :mod:`cudal.extdisp1`, this is a new derivation extending
   CuDAL's methodology to a USP <711> dosage-form category not covered by
   the original SAS system. See :func:`cudal.core.extended_release_bound`.

Structurally mirrors :mod:`cudal.cusp2` exactly (two-sided MEANL/MEANU
search via the same within-/between-location variance-components model),
with ``extended_release_bound`` in place of ``content_uniformity_bound``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import (
    batched_two_sided_bounds,
    cinv,
    extended_release_bound,
    probchi,
    probit,
    probnorm,
)
from .cusp2 import _variance_components


def acceptance_limit_table(
    num: int,
    loc: int,
    ql: float,
    qu: float,
    lbound: float,
    cilevel: float,
    se_values,
    sm_values,
    mean_search_range=None,
) -> pd.DataFrame:
    """
    For each (SE, SM) combination, finds the acceptable range of sample
    mean [MEANL, MEANU] for which the probability of passing the USP <711>
    Extended-Release test meets the required lower bound.

    Parameters
    ----------
    num : int
        Units assayed per location.
    loc : int
        Number of locations.
    ql, qu : float
        Lower and upper ends of the stated acceptance range (% of label
        claim).
    lbound, cilevel : float
        Required lower bound (%) and confidence level (%).
    se_values, sm_values : iterable of float
        Grids of within-location (SE) and between-location (SM) standard
        deviations to evaluate.
    mean_search_range : (float, float), optional
        Search bounds for the mean. Defaults to (ql - 20, qu + 20).

    Returns
    -------
    pandas.DataFrame with columns SE, SM, MEANL, MEANU (NaN where no
    acceptable mean range exists).
    """
    if mean_search_range is None:
        mean_search_range = (ql - 20.0, qu + 20.0)

    nn, l = num, loc
    n = nn * l
    z = probit((1 + np.sqrt(cilevel / 100)) / 2)
    chierr = cinv(1 - np.sqrt(cilevel / 100), l * (nn - 1))
    chiloc = cinv(1 - np.sqrt(cilevel / 100), l - 1)
    target_prob = lbound / 100
    lo, hi = mean_search_range

    se_grid, sm_grid = np.meshgrid(
        np.asarray(se_values, dtype=float),
        np.asarray(sm_values, dtype=float),
        indexing="ij",
    )
    se_flat = se_grid.ravel()
    sm_flat = sm_grid.ravel()

    var, mvar = _variance_components(se_flat, sm_flat, nn, l, chierr, chiloc)
    sigma = np.sqrt(var)
    se_of_mean = np.sqrt(mvar / n)

    def func_lower(mean):
        llu = mean - z * se_of_mean
        return extended_release_bound(llu, sigma, ql, qu) - target_prob

    def func_upper(mean):
        ulu = mean + z * se_of_mean
        return extended_release_bound(ulu, sigma, ql, qu) - target_prob

    meanl, meanl_found, meanu, meanu_found = batched_two_sided_bounds(
        func_lower, func_upper, lo, hi
    )

    ok = meanl_found & meanu_found & (meanu > meanl)
    meanl_out = np.where(ok, meanl, np.nan)
    meanu_out = np.where(ok, meanu, np.nan)

    return pd.DataFrame({"SE": se_flat, "SM": sm_flat, "MEANL": meanl_out, "MEANU": meanu_out})


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
    Given the acceptance-limit table, sums over every (SE, SM) grid cell
    the probability that a batch with an assumed true mean and true
    within-/between-location standard deviations falls within the
    acceptance region. Identical structure to
    :func:`cudal.cusp2.probability_of_passing`.

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

    expse2 = sigse**2
    expsm2 = expse2 + nn * sigsm**2

    pmean = probnorm((meanu - u) * np.sqrt(n / expsm2)) - probnorm(
        (meanl - u) * np.sqrt(n / expsm2)
    )
    pse = probchi(l * (nn - 1) * se**2 / expse2, l * (nn - 1)) - probchi(
        l * (nn - 1) * (se - dse) ** 2 / expse2, l * (nn - 1)
    )
    psm = probchi((l - 1) * nn * sm**2 / expsm2, l - 1) - probchi(
        (l - 1) * nn * (sm - dsm) ** 2 / expsm2, l - 1
    )
    psum = np.sum(pmean * pse * psm, axis=0)

    uu, ee, mm = np.meshgrid(
        np.asarray(u_values, dtype=float),
        np.asarray(sigse_values, dtype=float),
        np.asarray(sigsm_values, dtype=float),
        indexing="ij",
    )
    return pd.DataFrame(
        {
            "U": uu.ravel(),
            "SIGSE": ee.ravel(),
            "SIGSM": mm.ravel(),
            "PSUM": psum.ravel(),
        }
    )


def sample_probability(
    mean: float,
    se: float,
    sm: float,
    num: int,
    loc: int,
    ql: float,
    qu: float,
    cilevel: float,
) -> dict:
    """
    Given an observed sample MEAN, within-location SD (SE), and
    between-location SD (SM), computes the probability that future
    samples from that population will pass the USP <711> Extended-Release
    test.
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

    overbdl = extended_release_bound(llu, sigma, ql, qu)
    overbdu = extended_release_bound(ulu, sigma, ql, qu)
    overbd = min(overbdl, overbdu)

    return {
        "MEAN": mean,
        "SE": se,
        "SM": sm,
        "VAR": var,
        "MVAR": mvar,
        "SIGMA": sigma,
        "OVERBDL": overbdl,
        "OVERBDU": overbdu,
        "OVERBD": overbd,
    }
