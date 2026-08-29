# ===========================================================================
# CuDAL System: Content Uniformity and Dissolution Acceptance Limits
# Combined R Implementation (Core, CUSP1, CUSP2, DISP1, DISP2)
# ===========================================================================


# ===========================================================================
# SECTION 1: CORE STATISTICAL UTILITIES & PROBABILITY ENGINES
# ===========================================================================

#' Calculate Content Uniformity Stage Probability
#'
#' Computes a single stage probability for the USP <905> Content Uniformity test
#' using discrete numerical integration over specific windows, matching the original
#' macro's h=0.05 step size.
#'
#' @param mu Numeric vector. True population mean (% of label claim).
#' @param sigma Numeric vector. True population standard deviation (% of label claim).
#' @param E Numeric vector. Adjusted target value for the test limit.
#' @param n Integer. Number of samples for the specific stage (10 for Stage 1, 30 for Stage 2).
#' @param k Numeric. Acceptance constant for the stage (2.4 for Stage 1, 2.0 for Stage 2).
#'
#' @return A numeric vector representing pass probabilities for each element.
cu_stage_prob <- function(mu, sigma, E, n, k) {
  h <- 0.05
  L1 <- 15.0
  z1 <- (E - mu) * sqrt(n) / sigma
  z2 <- (98.5 - mu) * sqrt(n) / sigma
  chi_a <- pchisq((n - 1) * L1^2 / (k * sigma)^2, df = n - 1)
  int1 <- (pnorm(z1) - pnorm(z2)) * chi_a

  int2 <- numeric(length(mu))
  int3 <- numeric(length(mu))

  n_steps <- round(15 / h)
  for (step in 0:(n_steps - 1)) {
    xs <- E + step * h
    x1 <- (xs - mu) * sqrt(n) / sigma
    x2 <- (xs + h - mu) * sqrt(n) / sigma
    chi_args <- (n - 1) * (E + 15 - xs - h / 2)^2 / (k * sigma)^2
    int2 <- int2 + (pnorm(x2) - pnorm(x1)) * pchisq(chi_args, df = n - 1)
  }

  xs3 <- seq(98.5 - 15, 98.5 - h, by = h)
  for (xs_val in xs3) {
    x1b <- (xs_val - mu) * sqrt(n) / sigma
    x2b <- (xs_val + h - mu) * sqrt(n) / sigma
    chi_args3 <- (n - 1) * (15 - 98.5 + xs_val + h / 2)^2 / (k * sigma)^2
    int3 <- int3 + (pnorm(x2b) - pnorm(x1b)) * pchisq(chi_args3, df = n - 1)
  }

  return(int1 + int2 + int3)
}

#' Content Uniformity Overall Bound
#'
#' Evaluates the total estimated probability that a batch passes the USP <905>
#' Content Uniformity test by calculating both Stage 1 and Stage 2 probabilities
#' and accounting for the compound tail term. Replicates the c1calc macro logic.
#'
#' @param mu Numeric vector. True population mean (% of label claim).
#' @param sigma Numeric vector. True population standard deviation (% of label claim).
#' @param target Numeric vector or scalar. Label claim / target value (usually 100).
#'
#' @return Numeric vector of overall pass probability bounds (OVERBD).
content_uniformity_bound <- function(mu, sigma, target) {
  E <- ifelse(target <= 101.5, 101.5, target)

  P1 <- cu_stage_prob(mu, sigma, E, n = 10, k = 2.4)
  P2a <- cu_stage_prob(mu, sigma, E, n = 30, k = 2.0)

  zzz1 <- (123.125 - mu) / sigma
  zzz2 <- ifelse(target <= 101.5,
                 (101.5 - 24.625 - mu) / sigma,
                 (target - 24.625 - mu) / sigma)
  P2b <- (pnorm(zzz1) - pnorm(zzz2))^30
  P2 <- pmax(0, P2a + P2b - 1)

  return(pmax(P1, P2))
}

