# =============================================================================
# CuDAL R Verification Functions
# CUSP1 and CUSP2 Acceptance-Limit Table Calculations
# =============================================================================
#
# Purpose
# -------
# Independent R re-implementation of the PyCuDAL CUSP1 (Content Uniformity,
# Sampling Plan 1) and CUSP2 (Content Uniformity, Sampling Plan 2)
# acceptance-limit table calculations, USP <905>.
#
# This file is written to be read and verified line-by-line against the
# PyCuDAL Python source (cudal/core.py, cudal/cusp1.py, cudal/cusp2.py) by a
# second reviewer, then run on the shared test data set (Appendix G) so its
# output can be compared directly against PyCuDAL's own output.
#
# Design notes for the reviewer
# ------------------------------
# 1. Every root search below works on ONE grid point (one MEAN, or one
#    (SE, SM) pair) at a time, using base R's `uniroot()`. This is
#    deliberately simpler than a hand-rolled vectorized bisection: it is
#    slower, but every step is a call to a standard, well-tested R function,
#    which makes this file much easier to audit and trust.
#
# 2. `content_uniformity_bound()` never uses `ifelse(<scalar condition>, ...)`
#    with vector branches. That specific pattern is a known R pitfall:
#    `ifelse()`'s output length follows the length of its *condition*
#    argument, not its `yes`/`no` branches -- so if the condition happens to
#    be a single TRUE/FALSE (as it is here, since `target` is one fixed
#    value for an entire table) while the branches are vectors, R silently
#    truncates the result to length 1 and then recycles that single value
#    against everything downstream. Every element after the first ends up
#    silently reusing element 1's value. This file avoids the pattern
#    entirely: the target/label-claim branch (E) is computed once with a
#    plain `if/else` (correct, since `target` is always scalar here) and
#    then reused directly wherever the same branch is needed again, instead
#    of re-deriving it with a second `ifelse()`.
#
# =============================================================================


# =============================================================================
# SECTION 1: Core statistical primitives
# =============================================================================

#' Standard Normal Cumulative Distribution Function
#'
#' Direct wrapper around \code{pnorm()}. Named to match the SAS PROBNORM
#' function and the PyCuDAL \code{probnorm()} for side-by-side comparison.
#'
#' @param x Numeric. Value(s) at which to evaluate the standard normal CDF.
#' @return Numeric. P(Z <= x) for standard normal Z.
probnorm <- function(x) pnorm(x)

#' Standard Normal Quantile Function
#'
#' Direct wrapper around \code{qnorm()}. Matches SAS PROBIT / PyCuDAL
#' \code{probit()}.
#'
#' @param p Numeric. Probability (or probabilities), in (0, 1).
#' @return Numeric. The standard normal quantile (z-value) for p.
probit <- function(p) qnorm(p)

#' Chi-Square Cumulative Distribution Function
#'
#' Direct wrapper around \code{pchisq()}. Matches SAS PROBCHI / PyCuDAL
#' \code{probchi()}.
#'
#' @param x Numeric. Value(s) at which to evaluate the CDF.
#' @param df Numeric. Degrees of freedom.
#' @return Numeric. P(X <= x) for chi-square X with df degrees of freedom.
probchi <- function(x, df) pchisq(x, df)

#' Chi-Square Quantile Function
#'
#' Direct wrapper around \code{qchisq()}. Matches SAS CINV / PyCuDAL
#' \code{cinv()}.
#'
#' @param p Numeric. Probability.
#' @param df Numeric. Degrees of freedom.
#' @return Numeric. The chi-square quantile for p at df degrees of freedom.
cinv <- function(p, df) qchisq(p, df)

