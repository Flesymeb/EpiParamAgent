STAGE B OUTPUT CONTRACT
Return one JSON object containing BOTH required arrays:
{"records": [...], "dispositions": [...]}
Every supplied candidate ID needs one explicit disposition with candidate_id,
action and reason, including when the scientific fields remain unchanged.
Write an empty array explicitly when there are no entries for that array.
The field guide describes items inside records; it never replaces this envelope.
Candidate IDs, source text and the declared scope determine the review; do not
copy example IDs or values. The program does not infer dispositions from records.
For a source-window request use {"records":[],"dispositions":[],"request_block_ids":["exact block ID"]}; then return the complete two-array review after reading it.
Before sending a final response, verify that records and dispositions are both
present and every supplied ID has exactly one keep/correct/reject/pending action.