#' Dissolution Overall Bound
#'
#' Evaluates the total estimated probability that a batch passes the USP <711>
#' Dissolution test across Stage 1 (n=6), Stage 2 (n=12), and Stage 3 (n=24).
#' Replicates the COMPUTE macro logic.
#'
#' @param llu Numeric vector. Lower adjusted bound on population mean.
#' @param sigma Numeric vector. Population standard deviation.
#'
#' @return Numeric vector of max overall dissolution pass probabilities across stages.
dissolution_bound <- function(llu, sigma) {
  F1 <- (1 - pnorm((5 - llu) / sigma))^6

  sn2 <- sqrt(12)
  pm2 <- pnorm(sn2 * (-llu) / sigma)
  pb2 <- 1 - pnorm((-15 - llu) / sigma)
  F2 <- pb2^12 - pm2

  sn3 <- sqrt(24)
  pm3 <- pnorm(sn3 * (-llu) / sigma)
  p2 <- pnorm((-15 - llu) / sigma) - pnorm((-25 - llu) / sigma)
  p3 <- 1 - pnorm((-15 - llu) / sigma)
  F3 <- p3^24 + 24 * p2 * p3^23 + 276 * p2^2 * p3^22 - pm3

  return(pmax(pmax(F1, F2), F3))
}

#' Compute Two-Tier Variance Components
#'
#' Calculates the total variance (VAR) and upper bound on between-location variance
#' (MVAR) for Sampling Plan 2 models.
#'
#' @param se Numeric vector. Within-location standard deviation.
#' @param sm Numeric vector. Between-location standard deviation.
#' @param nn Integer. Assays per location.
#' @param l Integer. Number of locations.
#' @param chierr Numeric. Lower quantile of error chi-square distribution.
#' @param chiloc Numeric. Lower quantile of location chi-square distribution.
#'
#' @return A list with elements \code{var} and \code{mvar}.
variance_components <- function(se, sm, nn, l, chierr, chiloc) {
  se2 <- se^2
  h2 <- l * (nn - 1) / chierr - 1
  sec <- ((1 - 1/nn) * h2 * se2)^2

  sl2 <- sm^2 * nn
  sl2ub <- (l - 1) * sl2 / chiloc
  h1 <- (l - 1) / chiloc - 1
  first <- ((1/nn) * h1 * sl2)^2

  ptest <- (1/nn) * sl2 + (1 - 1/nn) * se2
  var_val <- ptest + sqrt(first + sec)
  mvar_val <- sl2ub

  list(var = var_val, mvar = mvar_val)
}

#' Batched Grid Root Finder
#'
#' Evaluates roots for a target probability function across an entire grid simultaneously
#' using vectorized linear scanning and iterative bisection refinement.
#'
#' @param func Function accepting a vector of test candidate values and returning residuals.
#' @param lo Numeric. Lower search boundary.
#' @param hi Numeric. Upper search boundary.
#' @param grid_size Integer. Number of grid elements being evaluated simultaneously.
#' @param scan_points Integer. Initial linear scan resolution (default 12).
#' @param bisect_iters Integer. Bisection refinement iterations (default 22).
#' @param which Character. "first" for lowest-x root, "last" for highest-x root.
#'
#' @return A list containing \code{root} (vector of solutions) and \code{found} (logical vector).
batched_root_find <- function(func, lo, hi, grid_size, scan_points = 12, bisect_iters = 22, which = "first") {
  xs <- seq(lo, hi, length.out = scan_points)
  vals <- matrix(0, nrow = scan_points, ncol = grid_size)

  for (i in seq_along(xs)) {
    vals[i, ] <- func(rep(xs[i], grid_size))
  }

  signs <- sign(vals)
  changes <- diff(signs) != 0
  found <- apply(changes, 2, any)
  idx <- integer(grid_size)

  for (j in seq_len(grid_size)) {
    if (found[j]) {
      idx[j] <- if (which == "first") which(changes[, j])[1] else tail(which(changes[, j]), 1)
    } else {
      idx[j] <- 1
    }
  }

  lo_x <- ifelse(found, xs[idx], lo)
  hi_x <- ifelse(found, xs[idx + 1], hi)

  lo_val <- numeric(grid_size)
  for (j in seq_len(grid_size)) {
    lo_val[j] <- ifelse(found[j], vals[idx[j], j], vals[1, j])
  }

  cur_lo <- lo_x
  cur_hi <- hi_x
  cur_lo_val <- lo_val

  for (iter in 1:bisect_iters) {
    mid <- (cur_lo + cur_hi) / 2
    f_mid <- func(mid)
    same_sign <- sign(f_mid) == sign(cur_lo_val)
    cur_lo <- ifelse(same_sign, mid, cur_lo)
    cur_hi <- ifelse(same_sign, cur_hi, mid)
    cur_lo_val <- ifelse(same_sign, f_mid, cur_lo_val)
  }

  return(list(root = (cur_lo + cur_hi) / 2, found = found))
}


