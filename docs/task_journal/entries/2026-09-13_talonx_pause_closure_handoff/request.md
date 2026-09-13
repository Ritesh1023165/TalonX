# Request

Verbatim user request (2026-09-13), immediately following Task 129's
research programme pause decision:

> TALONX — IMPLEMENT THE TASK129 RESEARCH PAUSE AND PRESERVE A
> RESTARTABLE HANDOFF
>
> OBJECTIVE
> Make the accepted research pause concrete. Preserve the application,
> evidence, and outstanding paper obligations, and leave one clear
> handoff for any future resumption.
>
> This is administrative closure, not Task130 alpha research. Do not
> invent another experiment or restart the application.
>
> BASELINE
> Research branch: research/talonx-profitability-2026-09
> Expected HEAD: e0d26bde41d6691bee30c73576b999c3aa9b4713
> Release branch: research/talonx-strategy-validation
> Expected HEAD: f28986999eec5e313cfc89db24e4dbacfb378891
> Verify actual SHAs. Preserve unrelated changes.
>
> 1. REUSE TASK129'S DECISION — read TASK129_RESEARCH_PROGRAM_DECISION.md
>    and the current handoff. Preserve: PAUSE_ALPHA_RESEARCH_UNDER_CURRENT_CONSTRAINTS;
>    no supported profitable-alert candidate on the live-configured
>    population; V2 configured-scope evidence remains inconclusive; no
>    claim that all possible strategies fail or that paid data would
>    solve the problem. Correct any wording implying that production or
>    passive V2 observation is currently running. Distinguish
>    implemented application capabilities from validated trading
>    strategies.
>
> 2. VERIFY STOPPED STATE ONCE — bounded, read-only check of: release
>    and research repository state; TalonX-owned processes and
>    application ports; Redis availability without changing its
>    contents; authoritative paper-ledger paths and outstanding
>    positions. Do not start, stop, migrate, reset, flush, expire, or
>    modify production state. If unexpected live processes are found,
>    report their ownership and status — do not assume this closure
>    task authorizes terminating an independently started session. Do
>    not claim ongoing monitoring after this snapshot.
>
> 3. PRESERVE OPEN PAPER OBLIGATIONS EXPLICITLY — read the authoritative
>    Experimental ledger and verify SPCX's current recorded state
>    rather than copying an old report. Record: position identifier and
>    quantity; entry and existing exit policy; last stored mark with
>    timestamp and source; whether exit evaluation is currently
>    inactive because the application is stopped. Do not present an old
>    mark as current. Do not fabricate a closing fill, flatten the
>    position, or reset the ledger. Make clear that stopping the
>    application interrupts active paper exit evaluation. A future
>    restart must disclose that observation gap and follow the existing
>    recovery policy without claiming uninterrupted monitoring or
>    executable historical fills.
>
> 4. LEAVE ONE CONCISE RESUMPTION HANDOFF — update the existing handoff
>    in place; do not create another documentation hierarchy. Include:
>    exact release and research SHAs; production state as of the
>    verification timestamp; outstanding paper obligations; links to
>    Task129's decision and evidence matrix; what work is paused;
>    Task129's exact named resumption conditions. A future proposal
>    must specify: what new information or capability has become
>    available; which documented limitation it addresses; one bounded
>    experiment and the product decision it would change; data
>    provenance, cost, acceptance criteria, and stop condition; required
>    authorization, if any. Do not recommend paid data, scope
>    expansion, filter relaxation, or another candidate without
>    supporting evidence.
>
> 5. JOURNAL AND FINISH — record this exact prompt, actions, timestamped
>    findings, and outcome in the existing task journal. Make only the
>    minimum necessary research-document changes. If the handoff
>    already satisfies these requirements, state that and avoid
>    duplicate reports. Commit and push necessary documentation
>    normally to the research branch. No release/main merge, code
>    changes, downloads, backtests, or external messages.
>
> FINAL RESPONSE (concise): 1. PAUSE_RECORDED / unexpected finding. 2.
> Verified SHAs and any documentation commit. 3. Application state at
> the check timestamp. 4. Outstanding paper obligations and monitoring
> gap. 5. Handoff and Task129 decision links.
>
> End with: "No further task scheduled. Research and application
> activation remain paused pending a concrete resumption decision."
