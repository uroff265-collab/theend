# TheEnd — Last Asylum: Plague automation architecture

## What public competitor material establishes

This document separates observed product behavior from implementation hypotheses.

- FarmHarder publicly describes a cloud-hosted service with no local emulator, account linking, activity settings, run history, and a pause/resume flow when the player opens the game.
- Its public feature guides describe decision-making before actions: rally target/participant/slot checks, predicted losses and configurable limits; excavation discovery from alliance chat, eligibility checks, completion monitoring and reward claiming.
- MuBots publicly documents three delivery modes: local software, a provider-managed server, and a browser/cloud portal. Its Last Asylum guide uses one emulator instance per game account and supports MEmu, LDPlayer and BlueStacks.
- A public video for a local Last Asylum bot demonstrates emulator installation, screen-capture permission, selectable task modules, squad settings, and an in-game overlay/statistics.
- None of these public materials disclose FarmHarder's source code, exact cloud provider/instance type, private game protocol, or internal vision model. TheEnd must not claim to know those internals.

## Target architecture

Browser dashboard -> HTTPS settings/schedules/history/pause-resume -> TheEnd API + PostgreSQL -> durable job queue and worker leases -> one isolated worker per game account -> Android runtime (emulator or hosted Android device) -> ADB/screenshots/accessibility hierarchy -> perception -> game state -> policy -> action -> verification.

The website/API is the control plane. It does not itself run Android or play the game. A separate always-on Android runtime is required for phone/PC-off operation.

## Worker loop

1. Acquire a lease for one account; reject duplicate workers for that account.
2. Check pause state and session ownership before touching the game.
3. Capture screenshot and Android accessibility hierarchy.
4. Classify the current screen and extract labels, timers, resources, squads and buttons.
5. Load the enabled activity policy and resource/loss limits.
6. Build candidate actions. Require a unique target and the correct screen context.
7. Execute one action only; never use generic blind coordinate fallbacks.
8. Capture a new state and compare it with the expected postcondition.
9. Mark success only when a game-state change or reward evidence is observed; otherwise record unconfirmed/failed and stop that task.
10. Persist screenshots only when explicitly enabled and redact account identifiers.

## Activity state machines

Each activity is a separate state machine, not a generic click macro. Example rally states:

- scan_board
- read_rally_details
- check_open_slot
- select_allowed_squad
- estimate_losses
- skip_if_over_limit
- join
- verify_joined
- record_result

Excavation states:

- discover_shared_link
- open_dig
- check_eligibility
- join_if_allowed
- wait_for_completion
- claim_if_available
- verify_reward
- record_result

Town production and offline rewards require their own screen-specific state machines and verified labels/templates. No guessed coordinates.

## TheEnd current implementation status

- Existing web dashboard/API and PostgreSQL queue are deployed on Render.
- Existing Windows ADB agent can connect to LDPlayer and poll TheEnd.
- theend_vision.py contains conservative Android accessibility parsing and context-bound action selection.
- Automated unit tests cover hierarchy parsing, unique-target selection, wrong-screen refusal and disabled/duplicate target refusal.
- These tests validate the generic decision layer only. They do not prove the Last Asylum UI labels are exposed by Android accessibility, nor do they prove any complete in-game activity works.
- The currently supported semantic activity set is intentionally limited. Other dashboard toggles must not be advertised as operational until their state machines are implemented and verified.

## Deployment constraints

Render's current web service is a Node.js API/dashboard, not an Android emulator host. A production cloud worker needs a separate Linux host with Android runtime support, ADB, persistent worker supervision, and enough CPU/RAM/storage. Android emulator acceleration generally depends on host virtualization support; a normal web-service container cannot be assumed to provide it.

A genuinely free, always-on cloud Android machine is not established by the sources reviewed. Keep the existing local LDPlayer path as the zero-infrastructure development mode. Do not create paid servers, store game credentials, or switch providers without the owner's explicit approval.

## Release gates

A feature is operational only after all of these pass:

- screen recognition on the actual game build and language;
- target uniqueness and safe-action policy;
- successful action in a controlled test account;
- postcondition verification against the game result;
- restart/reconnect behavior;
- no unintended taps during a long soak test;
- accurate activity history and pause/resume behavior.