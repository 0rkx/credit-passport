# Credit Passport public-data research models

## Summary

These are reproducible research artifacts for testing two narrow questions on a public benchmark. They are not production lending models, not an India credit score, and not the Credit Passport's eventual multi-source scorecard.

The primary source is the [Zenodo Lending Club loan dataset for granting models](https://zenodo.org/records/11295916), DOI `10.5281/zenodo.11295916`, licensed CC BY 4.0. It contains 1,347,681 US loans issued from 2007–2018 and was cleaned by the dataset authors to retain application-time variables and final outcomes.

## Intended research uses

1. Measure how well a small set of application metrics can reconstruct an observed bureau/FICO field.
2. Measure default discrimination and probability calibration on a real final repayment outcome.
3. Provide a deterministic API-ready artifact boundary for later FastAPI integration.

The artifacts must not be used to approve, decline, price, or limit a real person's credit. They have no evidence of validity for India, migrants, students, gig workers, remittance customers, or any corridor not represented in the source.

## Targets and features

### FICO regression

- Target: `fico_n`, an observed FICO field in the LendingClub application record.
- Features: `revenue`, `dti_n`, `loan_amnt`, `experience_c`, `emp_length`, `purpose`, and `home_ownership_n`.
- Deliberately excluded: `fico_n` itself, `Default`, `id`, `issue_d`, `zip_code`, `addr_state`, `title`, and `desc`.
- Model: median-imputed numeric values plus explicit ordinal encoding of categorical application fields and a `HistGradientBoostingRegressor`.

### Default classification

- Target: `Default` (`1` = charged off/default, `0` = fully paid).
- Features: `revenue`, `dti_n`, `loan_amnt`, `fico_n`, `experience_c`, `emp_length`, `purpose`, and `home_ownership_n`.
- Deliberately excluded: `id`, `issue_d`, `zip_code`, `addr_state`, `title`, `desc`, sex, age, education, marriage, employer prestige, school prestige, GPS, contacts, SMS, app-install and social variables.
- Model: imputed/standardised numeric values and one-hot categorical values followed by an averaged `SGDClassifier(loss="log_loss")`.
- Calibration: a Platt sigmoid is fitted only on the middle chronological 20% partition; the latest 20% is held out for final evaluation.

No post-origination performance field is used as an input. The final outcome is only used as the classification label.

## Evaluation protocol

Rows are sorted by `issue_d`, then split chronologically into 60% train, 20% calibration, and 20% test. This is intentionally stricter than a random split because it approximates later applications being scored from earlier experience. The random seed for model components is `20260920`.

### Primary LendingClub test results

| Task | Model | MAE | RMSE | R² | ROC-AUC | PR-AUC | Brier | ECE (10 bins) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| FICO regression | public-data model | 26.4723 | 34.6998 | 0.0152 | — | — | — | — |
| FICO regression | train-mean baseline | 26.8437 | 35.3961 | -0.0247 | — | — | — | — |
| Default classification | calibrated model | — | — | — | 0.6664 | 0.3410 | 0.1609 | 0.0072 |
| Default classification | constant-prevalence baseline | — | — | — | 0.5000 | 0.2176 | 0.1714 | 0.0336 |

The regression result is intentionally modest: revenue, DTI, requested amount and employment context do not reconstruct a bureau score. That is evidence for the product's multi-source design, not a reason to relabel the result as a Credit Passport score. The classifier shows benchmark discrimination, but it is not a calibrated approval policy.

### Secondary HELOC score-reconstruction benchmark

The separately labelled [FICO Explainable ML Challenge](https://community.fico.com/s/explainable-machine-learning-challenge) benchmark uses a pinned public mirror and 10,459 anonymised US HELOC applications. Rows with sentinel/missing `ExternalRiskEstimate` targets (`x1 < 0`) are excluded, leaving 9,861 real target rows. Predicting `ExternalRiskEstimate` from the remaining anonymised credit-report fields produced:

- MAE: **2.4844**
- RMSE: **3.2605**
- R²: **0.8897**
- Mean-predictor baseline MAE/RMSE/R²: **8.2669 / 9.8223 / -0.0009**

This secondary result is not combined with the primary model. It shows that detailed bureau-history attributes contain strong information about the bureau field itself; it does not show that bank statements, remittances or migrant evidence can produce an equivalent score.

## Limitations and risks

- **Geography:** all primary rows are US LendingClub borrowers; the data do not establish performance in India or any migration corridor.
- **Time:** the source ends in 2018; underwriting policy, macro conditions and borrower mix have changed.
- **Selection:** LendingClub applicants are not a representative population and fully-paid/charged-off filtering changes the target population.
- **Label:** `Default` is a final status, not a universal definition of repayment stress or a causal risk measure.
- **Fairness:** even without explicitly protected fields, financial variables can act as proxies. A production review requires subgroup performance, adverse-impact tests, explainability and legal sign-off.
- **Calibration:** the reported ECE is sample- and bin-dependent. It does not prove calibration in a new corridor.
- **Evidence mismatch:** the source has application fields, not permissioned payroll, rent, wallet, remittance, statement or transition evidence.
- **Operational safety:** artifacts are not secure scoring endpoints; add authentication, audit logs, consent checks, version pinning and human review before integration.

## Reproducibility and provenance

Run:

```bash
.venv/bin/python scripts/download_data.py
.venv/bin/python scripts/train_models.py
.venv/bin/python scripts/train_secondary_benchmarks.py
.venv/bin/pytest
```

The downloader verifies exact SHA-256 bytes and fails closed. It never generates rows or substitutes a different source. `artifacts/data_manifest.json` records the source URL, licence, geography, row count and verified digest; `artifacts/metrics.json` and `artifacts/secondary_heloc_metrics.json` contain the evaluation evidence.

## ICP event-native synthetic challenger

`artifacts/icp_challenger.joblib` is a separately versioned, synthetic-only
challenger artifact. It is trained by `scripts/train_icp_model.py` on 12,000
algorithmically generated applicants spanning three products and three
anonymised corridors. The target is an adverse 90-day outcome: at least one
30-days-past-due event or adverse restructure. The model consumes only the
event-native fields listed in `artifacts/icp_feature_contract.json`; evidence
volume fields are excluded from the learned feature vector and are reserved for
coverage diagnostics/abstention.

The split is chronological and person-disjoint (60% train, 20% calibration,
latest 20% test); Platt calibration is fitted only on the middle block. The
latest synthetic test block reports ROC-AUC **0.8520**, PR-AUC **0.7192**, Brier
**0.1363**, and 10-bin ECE **0.0189**. These numbers measure recovery of the
generator's synthetic mechanism, not real-world performance. Synthetic-to-real
transfer is unvalidated and requires consented real validation data, subgroup
checks, drift monitoring, governance review, and human oversight before any
decision use.
