# Lucent: API changes for the anzen-bot bridge

Six additive changes. Nothing existing changes behaviour, and the browser client keeps
using its cookie session exactly as it does now.

The bridge (in anzen-bot) authenticates with `Authorization: Bearer <token>` on every
request. It never sends a cookie, never opens a page, and never asks a human to click
anything. Everything else it needs already exists: profile photos, teams, members,
projects, tasks, subtasks, comments, events, insights, focus, notifications, export.

---

## 1. Token table — `server/schema.sql`

Append to the end of the file:

```sql
CREATE TABLE IF NOT EXISTS api_tokens (
  token_hash TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       TEXT NOT NULL DEFAULT '',
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);
```

`db.ts:12` runs `schema.sql` on every boot with `CREATE TABLE IF NOT EXISTS`, so an
existing database picks this up with no migration entry.

## 2. Bearer auth — `server/auth.ts`

`currentUser` (line 119) currently reads only the cookie. Add the token path, using the
same `sha256` helper and the same join, so the returned `SessionUser` is identical:

```ts
export function currentUser(req: Request): SessionUser | undefined {
  const bearer = (req.headers.authorization ?? "").replace(/^Bearer\s+/i, "");
  const cookie = parseCookies(req)[SESSION_COOKIE];
  if (!bearer && !cookie) return undefined;

  const sql = bearer
    ? `SELECT u.id, u.email, u.name, u.role, u.team, u.location, u.tz_offset, u.hue,
              u.avatar, m.workspace_id, w.name AS workspace_name, m.role = 'admin' AS is_admin
         FROM api_tokens t
         JOIN users u ON u.id = t.user_id
         JOIN memberships m ON m.user_id = u.id
         JOIN workspaces w ON w.id = m.workspace_id
        WHERE t.token_hash = ? AND t.expires_at > ?`
    : `SELECT u.id, u.email, u.name, u.role, u.team, u.location, u.tz_offset, u.hue,
              u.avatar, m.workspace_id, w.name AS workspace_name, m.role = 'admin' AS is_admin
         FROM sessions s
         JOIN users u ON u.id = s.user_id
         JOIN memberships m ON m.user_id = u.id
         JOIN workspaces w ON w.id = m.workspace_id
        WHERE s.token_hash = ? AND s.expires_at > ?`;

  const found = row<Omit<SessionUser, "is_admin"> & { is_admin: number }>(
    sql, sha256(bearer || cookie), nowIso(),
  );
  return found ? { ...found, is_admin: !!found.is_admin } : undefined;
}
```

`originGuard` (line 151) rejects any write without a matching `Origin` or
`Sec-Fetch-Site: same-origin`. A bearer token is explicit rather than ambient, so it is
not a CSRF vector — exempt it:

```ts
export function originGuard(req: Request, res: Response, next: NextFunction) {
  if (req.method === "GET" || req.method === "HEAD") return next();
  if (req.headers.authorization) return next();
  ...
}
```

## 3. Mint a token — `server/api.ts`

Under the auth section. Takes credentials **or** an existing session, and sets no cookie:

```ts
import { createHash, randomBytes } from "node:crypto"; // already imported in auth.ts

api.post("/auth/token", async (req, res) => {
  const signedIn = currentUser(req);
  let userId = signedIn?.id;
  if (!userId) {
    const email = text(req.body?.email, 160).toLowerCase();
    const password = typeof req.body?.password === "string" ? req.body.password : "";
    const found = row<{ id: string; password_hash: string }>(
      "SELECT id, password_hash FROM users WHERE email = ?", email,
    );
    if (!found || !(await verifyPassword(password, found.password_hash))) {
      return res.status(401).json({ error: "Email or password is incorrect." });
    }
    userId = found.id;
  }
  const token = randomBytes(32).toString("base64url");
  // No expiry. A far-future date rather than NULL keeps `expires_at TEXT NOT NULL` and every
  // `expires_at > now` comparison exactly as written. Revocation is DELETE /auth/token.
  const expires = "9999-12-31T23:59:59.000Z";
  run(
    "INSERT INTO api_tokens (token_hash, user_id, name, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
    createHash("sha256").update(token).digest("hex"), userId,
    text(req.body?.name, 80) || "API token", expires, nowIso(),
  );
  res.status(201).json({ token, user_id: userId, expires_at: expires });
});

api.delete("/auth/token", requireUser, (req, res) => {
  const bearer = (req.headers.authorization ?? "").replace(/^Bearer\s+/i, "");
  if (bearer) run("DELETE FROM api_tokens WHERE token_hash = ?",
    createHash("sha256").update(bearer).digest("hex"));
  res.json({ ok: true });
});
```