# ===========================================================================
# SECTION 2: CONTENT UNIFORMITY SAMPLING PLAN 1 (CUSP1)
# ===========================================================================

#' CUSP1 Acceptance Limit Table
#'
#' Calculates the maximum allowed sample CV for each candidate mean under USP <905>
#' Plan 1 (single location)[cite: 5].
#'
#' @param number Integer. Sample size N.
#' @param target Numeric. Label claim target (e.g., 100.0).
#' @param lbound Numeric. Lower bound probability target percentage (e.g., 95.0).
#' @param cilevel Numeric. Confidence level percentage (e.g., 95.0).
#' @param mean_low Numeric. Minimum mean to evaluate (default 85.1).
#' @param mean_high Numeric. Maximum mean to evaluate (default 114.9).
#' @param mean_step Numeric. Increment step for mean grid (default 0.1).
#'
#' @return A data frame containing columns MEAN and CV.
cusp1_acceptance_limit_table <- function(number, target, lbound, cilevel,
                                         mean_low = 85.1, mean_high = 114.9, mean_step = 0.1) {
  z <- qnorm((1 + sqrt(cilevel / 100)) / 2)
  n <- number
  chi <- qchisq(1 - sqrt(cilevel / 100), df = n - 1)
  target_prob <- lbound / 100

  means <- round(seq(mean_low, mean_high, by = mean_step), 6)
  grid_size <- length(means)

  func <- function(sampsd) {
    sigma <- sqrt((n - 1) * sampsd^2 / chi)
    llu <- means - z * sigma / sqrt(n)
    ulu <- means + z * sigma / sqrt(n)
    overlbd <- content_uniformity_bound(llu, sigma, target)
    overubd <- content_uniformity_bound(ulu, sigma, target)
    pmin(overlbd, overubd) - target_prob
  }

  sd_lo <- 0.01
  sd_hi <- 7.8
  res <- batched_root_find(func, sd_lo, sd_hi, grid_size)

  floor_fail <- func(rep(sd_lo, grid_size)) < 0
  sd <- ifelse(floor_fail, sd_lo, ifelse(res$found, res$root, sd_hi))
  cv <- ifelse(floor_fail, 0.0, 100 * sd / means)

  data.frame(MEAN = means, CV = cv)
}

#' CUSP1 Probability of Passing Operating Characteristic
#'
#' Evaluates pass probability across operating characteristic grid (U x CV) for CUSP1[cite: 5].
#'
#' @param table Data frame. CUSP1 acceptance limit table containing MEAN and CV.
#' @param number Integer. Sample size N.
#' @param u_values Numeric vector. True population means to evaluate.
#' @param cv_values Numeric vector. True population CV percentages to evaluate.
#'
#' @return A data frame with columns U, CV, and PTRAP (pass probability).
cusp1_probability_of_passing <- function(table, number, u_values, cv_values) {
  t <- table[order(table$MEAN), ]
  n <- number

  grid <- expand.grid(x_idx = 1:(nrow(t) - 1), u = u_values, cv = cv_values)
  x_lo <- t$MEAN[grid$x_idx]
  x_hi <- t$MEAN[grid$x_idx + 1]
  std_lo <- (t$MEAN * t$CV / 100)[grid$x_idx]
  std_hi <- (t$MEAN * t$CV / 100)[grid$x_idx + 1]

  sigma <- grid$u * grid$cv / 100
  pmean <- pnorm((x_hi - grid$u) * sqrt(n) / sigma) - pnorm((x_lo - grid$u) * sqrt(n) / sigma)
  aveht <- (std_hi + std_lo) / 2
  pstd <- pchisq((n - 1) * aveht^2 / sigma^2, df = n - 1)

  grid$ptrap <- pmean * pstd
  res <- aggregate(ptrap ~ u + cv, data = grid, FUN = sum)
  names(res) <- c("U", "CV", "PTRAP")
  return(res)
}

