# Paper Event Contract

The lifecycle is `SIGNAL → ORDER_INTENT → PAPER_ORDER_SUBMITTED → PAPER_ORDER_ACCEPTED | PAPER_ORDER_REJECTED | PAPER_ORDER_CANCELLED → PARTIAL_FILL | FILLED → POSITION_OPENED → STOP_TRIGGERED | EXIT_REQUESTED → EXIT_FILLED → POSITION_CLOSED`, with `EOD_FLATTEN` at cutoff.

Stable SHA-256-derived IDs connect signals and intents; Alpaca supplies `broker_order_id`; positions receive stable IDs. An intent is persisted before submission. A replay with the same semantic intent ID fails closed and submits nothing. Only a positively verified `https://paper-api.alpaca.markets` identity may reach broker mutation methods.
