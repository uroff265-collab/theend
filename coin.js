const crypto = require("node:crypto");

function verifyTelegramInitData(initData, botToken) {
  if (typeof initData !== "string" || !initData || !botToken) return null;
  const params = new URLSearchParams(initData);
  const receivedHash = params.get("hash");
  const authDate = Number(params.get("auth_date"));
  if (!receivedHash || !Number.isFinite(authDate)) return null;

  const now = Math.floor(Date.now() / 1000);
  if (authDate > now + 30 || now - authDate > 86400) return null;

  params.delete("hash");
  const dataCheckString = [...params.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => key + "=" + value)
    .join("\n");

  const secretKey = crypto.createHmac("sha256", "WebAppData").update(botToken).digest();
  const calculatedHash = crypto.createHmac("sha256", secretKey).update(dataCheckString).digest("hex");
  const a = Buffer.from(calculatedHash, "hex");
  const b = Buffer.from(receivedHash, "hex");
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;

  try {
    const user = JSON.parse(params.get("user") || "null");
    if (!user || !Number.isSafeInteger(user.id) || user.id <= 0) return null;
    return user;
  } catch {
    return null;
  }
}

async function initializeCoinDatabase(pool) {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS coin_players (
      telegram_id BIGINT PRIMARY KEY,
      username VARCHAR(64),
      first_name VARCHAR(128) NOT NULL DEFAULT '',
      balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
      last_mint_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS coin_ledger (
      id BIGSERIAL PRIMARY KEY,
      telegram_id BIGINT NOT NULL REFERENCES coin_players(telegram_id) ON DELETE CASCADE,
      amount BIGINT NOT NULL,
      operation VARCHAR(30) NOT NULL,
      description VARCHAR(160) NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS coin_ledger_player_created_idx
      ON coin_ledger (telegram_id, created_at DESC);
  `);
}

function registerCoinRoutes(app, pool) {
  const botToken = process.env.THEEND_COIN_BOT_TOKEN;

  async function requireTelegramUser(req, res, next) {
    if (!botToken) return res.status(503).json({ error: "Telegram bot token is not configured on the server." });
    const user = verifyTelegramInitData(req.get("x-telegram-init-data") || "", botToken);
    if (!user) return res.status(401).json({ error: "Открой игру через Telegram, чтобы войти." });
    try {
      const result = await pool.query(
        `INSERT INTO coin_players (telegram_id, username, first_name)
         VALUES ($1, $2, $3)
         ON CONFLICT (telegram_id) DO UPDATE SET
           username=EXCLUDED.username, first_name=EXCLUDED.first_name, updated_at=NOW()
         RETURNING telegram_id`,
        [String(user.id), user.username || null, String(user.first_name || "").slice(0, 128)]
      );
      req.coinUser = { id: String(result.rows[0].telegram_id), telegram: user };
      next();
    } catch (error) {
      console.error("Telegram player sign-in failed:", error.message);
      res.status(500).json({ error: "Не удалось войти в игру." });
    }
  }

  app.get("/coin", (_req, res) => {
    res.sendFile(require("node:path").join(__dirname, "coin.html"));
  });

  app.get("/api/coin/me", requireTelegramUser, async (req, res) => {
    try {
      const result = await pool.query(
        "SELECT balance, created_at AS \"createdAt\" FROM coin_players WHERE telegram_id=$1",
        [req.coinUser.id]
      );
      res.json({ player: { id: req.coinUser.id, firstName: req.coinUser.telegram.first_name || "", username: req.coinUser.telegram.username || null }, balance: result.rows[0].balance, createdAt: result.rows[0].createdAt });
    } catch (error) {
      console.error("Could not load TheEnd Coin profile:", error.message);
      res.status(500).json({ error: "Не удалось загрузить профиль." });
    }
  });

  app.post("/api/coin/mint", requireTelegramUser, async (req, res) => {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const updated = await client.query(
        `UPDATE coin_players
         SET balance=balance+1, last_mint_at=NOW(), updated_at=NOW()
         WHERE telegram_id=$1
           AND (last_mint_at IS NULL OR last_mint_at <= NOW() - INTERVAL '1.2 seconds')
         RETURNING balance`,
        [req.coinUser.id]
      );
      if (!updated.rowCount) {
        await client.query("ROLLBACK");
        return res.status(429).json({ error: "Подожди немного перед следующей чеканкой." });
      }
      await client.query(
        "INSERT INTO coin_ledger (telegram_id, amount, operation, description) VALUES ($1, 1, 'mint', 'Ручная чеканка')",
        [req.coinUser.id]
      );
      await client.query("COMMIT");
      res.json({ ok: true, minted: 1, balance: updated.rows[0].balance });
    } catch (error) {
      await client.query("ROLLBACK");
      console.error("Coin mint failed:", error.message);
      res.status(500).json({ error: "Не удалось отчеканить монету." });
    } finally {
      client.release();
    }
  });
}

module.exports = { initializeCoinDatabase, registerCoinRoutes };
