# TheEnd Supervisor

Independent security and reliability reviewer for TheEnd.

## MVP
- Runs on pushes to main, manually, and hourly.
- Reads tracked source/configuration/documentation only.
- Excludes filenames suggesting secrets, credentials, cookies, tokens, and private keys.
- Redacts common API keys, bearer tokens, and database passwords before model submission.
- Opens a GitHub issue for actionable medium/high/critical findings.
- Does not read game accounts, email inboxes, browser profiles, local files, or production database contents.
- Does not change application code or deploy.

## Required repository configuration
Add Actions secret OPENAI_API_KEY and Actions variable THEEND_SUPERVISOR_MODEL with a model identifier enabled for the API account.

Eligible, redacted repository source code is sent to the configured OpenAI API model. Review this data flow before enabling the secret. Never put game passwords, email codes, session cookies, or production credentials in source files.

## Next phase
Add a separate coding worker that consumes Supervisor issues on an isolated branch, runs tests, and opens a pull request. Keep review and code-writing as separate roles. Never grant the reviewer game login credentials.