The raw token is returned once; only its sha256 is stored. Apply the same
`loginRateLimit` middleware used by `/auth/login` to the credential branch.

A token never expires. It stops working only when it is revoked (`DELETE /auth/token`), when
the user is deleted (the foreign key cascades), or when the row is removed by hand. That is
the right default for a bot: a machine has no browser to re-authenticate with, so an expiry
would only ever surface as a bridge that went quiet after a month. Tokens already minted
under the 30-day rule keep their date; delete those rows and mint again to make them permanent.

## 4. Task list — `GET /api/tasks`

The only bulk read today is `/api/bootstrap`, which is far too large to poll. Add a
narrow one, next to `POST /tasks`:

```ts
api.get("/tasks", requireUser, (req, res) => {
  const actor = me(req);
  const assignee = req.query.assignee === "me" ? actor.id : idOf(req.query.assignee);
  const status = oneOf(String(req.query.status ?? ""), ["todo", "in_progress", "in_review", "done"] as const, "");
  const projectId = idOf(req.query.project_id);
  const limit = Math.min(200, Math.max(1, Number(req.query.limit) || 100));
  const where = ["workspace_id = ?", "archived = 0"];
  const params: unknown[] = [actor.workspace_id];
  if (assignee) { where.push("assignee_id = ?"); params.push(assignee); }
  if (status) { where.push("status = ?"); params.push(status); }
  if (projectId) { where.push("project_id = ?"); params.push(projectId); }
  res.json({
    tasks: rows(
      `SELECT id, title, description, status, priority, project_id, assignee_id,
              created_by, created_at, done_at
         FROM tasks WHERE ${where.join(" AND ")} ORDER BY position LIMIT ?`,
      ...params, limit,
    ),
  });
});
```

## 5. Team on the profile — `PATCH /api/profile`

A bot's title is its team, and a title can change. Accept `team`, validated against the
teams table:

```ts
const team = text(req.body?.team, 40);
if (team && !row("SELECT 1 AS ok FROM teams WHERE workspace_id = ? AND lower(name) = lower(?)",
                 actor.workspace_id, team)) {
  return res.status(400).json({ error: "Pick a team that exists in this workspace." });
}
run("UPDATE users SET name = ?, email = ?, role = ?, team = COALESCE(NULLIF(?, ''), team) WHERE id = ?",
    name, email, role || actor.role, team, actor.id);
```

## 6. Bug fix — bootstrap member photos

`api.ts:203` does not select `u.avatar`, so `Team.tsx:192` always receives `undefined`
and every teammate renders as initials, while `Avatar` already supports a photo. Add it:

```sql
SELECT u.id, u.name, u.email, u.role, u.team, u.location, u.tz_offset, u.hue, u.avatar,
       m.role AS workspace_role
```

---

## Acceptance test

No browser, no cookie:

```bash
BASE=https://lucent.example.com

# 1. Mint a token (the first account of an empty workspace is its admin).
#    expires_at must be 9999-12-31T23:59:59.000Z — no expiry.
curl -s -X POST $BASE/api/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"email":"anzen@bots.anzen.local","password":"...","name":"bridge"}' | tee /tmp/t.json
TOKEN=$(jq -r .token /tmp/t.json); jq -r .expires_at /tmp/t.json

# 2. It authenticates without a cookie.
curl -s $BASE/api/auth/me -H "Authorization: Bearer $TOKEN"

# 3. A write passes the origin guard with no Origin header.
curl -s -X POST $BASE/api/teams -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"Engineering"}'

# 4. The task list answers.
curl -s "$BASE/api/tasks?assignee=me&status=todo" -H "Authorization: Bearer $TOKEN"

# 5. Revocation.
curl -s -X DELETE $BASE/api/auth/token -H "Authorization: Bearer $TOKEN"
curl -s $BASE/api/auth/me -H "Authorization: Bearer $TOKEN"   # {"user":null}
```

Then `npm run typecheck && npm run smoke && npm run build`.
