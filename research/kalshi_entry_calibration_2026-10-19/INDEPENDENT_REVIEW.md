# Independent first-order enrichment review — October 19, 2026

Status: COMPLETE for corrected frozen script `35d6ea20` and report `ded71046` below. No remaining blocking join, arithmetic, provenance or interpretation defect found. Root's source-manifest portability defect was corrected and independently reproduced; numerical findings are unchanged. No network calls, repository changes, strategy tests, performance tests or sealed TEST access.

The scratch independent audit `/workspace/review-entry-oct19-independent.py` reconstructs the filled cohort directly from original day-money logs and six captured Railway responses. Output: `/workspace/review-entry-oct19-independent.json`. It does not import or run the producer's computation.

1,408 assertions passed. Verified original8 input hashes from the October18 report,149 unique day fills and60 unique settlements,55 nonempty traded windows, exhaustive unique query target IDs, six unsaturated requests with25/74/78/25/26/29 returned rows, exact standalone durable-intent rows, exact accepted venue-order joins, finite bounded fair/price/quantity, matching window/side, payload intent timestamp before first fill, and all first-order partials. Each of55 orders has exactly one standalone durable intent and one accepted event. The58 actual first-order fill receipts include3 orders with multiple partials. Query `latestDeployment` identifies service response metadata, not each historical row's deployment.

Independent arithmetic:

| Measure | Result |
| --- | ---: |
| First orders / actual first-order quantity |55 /165.56|
| Mean recorded side fair |52.5303980588%|
| Mean order limit |48.7454545455%|
| First-side winning official outcomes |24/55 =43.6363636364%|
| Equal-window quoted gross edge |+3.7849435133c|
| Equal-window actual first-order payoff |−5.1090909091c|
| Actual-quantity model-implied first-order payoff |+$6.2047297682518641280|
| Actual first-order payoff, fees included |−$16.3428|
| Completion field |45 absent;10 explicitly false|

This repairs the selected-five-capture limitation for the descriptive first-filled-order cohort. It does not sample all eligible decisions/nonfills, validate a tradable filter, certify input freshness, prove population miscalibration from55 dependent observations, or provide an untouched holdout. Missing completion flags stay unknown; no successful pair is inferred. Model-implied payoff is the recorded model's expectation applied to fixed observed quantities, not earned money or a counterfactual execution simulation. Existing next-day carry and five empty settlements must retain their original population handling. All actual first-order partials are retained; later orders are not discarded from overall strategy P&L.

Initial scratch verification failed because it required every provider-filtered row to be a standalone order. The filter also returns status/embedded-event rows. Correcting the verifier to parse only exact native standalone order prefixes produced the passing result; no original evidence changed. This limitation should be retained in the producer's extraction method as well.


## Earlier frozen reproduction and provenance (superseded hashes retained)

Reviewed frozen publication script SHA256 `dc895ae1aa77f38af85584fd405d62f6b170b45c94a129bd6d9ccb8241f2c85a` and report SHA256 `1a41042753f65f0e10b136068672e884956af5352d85a6d336930a47654e86d9` at `/workspace/entry-evidence-oct19/publication/`. Reproduced the portable analyzer once to `/workspace/review-entry-oct19-reproduced`, with **1,554 assertions passing** and JSON/CSV byte-identical to the frozen files. JSON SHA256 `836a94fe7c43aa2e66c7a0966723d046c0eba31b7b731bfc7864a09da3c1b657`; CSV SHA256 `2e7c77b03dc077e62a1dd0c4b93ad5100893ac34c9131d43c18e7767607329dc`.

Independent original-to-selection verification passed44 assertions across all six batches and the probe: private original envelope SHA, canonical response SHA, exact request equality, exact selected original indices, full row equality, original counts and probe ID filter. The minimized selected rows are exactly the standalone order events from their original responses; none of the nested status matches/fragments supplies an intent. The probe omits a separate client-ID array; its exact ID is in the retained request filter. My initial selection checker assumed the array existed on the probe, then checked that probe explicitly; no source changed. The complete publication SHA256SUMS manifest also verified.

The report correctly records nine delayed provider publications after the actual fill while preserving the original payload clock; it warns about separate local/venue clock domains and makes no exact latency assertion. All55 decisions retain BTC exchange-to-decision and receipt-to-decision timing with statusok; these do not prove full both-side book freshness or fill-time fair. Completion is missing for45 and false for10; no historical per-row model/deployment identity is invented. The latest service deployment metadata is explicitly excluded as historical source identity.

Report interpretation is appropriately descriptive: no confidence interval/significance, parameter search, independent holdout, executable replacement or profit claim. The secondary Brier comparison is clearly labeled own bid proxy, not an independent market forecast; it should remain secondary rather than motivate a trading rule. The full strategy's −$8.1698 remains, together with all empty/carry/cohort boundaries. This evidence improves historical diagnosis and does not clear recovery, current exposure or new real-order admission.


## Final corrected freeze

Root caught a publication portability defect: both source-manifest expressions preferred repository-relative keys when a file was inside both the package and repository. Installing the package in its intended research directory changed the JSON manifest keys even with identical inputs. Reviewed the exact two-line correction in `PORTABILITY_FIX.diff`: package-relative keys now take priority in both `load()` and the additional-source loop, while external repository inputs retain `repository/` prefixes. The report now gives the installed-package reproduction command. This changes provenance naming, not cohort selection or arithmetic.

Independently reproduced the corrected frozen portable script once to `/workspace/review-entry-oct19-reproduced-v2`: **1,554 assertions**, JSON and CSV byte-identical to the corrected package. Compared old/new JSON after removing only `source_sha256`: every other field is identical. CSV is unchanged. The producer's separate dummy-repository installation receipt documents identical default-repo output after relocation; I reviewed that receipt and the exact source-key logic without rerunning its additional relocation experiment. Final SHA256SUMS passes for all12 files.

Final reviewed hashes:

- Script: `35d6ea20810209810654470ba28ce2d003a3b073a2722f093caf600b05303b3f`.
- Report: `ded7104631dcfec3ac521e8ab76ebc4938af9d6681ce4859be845c7378b3cc26`.
- JSON: `063c66d043ee4e716d9157e3b926c2aa7c1321c697c88144cbf9751253d4a486`.
- CSV: `2e7c77b03dc077e62a1dd0c4b93ad5100893ac34c9131d43c18e7767607329dc`.

The initial1,408-check independent raw reconstruction and44-check original-to-selection verification still apply because captures, selected rows and numerical findings did not change. No arena candidate review was undertaken: root reports its required timing failed. This review clears only the bounded historical evidence package, not source release, operational recovery or new live entries.
