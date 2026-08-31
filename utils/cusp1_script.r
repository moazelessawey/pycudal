source("cudal_cu.r")

groups <- list(
  c(5, 100.0, 50.0, 50.0), c(2000, 100.0, 50.0, 50.0),
  c(5, 100.0, 50.0, 99.0), c(2000, 100.0, 50.0, 99.0),
  c(5, 100.0, 99.0, 99.0), c(2000, 100.0, 99.0, 99.0),
  c(5, 104.5, 50.0, 50.0), c(2000, 104.5, 50.0, 50.0),
  c(5, 104.5, 50.0, 99.0), c(2000, 104.5, 50.0, 99.0),
  c(5, 104.5, 99.0, 99.0), c(2000, 104.5, 99.0, 99.0)
)

results <- list()
for (g in groups) {
  size <- g[1]; target <- g[2]; lbound <- g[3]; ci <- g[4]
  tab <- cusp1_acceptance_limit_table(number=size, target=target, lbound=lbound, cilevel=ci,
                                       mean_low=85.1, mean_high=114.9, mean_step=14.9)
  for (i in 1:nrow(tab)) {
    results[[length(results)+1]] <- list(size=size, target=target, lbound=lbound, ci=ci,
                                          mean=tab$MEAN[i], cv=tab$CV[i])
  }
}
df <- do.call(rbind, lapply(results, as.data.frame))
print(round(df, 2))
