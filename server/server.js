import express from "express";
import pg from "pg";
import crypto from "node:crypto";

const { Pool } = pg;
const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "32kb" }));

const PORT = Number(process.env.PORT || 3000);
const API_KEY = process.env.API_KEY;
const DATABASE_URL = process.env.DATABASE_URL;
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN || "";

if (!API_KEY || !DATABASE_URL) {
  console.error("Set API_KEY and DATABASE_URL before starting TheEnd API.");
  process.exit(1);
}

const pool = new Pool({
  connectionString: DATABASE_URL,
  ssl: process.env.PGSSLMODE === "disable" ? false : { rejectUnauthorized: false }
});

app.use((req, res, next) => {
  const origin = req.get("origin");
  if (ALLOWED_ORIGIN && origin === ALLOWED_ORIGIN) {
    res.setHeader("Access-Control-Allow-Origin", ALLOWED_ORIGIN);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-API-Key");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS");
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

function auth(req, res, next) {
  const supplied = req.get("x-api-key") || "";
  const a = Buffer.from(supplied);
  const b = Buffer.from(API_KEY);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  next();
}

function validText(value, max = 120) {
  return typeof value === "string" && value.trim().length > 0 && value.trim().length <= max;
}
function validDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value) && !Number.isNaN(Date.parse(value));
}

await pool.query(`
  CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, uid TEXT NOT NULL,
    server TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Демо',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, type TEXT NOT NULL,
    account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
    scheduled_at TIMESTAMPTZ NOT NULL, recurrence TEXT NOT NULL DEFAULT 'once',
    enabled BOOLEAN NOT NULL DEFAULT TRUE, last_notified_date TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY, task_id TEXT, title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE UNIQUE INDEX IF NOT EXISTS one_task_event_per_day
    ON events (task_id, (created_at AT TIME ZONE 'UTC')::date)
    WHERE task_id IS NOT NULL;
`);

app.get("/health", async (_req, res) => {
  try { await pool.query("SELECT 1"); res.json({ ok: true, service: "theend-api" }); }
  catch { res.status(503).json({ ok: false }); }
});

app.use("/api", auth);

app.get("/api/accounts", async (_req, res) => {
  const { rows } = await pool.query("SELECT * FROM accounts ORDER BY created_at");
  res.json(rows);
});
app.post("/api/accounts", async (req, res) => {
  const { name, uid, server, status = "Демо" } = req.body || {};
  if (!validText(name, 50) || !validText(uid, 80) || !validText(server, 50) || !validText(status, 30))
    return res.status(400).json({ error: "name, uid, server and status are required" });
  const id = crypto.randomUUID();
  const { rows } = await pool.query(
    "INSERT INTO accounts(id,name,uid,server,status) VALUES($1,$2,$3,$4,$5) RETURNING *",
    [id, name.trim(), uid.trim(), server.trim(), status.trim()]
  );
  res.status(201).json(rows[0]);
});
app.patch("/api/accounts/:id", async (req, res) => {
  const { name, uid, server, status } = req.body || {};
  if (!validText(name, 50) || !validText(uid, 80) || !validText(server, 50) || !validText(status, 30))
    return res.status(400).json({ error: "All account fields are required" });
  const { rows } = await pool.query(
    "UPDATE accounts SET name=$2,uid=$3,server=$4,status=$5 WHERE id=$1 RETURNING *",
    [req.params.id, name.trim(), uid.trim(), server.trim(), status.trim()]
  );
  if (!rows[0]) return res.status(404).json({ error: "Account not found" });
  res.json(rows[0]);
});
app.delete("/api/accounts/:id", async (req, res) => {
  const result = await pool.query("DELETE FROM accounts WHERE id=$1", [req.params.id]);
  if (!result.rowCount) return res.status(404).json({ error: "Account not found" });
  res.sendStatus(204);
});

