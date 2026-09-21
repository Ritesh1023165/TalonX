# Sentinel revalidation
**SENTINEL REVALIDATION: NOT_RUN - CONTROLLED MESSAGES SENT: 0.**
Gate 'B' (credential rotation) failed (primary token unrotated), so the task's own rule is NO_GO before any real send; I did not send the validation message.
The Sentinel token itself IS rotated (new fingerprint 76852a85a801), so its earlier validation no longer applies (`sentinel_delivery_validation_bound` FAIL = NEEDS_REVALIDATION).
