# Data analysis conventions: official baseline + typical house rules

## 1. Source and hierarchy

There is no single official guide for computing and reporting metrics. Four primary documents cover
different parts of the problem, with no hierarchy among them: the Eurostat Handbook on Residential
Property Price Indices (2013, joint with ILO, IMF, OECD, UNECE and World Bank) for property prices,
mix change and index methods; the European Statistics Code of Practice (2017 edition) for the
quality of anything published as a statistic; the NIST/SEMATECH e-Handbook of Statistical Methods
for location measures and outliers; and the ASA Statement on Statistical Significance and P-Values
(Wasserstein and Lazar, 2016) for inference. The modifiable areal unit problem (MAUP) comes from the
quantitative geography literature (Gehlke and Biehl, 1934; Openshaw, 1984), cited here through a secondary summary. When in
doubt: the RPPI Handbook for anything that is a price over time, the Code of Practice for what a
published figure must carry, and the project's semantic layer for the definitions none of them fix.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| Skewed prices, median | "house price distributions are generally positively skewed ... the median is typically used rather than the mean" (RPPI Handbook, ch. 4) | median by default for price levels, with the skew as the stated reason |
| Mix is not price | "Compositional changes of the sample over time, just like quality changes of the individual dwellings, should not be interpreted as price changes" (RPPI Handbook, 2.6) | a period-on-period change must say whether the mix moved |
| Median index under mix change | "a median (or mean) index will be a very inaccurate guide to price change when there is substantial change in the composition of houses sold between periods" (RPPI Handbook, 4.2) | a raw median is a level, not an index; trends need mix control |
| Small cells | "the cell indices may be subject to a considerable amount of sampling variability due to small sample sizes or some cells may be empty for some periods" (RPPI Handbook, 4.26) | finer areas trade bias for noise; a minimum n is required |
| Asking prices | "These indices ignore reductions in prices that sellers subsequently make" (RPPI Handbook, 9.10) | asking and transaction prices measure different things |
| Outliers kept | "In any event, we typically do not want to simply delete the outlying observation" (NIST e-Handbook, 1.3.5.17) | flag and handle with robust methods, never silent removal |
| Outlier labeling rule | "These authors recommend that modified Z-scores with an absolute value of greater than 3.5 be labeled as potential outliers" (NIST e-Handbook, 1.3.5.17) | a named, median/MAD-based rule, not a judgment call per row |
| Heavy tails | "In general, for data with extreme values in the tails, the median provides a better estimate of location than does the mean" (NIST e-Handbook, 1.3.5.1) | robust location for listing data with extreme values |
| No threshold-only decisions | "Scientific conclusions and business or policy decisions should not be based only on whether a p-value passes a specific threshold" (ASA statement, principle 3) | report the estimate and its interval, not a significance flag |
| Errors measured | "Sampling errors and non-sampling errors are measured and systematically documented according to the European standards" (Code of Practice, 12.2) | every published figure carries its uncertainty and known biases |
| Common definitions | "Statistics are compiled on the basis of common standards with respect to scope, definitions, units and classifications in the different surveys and data sources" (Code of Practice, 14.3) | one definition per metric, shared by every source and consumer |
| MAUP | "The modifiable areal unit problem (MAUP) is a source of statistical bias that can significantly impact the results of statistical hypothesis tests" (Wikipedia, Modifiable areal unit problem) | the spatial unit is a modeling choice that changes the answer |

## 3. What the official guide does NOT say

- None of the sources sets a minimum sample size per area. The RPPI Handbook names the small-cell
  problem and fills empty cells with hedonic imputation inside an index; it says nothing about
  publishing an imputed level for an area as if it were observed.
- The RPPI Handbook covers sale prices; it does not cover rents or asking rents from listing portals.
  Rent indices belong to the CPI/HICP manuals, not used here.
- The NIST outlier tests assume approximate normality; the handbook says so and points to a log
  transform for lognormal data, but it does not say which rule fits price-per-square-metre data.
- The MAUP literature names the problem (scale and zoning effects) and offers no single fix: no
  source says which spatial unit is correct for a city.
- The ASA statement does not propose a replacement threshold and says nothing about effect-size
  conventions for business metrics.
- None of the sources covers chart design, pipeline reproducibility tooling, or how a metric
  definition is versioned in code.

## 4. Typical house rules (labeled as such)

