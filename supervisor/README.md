# TheEnd Supervisor

Independent security and reliability reviewer for TheEnd.

## MVP
- Runs free static checks on pushes to main and the Supervisor feature branch, manually, and hourly.
- Reads tracked source/configuration/documentation only.
- Excludes filenames suggesting secrets, credentials, cookies, tokens, and private keys.
- Redacts recognizable private-key blocks, common provider keys, bearer tokens, JWTs, and credential-bearing URLs before model submission.
- Optional paid AI review can be started manually; it is off by default.
- Does not read game accounts, email inboxes, browser profiles, local files, or production database contents.
- Does not change application code or deploy.

## Free mode (default)
Run `python supervisor/static_audit.py`. It checks tracked source/configuration files for selected risky patterns, makes no network requests, requires no API key, and does not create API charges. Findings are pattern matches and require human review; no findings do not prove the application is secure.

## Optional AI mode
The paid AI review is disabled by default. To enable it, manually start the GitHub Actions workflow and set `run_ai` to true. It requires the `OPENAI_API_KEY` Actions secret and an API-enabled model. Eligible redacted repository source code is sent to the configured OpenAI API. Never put game passwords, email codes, session cookies, or production credentials in source files.

## Safety notes\n- Redaction is best-effort, not a guarantee. Do not commit secrets to the repository.\n- The configured model must be enabled for the API account; a successful workflow syntax check does not prove API access.\n- Findings must be reviewed by a person before changes are made.\n\n## Next phase
Add a separate coding worker that consumes Supervisor issues on an isolated branch, runs tests, and opens a pull request. Keep review and code-writing as separate roles. Never grant the reviewer game login credentials.
