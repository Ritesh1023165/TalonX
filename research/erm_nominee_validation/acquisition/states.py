"""Evidence states for every acquisition request (r9 §10; this task §4). A failed request is never an absence."""
USABLE = "RETRIEVED_USABLE"                      # retrieved, parsed, valid
ABSENT = "RETRIEVED_LEGITIMATELY_ABSENT"         # provider answered definitively 'does not exist' (e.g. SEC 404 for a
                                                 # specific filing header / submissions file) -> frozen unresolved policy
INSUFFICIENT = "INSUFFICIENT_HISTORICAL_COVERAGE"  # retrieved but coverage < required (e.g. dataset not yet published,
                                                   # S&P file as-of date before the scope end)
TRANSPORT = "TRANSPORT_OR_PROVIDER_FAILURE"      # network / timeout / 5xx / 429 exhausted / auth failure / refused
MALFORMED = "MALFORMED_OR_INCOMPLETE_RESPONSE"   # unparsable, missing required fields, truncated pagination

OK_STATES = (USABLE, ABSENT)
FAIL_STATES = (INSUFFICIENT, TRANSPORT, MALFORMED)


class AcquisitionFailure(RuntimeError):
    """A REQUIRED input ended in a FAIL state: acquisition stops before any build / outcome / scoring."""