- **Every metric is defined once, in the semantic layer**: formula, unit, population, period, price
  type (asking or transaction) and spatial unit, with a stable id. SQL views, scripts, reports and
  AI features compute it from that definition only; a second formula anywhere is a defect.
- **Median and robust measures for skewed prices, with the reason stated**: median, interquartile
  range or trimmed mean, never a bare mean of prices or of price per square metre without saying
  why the mean is appropriate there.
- **Asking and transaction prices are never mixed silently**: they are separate metrics with
  separate ids; a comparison between them is labeled as such, with the source of each.
- **Sample size and an uncertainty interval next to every figure**: `n` and an interval (bootstrap
  for medians) are part of the metric's output type, not optional decoration.
- **Minimum n per area before publishing**: below the threshold the result is the explicit state
  `insufficient_data`, never an imputed, borrowed or smoothed number presented as observed. The
  threshold is part of the metric definition.
- **Outliers flagged by a declared rule, never deleted silently**: the rule (for example modified
  Z-score above 3.5 on log prices) and the count of flagged rows are reported; excluded rows stay in
  storage with the flag.
- **Mix change acknowledged when comparing periods**: a raw median change is reported as a change in
  level of what was listed or sold; a price trend uses stratification, a hedonic model or repeat
  sales, and says which.
- **Spatial unit stated (MAUP)**: every area figure names its unit (district, neighbourhood, census
  section, grid cell); a ranking that flips under a different unit is reported as unstable.
- **Scores and rankings carry their inputs**: weights, normalization and the components of each
  score are versioned with the definition, so a rank change can be traced to data or to method.
- **Reproducible analysis**: pinned input snapshots (hash or extraction date), scripted steps,
  seeded randomness, deterministic ordering and output; same inputs give the same bytes.
- **Models in a statistical setting are estimates, not oracles**: a hedonic or ML model reports its
  holdout error against a naive baseline (area median) and its predictions carry intervals.
- **Honest charts**: bars start at zero, no dual axes that imply a relationship, the period, `n`
  and source are printed on the chart, and areas below the minimum n are shown as missing.
- **Evidence over claims**: a figure in a report links to the query or script and the input
  snapshot that produced it; a number with no traceable origin is not published.

## 5. How it's checked

| Rule | Cheap detector | Better detector |
|---|---|---|
| Single definition per metric | grep for duplicated formula fragments outside the semantic layer | contract test: every consumer reads the metric id from the semantic registry |
| Median for skewed prices | grep for `mean(`/`AVG(` on price columns | golden test on a skewed fixture where mean and median diverge |
| Asking vs transaction | column naming convention (`asking_`, `transaction_`) | type-level separation: distinct metric ids that cannot be joined without a declared mapping |
| `n` and interval present | schema check: output rows have `n` and interval columns | property test: interval width shrinks as `n` grows on synthetic data |
| Minimum n per area | assert no published area below threshold | test that an area under threshold returns `insufficient_data`, never a number |
| Outliers flagged, not deleted | row count before and after equals flagged plus kept | snapshot test of flag counts per run with a negative control row |
| Mix change | report template requires a method field for trends | backtest: stratified vs raw median on a period with a known mix shift |
| Spatial unit and MAUP | metric output carries the unit name | sensitivity run of rankings at two spatial units, rank correlation reported |
| Reproducibility | rerun the pipeline and diff outputs | CI job comparing output bytes against a versioned golden file |
| Honest charts | review checklist in PR | chart lint: zero baseline asserted in plotting helper tests |

## Sources

- https://ec.europa.eu/eurostat/documents/3859598/5925925/KS-RA-12-022-EN.PDF
- https://ec.europa.eu/eurostat/documents/4031688/8971242/KS-02-18-142-EN-N.pdf
- https://www.itl.nist.gov/div898/handbook/eda/section3/eda351.htm
- https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm
- https://www.amstat.org/asa/files/pdfs/p-valuestatement.pdf
- https://en.wikipedia.org/wiki/Modifiable_areal_unit_problem

## Verdict

The sources agree on the hard parts (prices are skewed, mix is not price, small cells are noise,
errors must be measured and documented) but none of them turns that into a contract. The
auditability of a published metric rests on house rules: one definition in the semantic layer, `n`
and an interval on every figure, and `insufficient_data` instead of an invented value.
