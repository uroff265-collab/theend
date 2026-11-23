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
app.use(express.json({ limit: "5mb" }));

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
    CREATE TABLE IF NOT EXISTS agent_state (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      device_name VARCHAR(100) NOT NULL DEFAULT '',
      emulator_connected BOOLEAN NOT NULL DEFAULT FALSE,
      last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS task_history (
      id BIGSERIAL PRIMARY KEY,
      title VARCHAR(160) NOT NULL,
      detail TEXT NOT NULL DEFAULT '',
      occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS agent_commands (
      id BIGSERIAL PRIMARY KEY,
      command_type VARCHAR(20) NOT NULL CHECK (command_type IN ('tap')),
      x INTEGER NOT NULL,
      y INTEGER NOT NULL,
      status VARCHAR(20) NOT NULL DEFAULT 'pending',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      completed_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS agent_tasks (
      id BIGSERIAL PRIMARY KEY,
      instruction TEXT NOT NULL,
      status VARCHAR(20) NOT NULL DEFAULT 'queued',
      result TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      started_at TIMESTAMPTZ,
      completed_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS automation_settings (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      activities JSONB NOT NULL DEFAULT '{}'::jsonb,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    INSERT INTO automation_settings (id, activities)
    VALUES (1, '{
      "town_production": false,
      "exploration_camp": false,
      "sanctuary": false,
      "heal_wounded": false,
      "alliance_help": false,
      "alliance_tech": false,
      "rallies": false,
      "excavations": false,
      "caravans": false,
      "black_ops": false,
      "golden_eggs": false,
      "town_shield": false,
      "cheese_thief": false,
      "survival_battle": false,
      "scouting": false
    }'::jsonb)
    ON CONFLICT (id) DO NOTHING;
  `);
}

function requireAgentToken(req, res, next) {
  const expected = process.env.THEEND_AGENT_TOKEN;
  const supplied = req.get("authorization") || "";
  if (!expected) return res.status(503).json({ error:"Агент не настроен на сервере." });
  if (supplied !== "Bearer " + expected) return res.status(401).json({ error:"Неверный токен агента." });
  next();
}

const ACTIVITY_KEYS = [
  "town_production","exploration_camp","sanctuary","heal_wounded",
  "alliance_help","alliance_tech","rallies","excavations","caravans",
  "black_ops","golden_eggs","town_shield","cheese_thief","survival_battle","scouting"
];

app.get("/api/automation/settings", async (_req, res) => {
  try {
    const result = await pool.query("SELECT activities, updated_at AS \"updatedAt\" FROM automation_settings WHERE id=1");
    res.json(result.rows[0] || {activities:{}, updatedAt:null});
  } catch (error) {
    console.error("Could not load automation settings:", error.message);
    res.status(500).json({error:"Не удалось загрузить настройки автоматизации."});
  }
});

app.put("/api/automation/settings", async (req, res) => {
  const incoming = req.body && req.body.activities;
  if (!incoming || typeof incoming !== "object" || Array.isArray(incoming)) {
    return res.status(400).json({error:"Ожидается объект activities."});
  }
  const activities = {};
  for (const key of ACTIVITY_KEYS) {
    if (incoming[key] !== undefined && typeof incoming[key] !== "boolean") {
      return res.status(400).json({error:"Настройка " + key + " должна быть true или false."});
    }
    activities[key] = incoming[key] === true;
  }
  try {
    const result = await pool.query(
      "INSERT INTO automation_settings (id, activities, updated_at) VALUES (1, $1::jsonb, NOW()) ON CONFLICT (id) DO UPDATE SET activities=EXCLUDED.activities, updated_at=NOW() RETURNING activities, updated_at AS \"updatedAt\"",
      [JSON.stringify(activities)]
    );
    res.json({ok:true, ...result.rows[0]});
  } catch (error) {
    console.error("Could not save automation settings:", error.message);
    res.status(500).json({error:"Не удалось сохранить настройки автоматизации."});
  }
});

app.get("/api/agent/config", requireAgentToken, async (_req, res) => {
  try {
    const result = await pool.query("SELECT activities, updated_at AS \"updatedAt\" FROM automation_settings WHERE id=1");
    res.json(result.rows[0] || {activities:{}, updatedAt:null});
  } catch (error) {
    console.error("Could not load agent config:", error.message);
    res.status(500).json({error:"Не удалось загрузить конфигурацию агента."});
  }
});

app.get("/api/agent/tasks", async (_req, res) => {
  try {
    const result=await pool.query(`
      SELECT id, instruction, status, result, created_at AS "createdAt",
             started_at AS "startedAt", completed_at AS "completedAt"
      FROM agent_tasks ORDER BY id DESC LIMIT 20
    `);
    res.json(result.rows.map(row=>({...row,id:String(row.id)})));
  } catch(error) {
    console.error("Could not list agent tasks:",error.message);
    res.status(500).json({error:"Не удалось загрузить задачи ИИ."});
  }
});

app.post("/api/agent/tasks", async (req, res) => {
  const instruction=req.body && req.body.instruction;
  if(typeof instruction!=="string" || !instruction.trim() || instruction.trim().length>500) {
    return res.status(400).json({error:"Напиши задачу длиной до 500 символов."});
  }
  try {
    const active=await pool.query("SELECT id FROM agent_tasks WHERE status IN ('queued','running') LIMIT 1");
    if(active.rowCount) return res.status(409).json({error:"Сначала дождись завершения текущей задачи."});
    const result=await pool.query(
      "INSERT INTO agent_tasks (instruction) VALUES ($1) RETURNING id, instruction, status, created_at AS \"createdAt\"",
      [instruction.trim()]
    );
    res.status(201).json({...result.rows[0],id:String(result.rows[0].id)});
  } catch(error) {
    console.error("Could not queue agent task:",error.message);
    res.status(500).json({error:"Не удалось поставить задачу в очередь."});
  }
});

app.get("/api/agent/tasks/next", requireAgentToken, async (_req, res) => {
  try {
    const result=await pool.query(`
      WITH next_task AS (
        SELECT id FROM agent_tasks WHERE status='queued'
        ORDER BY id ASC LIMIT 1 FOR UPDATE SKIP LOCKED
      )
      UPDATE agent_tasks AS task SET status='running', started_at=NOW()
      FROM next_task WHERE task.id=next_task.id
      RETURNING task.id, task.instruction
    `);
    res.json({task:result.rows[0]?{...result.rows[0],id:String(result.rows[0].id)}:null});
  } catch(error) {
    console.error("Could not fetch agent task:",error.message);
    res.status(500).json({error:"Не удалось получить задачу ИИ."});
  }
});

app.post("/api/agent/tasks/:id/result", requireAgentToken, async (req, res) => {
  const id=Number(req.params.id), {status,result=""}=req.body||{};
  if(!Number.isSafeInteger(id)||id<1||!["completed","needs_input","failed"].includes(status)||
     typeof result!=="string"||result.length>4000) return res.status(400).json({error:"Некорректный результат задачи."});
  try {
    const updated=await pool.query(
      "UPDATE agent_tasks SET status=$1,result=$2,completed_at=NOW() WHERE id=$3 AND status='running' RETURNING id",
      [status,result,id]
    );
    if(!updated.rowCount) return res.status(404).json({error:"Активная задача не найдена."});
    res.json({ok:true});
  } catch(error) {
    console.error("Could not save agent task result:",error.message);
    res.status(500).json({error:"Не удалось сохранить результат задачи."});
  }
});

app.get("/api/agent/status", async (_req, res) => {
  try {
    const result = await pool.query('SELECT device_name AS "deviceName", emulator_connected AS "emulatorConnected", last_seen AS "lastSeen" FROM agent_state WHERE id=1');
    const agent = result.rows[0] || null;
    const online = !!agent && (Date.now() - new Date(agent.lastSeen).getTime() < 45000);
    res.json({ configured:!!process.env.THEEND_AGENT_TOKEN, online, agent });
  } catch (error) {
    console.error("Could not load agent status:", error.message);
    res.status(500).json({ error:"Не удалось проверить агента." });
  }
});

app.post("/api/agent/heartbeat", requireAgentToken, async (req, res) => {
  const { deviceName = "Android emulator", emulatorConnected = false } = req.body || {};
  if (typeof deviceName !== "string" || !deviceName.trim() || deviceName.length > 100 || typeof emulatorConnected !== "boolean") {
    return res.status(400).json({ error:"Некорректный статус агента." });
  }
  try {
    await pool.query(`INSERT INTO agent_state (id, device_name, emulator_connected, last_seen)
      VALUES (1, $1, $2, NOW())
      ON CONFLICT (id) DO UPDATE SET device_name=EXCLUDED.device_name,
      emulator_connected=EXCLUDED.emulator_connected, last_seen=NOW()`,
      [deviceName.trim(), emulatorConnected]);
    res.json({ ok:true });
  } catch (error) {
    console.error("Could not save agent heartbeat:", error.message);
    res.status(500).json({ error:"Не удалось сохранить статус агента." });
  }
});

app.post("/api/agent/collect-resources", async (_req, res) => {
  // Collection is driven by the agent's local screen recognition. Never enqueue blind coordinates.
  try {
    const state = await pool.query("SELECT emulator_connected, last_seen FROM agent_state WHERE id=1");
    const row = state.rows[0];
    const online = !!row && row.emulator_connected && (Date.now() - new Date(row.last_seen).getTime() < 45000);
    if (!online) return res.status(409).json({error:"Android-агент или эмулятор не подключён."});
    res.status(202).json({ok:true,queued:0,message:"Запрос принят. Агент непрерывно анализирует экран локально; автоматическое действие выполняется только при распознанной цели."});
  } catch (error) {
    console.error("Could not check resource collection agent:", error.message);
    res.status(500).json({error:"Не удалось проверить агента."});
  }
});

app.get("/api/agent/commands/next", requireAgentToken, async (_req, res) => {
  try {
    const result = await pool.query(`
      WITH next_command AS (
        SELECT id FROM agent_commands
        WHERE status='pending'
        ORDER BY id ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
      )
      UPDATE agent_commands AS commands
      SET status='processing'
      FROM next_command
      WHERE commands.id=next_command.id
      RETURNING commands.id, commands.command_type AS type, commands.x, commands.y
    `);
    res.json({ command: result.rows[0] ? { ...result.rows[0], id:String(result.rows[0].id) } : null });
  } catch (error) {
    console.error("Could not fetch agent command:", error.message);
    res.status(500).json({ error:"Не удалось получить команду." });
  }
});

app.post("/api/agent/commands/:id/result", requireAgentToken, async (req, res) => {
  const id = Number(req.params.id);
  const { ok } = req.body || {};
  if (!Number.isSafeInteger(id) || id < 1 || typeof ok !== "boolean") return res.status(400).json({ error:"Некорректный результат команды." });
  try {
    const result = await pool.query("UPDATE agent_commands SET status=$1, completed_at=NOW() WHERE id=$2 AND status='processing' RETURNING id", [ok ? "completed" : "failed", id]);
    if (!result.rowCount) return res.status(404).json({ error:"Команда не найдена." });
    res.json({ ok:true });
  } catch (error) {
    console.error("Could not save agent command result:", error.message);
    res.status(500).json({ error:"Не удалось сохранить результат команды." });
  }
});

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
