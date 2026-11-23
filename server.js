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
