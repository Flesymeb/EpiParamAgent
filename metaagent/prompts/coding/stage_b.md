Stage B: check and finalize estimates against this source. Candidates are
fallible hypotheses, never evidence. If candidates are absent, directly extract
and finalize from the same source. Inspect for omitted estimates in both modes.
Return exactly {"records": [...], "dispositions": [...]} as JSON. Each disposition
has candidate_id, action (keep/correct/reject/pending), reason. Account for EVERY
candidate exactly once. Each kept/corrected/pending candidate has exactly one record
with its candidate_id. Rejected candidates have no record. Additions have
candidate_id=null and supporting _field_evidence. Pending records must set
needs_review=true.

First resolve coding-scope eligibility against the declared extraction scope.
A candidate clearly outside that scope MUST have action=reject, with a reason
identifying the source population/statistic/model that conflicts with the scope;
it has NO records entry. Do not keep it or mark it pending merely to preserve
all reported estimates, and do not say "out of scope but retained" in notes.
Only a genuinely unresolved source-to-scope relationship warrants pending.
If A is absent, omit clearly out-of-scope additions; null-ID additions still
must satisfy the same coding scope. With no explicit scope, retain the full
codebook scope rather than narrowing it to a preferred estimate.

After applying coding scope, leave statistical contribution selection to
synthesis: do not pool results, choose one of several in-scope models, convert
uncertainty types or assert independence to make pooling possible. Rejecting an
explicit coding-scope mismatch is your responsibility, not synthesis selection.
Check candidate field assertions afresh against the source. Resolve a missing
quote by finding the relevant original passage; do not blindly copy stale A
flags or erase a supported value to avoid review. A corrected unsupported
assertion requires an explicit correct disposition and source-based reason.
Dispositions contain ONLY supplied candidate IDs. A newly added record with
candidate_id:null has NO entry in dispositions; null disposition IDs are invalid.

If the supplied windows cannot resolve a relationship, inspect the source_catalog.
You may return {"records":[],"dispositions":[],"request_block_ids":["exact block ID"]} instead of a final answer
to request up to two exact source blocks. There are at most two request rounds.
Use only catalog IDs. Then finalize or mark pending; never invent unseen content.

In each returned record, use _field_evidence to map non-missing field names to
exact contiguous source quotations. This is the JSON record format, not the
LangExtract transport envelope.

Candidate association is a required output field in EVERY record, including additions.
Before responding, check these schema invariants:
- Every keep/correct/pending disposition ID occurs in exactly one records item.
- Every reject disposition ID occurs in no records item.
- Each supplied ID occurs exactly once in dispositions. Copy the complete exact ID.
- Only genuinely new source-supported additions use candidate_id:null.
Structural example (IDs and field names only; not study evidence):
{"records":[{"candidate_id":"candidate:example-id","needs_review":true}],
 "dispositions":[{"candidate_id":"candidate:example-id","action":"pending","reason":"association or source field requires review"}]}
Fill the declared source-grounded record fields as required; this example is not a
permission to omit reported fields or copy a demonstration ID into the task output.
