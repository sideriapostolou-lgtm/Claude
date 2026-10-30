# Independent header correction review

No blocking correction finding. The reviewer independently read exactly the
first line of the private CSV, which is
`timestamp,open,high,low,close,volume` with CRLF. No price row or return was read.
The original metadata's headerless claim was wrong; prior synthetic parser checks
did not verify that claim. The first replay's failure and original runner,
declaration, manifest and tests remain in `first_attempt/`; the prior independent
review is preserved.

The source diff adds a strict `parse_csv_rows` wrapper that requires exactly that
six-column first record, then calls the unchanged row parser. It changes only
the ingestion callsite. It does not skip arbitrary nonnumeric rows or change
signal rules, costs, dates, prices or accounting.

Twelve independent invented-data probes passed: one exact header produces the
same bar as the existing row parser; empty input, header-only, absent/repeated
headers, changed case, whitespace, missing/extra/reordered columns and a leading
blank row all reject. The 62 independent regressions and 14 root runner tests
also passed (`76 passed in 0.42s`).

Reviewed hashes:

- Corrected runner: `e71008ad7604de1464eb63519457644254596cc16e80c0d76ad86fbb1fe35b0c`.
- Corrected declaration: `f43925d6a91017094b1acd10885c413eb2e43c61a77e2e7d22f92f32e8097dcf`.
- Unchanged simulator: `69caef01eb392211342524b2fc3bc695f5cb31eab9d6d64763a4fc4503c2615b`.
- Archived original runner: `6e9d820aabc18776d7c6a316e9016dd24a94d87238f0f92a058eda5ce03fe76e`, matching the prior review.

The corrected source/declaration must be frozen before the next replay. The
original failure occurred on the first record before OHLC parsing or simulator
invocation, so this is a documented ingestion correction without outcome-based
tuning. This review does not independently recount all CSV records or verify
historical returns; the separate data correction supplies timestamp/row evidence.
Actual contract identity, adjustment/roll history, costs and profitability remain
unverified. No old TEST, accounts, production or network access occurred.
