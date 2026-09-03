const WEEKDAYS = new Set(["sunday", "monday", "tuesday", "wednesday", "thursday"]);
const MAX_AGE = 8 * 60 * 60;

const json = (value, status = 200, headers = {}) => new Response(JSON.stringify(value), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", ...headers },
});
const now = () => new Date().toISOString();
const b64 = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const fromB64 = (value) => { const normalized = value.replace(/-/g, "+").replace(/_/g, "/"); return Uint8Array.from(atob(normalized + "=".repeat((4 - normalized.length % 4) % 4)), (c) => c.charCodeAt(0)); };
const randomToken = (bytes = 32) => b64(crypto.getRandomValues(new Uint8Array(bytes)));
const hash = async (value) => b64(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)));
const same = (a, b) => {
  if (!a || !b || a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i += 1) result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return result === 0;
};

async function verifyPassword(password, encoded) {
  const [algorithm, iterationsText, saltText, digestText] = String(encoded || "").split("$");
  if (algorithm !== "pbkdf2" || !/^\d+$/.test(iterationsText) || !saltText || !digestText) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", salt: fromB64(saltText), iterations: Number(iterationsText), hash: "SHA-256" }, key, 256);
  return same(b64(bits), digestText);
}

function cookie(request, name) {
  const header = request.headers.get("Cookie") || "";
  const match = header.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : "";
}
function originOK(request, env, required = false) {
  const origin = request.headers.get("Origin");
  if (!origin) return !required;
  return origin === env.ADMIN_ORIGIN;
}
function csrfRequired(request) {
  return ["POST", "PATCH", "DELETE"].includes(request.method);
}
async function rateLimit(env, key, limit, seconds) {
  const bucket = Math.floor(Date.now() / 1000 / seconds) * seconds;
  const row = await env.DB.prepare("SELECT window_start, attempts FROM rate_limits WHERE bucket_key=?1").bind(key).first();
  if (!row || Number(row.window_start) !== bucket) {
    await env.DB.prepare("INSERT OR REPLACE INTO rate_limits(bucket_key, window_start, attempts) VALUES(?1, ?2, 1)").bind(key, bucket).run();
    return true;
  }
  if (Number(row.attempts) >= limit) return false;
  await env.DB.prepare("UPDATE rate_limits SET attempts=attempts+1 WHERE bucket_key=?1").bind(key).run();
  return true;
}