#' CUSP1 Sample Pass Probability
#'
#' Computes direct USP <905> pass probability (OVERBD) for an observed sample mean and CV[cite: 5].
#'
#' @param mean Numeric. Observed sample mean (% of claim).
#' @param cv Numeric. Observed sample CV (%).
#' @param number Integer. Sample size N.
#' @param target Numeric. Label claim target.
#' @param lbound Numeric. Target probability lower bound.
#' @param cilevel Numeric. Confidence level.
#'
#' @return A list containing MEAN, CV, SAMPSD, and OVERBD.
cusp1_sample_probability <- function(mean, cv, number, target, lbound, cilevel) {
  z <- qnorm((1 + sqrt(cilevel / 100)) / 2)
  n <- number
  chi <- qchisq(1 - sqrt(cilevel / 100), df = n - 1)

  sampsd <- mean * cv / 100
  sigma <- sqrt((n - 1) * sampsd^2 / chi)
  llu <- mean - z * sigma / sqrt(n)
  ulu <- mean + z * sigma / sqrt(n)

  overlbd <- content_uniformity_bound(llu, sigma, target)
  overubd <- content_uniformity_bound(ulu, sigma, target)
  overbd <- min(overlbd, overubd)

  list(MEAN = mean, CV = cv, SAMPSD = sampsd, OVERBD = overbd)
}


# ===========================================================================
# SECTION 3: CONTENT UNIFORMITY SAMPLING PLAN 2 (CUSP2)
# ===========================================================================

#' CUSP2 Acceptance Limit Table
#'
#' Calculates lower and upper acceptable mean limits (MEANL, MEANU) across a grid
#' of SE and SM values for Content Uniformity Plan 2 (multiple locations).
#'
#' @param num Integer. Number of units assayed per location.
#' @param loc Integer. Number of locations sampled.
#' @param target Numeric. Label claim target value.
#' @param lbound Numeric. Lower bound probability target percentage.
#' @param cilevel Numeric. Confidence level percentage.
#' @param se_values Numeric vector. Within-location standard deviations.
#' @param sm_values Numeric vector. Between-location standard deviations.
#'
#' @return A data frame containing SE, SM, MEANL, and MEANU.
cusp2_acceptance_limit_table <- function(num, loc, target, lbound, cilevel, se_values, sm_values) {
  nn <- num
  l <- loc
  n <- nn * l
  z <- qnorm((1 + sqrt(cilevel / 100)) / 2)
  chierr <- qchisq(1 - sqrt(cilevel / 100), df = l * (nn - 1))
  chiloc <- qchisq(1 - sqrt(cilevel / 100), df = l - 1)
  target_prob <- lbound / 100

  grid <- expand.grid(SE = se_values, SM = sm_values)
  se_flat <- grid$SE
  sm_flat <- grid$SM
  grid_size <- length(se_flat)

  vc <- variance_components(se_flat, sm_flat, nn, l, chierr, chiloc)
  sigma <- sqrt(vc$var)
  se_of_mean <- sqrt(vc$mvar / n)

  func_lower <- function(mean_val) {
    llu <- mean_val - z * se_of_mean
    content_uniformity_bound(llu, sigma, target) - target_prob
  }

  func_upper <- function(mean_val) {
    ulu <- mean_val + z * se_of_mean
    content_uniformity_bound(ulu, sigma, target) - target_prob
  }

  res_lower <- batched_root_find(func_lower, 70, target, grid_size, which = "first")
  res_upper <- batched_root_find(func_upper, target, 130, grid_size, which = "last")

  meanl <- ifelse(res_lower$found, res_lower$root, NA)
  meanu <- ifelse(res_upper$found, res_upper$root, NA)

  data.frame(SE = se_flat, SM = sm_flat, MEANL = round(meanl, 1), MEANU = round(meanu, 1))
}

