# Proposed arena block-scan review

Read-only review of scratch `blocks` candidate before source edits. No CPU-heavy tests or benchmarks run.

For tuples of ordinary finite native numeric Level fields, the prefix/suffix boundaries appear correct: equal blocks may be retained, duplicate values and insertions/deletions reconstruct equal numeric ladders, and the `limit-start` suffix bound prevents overlap. `book_wire` still sends the event metadata, so an empty ladder splice does not suppress timestamps/sequences.

However, value equality is a change from the original identity-only contract and is not universally lossless. Two small offline reproductions confirmed:

1. Sixteen recreated `Level(.5,-0.0)` replacing `Level(.5,+0.0)` produce candidate `(16,16,())`; reconstruction retains positive zero. Original algorithm transmits negative zero. Ordinary equality checks miss this representation change.
2. A float subclass overriding equality can compare `.99` equal to `.49`. With16 such levels, candidate reconstruction retains old `.49` while original transmits new `.99`. Runtime Level fields are not enforced by annotations; nearby `_book_level_facts` explicitly handles subclasses/non-native numeric objects through its fallback path. An equality method can also raise where identity comparisons cannot.

NaNs need separate same-object and distinct-object cases: dataclass/tuple equality has identity shortcuts, so a generic assertion using only `==` is not sufficient to prove preservation. Normal market feed parsers reject nonfinite prices/sizes; these malformed cases should stay rejected and never become apparently valid old data.

Prefer an identity-preserving optimization, such as benchmarking `all(map(operator.is_, chunk_a, chunk_b))` for chunks, if it meets unchanged timing thresholds. Otherwise the value-based fast path needs an explicit supported-input guard with original fallback and a documented representation contract; guard overhead must be included in actual tests. Do not infer a performance win from microbenchmarks alone.

Required focused coverage: lengths0/1/15/16/17/31/32/33; changes at every boundary; long equal prefix/suffix with no overlap; insertions/deletions/empty ladders; duplicate prices; recreated equal Level objects; signed-zero and int/float representation; same/distinct NaN and infinity; subclass/equality-exception fallback; multi-event book-wire round trips with unchanged timestamp/sequence/order. For identity-preserving implementation, require exact old delta output/frame equality, not only reconstructed numeric equality. Then run existing feed reconstruction, backlog, and unchanged performance nodes before broader release checks.

No source approval is given for the unguarded value-equality candidate as universally lossless. The intended ordinary-native-data optimization is plausible; the concrete corner cases above need resolution before source release.
