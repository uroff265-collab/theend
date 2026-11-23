const express = require("express");
const { Pool } = require("pg");

const app = express();
const PORT = Number(process.env.PORT) || 10000;
const DATABASE_URL = process.env.DATABASE_URL;

if (!DATABASE_URL) {
  console.error("DATABASE_URL is missing. Add it to the server environment.");
  process.exit(1);
}

const pool = new Pool({
  connectionString: DATABASE_URL,
  max: 5,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 10000
});

app.disable("x-powered-by");
app.use(express.json({ limit: "100kb" }));

async function initializeDatabase() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS accounts (
      id BIGSERIAL PRIMARY KEY,
      name VARCHAR(50) NOT NULL,
      uid VARCHAR(80) NOT NULL,
      server VARCHAR(50) NOT NULL,
      status VARCHAR(20) NOT NULL DEFAULT 'Демо',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS tasks (
      id BIGSERIAL PRIMARY KEY,
      title VARCHAR(70) NOT NULL,
      type VARCHAR(80) NOT NULL,
      account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,
      scheduled_at TIMESTAMP,
      recurrence VARCHAR(10) NOT NULL DEFAULT 'once',
      enabled BOOLEAN NOT NULL DEFAULT TRUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE tasks ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
    ALTER TABLE tasks ADD COLUMN IF NOT EXISTS last_notified_date DATE;

    CREATE TABLE IF NOT EXISTS task_history (
      id BIGSERIAL PRIMARY KEY,
      title VARCHAR(160) NOT NULL,
      detail TEXT NOT NULL DEFAULT '',
      occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
  `);
}

app.get("/api/health", async (_req, res) => {
  try {
    await pool.query("SELECT 1");
    res.json({ ok: true, service: "TheEnd API", database: "connected" });
  } catch (_error) {
    res.status(503).json({ ok: false, service: "TheEnd API", database: "unavailable" });
  }
});

app.get("/api/accounts", async (_req, res) => {
  try {
    const result = await pool.query(
      "SELECT id, name, uid, server, status FROM accounts ORDER BY created_at ASC, id ASC"
    );
    res.json(result.rows);
  } catch (error) {
    console.error("Could not load accounts:", error.message);
    res.status(500).json({ error: "Не удалось загрузить аккаунты." });
  }
});

app.post("/api/accounts", async (req, res) => {
  const { name, uid, server, status = "Демо" } = req.body || {};
  if (typeof name !== "string" || typeof uid !== "string" || typeof server !== "string" ||
      !name.trim() || !uid.trim() || !server.trim() ||
      name.length > 50 || uid.length > 80 || server.length > 50 ||
      !["Демо", "Активен", "Неактивен"].includes(status)) {
    return res.status(400).json({ error: "Проверь ник, UID, сервер и статус профиля." });
  }
  try {
    const result = await pool.query(
      "INSERT INTO accounts (name, uid, server, status) VALUES ($1, $2, $3, $4) RETURNING id, name, uid, server, status",
      [name.trim(), uid.trim(), server.trim(), status]
    );
    res.status(201).json(result.rows[0]);
  } catch (error) {
    console.error("Could not create account:", error.message);
    res.status(500).json({ error: "Не удалось создать аккаунт." });
  }
});

app.put("/api/accounts/:id", async (req, res) => {
  const id = Number(req.params.id);
  const { name, uid, server, status } = req.body || {};
  if (!Number.isSafeInteger(id) || id < 1 ||
      typeof name !== "string" || typeof uid !== "string" || typeof server !== "string" ||
      !name.trim() || !uid.trim() || !server.trim() ||
      name.length > 50 || uid.length > 80 || server.length > 50 ||
      !["Демо", "Активен", "Неактивен"].includes(status)) {
    return res.status(400).json({ error: "Проверь данные профиля." });
  }
  try {
    const result = await pool.query(
      "UPDATE accounts SET name=$1, uid=$2, server=$3, status=$4 WHERE id=$5 RETURNING id, name, uid, server, status",
      [name.trim(), uid.trim(), server.trim(), status, id]
    );
    if (!result.rowCount) return res.status(404).json({ error: "Аккаунт не найден." });
    res.json(result.rows[0]);
  } catch (error) {
    console.error("Could not update account:", error.message);
    res.status(500).json({ error: "Не удалось обновить аккаунт." });
  }
});

app.delete("/api/accounts/:id", async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isSafeInteger(id) || id < 1) {
    return res.status(400).json({ error: "Некорректный ID аккаунта." });
  }
  try {
    const result = await pool.query("DELETE FROM accounts WHERE id=$1 RETURNING id", [id]);
    if (!result.rowCount) return res.status(404).json({ error: "Аккаунт не найден." });
    res.json({ ok: true, deleted: id });
  } catch (error) {
    console.error("Could not delete account:", error.message);
    res.status(500).json({ error: "Не удалось удалить аккаунт." });
  }
});

function validTaskInput(body) {
  const { title, type, accountId = null, scheduledAt, recurrence = "once", enabled = true } = body || {};
  if (typeof title !== "string" || !title.trim() || title.length > 70 ||
      typeof type !== "string" || !type.trim() || type.length > 80 ||
      !(accountId === null || (Number.isSafeInteger(accountId) && accountId > 0)) ||
      typeof scheduledAt !== "string" ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(scheduledAt) ||
      Number.isNaN(new Date(scheduledAt).getTime()) ||
      !["once", "daily"].includes(recurrence) || typeof enabled !== "boolean") {
    return null;
  }
  return { title:title.trim(), type:type.trim(), accountId, scheduledAt, recurrence, enabled };
}

const taskSelect = `
  SELECT id, title, type, account_id AS "accountId",
         to_char(scheduled_at, 'YYYY-MM-DD"T"HH24:MI') AS "scheduledAt",
         recurrence, enabled, notified_at AS "notifiedAt",
         to_char(last_notified_date, 'YYYY-MM-DD') AS "lastNotifiedDate"
  FROM tasks
`;

app.get("/api/tasks", async (_req, res) => {
  try {
    const result = await pool.query(taskSelect + " ORDER BY created_at ASC, id ASC");
    res.json(result.rows.map(task => ({ ...task, id:String(task.id), accountId:task.accountId === null ? null : String(task.accountId), notifiedAt:task.notifiedAt || "", lastNotifiedDate:task.lastNotifiedDate || "" })));
  } catch (error) {
    console.error("Could not load tasks:", error.message);
    res.status(500).json({ error: "Не удалось загрузить задачи." });
  }
});

app.post("/api/tasks", async (req, res) => {
  const task = validTaskInput(req.body);
  if (!task) return res.status(400).json({ error: "Проверь название, тип, дату, повторение и профиль задачи." });
  try {
    const result = await pool.query(
      `INSERT INTO tasks (title, type, account_id, scheduled_at, recurrence, enabled)
       VALUES ($1, $2, $3, $4::timestamp, $5, $6)
       RETURNING id, title, type, account_id AS "accountId",
         to_char(scheduled_at, 'YYYY-MM-DD"T"HH24:MI') AS "scheduledAt",
         recurrence, enabled`,
      [task.title, task.type, task.accountId, task.scheduledAt, task.recurrence, task.enabled]
    );
    res.status(201).json({ ...result.rows[0], id:String(result.rows[0].id), accountId:result.rows[0].accountId === null ? null : String(result.rows[0].accountId) });
  } catch (error) {
    console.error("Could not create task:", error.message);
    res.status(500).json({ error: "Не удалось создать задачу. Проверь, что выбранный аккаунт существует." });
  }
});

app.put("/api/tasks/:id", async (req, res) => {
  const id = Number(req.params.id);
  const task = validTaskInput(req.body);
  if (!Number.isSafeInteger(id) || id < 1 || !task) return res.status(400).json({ error: "Проверь данные задачи." });
  try {
    const result = await pool.query(
      `UPDATE tasks SET title=$1, type=$2, account_id=$3, scheduled_at=$4::timestamp,
         recurrence=$5, enabled=$6
       WHERE id=$7
       RETURNING id, title, type, account_id AS "accountId",
         to_char(scheduled_at, 'YYYY-MM-DD"T"HH24:MI') AS "scheduledAt",
         recurrence, enabled`,
      [task.title, task.type, task.accountId, task.scheduledAt, task.recurrence, task.enabled, id]
    );
    if (!result.rowCount) return res.status(404).json({ error: "Задача не найдена." });
    res.json({ ...result.rows[0], id:String(result.rows[0].id), accountId:result.rows[0].accountId === null ? null : String(result.rows[0].accountId) });
  } catch (error) {
    console.error("Could not update task:", error.message);
    res.status(500).json({ error: "Не удалось обновить задачу. Проверь выбранный аккаунт." });
  }
});

app.patch("/api/tasks/:id/reminder", async (req, res) => {
  const id = Number(req.params.id);
  const { notifiedAt, lastNotifiedDate } = req.body || {};
  const hasNotifiedAt = typeof notifiedAt === "string" && !Number.isNaN(Date.parse(notifiedAt));
  const hasLastDate = typeof lastNotifiedDate === "string" && /^\d{4}-\d{2}-\d{2}$/.test(lastNotifiedDate);
  if (!Number.isSafeInteger(id) || id < 1 || (!hasNotifiedAt && !hasLastDate)) {
    return res.status(400).json({ error: "Некорректные данные напоминания." });
  }
  try {
    const result = await pool.query(
      `UPDATE tasks SET
         notified_at = CASE WHEN $2::boolean THEN $3::timestamptz ELSE notified_at END,
         last_notified_date = CASE WHEN $4::boolean THEN $5::date ELSE last_notified_date END
       WHERE id=$1 RETURNING id`,
      [id, hasNotifiedAt, hasNotifiedAt ? notifiedAt : null, hasLastDate, hasLastDate ? lastNotifiedDate : null]
    );
    if (!result.rowCount) return res.status(404).json({ error: "Задача не найдена." });
    res.json({ ok:true, id:String(id) });
  } catch (error) {
    console.error("Could not save reminder state:", error.message);
    res.status(500).json({ error: "Не удалось сохранить состояние напоминания." });
  }
});

app.delete("/api/tasks/:id", async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isSafeInteger(id) || id < 1) return res.status(400).json({ error: "Некорректный ID задачи." });
  try {
    const result = await pool.query("DELETE FROM tasks WHERE id=$1 RETURNING id", [id]);
    if (!result.rowCount) return res.status(404).json({ error: "Задача не найдена." });
    res.json({ ok:true, deleted:String(id) });
  } catch (error) {
    console.error("Could not delete task:", error.message);
    res.status(500).json({ error: "Не удалось удалить задачу." });
  }
});

app.get("/api/history", async (_req, res) => {
  try {
    const result = await pool.query(
      'SELECT id, title, detail, occurred_at AS "at" FROM task_history ORDER BY occurred_at DESC, id DESC LIMIT 100'
    );
    res.json(result.rows.map(item => ({ ...item, id:String(item.id) })));
  } catch (error) {
    console.error("Could not load history:", error.message);
    res.status(500).json({ error: "Не удалось загрузить историю." });
  }
});

app.post("/api/history", async (req, res) => {
  const { title, detail = "" } = req.body || {};
  if (typeof title !== "string" || !title.trim() || title.length > 160 ||
      typeof detail !== "string" || detail.length > 2000) {
    return res.status(400).json({ error: "Проверь название и описание записи истории." });
  }
  try {
    const result = await pool.query(
      'INSERT INTO task_history (title, detail) VALUES ($1, $2) RETURNING id, title, detail, occurred_at AS "at"',
      [title.trim(), detail]
    );
    res.status(201).json({ ...result.rows[0], id:String(result.rows[0].id) });
  } catch (error) {
    console.error("Could not create history entry:", error.message);
    res.status(500).json({ error: "Не удалось сохранить запись истории." });
  }
});

app.delete("/api/history", async (_req, res) => {
  try {
    const result = await pool.query("DELETE FROM task_history");
    res.json({ ok:true, deleted:result.rowCount });
  } catch (error) {
    console.error("Could not clear history:", error.message);
    res.status(500).json({ error: "Не удалось очистить историю." });
  }
});

app.get("/", (_req, res) => {
  res.sendFile(require("path").join(__dirname, "index.html"));
});

async function start() {
  try {
    await initializeDatabase();
    app.listen(PORT, "0.0.0.0", () => {
      console.log(`TheEnd server listening on port ${PORT}`);
    });
  } catch (error) {
    console.error("Could not initialize PostgreSQL:", error.message);
    process.exit(1);
  }
}

process.on("SIGTERM", async () => {
  await pool.end();
  process.exit(0);
});

start();