#' CUSP2 Probability of Passing Operating Characteristic
#'
#' Calculates total pass probabilities across true U, SIGSE, and SIGSM for CUSP2.
#'
#' @param table Data frame. CUSP2 acceptance limit table containing SE, SM, MEANL, MEANU.
#' @param num Integer. Assays per location.
#' @param loc Integer. Number of locations.
#' @param dse Numeric. SE step size used in table generation.
#' @param dsm Numeric. SM step size used in table generation.
#' @param u_values Numeric vector. Population mean values.
#' @param sigse_values Numeric vector. True within-location SDs.
#' @param sigsm_values Numeric vector. True between-location SDs.
#'
#' @return A data frame with columns U, SIGSE, SIGSM, and PSUM.
cusp2_probability_of_passing <- function(table, num, loc, dse, dsm, u_values, sigse_values, sigsm_values) {
  t <- table[!is.na(table$MEANL) & !is.na(table$MEANU), ]
  nn <- num
  l <- loc
  n <- nn * l

  grid <- expand.grid(row_idx = 1:nrow(t), u = u_values, sigse = sigse_values, sigsm = sigsm_values)
  se <- t$SE[grid$row_idx]
  sm <- t$SM[grid$row_idx]
  meanl <- t$MEANL[grid$row_idx]
  meanu <- t$MEANU[grid$row_idx]
  u <- grid$u
  sigse <- grid$sigse
  sigsm <- grid$sigsm

  expse2 <- sigse^2
  expsm2 <- expse2 + nn * sigsm^2

  pmean <- pnorm((meanu - u) * sqrt(n / expsm2)) - pnorm((meanl - u) * sqrt(n / expsm2))
  pse <- pchisq(l * (nn - 1) * se^2 / expse2, df = l * (nn - 1)) -
         pchisq(l * (nn - 1) * (se - dse)^2 / expse2, df = l * (nn - 1))
  psm <- pchisq((l - 1) * nn * sm^2 / expsm2, df = l - 1) -
         pchisq((l - 1) * nn * (sm - dsm)^2 / expsm2, df = l - 1)

  grid$psum <- pmean * pse * psm
  res <- aggregate(psum ~ u + sigse + sigsm, data = grid, FUN = sum)
  names(res) <- c("U", "SIGSE", "SIGSM", "PSUM")
  return(res)
}

#' CUSP2 Sample Pass Probability
#'
#' Evaluates direct USP <905> pass probability (OVERBD) given observed sample mean,
#' within-location SD (SE), and between-location SD (SM).
#'
#' @param mean Numeric. Observed sample mean.
#' @param se Numeric. Observed within-location SD.
#' @param sm Numeric. Observed between-location SD.
#' @param num Integer. Assays per location.
#' @param loc Integer. Number of locations.
#' @param target Numeric. Label claim target.
#' @param lbound Numeric. Lower bound target probability.
#' @param cilevel Numeric. Confidence level percentage.
#'
#' @return A list with elements MEAN, SE, SM, VAR, MVAR, SIGMA, and OVERBD.
cusp2_sample_probability <- function(mean, se, sm, num, loc, target, lbound, cilevel) {
  nn <- num
  l <- loc
  n <- nn * l
  z <- qnorm((1 + sqrt(cilevel / 100)) / 2)
  chierr <- qchisq(1 - sqrt(cilevel / 100), df = l * (nn - 1))
  chiloc <- qchisq(1 - sqrt(cilevel / 100), df = l - 1)

  vc <- variance_components(se, sm, nn, l, chierr, chiloc)
  sigma <- sqrt(vc$var)
  se_of_mean <- sqrt(vc$mvar / n)

  llu <- mean - z * se_of_mean
  ulu <- mean + z * se_of_mean

  overlbd <- content_uniformity_bound(llu, sigma, target)
  overubd <- content_uniformity_bound(ulu, sigma, target)
  overbd <- min(overlbd, overubd)

  list(MEAN = mean, SE = se, SM = sm, VAR = vc$var, MVAR = vc$mvar, SIGMA = sigma, OVERBD = overbd)
}