#' Content Uniformity Stage Probability
#'
#' Computes one stage's pass probability for the USP <905> Content Uniformity
#' test (Stage 1: n = 10, k = 2.4; Stage 2: n = 30, k = 2.0), via the same
#' h = 0.05 numerical (Riemann-sum) integration used by the original SAS
#' macros and by PyCuDAL's \code{_cu_stage_prob()}.
#'
#' All arguments here are scalars: this function is only ever called with a
#' single (mu, sigma) pair at a time (see the design note at the top of this
#' file), so no vector broadcasting is required or attempted.
#'
#' @param mu Numeric scalar. True population mean (% of label claim).
#' @param sigma Numeric scalar. True population standard deviation.
#' @param E Numeric scalar. Adjusted upper test limit (see
#'   \code{content_uniformity_bound}).
#' @param n Integer. Stage sample size (10 or 30).
#' @param k Numeric. Stage acceptance constant (2.4 or 2.0).
#' @return Numeric scalar. The stage pass probability.
cu_stage_prob <- function(mu, sigma, E, n, k) {
  h <- 0.05
  L1 <- 15.0

  z1 <- (E - mu) * sqrt(n) / sigma
  z2 <- (98.5 - mu) * sqrt(n) / sigma
  chi_a <- probchi((n - 1) * L1^2 / (k * sigma)^2, df = n - 1)
  int1 <- (probnorm(z1) - probnorm(z2)) * chi_a

  n_steps <- round(15 / h)

  # int2: Riemann sum over [E, E + 15), step h
  steps <- 0:(n_steps - 1)
  xs <- E + steps * h
  x1 <- (xs - mu) * sqrt(n) / sigma
  x2 <- (xs + h - mu) * sqrt(n) / sigma
  chi_args <- (n - 1) * (E + 15 - xs - h / 2)^2 / (k * sigma)^2
  int2 <- sum((probnorm(x2) - probnorm(x1)) * probchi(chi_args, df = n - 1))

  # int3: Riemann sum over [98.5 - 15, 98.5), step h
  xs3 <- 98.5 - 15 + steps * h
  x1b <- (xs3 - mu) * sqrt(n) / sigma
  x2b <- (xs3 + h - mu) * sqrt(n) / sigma
  chi_args3 <- (n - 1) * (15 - 98.5 + xs3 + h / 2)^2 / (k * sigma)^2
  int3 <- sum((probnorm(x2b) - probnorm(x1b)) * probchi(chi_args3, df = n - 1))

  int1 + int2 + int3
}

#' Content Uniformity Overall Pass-Probability Bound
#'
#' Estimated probability that a batch with true population mean \code{mu}
#' and true standard deviation \code{sigma} passes the USP <905> Content
#' Uniformity test (Stage 1 and Stage 2 combined), for label claim/target
#' \code{target}. Matches PyCuDAL's \code{content_uniformity_bound()}
#' exactly, including the Stage-2 compound tail term (P2b).
#'
#' \code{mu} and \code{sigma} are scalars in every call in this file (see the
#' design note at the top): \code{target} is always a single fixed value for
#' an entire acceptance-limit table, so there is no vector-broadcasting
#' concern here to begin with.
#'
#' @param mu Numeric scalar. True population mean (% of label claim).
#' @param sigma Numeric scalar. True population standard deviation.
#' @param target Numeric scalar. Label claim / target value (usually 100).
#' @return Numeric scalar. The overall pass probability ("OVERBD").
content_uniformity_bound <- function(mu, sigma, target) {
  E <- if (target <= 101.5) 101.5 else target

  P1 <- cu_stage_prob(mu, sigma, E, n = 10, k = 2.4)
  P2a <- cu_stage_prob(mu, sigma, E, n = 30, k = 2.0)

  zzz1 <- (123.125 - mu) / sigma
  zzz2 <- (E - 24.625 - mu) / sigma  # reuses E; see design note above
  P2b <- (probnorm(zzz1) - probnorm(zzz2))^30
  P2 <- max(0, P2a + P2b - 1)

  max(P1, P2)
}

#' Two-Tier Variance Components (CUSP2)
#'
#' Computes the total variance (VAR) and the upper-confidence-bound
#' between-location variance (MVAR) from the within-location standard
#' deviation (SE) and between-location standard deviation (SM). Matches
#' PyCuDAL's \code{_variance_components()}.
#'
#' @param se Numeric. Within-location standard deviation.
#' @param sm Numeric. Between-location standard deviation.
#' @param nn Integer. Units assayed per location.
#' @param l Integer. Number of locations.
#' @param chierr Numeric. Chi-square quantile for the error (within-location)
#'   variance component.
#' @param chiloc Numeric. Chi-square quantile for the location (between-
#'   location) variance component.
#' @return A list with elements \code{var} and \code{mvar}.
variance_components <- function(se, sm, nn, l, chierr, chiloc) {
  se2 <- se^2
  h2 <- l * (nn - 1) / chierr - 1
  sec <- ((1 - 1 / nn) * h2 * se2)^2

  sl2 <- sm^2 * nn
  sl2ub <- (l - 1) * sl2 / chiloc
  h1 <- (l - 1) / chiloc - 1
  first <- ((1 / nn) * h1 * sl2)^2

  ptest <- (1 / nn) * sl2 + (1 - 1 / nn) * se2
  var_val <- ptest + sqrt(first + sec)
  mvar_val <- sl2ub

  list(var = var_val, mvar = mvar_val)
}


