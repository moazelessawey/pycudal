"""
cudal.deldisp1
==============

USP <711> Delayed-Release Dissolution, Sampling Plan 1 (single location):
combined Acid Stage (Acceptance Table 3) + Buffer Stage (Acceptance
Table 4).

.. note::
   As with :mod:`cudal.extdisp1`/:mod:`cudal.extdisp2`, this is a new
   derivation -- Delayed-Release was not part of the original SAS CuDAL
   system. See :func:`cudal.core.delayed_release_bound` for the full
   derivation, including the documented independence assumption between
   the Acid Stage and Buffer Stage.

Modeling simplification
------------------------
A full two-stage acceptance-limit search (over both Acid-Stage and
Buffer-Stage sample statistics simultaneously) is a substantially harder
problem than anything else in this package. As a documented, deliberate
simplification, the Acid Stage's performance (its sample mean and %CV) is
treated as a **fixed, given input** to :func:`acceptance_limit_table` and
:func:`probability_of_passing` -- reflecting that acid resistance is
typically a well-characterized, tightly-controlled coating property --
and the acceptance-limit search is performed only over the Buffer Stage's
mean, exactly as in :mod:`cudal.disp1` (a one-sided "at least Q"
criterion, since the Buffer Stage's Acceptance Table 4 is structurally
identical to Immediate-Release's Acceptance Table 1).

:func:`sample_probability` has no such restriction: it accepts observed
Acid-Stage *and* Buffer-Stage statistics directly and returns the full
combined probability, with no simplification needed.
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


def acceptance_limit_table(
    number: int,
    mean_acid: float,
    cv_acid: float,
    q_buffer: float,
    lbound: float,
    cilevel: float,
    mean_low: float = None,
    mean_high: float = None,
    mean_step: float = 0.2,
) -> pd.DataFrame:
    """
    Holding the Acid Stage's observed performance fixed, finds -- for each
    candidate Buffer Stage sample MEAN -- the largest Buffer Stage %CV for
    which the combined probability of passing the USP <711> Delayed-
    Release test still meets the required lower bound.

    Parameters
    ----------
    number : int
        Sample size N (assumed the same for Acid and Buffer Stage
        measurements, as they are performed on the same dosage units).
    mean_acid, cv_acid : float
        Fixed, given Acid Stage sample mean and %CV (% dissolved).
    q_buffer : float
        Buffer Stage Q value (% dissolved); 75% unless the monograph
        specifies otherwise.
    lbound, cilevel : float
        Required lower bound (%) and confidence level (%).
    mean_low, mean_high : float, optional
        Range of the candidate Buffer Stage MEAN grid. Defaults to
        ``(q_buffer, 100)``, since the Buffer Stage mean is a cumulative
        % dissolved and cannot sensibly be evaluated below Q.
    mean_step : float, default 0.2
        Step size of the candidate MEAN grid.

    Returns
    -------
    pandas.DataFrame with columns ["MEAN", "CV"] (Buffer Stage sample
    mean and %CV). A CV of 0.0 marks a mean where even a (near) zero
    standard deviation fails to meet the bound.
    """
    if mean_low is None:
        mean_low = q_buffer
    if mean_high is None:
        mean_high = 100.0

    z = probit(
        np.sqrt(cilevel / 100)
    )  # one-sided, as in disp1 (Buffer Stage is a lower-bound criterion)
    n = number
    chi = cinv(1 - np.sqrt(cilevel / 100), n - 1)
    target_prob = lbound / 100

    sampsd_acid = mean_acid * cv_acid / 100
    sigma_acid = np.sqrt((n - 1) * sampsd_acid**2 / chi)
    llu_acid = mean_acid - z * sigma_acid / np.sqrt(n)

    means = np.round(np.arange(mean_low, mean_high + mean_step / 2, mean_step), 6)

    def overbd_of_sd(sampsd_buffer):
        sigma_buffer = np.sqrt((n - 1) * sampsd_buffer**2 / chi)
        # Confidence lower bound on the *absolute* Buffer Stage mean (not
        # Q-shifted -- delayed_release_bound performs the Q-shift itself,
        # exactly as it does internally for llu_acid above).
        mean_lo_buffer = means - z * sigma_buffer / np.sqrt(n)
        return (
            delayed_release_bound(llu_acid, sigma_acid, mean_lo_buffer, sigma_buffer, q_buffer)
            - target_prob
        )

    sd_lo, sd_hi = 0.01, 30.0
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
    Given the Buffer Stage acceptance-limit table (with the Acid Stage
    held fixed as in :func:`acceptance_limit_table`), evaluates the
    probability of passing for a grid of assumed true Buffer Stage
    population means and %CVs. Same trapezoidal-style accumulation as
    :func:`cudal.disp1.probability_of_passing`.

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
    mean_acid: float,
    cv_acid: float,
    mean_buffer: float,
    cv_buffer: float,
    number: int,
    q_buffer: float,
    cilevel: float,
) -> dict:
    """
    Given observed Acid Stage and Buffer Stage sample statistics, computes
    the combined probability that future samples will pass the USP <711>
    Delayed-Release test.

    Parameters
    ----------
    mean_acid, cv_acid : float
        Observed Acid Stage sample mean and %CV (% dissolved).
    mean_buffer, cv_buffer : float
        Observed Buffer Stage sample mean (cumulative % dissolved) and
        %CV.
    number : int
        Sample size N.
    q_buffer : float
        Buffer Stage Q value (% dissolved); 75% unless the monograph
        specifies otherwise.
    cilevel : float
        Confidence level (%).

    Returns
    -------
    dict with keys: MEAN_ACID, CV_ACID, MEAN_BUFFER, CV_BUFFER, OVERBD
    """
    z = probit(np.sqrt(cilevel / 100))
    n = number
    chi = cinv(1 - np.sqrt(cilevel / 100), n - 1)

    sampsd_acid = mean_acid * cv_acid / 100
    sigma_acid = np.sqrt((n - 1) * sampsd_acid**2 / chi)
    llu_acid = mean_acid - z * sigma_acid / np.sqrt(n)

    sampsd_buffer = mean_buffer * cv_buffer / 100
    sigma_buffer = np.sqrt((n - 1) * sampsd_buffer**2 / chi)
    # Confidence lower bound on the *absolute* Buffer Stage mean (not
    # Q-shifted -- delayed_release_bound performs the Q-shift itself).
    mean_lo_buffer = mean_buffer - z * sigma_buffer / np.sqrt(n)

    overbd = delayed_release_bound(llu_acid, sigma_acid, mean_lo_buffer, sigma_buffer, q_buffer)

    return {
        "MEAN_ACID": mean_acid,
        "CV_ACID": cv_acid,
        "MEAN_BUFFER": mean_buffer,
        "CV_BUFFER": cv_buffer,
        "OVERBD": overbd,
    }