# ===========================================================================
# SECTION 4: DISSOLUTION SAMPLING PLAN 1 (DISP1)
# ===========================================================================

#' DISP1 Acceptance Limit Table
#'
#' Calculates maximum allowable sample CV values for dissolution testing under
#' USP <711> Plan 1 (single location)[cite: 6].
#'
#' @param number Integer. Sample size N.
#' @param q Numeric. USP Q value (% dissolved).
#' @param lbound Numeric. Target lower bound probability percentage.
#' @param cilevel Numeric. One-sided confidence level percentage[cite: 6].
#' @param meanadj_step Numeric. Increment step for adjusted mean grid (default 0.2)[cite: 6].
#'
#' @return A data frame containing MEAN and CV.
disp1_acceptance_limit_table <- function(number, q, lbound, cilevel, meanadj_step = 0.2) {
  lim <- 100 - q
  n <- number
  z <- qnorm(sqrt(cilevel / 100))
  chi <- qchisq(1 - sqrt(cilevel / 100), df = n - 1)
  target_prob <- lbound / 100

  meanadjs <- round(seq(meanadj_step, lim, by = meanadj_step), 6)
  grid_size <- length(meanadjs)

  func <- function(sampsd) {
    sigma <- sqrt((n - 1) * sampsd^2 / chi)
    llu <- meanadjs - z * sigma / sqrt(n)
    dissolution_bound(llu, sigma) - target_prob
  }

  sd_lo <- 0.002
  sd_hi <- 60.0
  res <- batched_root_find(func, sd_lo, sd_hi, grid_size)

  floor_fail <- func(rep(sd_lo, grid_size)) < 0
  sd <- ifelse(floor_fail, sd_lo, ifelse(res$found, res$root, sd_hi))
  mean_val <- meanadjs + q
  cv <- ifelse(floor_fail, 0.0, 100 * sd / mean_val)

  data.frame(MEAN = mean_val, CV = cv)
}

#' DISP1 Probability of Passing Operating Characteristic
#'
#' Evaluates overall pass probability for DISP1 across U and CV, including the upper tail
#' correction for rows where mean > 99.9[cite: 6].
#'
#' @param table Data frame. DISP1 acceptance table with MEAN and CV.
#' @param number Integer. Sample size N.
#' @param u_values Numeric vector. True mean values.
#' @param cv_values Numeric vector. True CV percentages.
#'
#' @return A data frame containing U, CV, and PTRAP.
disp1_probability_of_passing <- function(table, number, u_values, cv_values) {
  t <- table[order(table$MEAN), ]
  n <- number

  grid <- expand.grid(x_idx = 1:(nrow(t) - 1), u = u_values, cv = cv_values)
  x_lo <- t$MEAN[grid$x_idx]
  x_hi <- t$MEAN[grid$x_idx + 1]
  std_lo <- (t$MEAN * t$CV / 100)[grid$x_idx]
  std_hi <- (t$MEAN * t$CV / 100)[grid$x_idx + 1]

  sigma <- grid$u * grid$cv / 100
  pmean <- pnorm((x_hi - grid$u) * sqrt(n) / sigma) - pnorm((x_lo - grid$u) * sqrt(n) / sigma)
  aveht <- (std_hi + std_lo) / 2
  pstd <- pchisq((n - 1) * aveht^2 / sigma^2, df = n - 1)

  grid$ptrap <- pmean * pstd
  res <- aggregate(ptrap ~ u + cv, data = grid, FUN = sum)
  names(res) <- c("U", "CV", "PTRAP")

  tail_mask <- t$MEAN > 99.9
  if (any(tail_mask)) {
    t_tail <- t[tail_mask, ]
    tail_grid <- expand.grid(x_idx = 1:nrow(t_tail), u = u_values, cv = cv_values)
    xt <- t_tail$MEAN[tail_grid$x_idx]
    stdt <- (t_tail$MEAN * t_tail$CV / 100)[tail_grid$x_idx]
    sigma_t <- tail_grid$u * tail_grid$cv / 100

    pmean_t <- 1 - pnorm((xt - tail_grid$u) * sqrt(n) / sigma_t)
    pstd_t <- pchisq((n - 1) * stdt^2 / sigma_t^2, df = n - 1)

    tail_grid$ptrap_t <- pmean_t * pstd_t
    tail_res <- aggregate(ptrap_t ~ u + cv, data = tail_grid, FUN = sum)

    res <- merge(res, tail_res, by = c("U", "CV"), all.x = TRUE)
    res$ptrap_t[is.na(res$ptrap_t)] <- 0
    res$PTRAP <- res$PTRAP + res$ptrap_t
    res$ptrap_t <- NULL
  }

  return(res)
}