app.get("/api/tasks", async (_req, res) => {
  const { rows } = await pool.query("SELECT * FROM tasks ORDER BY scheduled_at");
  res.json(rows);
});
app.post("/api/tasks", async (req, res) => {
  const { title, type = "Ежедневное напоминание", accountId = null, scheduledAt, recurrence = "once", enabled = true } = req.body || {};
  if (!validText(title, 70) || !validText(type, 70) || !validDate(scheduledAt) ||
      !["once", "daily"].includes(recurrence) || typeof enabled !== "boolean")
    return res.status(400).json({ error: "Invalid task fields" });
  const id = crypto.randomUUID();
  try {
    const { rows } = await pool.query(
      "INSERT INTO tasks(id,title,type,account_id,scheduled_at,recurrence,enabled) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *",
      [id, title.trim(), type.trim(), accountId, new Date(scheduledAt), recurrence, enabled]
    );
    res.status(201).json(rows[0]);
  } catch (e) {
    if (e.code === "23503") return res.status(400).json({ error: "Account not found" });
    throw e;
  }
});
app.patch("/api/tasks/:id", async (req, res) => {
  const { title, type, accountId = null, scheduledAt, recurrence, enabled } = req.body || {};
  if (!validText(title, 70) || !validText(type, 70) || !validDate(scheduledAt) ||
      !["once", "daily"].includes(recurrence) || typeof enabled !== "boolean")
    return res.status(400).json({ error: "Invalid task fields" });
  const { rows } = await pool.query(
    "UPDATE tasks SET title=$2,type=$3,account_id=$4,scheduled_at=$5,recurrence=$6,enabled=$7 WHERE id=$1 RETURNING *",
    [req.params.id, title.trim(), type.trim(), accountId, new Date(scheduledAt), recurrence, enabled]
  );
  if (!rows[0]) return res.status(404).json({ error: "Task not found" });
  res.json(rows[0]);
});
app.delete("/api/tasks/:id", async (req, res) => {
  const result = await pool.query("DELETE FROM tasks WHERE id=$1", [req.params.id]);
  if (!result.rowCount) return res.status(404).json({ error: "Task not found" });
  res.sendStatus(204);
});
app.get("/api/events", async (_req, res) => {
  const { rows } = await pool.query("SELECT * FROM events ORDER BY created_at DESC LIMIT 100");
  res.json(rows);
});

// Server-side reminder scheduler: records due reminders, but never controls the game.
async function processDueTasks() {
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  const { rows } = await pool.query("SELECT * FROM tasks WHERE enabled=TRUE");
  for (const task of rows) {
    const due = new Date(task.scheduled_at);
    const dueNow = task.recurrence === "daily"
      ? now.getUTCHours() * 60 + now.getUTCMinutes() >= due.getUTCHours() * 60 + due.getUTCMinutes()
      : due <= now;
    if (!dueNow || (task.recurrence === "once" && task.last_notified_date) ||
        (task.recurrence === "daily" && task.last_notified_date === today)) continue;
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const inserted = await client.query(
        "INSERT INTO events(task_id,title,detail) VALUES($1,$2,$3) ON CONFLICT DO NOTHING RETURNING id",
        [task.id, "Напоминание: " + task.title, "Наступило запланированное время."]
      );
      if (inserted.rowCount) {
        await client.query("UPDATE tasks SET last_notified_date=$2, enabled=CASE WHEN recurrence='once' THEN FALSE ELSE enabled END WHERE id=$1", [task.id, today]);
      }
      await client.query("COMMIT");
    } catch (e) {
      await client.query("ROLLBACK");
      console.error("Reminder scheduler error:", e.message);
    } finally { client.release(); }
  }
}
setInterval(() => processDueTasks().catch(e => console.error(e)), 30000);
processDueTasks().catch(e => console.error(e));

app.use((err, _req, res, _next) => {
  console.error(err);
  res.status(500).json({ error: "Internal server error" });
});
app.listen(PORT, () => console.log("TheEnd API listening on " + PORT));
