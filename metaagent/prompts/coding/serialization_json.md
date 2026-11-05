JSON record serialization: return exactly {"records": [...]} as a JSON object
using the declared fields. For each non-missing field except the supplied PMID, add _field_evidence,
a mapping from field name to exact contiguous source quotation(s). Return
{"records": []} when no scoped candidate is supported.
Do not emit a LangExtract envelope in JSON mode.
