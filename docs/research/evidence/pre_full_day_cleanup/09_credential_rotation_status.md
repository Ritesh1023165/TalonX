# Credential rotation (TASK H)

**TELEGRAM TOKEN ROTATED: USER_ACTION_REQUIRED  (ROTATION_REQUIRED_USER_ACTION)** - I cannot revoke a bot token; it is only possible in BotFather. **OLD TOKEN STILL TRUSTED: NO** (the release gate refuses it) - but Telegram keeps the old
tokens VALID until you revoke them, so revocation is the actual fix.

Two credentials must be rotated: `TELEGRAM_BOT_TOKEN` (legacy/primary bot) and `TALONX_NOTIFY_OPERATIONS_BOT_TOKEN` (TalonX Sentinel). Signal's token and Lab's token were never exposed; do not rotate them.

Exact steps (do not paste tokens into chat, commits or evidence):
1. Telegram -> @BotFather -> `/mybots` -> select the **Sentinel** bot -> *API Token* -> *Revoke current token* -> copy the new token.
2. Same for the bot behind `TELEGRAM_BOT_TOKEN` (the primary/`/ping` listener bot).
3. Edit `C:\workspace\TalonX\.env`: replace the two values (`TALONX_NOTIFY_OPERATIONS_BOT_TOKEN=...`, `TELEGRAM_BOT_TOKEN=...`). Chat ids do not change.
4. Verify by fingerprint only: `.venv\Scripts\python.exe -m talonx_v2.release_gate` -> `compromised_credentials_rotated` must be PASS (it prints key names, never values).
5. Re-validate Sentinel (one harmless message, needs your authorization): `.venv\Scripts\python.exe -m talonx_ops.notify.validate --destination OPERATIONS --send`
   (dry-run without `--send`). It rewrites `docs/research/evidence/v2_release_integration_ri4/delivery_validation.json` with the new one-way fingerprint; Signal's entry is preserved.
6. Send `/ping` in TalonX Signal to confirm the listener works with the new primary token.
Then re-run the release gate: expect READY, 0 FAIL.
