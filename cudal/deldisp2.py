"""
cudal.deldisp2
==============

USP <711> Delayed-Release Dissolution, Sampling Plan 2 (multiple
locations, variance-components model): combined Acid Stage (Acceptance
Table 3) + Buffer Stage (Acceptance Table 4).

.. note::
   As with the other new modules in this package, this is a fresh
   derivation extending CuDAL's methodology to a USP <711> category not
   covered by the original SAS system. See
   :func:`cudal.core.delayed_release_bound`.

Modeling simplification
------------------------
Following :mod:`cudal.deldisp1`, the Acid Stage's performance (mean and
%CV, assumed single-location / not modeled with location-to-location
variance components) is treated as a **fixed, given input**, and the
acceptance-limit search is performed only over the Buffer Stage's
within-/between-location variance-components model -- structurally
identical to :mod:`cudal.disp2` (single-sided, one MEANL boundary per
(SE, SM) cell, since Buffer Stage Acceptance Table 4 has only a lower
bound, just like Immediate-Release).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import (
    batched_root_find,
    cinv,
    delayed_release_bound,
    probchi,
    probit,
    probnorm,
)
from .cusp2 import _variance_components


def acceptance_limit_table(
    num: int,
    loc: int,
    mean_acid: float,
    cv_acid: float,
    number_acid: int,
    q_buffer: float,
    lbound: float,
    cilevel: float,
    se_values,
    sm_values,
    meanadj_search_range=(-20.0, 100.0),
) -> pd.DataFrame:
    """
    Holding the Acid Stage's observed performance fixed, finds -- for each
    (SE, SM) Buffer Stage combination -- the smallest acceptable Buffer
    Stage sample mean for which the combined probability of passing the
    USP <711> Delayed-Release test meets the required lower bound.

    Parameters
    ----------
    num : int
        Buffer Stage units assayed per location.
    loc : int
        Number of locations.
    mean_acid, cv_acid : float
        Fixed, given Acid Stage sample mean and %CV (% dissolved).
    number_acid : int
        Acid Stage sample size (may differ from the Buffer Stage's
        ``num * loc``, since the Acid Stage is treated as single-location
        per the simplification above).
    q_buffer : float
        Buffer Stage Q value (% dissolved); 75% unless the monograph
        specifies otherwise.
    lbound, cilevel : float
        Required lower bound (%) and confidence level (%).
    se_values, sm_values : iterable of float
        Grids of Buffer Stage within-location (SE) and between-location
        (SM) standard deviations to evaluate.
    meanadj_search_range : (float, float)
        Search bounds for the Buffer Stage mean adjustment
        (mean - q_buffer).

    Returns
    -------
    pandas.DataFrame with columns ["SE", "SM", "MEAN"] (Buffer Stage
    within-location SD, between-location SD, and the smallest acceptable
    Buffer Stage sample mean). MEAN is NaN where no acceptable mean
    exists for that (SE, SM).
    """
    nn, l = num, loc
    n = nn * l
    z_acid = probit(np.sqrt(cilevel / 100))
    chi_acid = cinv(1 - np.sqrt(cilevel / 100), number_acid - 1)
    sampsd_acid = mean_acid * cv_acid / 100
    sigma_acid = np.sqrt((number_acid - 1) * sampsd_acid**2 / chi_acid)
    llu_acid = mean_acid - z_acid * sigma_acid / np.sqrt(number_acid)

    z = probit(np.sqrt(cilevel / 100))
    chierr = cinv(1 - np.sqrt(cilevel / 100), l * (nn - 1))
    chiloc = cinv(1 - np.sqrt(cilevel / 100), l - 1)
    target_prob = lbound / 100
    lo, hi = meanadj_search_range

    se_grid, sm_grid = np.meshgrid(
        np.asarray(se_values, dtype=float),
        np.asarray(sm_values, dtype=float),
        indexing="ij",
    )
    se_flat = se_grid.ravel()
    sm_flat = sm_grid.ravel()

    var, mvar = _variance_components(se_flat, sm_flat, nn, l, chierr, chiloc)
    sigma_buffer = np.sqrt(var)
    se_of_mean = np.sqrt(mvar / n)

    def func(meanadj):
        mean_lo_buffer = (meanadj + q_buffer) - z * se_of_mean
        return (
            delayed_release_bound(llu_acid, sigma_acid, mean_lo_buffer, sigma_buffer, q_buffer)
            - target_prob
        )

    meanl, found = batched_root_find(func, lo, hi, which="first")
    mean = np.where(found, meanl + q_buffer, np.nan)

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
    One-sided analogue of :func:`cudal.cusp2.probability_of_passing`,
    identical in structure to :func:`cudal.disp2.probability_of_passing`.

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

    expse2 = sigse**2
    expsm2 = expse2 + nn * sigsm**2

    pmean = 1 - probnorm((mean - u) * np.sqrt(n / expsm2))
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
    mean_acid: float,
    cv_acid: float,
    number_acid: int,
    mean_buffer: float,
    se_buffer: float,
    sm_buffer: float,
    num: int,
    loc: int,
    q_buffer: float,
    cilevel: float,
) -> dict:
    """
    Given observed Acid Stage sample statistics and observed Buffer Stage
    mean / within-location SD / between-location SD, computes the
    combined probability that future samples will pass the USP <711>
    Delayed-Release test.
    """
    z_acid = probit(np.sqrt(cilevel / 100))
    chi_acid = cinv(1 - np.sqrt(cilevel / 100), number_acid - 1)
    sampsd_acid = mean_acid * cv_acid / 100
    sigma_acid = np.sqrt((number_acid - 1) * sampsd_acid**2 / chi_acid)
    llu_acid = mean_acid - z_acid * sigma_acid / np.sqrt(number_acid)

    nn, l = num, loc
    n = nn * l
    z = probit(np.sqrt(cilevel / 100))
    chierr = cinv(1 - np.sqrt(cilevel / 100), l * (nn - 1))
    chiloc = cinv(1 - np.sqrt(cilevel / 100), l - 1)

    var, mvar = _variance_components(se_buffer, sm_buffer, nn, l, chierr, chiloc)
    sigma_buffer = np.sqrt(var)
    se_of_mean = np.sqrt(mvar / n)
    mean_lo_buffer = mean_buffer - z * se_of_mean

    overbd = delayed_release_bound(llu_acid, sigma_acid, mean_lo_buffer, sigma_buffer, q_buffer)

    return {
        "MEAN_ACID": mean_acid,
        "CV_ACID": cv_acid,
        "MEAN_BUFFER": mean_buffer,
        "SE_BUFFER": se_buffer,
        "SM_BUFFER": sm_buffer,
        "VAR_BUFFER": var,
        "MVAR_BUFFER": mvar,
        "SIGMA_BUFFER": sigma_buffer,
        "OVERBD": overbd,
    }
