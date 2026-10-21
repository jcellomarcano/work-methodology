# Statistical machine learning conventions: official baseline + typical house rules

## 1. Source and hierarchy

There is no single official guide for machine learning in a statistical setting: no PEP 8, no ISO
style standard. This document leans on five primary sources, each authoritative only inside its own
scope. The scikit-learn user guide (https://scikit-learn.org/stable/) rules on leakage, splitting,
randomness, and probability calibration. Hyndman & Athanasopoulos, *Forecasting: Principles and
Practice*, 3rd ed. (https://otexts.com/fpp3/) rules on forecasting benchmarks, accuracy measures,
time series cross-validation, and prediction intervals. Roberts et al. 2017 (*Ecography*) rules on
blocked cross-validation for spatially or temporally dependent data. Angelopoulos & Bates
(arXiv 2107.07511) rules on distribution-free uncertainty. Mitchell et al. (Model Cards, arXiv
1810.03993) and Gebru et al. (Datasheets, arXiv 1803.09010) rule on documentation. Where they
overlap, the narrower source wins for its domain; the project's own `CONVENTIONS.md` covers what none
of them say. Generic Python style lives in `python.md` and is not repeated here.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| What leakage is | "Data leakage occurs when information that would not be available at prediction time is used when building the model. This results in overly optimistic performance estimates" (scikit-learn, Common pitfalls) | a leaked score is not a pessimistic-but-usable score; it is a wrong one |
| Split before anything | "Always split the data into train and test subsets first, particularly before any preprocessing steps" and "The general rule is to never call fit on the test data" (scikit-learn, Common pitfalls) | scalers, imputers, and feature selectors are fitted too; they belong inside the split |
| Reproducible runs | "For reproducible results across executions, remove any use of random_state=None" (scikit-learn, Common pitfalls) | every randomized estimator and splitter gets an explicit seed |
| Temporal split | "other cross-validation methods are inappropriate, as they would lead to training on future data and evaluating on past data. To ensure comparable metrics across folds, samples must be equally spaced" (scikit-learn, TimeSeriesSplit) | `KFold` with shuffle on a time series is a leak, not a choice |
| Rolling origin | "The corresponding training set consists only of observations that occurred prior to the observation that forms the test set. Thus, no future observations can be used in constructing the forecast" (FPP3, 5.10) | evaluate on many forecast origins, not one lucky cut |
| Dependent data | "when performing cross-validation, these structures are regularly ignored, resulting in serious underestimation of predictive error" and "We recommend that block cross-validation be used wherever dependence structures exist in a dataset" (Roberts et al. 2017) | spatial autocorrelation needs spatial blocks, same as time needs time order |
| Benchmarks are mandatory | "any forecasting methods we develop will be compared to these simple methods to ensure that the new method is better than these simple alternatives. If not, the new method is not worth considering" (FPP3, 5.2) | naive and seasonal naive are the floor, not a formality |
| Residuals are not errors | "the size of the residuals is not a reliable indication of how large true forecast errors are likely to be" (FPP3, 5.8) | in-sample fit proves nothing about forecast accuracy |
| Scale-free accuracy | "A scaled error is less than one if it arises from a better forecast than the average one-step naïve forecast computed on the training data" and "MASE or RMSSE are often preferable scale-free measures for point forecast accuracy" (FPP3, 5.8) | MASE below 1 is the baseline comparison built into the metric |
| Calibrated confidence | "Well calibrated classifiers are probabilistic classifiers for which the output of the predict_proba method can be directly interpreted as a confidence level" and "Ideally, the calibrator is fit on a dataset independent of the training data" (scikit-learn, Probability calibration) | an uncalibrated score is a ranking, not a probability |
| Distribution-free intervals | "the sets are valid in a distribution-free sense: they possess explicit, non-asymptotic guarantees even without distributional assumptions or model assumptions" (Angelopoulos & Bates) | conformal wraps any trained model with an interval of chosen coverage |
| Model and data documentation | "Model cards are short documents accompanying trained machine learning models that provide benchmarked evaluation in a variety of conditions" (Mitchell et al.); "every dataset be accompanied with a datasheet that documents its motivation, composition, collection process, recommended uses" (Gebru et al.) | the model ships with its evaluation; the data ships with its origin |

## 3. What the official guide does NOT say

- No source sets a minimum improvement over the baseline before a model may ship: "better" is left
  undefined, so the margin is a project decision.
- FPP3 does not prescribe spatial cross-validation, and scikit-learn has no spatial splitter: the
  closest native tool is `GroupKFold` over a spatial block id the project must build itself.
- Roberts et al. warn that blocking "may also unwittingly induce extrapolations"; no source gives a
  block size. It is chosen from the observed autocorrelation range, and that choice is recorded.
- The scikit-learn calibration guide covers classifiers; it says nothing about calibrating regression
  intervals or ranking scores.
- The conformal guarantee is not a guarantee under drift: the abstract lists "distribution shift" and
  "time-series" among the extensions, not the base case.
- Model cards and datasheets propose a format; neither says when a card must be updated, nor makes it
  a release gate.
- None of the sources address monitoring after deployment: drift detection and retraining cadence
  are outside all of them.

## 4. Typical house rules (labeled as such)

- **Split first, fit inside a `Pipeline`**: every transform that learns a parameter (scaling,
  imputation, target encoding, feature selection) lives in the pipeline, so cross-validation refits
  it per fold. A transform fitted on the full table is a leak, even if the score looks plausible.
- **Prediction-time features only**: each feature carries the timestamp at which it becomes known;
  a feature known after the target's date is dropped, not lagged by guesswork.
- **Temporal data gets a temporal split**: `TimeSeriesSplit` or rolling origin with a gap, test
  window at least as long as the forecast horizon, never shuffled.
- **Spatial data gets blocked cross-validation**: folds by neighbourhood, district, or a grid cell
  sized from the measured autocorrelation range, via `GroupKFold` on that block id. Random folds on
  listings from the same building are neighbours, not independent samples.
- **Every model is reported against its baseline, with the delta**: naive and seasonal naive for
  series, median by area (and by period) for prices, the current production rule for rankings. The
  report states baseline error, model error, and the difference on the same folds.
- **A model that does not beat its baseline does not ship**: on the same folds, by the margin the
  card declared before the run, not chosen after seeing the result.
- **Scale-free point error plus intervals with measured coverage**: MASE (or RMSSE) next to the error
  in business units, and every forecast with a prediction interval whose empirical coverage on held-
  out data is reported next to the nominal level. A 90% interval that covers 70% is a defect.
- **Calibrate before thresholding**: any confidence score that drives a decision (an AI component's
  match confidence, a ranking cut-off) is calibrated on data not used to fit the model, and its
  reliability curve or Brier score is in the report. Thresholds are set on calibrated scores only.
- **Pinned seeds, pinned snapshots**: an integer `random_state` on every estimator and splitter, no
  global `np.random.seed`, and the training data identified by a snapshot id or content hash. Same
  code, same snapshot, same seed: same metrics, byte for byte in the report.
- **One model card per shipped model, one datasheet per training snapshot**: intended use, data
  window, evaluation folds, baseline delta, interval coverage, known failure areas. The card is
  versioned next to the code and updated by the same change that retrains the model.
- **Drift is monitored, not assumed absent**: input distributions and live error against the
  baseline are tracked per period; a model whose live error crosses its baseline is rolled back to
  the baseline, which is always kept deployable.
- **Uncertainty is stated, never smoothed away**: an unsupported region or a sparse area returns an
  explicit "insufficient evidence" state instead of a point estimate with no interval.

## 5. How it's checked

| Rule | Cheap detector | Better detector |
|---|---|---|
| No preprocessing leak | grep for `fit`/`fit_transform` before the split call | test that the pipeline refits per fold (spy transformer counting `fit` calls) |
| No future information | feature list with an "available at" column reviewed in PR | test that shifts the target date and asserts no feature value changes |
| Temporal split | grep for `shuffle=True` / `KFold` on time-indexed data | test asserting max(train time) < min(test time) on every fold |
| Spatial blocking | block id present in the split call | report of error under random vs blocked folds; a large gap confirms dependence |
| Baseline delta reported | report schema requires `baseline_error` and `delta` fields | CI job that fails when the model does not beat the baseline on the same folds |
| Interval coverage | coverage column in the evaluation report | test on held-out data with coverage within tolerance of nominal |
| Calibrated confidence | reliability curve in the report | Brier score / expected calibration error gated in CI against a stored value |
| Reproducibility | grep for `random_state=None` or missing seeds | run training twice in CI and diff the metrics file byte for byte |
| Model card current | card file exists next to the model artifact | CI check that the card's snapshot hash matches the trained artifact's |
| Drift | periodic job comparing input histograms | live error vs baseline per period with an alert and a rollback path |

## Sources

- https://scikit-learn.org/stable/common_pitfalls.html
- https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- https://scikit-learn.org/stable/modules/cross_validation.html
- https://scikit-learn.org/stable/modules/calibration.html
- https://otexts.com/fpp3/toolbox.html (chapter 5; sections 5.2, 5.8, 5.10)
- https://pred.uni-regensburg.de/id/eprint/1455/ (Roberts et al. 2017, *Ecography* 40(8), doi:10.1111/ecog.02881)
- https://arxiv.org/abs/2107.07511
- https://arxiv.org/abs/1810.03993
- https://arxiv.org/abs/1803.09010

## Verdict

The sources agree on the evaluation method: split before fitting, respect time and space when
splitting, compare against a naive benchmark, and report uncertainty. They stop short of turning that
method into a release decision. The house rules close the gap: a declared baseline margin, measured
interval coverage, calibrated scores, and a versioned model card turn "the model looks good" into a
claim that can be checked and reproduced.
