# Exact declaration review

Initial full draft SHA256 d0d6600363138aa3935ad21199fdce9c6f9c42d9f3992b0afaf8438b2b38436a, path ../PROTOCOL.md. No new outcome data accessed.

Two required prepublication clarifications sent to root:

1. Seal confirmation official candle and Coinbase feature data as well as book/outcome files until implementation/test hashes and independent code review are frozen. Full historical candle paths may reveal outcomes; feature availability can influence later changes.
2. UNKNOWN_ENTRY is not the same as observed UNFILLED. Missing arrival may conceal a losing filled position. A positive-screen gate based solely on known filled outcomes can select observable winners. Require zero UNKNOWN_ENTRY primary attempts, or a conservative all-attempt lower-bound test that remains positive in both aggregate and confirmation; otherwise insufficient evidence. Keep unknown attempt count/denominator even with no known position.

Also clarify that the two secondary exit policies share entries with the primary exit policy within each delay cohort; the3scohort may differ from the1scohort. The declared descriptive bootstrap need not exclude0 under this draft's positive-screen criterion, so it must not be reported as a significance test passed. No minimum feed-coverage percentage is specified; any positive screen remains conditional on the explicitly reported available/eligible sample, not reconstructed whole-period return.

Rest of full declaration is consistent with approved bounded design. Final text/hash approval pending root's clarifications. Implementation approval is separate and pending.

## Final declaration approval

Entire revised draft reread; independently computed SHA256 **91ff9c423b9b0ea4a594db9815ff0dc654a447baef23be63fa5b98338b64707b** matches root's proposed final artifact. Confirmation features/candles are now explicitly sealed, UNKNOWN_ENTRY contributes conservative loss bounds or blocks the positive screen, and each delay cohort has shared entries across its three exit policies. Both required fixes and the cohort clarification are present. APPROVED FOR DECLARATION PUBLICATION at this exact hash. This is design/declaration approval only, not code approval, data authenticity certification or economic-result approval. No confirmation outcomes accessed by this reviewer.
