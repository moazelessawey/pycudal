source("cudal_cu.r")

full_four <- list(c(0.1,0.1), c(0.1,3.0), c(3.0,0.1), c(3.0,3.0))
blocks <- list(
  list(3,2,100.0,50.0,50.0, full_four),
  list(3,300,100.0,50.0,50.0, full_four),
  list(300,2,100.0,50.0,50.0, full_four),
  list(300,300,100.0,50.0,50.0, full_four),
  list(3,2,100.0,99.0,50.0, full_four),
  list(3,300,100.0,99.0,50.0, full_four),
  list(300,2,100.0,99.0,50.0, full_four),
  list(300,300,100.0,99.0,50.0, full_four),
  list(3,2,100.0,99.0,99.0, list(c(0.1,0.1), c(3.0,3.0))),
  list(3,300,100.0,99.0,99.0, full_four),
  list(300,2,100.0,99.0,99.0, full_four),
  list(300,300,100.0,99.0,99.0, full_four)
)
singles <- list(
  list(3,2,102.5,50.0,50.0,0.1,3.0),
  list(300,300,102.5,50.0,99.0,3.0,3.0),
  list(3,2,102.5,50.0,99.0,0.1,0.1),
  list(3,300,102.5,50.0,99.0,0.1,3.0)
)

results <- list()
for (b in blocks) {
  loc <- b[[1]]; perloc <- b[[2]]; target <- b[[3]]; lbound <- b[[4]]; ci <- b[[5]]; pairs <- b[[6]]
  for (p in pairs) {
    se <- p[1]; sm <- p[2]
    tab <- cusp2_acceptance_limit_table(num=perloc, loc=loc, target=target, lbound=lbound, cilevel=ci,
                                         se_values=c(se), sm_values=c(sm))
    results[[length(results)+1]] <- list(loc=loc, perloc=perloc, target=target, lbound=lbound, ci=ci,
                                          se=se, sm=sm, meanl=tab$MEANL[1], meanu=tab$MEANU[1])
  }
}
for (s in singles) {
  loc <- s[[1]]; perloc <- s[[2]]; target <- s[[3]]; lbound <- s[[4]]; ci <- s[[5]]; se <- s[[6]]; sm <- s[[7]]
  tab <- cusp2_acceptance_limit_table(num=perloc, loc=loc, target=target, lbound=lbound, cilevel=ci,
                                       se_values=c(se), sm_values=c(sm))
  results[[length(results)+1]] <- list(loc=loc, perloc=perloc, target=target, lbound=lbound, ci=ci,
                                        se=se, sm=sm, meanl=tab$MEANL[1], meanu=tab$MEANU[1])
}
df2 <- do.call(rbind, lapply(results, as.data.frame))
print(round(df2, 2))
