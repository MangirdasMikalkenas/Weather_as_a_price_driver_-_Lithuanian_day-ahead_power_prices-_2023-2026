# Model validation summary

This repository builds three kinds of models on public Lithuanian power-market data and tests them the way a model-validation team would. Read that way, the day-ahead price forecast is fit for indicative use with documented limits, the risk measures are not yet fit for setting limits, and the explanatory regressions are robust in direction but uncertain in some magnitudes. Each finding links to its evidence in [results_analysis.md](results_analysis.md); severity follows a common scale, where high means the model should not be used for its purpose until fixed and medium that it can be used with a documented limitation.

## Decisions

| Model | Purpose | Decision | Severity of the main finding |
|---|---|---|---|
| Day-ahead price forecast (average of Lasso and LightGBM) | Forecast tomorrow's 24 hourly prices | Approve for indicative use, with monitoring | Medium |
| 80% prediction intervals (quantile regression averaging) | Quantify the forecast's uncertainty | Recalibrate before use | Medium |
| Solar PPA cash-flow-at-risk and Expected Shortfall | Daily risk limits for a solar PPA | Reject the 250-day historical simulation; re-test the volatility-scaled model and the Expected Shortfall | High |
| Price-driver regressions | Explain how the weather moves the price | Use the direction and the main effect; treat event-specific magnitudes as tentative | Medium |

## Three findings

1. **The forecast beats its benchmark out of sample, but its test period was not fully clean.** The model fixed in advance had a mean absolute error of 24.8 €/MWh in January–August 2026, against 41.8 €/MWh for repeating yesterday's prices (Diebold–Mariano p < 0.001), and beat the benchmark in every month to September. The same months had been used in the explanatory analysis, some wind and solar forecasts may be published after the auction (without them the gain is 28%), and the clean test covers only 26 days ([section 8](results_analysis.md#8-a-forecast-from-pre-auction-information-had-a-41-lower-error-than-repeating-yesterdays-prices), [section 15](results_analysis.md#15-limits)).
2. **The uncertainty estimates fail their backtests.** The 80% intervals covered 74% and 68% of hours, mainly because they under-predict spikes: the price exceeded the upper bound in 13.5% and 20.2% of hours, against 10%. For the solar PPA, the 250-day historical simulation recorded 40 exceptions at 99% in 974 days, with a red zone in 2025 and 2026, because 250 days cover only eight months of a market that trades every day. Volatility scaling cut the exceptions to 24, still a failure, and every model's Expected Shortfall is too small (Acerbi–Szekely p < 0.001) ([section 14](results_analysis.md#14-the-80-intervals-under-predict-price-spikes-and-a-250-day-cash-flow-at-risk-for-a-solar-ppa-fails-in-summer)).
3. **The main explanatory effect is robust; some headline magnitudes are not.** +10 percentage points of Baltic wind lowered the price by 7.6 €/MWh (95% CI 6.7–8.5), and the estimate holds in five additional checks on the same data. The extra effect during the Estlink 2 outage, 5.1–8.1 €/MWh, rests on a single 177-day event; several results sit at p = 0.04–0.07; and no adjustment was made for testing eleven hypotheses ([section 2](results_analysis.md#2-a-typical-windy-hour-was-17-mwh-19-cheaper-than-a-typical-calm-one), [section 4](results_analysis.md#4-while-estlink-2-was-out-the-same-wind-was-associated-with-a-larger-price-reduction-added-turbines-did-not-change-the-effect), [section 15](results_analysis.md#15-limits)).

## How the models were tested

- Walk-forward forecasts with the main model fixed in advance, naive benchmarks, a validation period for every setting and a clean test period that no decision used.
- Diebold–Mariano and Giacomini–White tests, and automatic checks that the inputs use only information available before the auction.
- Exact binomial, Kupiec and Christoffersen tests, the Basel traffic light and the Acerbi–Szekely test, with a sensitivity analysis and a stress scenario.
- Placebo, instrumental-variable, out-of-sample and leave-one-year-out checks of the regressions, and data-quality views in SQL.
- Unit tests of every statistical test against an independent reference, of the cache keys and of the SQL layer, run on every push (GitHub Actions).

## Scope and open issues

- The PPA measure is a cash-flow-at-risk on realized settlement, not a market-risk VaR: the PPA is not revalued off a forward curve, there is no risk-factor mapping, and no bank product (bonds, swaps, options) is modeled, so PFE, IRRBB and P&L attribution are out of scope.
- Fixed after review: the forecast inputs no longer use a load forecast cleaned with the actual load of the same hour; the cleaning now compares with the load of a week earlier, known at the auction, and the forecasts were recomputed. Stored forecasts are keyed to the code and data that produced them and record their date, git commit and warnings, which are counted rather than hidden. Re-fitting 12 days with ten times more Lasso iterations changed the forecasts by at most 0.18 €/MWh, so the convergence warnings do not affect the results; and the database is read with a single thread, so that inputs and cache keys repeat exactly.
- Open: the order of decisions is documented in the notebooks but not time-stamped by a third party.