# =============================================================================
# SECTION 2: Root finding (per grid point, via base R uniroot())
# =============================================================================

#' Find a Single Root of a Monotonically Decreasing Function
#'
#' Used by CUSP1: for a fixed candidate MEAN, the pass-probability bound is
#' monotonically decreasing in the candidate standard deviation, so it has at
#' most one crossing of the target probability in [lo, hi].
#'
#' @param f Function of one scalar argument, decreasing over [lo, hi].
#' @param lo,hi Numeric. Search interval.
#' @return A list with \code{root} (numeric) and \code{floor_fail} (logical,
#'   TRUE if even \code{f(lo)} is already below zero -- i.e. no standard
#'   deviation, however small, meets the requirement).
find_single_root <- function(f, lo, hi) {
  f_lo <- f(lo)
  if (f_lo < 0) {
    return(list(root = lo, floor_fail = TRUE))
  }
  f_hi <- f(hi)
  if (f_hi >= 0) {
    # Never crosses within [lo, hi]: even the least favorable case in range
    # still passes. Report hi, matching PyCuDAL's fallback convention.
    return(list(root = hi, floor_fail = FALSE))
  }
  root <- uniroot(f, interval = c(lo, hi))$root
  list(root = root, floor_fail = FALSE)
}

#' Find the First and Last Root of a Bump-Shaped Function
#'
#' Used by CUSP2: the pass-probability bound is bump-shaped in the candidate
#' MEAN (rises above the target probability, then falls again), so it has up
#' to two crossings in [lo, hi]. A coarse scan first brackets each crossing;
#' \code{uniroot()} then refines each bracket to a precise root.
#'
#' @param f Function of one scalar argument.
#' @param lo,hi Numeric. Search interval.
#' @param scan_points Integer. Number of points used to bracket the crossings
#'   before refining (default 200 -- the interval here typically spans
#'   40-50 units, so this resolves brackets to roughly 0.2-0.25 units before
#'   \code{uniroot()} refines further).
#' @return A list with \code{first} and \code{last} (each NA if no crossing
#'   was found).
find_first_last_root <- function(f, lo, hi, scan_points = 200) {
  xs <- seq(lo, hi, length.out = scan_points)
  vals <- vapply(xs, f, numeric(1))
  s <- sign(vals)
  chg <- which(diff(s) != 0)

  if (length(chg) == 0) {
    return(list(first = NA_real_, last = NA_real_))
  }

  first_i <- chg[1]
  last_i <- chg[length(chg)]
  first_root <- uniroot(f, interval = c(xs[first_i], xs[first_i + 1]))$root
  last_root <- uniroot(f, interval = c(xs[last_i], xs[last_i + 1]))$root

  list(first = first_root, last = last_root)
}


# =============================================================================
# SECTION 3: CUSP1 -- Content Uniformity, Sampling Plan 1
# =============================================================================