function validatePackage(input) {
  const errors = [];
  if (!input || typeof input !== "object" || Array.isArray(input)) errors.push("The import must be a JSON object");
  if (input?.schema_version !== 1) errors.push("schema_version must be 1");
  if (!input?.student || typeof input.student !== "object" || Array.isArray(input.student)) errors.push("student must be an object");
  const shahaf = input?.shahaf;
  if (!shahaf || typeof shahaf !== "object") errors.push("shahaf must be an object");
  if (shahaf && (shahaf.class_id === null || shahaf.class_id === undefined || String(shahaf.class_id).trim() === "")) errors.push("shahaf.class_id is required");
  if (shahaf && (shahaf.class_number === null || shahaf.class_number === undefined || !Number.isInteger(Number(shahaf.class_number)) || Number(shahaf.class_number) < 1)) errors.push("shahaf.class_number must be a positive integer");
  const rows = input?.weekly_schedule;
  if (!Array.isArray(rows) || rows.length === 0) errors.push("weekly_schedule must be a non-empty list");
  const seen = new Set();
  const normalizedRows = [];
  for (const [index, row] of (Array.isArray(rows) ? rows : []).entries()) {
    const path = `weekly_schedule[${index}]`;
    if (!row || typeof row !== "object") { errors.push(`${path} must be an object`); continue; }
    const weekday = String(row.weekday || "").toLowerCase();
    const period = Number(row.period);
    if (!WEEKDAYS.has(weekday)) errors.push(`${path}.weekday is invalid`);
    if (!Number.isInteger(period) || period < 0 || period > 13) errors.push(`${path}.period must be 0 through 13`);
    const key = `${weekday}:${period}`;
    if (seen.has(key)) errors.push(`${path} duplicates ${key}`);
    seen.add(key);
    if (!["lesson", "gap", "unknown"].includes(row.status)) errors.push(`${path}.status is invalid`);
    const timeOK = (value) => value === null || (typeof value === "string" && /^([01]\d|2[0-3]):[0-5]\d$/.test(value));
    if (!timeOK(row.start) || !timeOK(row.end)) errors.push(`${path} has an invalid time`);
    if (row.status === "unknown") errors.push(`${path} is unknown; fill it before publishing`);
    if (row.status === "lesson") {
      if (!row.start || !row.end) errors.push(`${path} lesson requires start and end`);
      for (const field of ["subject", "teacher", "room"]) if (typeof row[field] !== "string" || !row[field]) errors.push(`${path} lesson requires ${field}`);
    }
    if (row.status === "gap" && ["subject", "teacher", "room"].some((field) => row[field] !== null && row[field] !== undefined)) errors.push(`${path} gap fields must be null`);
    normalizedRows.push({ weekday, period, start: row.start ?? null, end: row.end ?? null, subject: row.subject ?? null, teacher: row.teacher ?? null, room: row.room ?? null, status: row.status });
  }
  const visible = input?.extraction?.visible_weekdays;
  if (!input?.extraction || typeof input.extraction !== "object" || Array.isArray(input.extraction)) errors.push("extraction must be an object");
  if (!Array.isArray(visible) || visible.length === 0) errors.push("extraction.visible_weekdays is required");
  for (const weekday of (Array.isArray(visible) ? visible : [])) {
    const value = String(weekday).toLowerCase();
    if (!WEEKDAYS.has(value)) errors.push(`invalid visible weekday ${value}`);
    const periods = new Set(normalizedRows.filter((row) => row.weekday === value).map((row) => row.period));
    for (let period = 0; period < 14; period += 1) if (!periods.has(period)) errors.push(`${value} is missing period ${period}`);
  }
  if (!input?.transit || typeof input.transit !== "object" || Array.isArray(input.transit)) errors.push("transit must be an object");
  if (!Array.isArray(shahaf?.shared_subjects)) errors.push("shahaf.shared_subjects must be a list");
  if (!Array.isArray(shahaf?.selectors)) errors.push("shahaf.selectors must be a list");
  if (!Array.isArray(shahaf?.exam_terms)) errors.push("shahaf.exam_terms must be a list");
  if (input?.transit?.enabled) {
    if (typeof input.transit.origin_address !== "string" || !input.transit.origin_address.trim()) errors.push("transit.origin_address is required when enabled");
    if (!Number.isFinite(Number(input.transit.origin_lat)) || !Number.isFinite(Number(input.transit.origin_lon))) errors.push("transit coordinates are required when enabled");
  }
  if (errors.length) return { errors };
  const name = input.student?.name;
  return { package: {
    schema_version: 1,
    student: { name: typeof name === "string" && name.trim() ? name.trim() : null },
    shahaf: { class_id: String(shahaf.class_id), class_number: Number(shahaf.class_number), shared_subjects: Array.isArray(shahaf.shared_subjects) ? shahaf.shared_subjects : [], selectors: Array.isArray(shahaf.selectors) ? shahaf.selectors : [], exam_terms: Array.isArray(shahaf.exam_terms) ? shahaf.exam_terms : [] },
    weekly_schedule: normalizedRows,
    transit: { enabled: Boolean(input.transit.enabled), origin_address: input.transit.origin_address ?? null, origin_lat: input.transit.enabled ? Number(input.transit.origin_lat) : null, origin_lon: input.transit.enabled ? Number(input.transit.origin_lon) : null },
    extraction: { visible_weekdays: [...new Set(visible.map((value) => String(value).toLowerCase()))], visible_periods: input.extraction.visible_periods || {}, warnings: Array.isArray(input.extraction.warnings) ? input.extraction.warnings : [] },
  }, warnings: Array.isArray(input.extraction?.warnings) ? input.extraction.warnings : [] };
}

