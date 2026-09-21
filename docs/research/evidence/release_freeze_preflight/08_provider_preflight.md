# Provider preflight (bounded, read-only; no broker endpoint; no secret printed)
- provider configured / reachable / SIP entitled / QUALIFIED (split honoured on the known NVDA 2024-06-07 10:1 split): gate `provider_readiness` = QUALIFIED
- contract V2_RELEASE_PRICE_CONTRACT@1, fingerprint ac5e51aa3599d6c9 (PASS); alpaca / sip / adjustment=split / fallback=NONE (PASS)
- market calendar available and next session resolved; 20-session CONTIGUOUS liquidity window retrievable on the release provider:
  `provider_liquidity_window_probe.txt` (AAPL: 73 daily bars, SPLIT_ADJUSTED, feed=sip, window PASS, n_sessions_used=20)
- csv default is not used for release (`release_pricing_mode` PASS; `--release` forces sip)
