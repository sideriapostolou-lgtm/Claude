# Header correction

The original metadata incorrectly reported `headerPresent:false`. The private FirstRateCSV has the literal first record `timestamp,open,high,low,close,volume`. It contains16201 CSV records: one header and16200 data rows, all six columns. Data timestamps parse as `%Y-%m-%d %H:%M:%S`, October1 00:00 through October16 16:59,2026, with zero duplicate timestamps.

The original metadata timestamp extraction already filtered out this header by requiring a numeric year, so its data-row count and eleven complete-date coverage findings remain unchanged. The ingestion correction is to validate and skip this header; strategy rules, costs and frozen dates need no change. Original DATA_FEASIBILITY files remain preserved. No price values or returns were inspected and no strategy was run in this audit. See DATA_CORRECTION.json for the exact CSV hash and counts.