async function auth(request, env, mutate = false) {
  if (!originOK(request, env, mutate)) return { error: json({ error: "origin rejected" }, 403) };
  const session = cookie(request, "__Host-shahaf_session");
  if (!session) return { error: json({ error: "login required" }, 401) };
  const row = await env.DB.prepare("SELECT token_hash, csrf_hash, expires_at FROM sessions WHERE token_hash=?1").bind(await hash(session)).first();
  if (!row || row.expires_at <= now()) return { error: json({ error: "session expired" }, 401) };
  if (mutate && csrfRequired(request)) {
    const supplied = request.headers.get("X-CSRF-Token") || "";
    if (!supplied || !same(await hash(supplied), row.csrf_hash)) return { error: json({ error: "csrf rejected" }, 403) };
  }
  return { row };
}

async function triggerPublish(env, profileId) {
  if (!env.GITHUB_DISPATCH_TOKEN || !env.GITHUB_REPO) throw new Error("GitHub dispatch is not configured");
  const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/sync.yml/dispatches`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "shahaf-profile-admin", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: env.GITHUB_REF || "main", inputs: { profile_id: profileId } }),
  });
  if (!response.ok && response.status !== 204) throw new Error(`GitHub dispatch returned HTTP ${response.status}`);
}

const adminHtml = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Shahaf profile admin</title><style>body{font:16px system-ui;max-width:900px;margin:auto;padding:24px;background:#f6f5f2;color:#252329}main{background:white;border:1px solid #ddd6d0;border-radius:20px;padding:24px}textarea,input{width:100%;box-sizing:border-box;padding:12px;border:1px solid #cfc7bf;border-radius:10px;font:inherit}textarea{min-height:300px;font-family:ui-monospace,monospace}button{padding:11px 16px;border:0;border-radius:10px;background:#292535;color:white;font-weight:700;cursor:pointer;margin:8px 5px 8px 0}.muted{color:#6c6570}.error{color:#a32035;white-space:pre-wrap}.profile{padding:15px 0;border-top:1px solid #eee}.hidden{display:none}code{word-break:break-all}</style></head><body><main><h1>Shahaf profile admin</h1><p class="muted">Private operator console. Names stay in D1 and are never published.</p><section id="login"><input id="password" type="password" placeholder="Admin passphrase"><button id="loginBtn">Log in</button><p id="loginMsg" class="error"></p></section><section id="app" class="hidden"><button id="logoutBtn">Log out</button><h2>Import profile</h2><label>Admin-only student name<input id="studentName" placeholder="Optional only if package already names the student"></label><p><input id="file" type="file" accept=".json,application/json"><button id="loadFile">Load JSON file</button></p><textarea id="payload" placeholder="Paste the complete GPT JSON package here"></textarea><button id="importBtn">Validate and publish</button><pre id="result" class="error"></pre><h2>Profiles</h2><div id="profiles">Loading…</div></section></main><script>let csrf="";const $=function(id){return document.getElementById(id)};async function api(path,options){options=options||{};const headers=Object.assign({"content-type":"application/json"},options.headers||{});if(csrf)headers["X-CSRF-Token"]=csrf;const r=await fetch(path,Object.assign({credentials:"include"},options,{headers:headers}));const body=await r.json().catch(function(){return {}});if(!r.ok)throw new Error(body.error||("HTTP "+r.status));return body}function show(msg){$("result").textContent=msg}async function refresh(){try{const data=await api("/api/profiles",{method:"GET"});$("profiles").innerHTML=data.profiles.map(function(p){return '<div class="profile"><strong>'+p.name+'</strong> <span class="muted">'+(p.active?"active":"disabled")+'</span><br>Public ID: <code>'+p.public_id+'</code><br><a href="'+p.page_url+'" target="_blank">Schedule</a> · <a href="'+p.wake_url+'" target="_blank">wake.json</a><br>Alarm label: <code>'+p.alarm_label+'</code><br><button data-disable="'+p.id+'" '+(p.active?"":"disabled")+'>Disable</button></div>'}).join("")||"No profiles yet";document.querySelectorAll("[data-disable]").forEach(function(b){b.onclick=async function(){if(confirm("Disable this profile?")){await api("/api/profiles/"+b.dataset.disable+"/disable",{method:"POST",body:"{}"});refresh()}}})}catch(e){$("profiles").textContent=e.message}}$("loginBtn").onclick=async function(){try{const r=await fetch("/api/login",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({password:$("password").value})});const b=await r.json();if(!r.ok)throw new Error(b.error||"Login failed");csrf=b.csrf;$("login").classList.add("hidden");$("app").classList.remove("hidden");refresh()}catch(e){$("loginMsg").textContent=e.message}};$("logoutBtn").onclick=async function(){await api("/api/logout",{method:"POST",body:"{}"});location.reload()};$("loadFile").onclick=function(){const f=$("file").files[0];if(!f)return;const reader=new FileReader();reader.onload=function(){$("payload").value=reader.result};reader.readAsText(f)};$("importBtn").onclick=async function(){try{const package=JSON.parse($("payload").value);const name=$("studentName").value.trim();const result=await api("/api/profiles/import",{method:"POST",body:JSON.stringify({name:name,package:package})});show("Queued "+result.public_id+"\\n"+result.page_url+"\\n"+result.wake_url+"\\nAlarm: "+result.alarm_label);refresh()}catch(e){show(e.message)}};</script></body></html>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") return new Response(adminHtml, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
    if (url.pathname === "/api/login" && request.method === "POST") {
      if (!originOK(request, env, true) || !(await rateLimit(env, `login:${request.headers.get("CF-Connecting-IP") || "unknown"}`, 8, 900))) return json({ error: "too many login attempts" }, 429);
      const body = await request.json().catch(() => ({}));
      if (!(await verifyPassword(body.password || "", env.ADMIN_PASSWORD_HASH))) return json({ error: "invalid passphrase" }, 401);
      const session = randomToken(); const csrf = randomToken(); const expires = new Date(Date.now() + MAX_AGE * 1000).toISOString();
      await env.DB.prepare("INSERT INTO sessions(token_hash, csrf_hash, created_at, expires_at) VALUES(?1, ?2, ?3, ?4)").bind(await hash(session), await hash(csrf), now(), expires).run();
      return json({ csrf }, 200, { "set-cookie": `__Host-shahaf_session=${encodeURIComponent(session)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${MAX_AGE}` });
    }
    if (url.pathname === "/api/logout" && request.method === "POST") {
      const check = await auth(request, env, true); if (check.error) return check.error;
      const session = cookie(request, "__Host-shahaf_session"); await env.DB.prepare("DELETE FROM sessions WHERE token_hash=?1").bind(await hash(session)).run();
      return json({ ok: true }, 200, { "set-cookie": "__Host-shahaf_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0" });
    }
    if (url.pathname === "/internal/profiles" && request.method === "GET") {
      if (!env.PROFILE_SYNC_TOKEN || request.headers.get("Authorization") !== `Bearer ${env.PROFILE_SYNC_TOKEN}`) return json({ error: "unauthorized" }, 401);
      const rows = await env.DB.prepare("SELECT public_id, package_json, active FROM profiles WHERE active=1 ORDER BY created_at").all();
      return json({ profiles: rows.results.map((row) => ({ public_id: row.public_id, active: Boolean(row.active), package: JSON.parse(row.package_json) })) });
    }
    const check = await auth(request, env, csrfRequired(request)); if (check.error) return check.error;
    if (url.pathname === "/api/profiles" && request.method === "GET") {
      const rows = await env.DB.prepare("SELECT id, public_id, name, active, created_at, updated_at, last_publish_status, last_publish_url FROM profiles ORDER BY created_at DESC").all();
      const origin = env.PUBLIC_SITE_ORIGIN.replace(/\/$/, "");
      return json({ profiles: rows.results.map((row) => ({ ...row, active: Boolean(row.active), page_url: `${origin}/students/${row.public_id}/`, wake_url: `${origin}/students/${row.public_id}/wake.json`, alarm_label: `Shahaf Wake - ${row.public_id.slice(0, 6).toUpperCase()}` })) });
    }
    const match = url.pathname.match(/^\/api\/profiles\/([^/]+)$/);
    if (match && request.method === "GET") {
      const row = await env.DB.prepare("SELECT id, public_id, name, package_json, active, created_at, updated_at, last_publish_status, last_publish_url FROM profiles WHERE id=?1").bind(match[1]).first();
      return row ? json({ ...row, package: JSON.parse(row.package_json), active: Boolean(row.active) }) : json({ error: "not found" }, 404);
    }
    if (url.pathname === "/api/profiles/import" && request.method === "POST") {
      if (!(await rateLimit(env, `import:${await hash(cookie(request, "__Host-shahaf_session"))}`, 20, 3600))) return json({ error: "publish rate limit reached" }, 429);
      const body = await request.json().catch(() => ({})); const checked = validatePackage(body.package); if (checked.errors) return json({ error: checked.errors.join("\n") }, 400);
      const name = String(body.name || checked.package.student.name || "").trim(); if (!name) return json({ error: "Enter the admin-only student name" }, 400);
      checked.package.student.name = name;
      const existing = await env.DB.prepare("SELECT id, public_id FROM profiles WHERE name=?1").bind(name).first();
      const id = existing?.id || crypto.randomUUID(); const publicId = existing?.public_id || randomToken(16); const timestamp = now();
      await env.DB.prepare("INSERT INTO profiles(id, public_id, name, package_json, active, created_at, updated_at, last_publish_status) VALUES(?1, ?2, ?3, ?4, 1, ?5, ?5, 'queued') ON CONFLICT(id) DO UPDATE SET package_json=excluded.package_json, active=1, updated_at=excluded.updated_at, last_publish_status='queued'").bind(id, publicId, name, JSON.stringify(checked.package), timestamp).run();
      try { await triggerPublish(env, id); } catch (error) { await env.DB.prepare("UPDATE profiles SET last_publish_status='publish_failed', updated_at=?1 WHERE id=?2").bind(now(), id).run(); return json({ error: `Profile saved but publish failed: ${error.message}` }, 502); }
      const origin = env.PUBLIC_SITE_ORIGIN.replace(/\/$/, ""); return json({ id, public_id: publicId, page_url: `${origin}/students/${publicId}/`, wake_url: `${origin}/students/${publicId}/wake.json`, alarm_label: `Shahaf Wake - ${publicId.slice(0, 6).toUpperCase()}`, warnings: checked.warnings || [], status: "queued" });
    }
    if (match && request.method === "PATCH") {
      const body = await request.json().catch(() => ({})); const checked = validatePackage(body.package); if (checked.errors) return json({ error: checked.errors.join("\n") }, 400);
      await env.DB.prepare("UPDATE profiles SET package_json=?1, updated_at=?2, last_publish_status='queued' WHERE id=?3").bind(JSON.stringify(checked.package), now(), match[1]).run();
      try { await triggerPublish(env, match[1]); } catch (error) { return json({ error: `Publish failed: ${error.message}` }, 502); }
      return json({ status: "queued" });
    }
    const disable = url.pathname.match(/^\/api\/profiles\/([^/]+)\/disable$/);
    if (disable && request.method === "POST") {
      if (!(await rateLimit(env, `publish:${await hash(cookie(request, "__Host-shahaf_session"))}`, 20, 3600))) return json({ error: "publish rate limit reached" }, 429);
      await env.DB.prepare("UPDATE profiles SET active=0, updated_at=?1, last_publish_status='queued' WHERE id=?2").bind(now(), disable[1]).run();
      try { await triggerPublish(env, disable[1]); } catch (error) { return json({ error: `Disabled locally but publish failed: ${error.message}` }, 502); }
      return json({ status: "queued" });
    }
    const publish = url.pathname.match(/^\/api\/publish\/([^/]+)$/);
    if (publish && request.method === "GET") {
      const row = await env.DB.prepare("SELECT id, public_id, active, last_publish_status, last_publish_url, updated_at FROM profiles WHERE id=?1").bind(publish[1]).first();
      return row ? json(row) : json({ error: "not found" }, 404);
    }
    return json({ error: "not found" }, 404);
  },
};