#' DISP1 Sample Pass Probability
#'
#' Directly calculates USP <711> pass probability (OVERBD) for an observed sample
#' mean (% dissolved) and CV (%)[cite: 6].
#'
#' @param mean Numeric. Observed sample mean (% dissolved).
#' @param cv Numeric. Observed sample CV (%).
#' @param number Integer. Sample size N.
#' @param q Numeric. USP Q value.
#' @param cilevel Numeric. One-sided confidence level.
#'
#' @return A list containing MEAN, CV, SAMPSD, and OVERBD.
disp1_sample_probability <- function(mean, cv, number, q, cilevel) {
  n <- number
  z <- qnorm(sqrt(cilevel / 100))
  chi <- qchisq(1 - sqrt(cilevel / 100), df = n - 1)

  meanadj <- mean - q
  sampsd <- mean * cv / 100
  sigma <- sqrt((n - 1) * sampsd^2 / chi)
  llu <- meanadj - z * sigma / sqrt(n)
  overbd <- dissolution_bound(llu, sigma)

  list(MEAN = mean, CV = cv, SAMPSD = sampsd, OVERBD = overbd)
}


# ===========================================================================
# SECTION 5: DISSOLUTION SAMPLING PLAN 2 (DISP2)
# ===========================================================================

#' DISP2 Acceptance Limit Table
#'
#' Finds minimum acceptable mean values (MEAN) across combinations of SE and SM
#' for USP <711> Plan 2 (multiple locations)[cite: 7].
#'
#' @param num Integer. Assays per location.
#' @param loc Integer. Number of locations sampled.
#' @param q Numeric. USP Q value (% dissolved).
#' @param lbound Numeric. Lower bound probability target percentage.
#' @param cilevel Numeric. One-sided confidence level percentage[cite: 6].
#' @param se_values Numeric vector. Within-location standard deviations.
#' @param sm_values Numeric vector. Between-location standard deviations.
#' @param meanadj_search_range Numeric vector. Min and max adjusted mean bounds (default c(-20.0, 100.0))[cite: 7].
#'
#' @return A data frame containing SE, SM, and MEAN.
disp2_acceptance_limit_table <- function(num, loc, q, lbound, cilevel,
                                         se_values, sm_values, meanadj_search_range = c(-20.0, 100.0)) {
  nn <- num
  l <- loc
  n <- nn * l
  lim <- 100 - q
  z <- qnorm(sqrt(cilevel / 100))
  chierr <- qchisq(1 - sqrt(cilevel / 100), df = l * (nn - 1))
  chiloc <- qchisq(1 - sqrt(cilevel / 100), df = l - 1)
  target_prob <- lbound / 100

  lo <- meanadj_search_range[1]
  hi <- min(meanadj_search_range[2], lim)

  grid <- expand.grid(SE = se_values, SM = sm_values)
  se_flat <- grid$SE
  sm_flat <- grid$SM
  grid_size <- length(se_flat)

  vc <- variance_components(se_flat, sm_flat, nn, l, chierr, chiloc)
  sigma <- sqrt(vc$var)
  se_of_mean <- sqrt(vc$mvar / n)

  func <- function(meanadj) {
    llu <- meanadj - z * se_of_mean
    dissolution_bound(llu, sigma) - target_prob
  }

  res <- batched_root_find(func, lo, hi, grid_size, which = "first")
  mean_val <- ifelse(res$found, res$root + q, NA)

  data.frame(SE = se_flat, SM = sm_flat, MEAN = mean_val)
}

