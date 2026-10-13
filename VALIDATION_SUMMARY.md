# Model validation summary

Three kinds of models built on public Lithuanian power-market data, and a market-risk, IRRBB and counterparty-exposure exercise on a small bank portfolio, tested with standard model-validation checks. The developer and the validator are the same person, so this is not an independent validation; on the bank portfolio, the risk model is mis-specified on purpose to test whether the checks detect it. Severity: high – not to be used for its purpose until fixed; medium – usable with a documented limitation. The evidence is in [results_analysis.md](results_analysis.md).

## Decisions

| Model | Purpose | Decision | Severity |
|---|---|---|---|
| Day-ahead price forecast (Lasso and LightGBM average) | Tomorrow's 24 hourly prices | Approve for indicative use, with monitoring | Medium |
| 80% prediction intervals (quantile regression averaging) | The forecast's uncertainty | Recalibrate before use | Medium |
| Solar PPA cash-flow-at-risk and Expected Shortfall | Daily risk limits | Reject the 250-day historical simulation; re-test the volatility-scaled model | High |
| Price-driver regressions | How the weather moves the price | Use the direction and the main effect; event-specific magnitudes are tentative | Medium |
| Bank portfolio VaR (historical simulation, five AAA nodes) | 1-day VaR and ES | Reject: add the sovereign spread as a risk factor and use volatility-scaled scenarios, then re-test | High |
| Counterparty exposure (Hull–White Monte Carlo) | PFE, effective EPE and EAD | Use after recalibrating the volatility to the swap's tenors | Medium |
| IRRBB, EVE and NII (stylised banking book) | Supervisory shocks and outlier tests | Use with limitations: the illustrative deposit assumptions decide the NII test | Medium |

## Main findings

1. **The forecast beats its benchmark out of sample, but its test period was not fully clean.** Its mean absolute error was 24.8 €/MWh in January–August 2026, against 41.8 €/MWh for repeating yesterday's prices (Diebold–Mariano p < 0.001). Those months had been used in the explanatory analysis, and the clean test covers only 26 days, on which the improved version's further 5% gain is borderline (small-sample Diebold–Mariano p = 0.050) ([section 8](results_analysis.md#8-a-forecast-from-pre-auction-information-had-a-41-lower-error-than-repeating-yesterdays-prices), [section 9](results_analysis.md#9-tuned-on-autumn-2025-an-improved-model-had-a-5-lower-error-in-september-2026-a-borderline-gain)).
2. **The uncertainty estimates fail their backtests.** The 80% intervals covered 74% and 68% of hours, missing mostly price spikes. The PPA's 250-day historical simulation had 40 exceptions at 99% in 974 days; volatility scaling cut them to 24, still a failure, and every Expected Shortfall is too small (Acerbi–Szekely p < 0.001) ([section 14](results_analysis.md#14-the-80-intervals-under-predict-price-spikes-and-a-250-day-cash-flow-at-risk-for-a-solar-ppa-fails-in-summer)).
3. **The main explanatory effect is robust; some magnitudes are not.** +10 percentage points of Baltic wind lowered the price by 7.6 €/MWh (95% CI 6.7–8.5), in five additional checks too, but the Estlink 2 effect rests on one 177-day event and no adjustment was made for testing eleven hypotheses ([section 15](results_analysis.md#15-limits)).
4. **On the bank portfolio, the defect planted on purpose is found by comparing P&L, not by the attribution test.** Mapping a government bond to the AAA curve gave 42 exceptions at 99% in 1,978 days against about 20 expected; with the right risk factors there are 32 (p = 0.009) and with volatility scaling as well 27 (p = 0.112), while scaling alone leaves the proxy at 42. The unexplained P&L traces the proxy to the sovereign spread (R² = 0.97); the attribution test was green in 26 of 28 quarters. With deposit rates floored at 0%, net interest income falls by 6.75% of Tier 1 under parallel down, above the 5% threshold. The exposure model's volatility, taken from the 1-year rate, is 23–34% below that of the rates that drive the swap, and its stressed calibration raises the effective EPE by 60% ([Appendix C](results_analysis.md#appendix-c-the-same-validation-toolkit-on-a-small-bank-portfolio)).

## Monitoring

Proposed: monthly, the forecast comparison (with the small-sample Diebold–Mariano test) and the coverage, VaR and cash-flow-at-risk backtests on new data; quarterly, the attribution test; yearly, a review of the stress period, the exposure calibration and the deposit assumptions. A red zone in any of these tests, or interval coverage below 75% in a month, triggers a re-validation.

## How the models were tested

Walk-forward forecasts fixed in advance with a clean test period; Diebold–Mariano and Giacomini–White tests; exact binomial, Kupiec, Christoffersen, traffic-light (Basel-style at levels other than 99%) and Acerbi–Szekely backtests with sensitivity and stress analyses; P&L attribution, martingale tests and an SA-CCR benchmark; placebo, instrumental-variable and out-of-sample checks of the regressions; and 58 unit tests against independent references, run on every push.

## Scope and open issues

The PPA measure is a cash-flow-at-risk on realized settlement, not a market-risk VaR; the bank portfolio is stylised, combines Basel 2.5 backtests with the FRTB attribution test to check detection rather than to compute capital, and is backtested on hypothetical P&L only; options and CVA are out of scope. Changed after the first runs: pre-auction cleaning of the load forecast, a cache keyed to code and data, a small-sample Diebold–Mariano test, a stress period chosen without hindsight, a 0% floor on deposit rates, three years of data and a stressed calibration for the exposure model, and a volatility-scaled challenger VaR. Open: the order of decisions is not time-stamped by a third party.
