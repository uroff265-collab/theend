# TheEnd API

Backend foundation for the TheEnd dashboard. It stores account profiles, scheduled reminders and event history in PostgreSQL.

## Important scope

This API is for dashboard data and reminders only. It does not connect to, control, or automate Last Asylum: Plague. Add game integration only through an official/authorized API or written permission from the game operator.

## Run locally

Requirements: Node.js 20+ and PostgreSQL.

1. Create a PostgreSQL database.
2. Set environment variables:
   - `DATABASE_URL` — PostgreSQL connection string
   - `API_KEY` — long random secret (never put it in frontend code or commit it)
   - `ALLOWED_ORIGIN` — optional exact dashboard origin, e.g. `https://uroff265-collab.github.io`
   - `PORT` — optional, defaults to 3000
3. In this folder run:
   ```sh
   npm install
   npm start
   ```
4. Check `GET /health`.

## API

All `/api/*` routes require `X-API-Key: <API_KEY>`.

- `GET/POST /api/accounts`
- `PATCH/DELETE /api/accounts/:id`
- `GET/POST /api/tasks`
- `PATCH/DELETE /api/tasks/:id`
- `GET /api/events`

Task JSON fields: `title`, `type`, `accountId` (nullable), `scheduledAt` (ISO date-time), `recurrence` (`once` or `daily`), `enabled` (boolean).

The scheduler records due reminders in `events` every 30 seconds while the service is running. It does not send push notifications yet; that will be a separate integration step.

## Deployment

Deploy this folder as a Node web service with a managed PostgreSQL database. Configure the environment variables above in the hosting provider's secret/environment settings. Do not commit API keys or database passwords. The dashboard is not connected to this API yet; that is the next integration step.
