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


# ------------------------------------------------------------------------------------------------ response scope
SCOPE_EXCEEDED = "RESPONSE_EXCEEDS_AUTHORISED_SCOPE"   # the provider returned content dated outside the declared,
                                                       # authorised envelope of the request: bytes quarantined,
                                                       # exposure recorded, acquisition stops (r9 step 0: RUN_INVALID)
FAIL_STATES = FAIL_STATES + (SCOPE_EXCEEDED,)

# ------------------------------------------------------------------------------------------------ run failure classes
IMPLEMENTATION_FAILURE = "IMPLEMENTATION_FAILURE"      # code / invariant error before outcomes
ACQUISITION_BLOCKED = "ACQUISITION_BLOCKED"            # a required input could not be acquired with sufficient,
                                                       # verified coverage inside the authorised scope; no outcome
RUN_INVALID = "RUN_INVALID"                            # r9 step 0: archive / hash / config verification failed, or
                                                       # guard / response scope exceeded
INCOMPLETE_AFTER_OUTCOME_EXPOSURE = "INCOMPLETE_AFTER_OUTCOME_EXPOSURE"   # failed after outcomes existed


class AcquisitionBlocked(AcquisitionFailure):
    """Acquisition cannot proceed (coverage, reference date, incomplete pagination...). No outcome exists."""
    failure_class = ACQUISITION_BLOCKED


class ScopeExceeded(AcquisitionFailure):
    """A response contained content outside the authorised envelope: exposure recorded, run invalid."""
    failure_class = RUN_INVALID


AcquisitionFailure.failure_class = ACQUISITION_BLOCKED