#' DISP2 Probability of Passing Operating Characteristic
#'
#' One-sided operating characteristic probability accumulation over U, SIGSE, and SIGSM for DISP2[cite: 7].
#'
#' @param table Data frame. DISP2 acceptance table containing SE, SM, and MEAN.
#' @param num Integer. Assays per location.
#' @param loc Integer. Number of locations.
#' @param dse Numeric. SE grid step size.
#' @param dsm Numeric. SM grid step size.
#' @param u_values Numeric vector. True mean values.
#' @param sigse_values Numeric vector. True within-location SDs.
#' @param sigsm_values Numeric vector. True between-location SDs.
#'
#' @return A data frame containing U, SIGSE, SIGSM, and PSUM.
disp2_probability_of_passing <- function(table, num, loc, dse, dsm, u_values, sigse_values, sigsm_values) {
  t <- table[!is.na(table$MEAN), ]
  nn <- num
  l <- loc
  n <- nn * l

  grid <- expand.grid(row_idx = 1:nrow(t),
                      u = u_values,
                      sigse = sigse_values,
                      sigsm = sigsm_values)

  se <- t$SE[grid$row_idx]
  sm <- t$SM[grid$row_idx]
  mean_val <- t$MEAN[grid$row_idx]
  u <- grid$u
  sigse <- grid$sigse
  sigsm <- grid$sigsm

  expse2 <- sigse^2
  expsm2 <- expse2 + nn * sigsm^2

  pmean <- 1 - pnorm((mean_val - u) * sqrt(n / expsm2))

  pse <- pchisq(l * (nn - 1) * se^2 / expse2, df = l * (nn - 1)) -
         pchisq(l * (nn - 1) * (se - dse)^2 / expse2, df = l * (nn - 1))

  psm <- pchisq((l - 1) * nn * sm^2 / expsm2, df = l - 1) -
         pchisq((l - 1) * nn * (sm - dsm)^2 / expsm2, df = l - 1)

  grid$psum <- pmean * pse * psm
  res <- aggregate(psum ~ u + sigse + sigsm, data = grid, FUN = sum)
  names(res) <- c("U", "SIGSE", "SIGSM", "PSUM")

  return(res)
}

#' DISP2 Sample Pass Probability
#'
#' Evaluates direct USP <711> pass probability (OVERBD) given observed sample mean,
#' within-location SD (SE), and between-location SD (SM)[cite: 7].
#'
#' @param mean Numeric. Observed sample mean (% dissolved).
#' @param se Numeric. Observed within-location SD.
#' @param sm Numeric. Observed between-location SD.
#' @param num Integer. Assays per location.
#' @param loc Integer. Number of locations.
#' @param q Numeric. USP Q value.
#' @param cilevel Numeric. One-sided confidence level[cite: 6].
#'
#' @return A list with elements MEAN, SE, SM, VAR, MVAR, SIGMA, and OVERBD[cite: 7].
disp2_sample_probability <- function(mean, se, sm, num, loc, q, cilevel) {
  nn <- num
  l <- loc
  n <- nn * l
  z <- qnorm(sqrt(cilevel / 100))
  chierr <- qchisq(1 - sqrt(cilevel / 100), df = l * (nn - 1))
  chiloc <- qchisq(1 - sqrt(cilevel / 100), df = l - 1)

  vc <- variance_components(se, sm, nn, l, chierr, chiloc)
  sigma <- sqrt(vc$var)
  se_of_mean <- sqrt(vc$mvar / n)

  meanadj <- mean - q
  llu <- meanadj - z * se_of_mean
  overbd <- dissolution_bound(llu, sigma)

  list(MEAN = mean, SE = se, SM = sm,
       VAR = vc$var, MVAR = vc$mvar, SIGMA = sigma,
       OVERBD = overbd)
}
