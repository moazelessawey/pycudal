"""
cudal.cusp1
===========

Translation of ``cusp1.sas`` -- Content Uniformity, Sampling Plan 1
(single location / composite sample, USP <905>).

Three analyses, matching the three SAS entry points:

  * :func:`acceptance_limit_table`  (``CALCUSP1`` / ``PRTCUSP1``, A1CUSP1=Y)
  * :func:`probability_of_passing`  (``EVCUSP1``, A2CUSP1=Y)
  * :func:`sample_probability`      (``SMPCUSP1``, A3CUSP1=Y)

Performance
-----------
``acceptance_limit_table`` finds, for every candidate MEAN in the grid,
the boundary standard deviation where the pass-probability crosses the
required bound. Rather than looping over means one at a time (each doing
its own root search), all means are solved *simultaneously* with
:func:`cudal.core.batched_root_find` -- a handful of vectorized numpy
calls covering the whole table instead of hundreds of individual ones.

``probability_of_passing`` vectorizes across the full (U, CV) grid at
once using broadcasting, rather than a Python loop over each combination.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import batched_root_find, cinv, content_uniformity_bound, probchi, probit, probnorm


def acceptance_limit_table(
    number: int,
    target: float,
    lbound: float,
    cilevel: float,
    mean_low: float = 85.1,
    mean_high: float = 114.9,
    mean_step: float = 0.1,
) -> pd.DataFrame:
    """
    SAS: ``%CALCUSP1`` (called when A1CUSP1=Y or A2CUSP1=Y).

    For each candidate sample MEAN, finds the largest sample standard
    deviation (expressed as CV%) for which the probability of passing
    USP <905> is still at least ``lbound`` (given as a percentage, e.g.
    95 for 95%) with ``cilevel``% confidence, for ``number`` (N) units
    and a label claim ``target``.

    The whole MEAN grid is solved in one vectorized batch (see module
    docstring) rather than one root-search per mean.

    Returns
    -------
    pandas.DataFrame with columns ["MEAN", "CV"].
    A CV of 0.0 marks a mean where even a (near) zero standard
    deviation batch would not meet the bound -- SAS's "CV = 0" branch.
    """
    z = probit((1 + np.sqrt(cilevel / 100)) / 2)
    n = number
    chi = cinv(1 - np.sqrt(cilevel / 100), n - 1)
    target_prob = lbound / 100

    means = np.round(np.arange(mean_low, mean_high + mean_step / 2, mean_step), 6)

    def overbd_of_sd(sampsd):
        # sampsd broadcasts against `means` (row vector (S,1) x (M,) -> (S,M),
        # or shape (M,) during the bisection refinement stage).
        sigma = np.sqrt((n - 1) * sampsd**2 / chi)
        llu = means - z * sigma / np.sqrt(n)
        ulu = means + z * sigma / np.sqrt(n)
        overlbd = content_uniformity_bound(llu, sigma, target)
        overubd = content_uniformity_bound(ulu, sigma, target)
        return np.minimum(overlbd, overubd) - target_prob

    sd_lo, sd_hi = 0.01, 7.8
    root, found = batched_root_find(overbd_of_sd, sd_lo, sd_hi)

    floor_fail = overbd_of_sd(np.full_like(means, sd_lo)) < 0  # even minimal SD fails -> CV = 0
    sd = np.where(floor_fail, sd_lo, np.where(found, root, sd_hi))
    cv = np.where(floor_fail, 0.0, 100 * sd / means)

    return pd.DataFrame({"MEAN": means, "CV": cv})


def probability_of_passing(
    table: pd.DataFrame,
    number: int,
    u_values,
    cv_values,
) -> pd.DataFrame:
    """
    SAS: ``%EVCUSP1`` / ``%SIGCUSP1`` (A2CUSP1=Y).

    Given the acceptance-limit ``table`` from :func:`acceptance_limit_table`
    (columns MEAN, CV), evaluate -- for every combination of assumed true
    population mean ``U`` and true population CV -- the probability that a
    sample of size ``number`` drawn from that population lands inside the
    acceptance region traced out by the table (a trapezoid-style sum over
    each pair of adjacent MEAN/CV/STD table entries, exactly reproducing
    the running ``PTRAP + PT`` accumulation in ``%SIGCUSP1``).

    The full (row, U, CV) computation is done as one broadcasted numpy
    array rather than a Python loop over (U, CV) pairs.

    Returns
    -------
    pandas.DataFrame with columns ["U", "CV", "PTRAP"] -- PTRAP is the
    estimated probability of passing.
    """
    t = table.sort_values("MEAN").reset_index(drop=True)
    x = t["MEAN"].to_numpy()
    std = (t["MEAN"] * t["CV"] / 100).to_numpy()
    n = number

    u = np.asarray(u_values, dtype=float)[None, :, None]  # (1, U, 1)
    cv = np.asarray(cv_values, dtype=float)[None, None, :]  # (1, 1, CV)
    sigma = u * cv / 100  # (1, U, CV)

    x_hi = x[1:, None, None]  # (R-1, 1, 1)
    x_lo = x[:-1, None, None]
    std_hi = std[1:, None, None]
    std_lo = std[:-1, None, None]

    pmean = probnorm((x_hi - u) * np.sqrt(n) / sigma) - probnorm((x_lo - u) * np.sqrt(n) / sigma)
    aveht = (std_hi + std_lo) / 2
    pstd = probchi((n - 1) * aveht**2 / sigma**2, n - 1)
    ptrap = np.sum(pmean * pstd, axis=0)  # (U, CV)

    u_flat = np.asarray(u_values, dtype=float)
    cv_flat = np.asarray(cv_values, dtype=float)
    uu, cc = np.meshgrid(u_flat, cv_flat, indexing="ij")
    return pd.DataFrame({"U": uu.ravel(), "CV": cc.ravel(), "PTRAP": ptrap.ravel()})


def sample_probability(
    mean: float,
    cv: float,
    number: int,
    target: float,
    lbound: float,
    cilevel: float,
) -> dict:
    """
    SAS: ``%SMPCUSP1`` (A3CUSP1=Y).

    Given an observed sample ``mean`` (% claim) and ``cv`` (%), directly
    computes the sample standard deviation and the probability
    ("OVERBD") that future samples from that population will pass
    USP <905>, for ``number`` units, label claim ``target``, at
    ``cilevel``% confidence with the requested ``lbound``% lower bound
    (lbound/cilevel are only used to report context; OVERBD itself does
    not depend on lbound, mirroring the SAS code).

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

    overlbd = content_uniformity_bound(llu, sigma, target)
    overubd = content_uniformity_bound(ulu, sigma, target)
    overbd = min(overlbd, overubd)

    return {"MEAN": mean, "CV": cv, "SAMPSD": sampsd, "OVERBD": overbd}
