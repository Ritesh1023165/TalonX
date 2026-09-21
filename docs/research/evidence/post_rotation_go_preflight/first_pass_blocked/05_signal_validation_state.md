# Signal validation state - UNEXPECTED CHANGE
The cleanup report said Signal's dedicated credential was unexposed and unchanged. The current `.env` shows the Signal (`TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN`) and Lab (`TALONX_NOTIFY_RESEARCH_BOT_TOKEN`) tokens ALSO changed
(fingerprints 6c83564c3a29 / ee0aca013c96; were eda34ed1... / d5673d63...). Consequently the Signal validation record no longer matches the active configuration: gate `signal_delivery_validation_bound` FAIL.
**SIGNAL CONFIG: NOT_READY (NEEDS_REVALIDATION).** Re-validating Signal needs one harmless Signal message, which this task did not authorize (only one OPERATIONS message). Lab stays OFF (gate `lab_off` PASS; Lab was not touched).