#' CUSP1 Acceptance-Limit Table
#'
#' For each candidate sample MEAN in the grid, finds the largest sample %CV
#' for which the probability of passing USP <905> still meets the required
#' lower bound at the given confidence level. Matches PyCuDAL's
#' \code{cusp1.acceptance_limit_table()}.
#'
#' @param number Integer. Sample size (N).
#' @param target Numeric. Label claim / target (usually 100).
#' @param lbound Numeric. Required lower bound on pass probability, as a
#'   percentage (e.g. 95 for 95%).
#' @param cilevel Numeric. Confidence level, as a percentage (e.g. 95).
#' @param mean_low Numeric. Low end of the candidate MEAN grid (default 85.1).
#' @param mean_high Numeric. High end of the candidate MEAN grid (default 114.9).
#' @param mean_step Numeric. Step size of the candidate MEAN grid (default 0.1).
#'
#' @return A data frame with columns \code{MEAN} and \code{CV}. A CV of 0
#'   marks a mean where even a (near) zero standard deviation fails to meet
#'   the bound.
cusp1_acceptance_limit_table <- function(number, target, lbound, cilevel,
                                          mean_low = 85.1, mean_high = 114.9,
                                          mean_step = 0.1) {
  z <- probit((1 + sqrt(cilevel / 100)) / 2)
  n <- number
  chi <- cinv(1 - sqrt(cilevel / 100), df = n - 1)
  target_prob <- lbound / 100

  means <- seq(mean_low, mean_high, by = mean_step)
  cv <- numeric(length(means))

  for (i in seq_along(means)) {
    mean_i <- means[i]

    f <- function(sd) {
      sigma <- sqrt((n - 1) * sd^2 / chi)
      llu <- mean_i - z * sigma / sqrt(n)
      ulu <- mean_i + z * sigma / sqrt(n)
      overlbd <- content_uniformity_bound(llu, sigma, target)
      overubd <- content_uniformity_bound(ulu, sigma, target)
      min(overlbd, overubd) - target_prob
    }

    res <- find_single_root(f, lo = 0.01, hi = 7.8)
    cv[i] <- if (res$floor_fail) 0 else 100 * res$root / mean_i
  }

  data.frame(MEAN = means, CV = cv)
}


# =============================================================================
# SECTION 4: CUSP2 -- Content Uniformity, Sampling Plan 2
# =============================================================================

#' CUSP2 Acceptance-Limit Table
#'
#' For each (SE, SM) combination, finds the acceptable range of sample mean
#' [MEANL, MEANU] for which the probability of passing USP <905> meets the
#' required lower bound. Matches PyCuDAL's \code{cusp2.acceptance_limit_table()}.
#'
#' @param num Integer. Units assayed per location.
#' @param loc Integer. Number of locations.
#' @param target Numeric. Label claim / target (usually 100).
#' @param lbound Numeric. Required lower bound on pass probability (%).
#' @param cilevel Numeric. Confidence level (%).
#' @param se_values Numeric vector. Within-location standard deviations to
#'   evaluate.
#' @param sm_values Numeric vector. Between-location standard deviations to
#'   evaluate.
#' @param mean_search_range Numeric vector of length 2. Search bounds for the
#'   mean (default c(80, 120)).
#'
#' @return A data frame with columns \code{SE}, \code{SM}, \code{MEANL},
#'   \code{MEANU}. MEANL/MEANU are \code{NA} where no acceptable mean range
#'   exists for that (SE, SM) combination.
cusp2_acceptance_limit_table <- function(num, loc, target, lbound, cilevel,
                                          se_values, sm_values,
                                          mean_search_range = c(80.0, 120.0)) {
  nn <- num
  l <- loc
  n <- nn * l
  z <- probit((1 + sqrt(cilevel / 100)) / 2)
  chierr <- cinv(1 - sqrt(cilevel / 100), df = l * (nn - 1))
  chiloc <- cinv(1 - sqrt(cilevel / 100), df = l - 1)
  target_prob <- lbound / 100
  lo <- mean_search_range[1]
  hi <- mean_search_range[2]

  grid <- expand.grid(SE = se_values, SM = sm_values)
  n_grid <- nrow(grid)
  meanl <- numeric(n_grid)
  meanu <- numeric(n_grid)

  for (i in seq_len(n_grid)) {
    se_i <- grid$SE[i]
    sm_i <- grid$SM[i]

    vc <- variance_components(se_i, sm_i, nn, l, chierr, chiloc)
    sigma <- sqrt(vc$var)
    se_of_mean <- sqrt(vc$mvar / n)

    f <- function(mean_val) {
      llu <- mean_val - z * se_of_mean
      ulu <- mean_val + z * se_of_mean
      overlbd <- content_uniformity_bound(llu, sigma, target)
      overubd <- content_uniformity_bound(ulu, sigma, target)
      min(overlbd, overubd) - target_prob
    }

    res <- find_first_last_root(f, lo, hi)

    if (is.na(res$first) || is.na(res$last) || res$last <= res$first) {
      meanl[i] <- NA_real_
      meanu[i] <- NA_real_
    } else {
      meanl[i] <- res$first
      meanu[i] <- res$last
    }
  }

  data.frame(SE = grid$SE, SM = grid$SM, MEANL = meanl, MEANU = meanu)
}
