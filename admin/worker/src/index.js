const WEEKDAYS = new Set(["sunday", "monday", "tuesday", "wednesday", "thursday"]);
const MAX_AGE = 8 * 60 * 60;

// The admin imports יא profiles only. Operators enter the visible class
// number; Shahaf's internal `cls` value is derived here and never typed.
const YA_CLASS_IDS = Object.freeze({
  "1": "61", "2": "11", "3": "12", "4": "13", "5": "14", "6": "15",
  "7": "16", "8": "17", "9": "18", "11": "45", "12": "62",
});

// This is a display-only fallback for the admin picker. The live list is read
// from Shahaf first, so an import never requires the operator to know `cls`.
const FALLBACK_SHAHAF_CLASSES = [
  ["60", "י - 1"], ["53", "י - 2"], ["3", "י - 3"], ["4", "י - 4"], ["5", "י - 5"],
  ["41", "י - 7"], ["30", "י - 8"], ["51", "י - 9"], ["55", "י - 11"], ["52", "י - 12"],
  ["61", "יא - 1"], ["11", "יא - 2"], ["12", "יא - 3"], ["13", "יא - 4"], ["14", "יא - 5"],
  ["15", "יא - 6"], ["16", "יא - 7"], ["17", "יא - 8"], ["18", "יא - 9"], ["45", "יא - 11"], ["62", "יא - 12"],
  ["63", "יב - 1"], ["21", "יב - 2"], ["22", "יב - 3"], ["23", "יב - 4"], ["24", "יב - 5"],
  ["25", "יב - 6"], ["26", "יב - 7"], ["27", "יב - 8"], ["28", "יב - 9"], ["50", "יב - 11"], ["64", "יב - 12"],
].map(([id, label]) => ({ id, label }));

const ALARM_DEFAULTS = Object.freeze({
  enabled: true,
  wake_buffer_minutes: 75,
  min_wake_time: null,
  max_wake_time: null,
  round_to_minutes: 1,
  stale_policy: "leave",
  no_lessons_policy: "clear",
  fallback_wake_time: "07:15",
  label_template: "Shahaf",
  alarm_label: null,
  transit_min_arrival_margin: 5,
  transit_walk_buffer_minutes: 0,
  transit_route_preference: null,
});
const ALARM_SETTING_FIELDS = Object.freeze(Object.keys(ALARM_DEFAULTS));
const ALARM_ROUNDS = new Set([1, 5, 10, 15]);
const ALARM_ACTIONS = new Set(["set", "clear", "leave"]);

function parseStoredJson(value, fallback = {}) {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : fallback;
  } catch (_) {
    return fallback;
  }
}

function validClock(value, allowNull = true) {
  if (value === null && allowNull) return true;
  return typeof value === "string" && /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
}

function validateAlarmSettings(input, { partial = false } = {}) {
  const raw = input && typeof input === "object" && !Array.isArray(input) ? input : {};
  const errors = [];
  const result = {};
  for (const field of ALARM_SETTING_FIELDS) {
    if (partial && !Object.prototype.hasOwnProperty.call(raw, field)) continue;
    const value = raw[field];
    if (partial && value === null) { result[field] = null; continue; }
    if (field === "enabled") {
      if (typeof value !== "boolean") errors.push("enabled must be true or false"); else result[field] = value;
    } else if (field === "wake_buffer_minutes") {
      if (!Number.isInteger(Number(value)) || Number(value) < 0 || Number(value) > 240) errors.push("wake_buffer_minutes must be an integer from 0 to 240"); else result[field] = Number(value);
    } else if (["min_wake_time", "max_wake_time", "fallback_wake_time"].includes(field)) {
      if (!validClock(value, field !== "fallback_wake_time")) errors.push(`${field} must use HH:MM`); else result[field] = value;
    } else if (field === "round_to_minutes") {
      if (!ALARM_ROUNDS.has(Number(value))) errors.push("round_to_minutes must be 1, 5, 10, or 15"); else result[field] = Number(value);
    } else if (field === "stale_policy") {
      if (!["leave", "set_fixed"].includes(value)) errors.push("stale_policy must be leave or set_fixed"); else result[field] = value;
    } else if (field === "no_lessons_policy") {
      if (!["clear", "leave"].includes(value)) errors.push("no_lessons_policy must be clear or leave"); else result[field] = value;
    } else if (field === "label_template") {
      if (typeof value !== "string" || !value.trim() || value.length > 80 || /[\r\n]/.test(value)) errors.push("label_template must be 1–80 characters without line breaks"); else result[field] = value.trim();
    } else if (field === "alarm_label") {
      if (value === null) result[field] = null;
      else if (typeof value !== "string" || !value.trim() || value.length > 80 || /[\r\n]/.test(value)) errors.push("alarm_label must be 1–80 characters without line breaks"); else result[field] = value.trim();
    } else if (field === "transit_min_arrival_margin") {
      if (!Number.isInteger(Number(value)) || Number(value) < 5 || Number(value) > 120) errors.push("transit_min_arrival_margin must be an integer from 5 to 120"); else result[field] = Number(value);
    } else if (field === "transit_walk_buffer_minutes") {
      if (!Number.isInteger(Number(value)) || Number(value) < 0 || Number(value) > 60) errors.push("transit_walk_buffer_minutes must be an integer from 0 to 60"); else result[field] = Number(value);
    } else if (field === "transit_route_preference") {
      if (value !== null && (typeof value !== "object" || Array.isArray(value))) errors.push("transit_route_preference must be an object or null"); else result[field] = value;
    }
  }
  if (result.min_wake_time && result.max_wake_time && result.min_wake_time > result.max_wake_time) errors.push("min_wake_time cannot be later than max_wake_time");
  if (errors.length) return { errors };
  if (!partial) return { settings: { ...ALARM_DEFAULTS, ...result } };
  return { settings: result };
}

function resolveAlarmSettings(globalSettings, profileSettings, publicId) {
  const merged = { ...ALARM_DEFAULTS, ...(globalSettings || {}) };
  for (const field of ALARM_SETTING_FIELDS) {
    if (profileSettings && profileSettings[field] !== undefined && profileSettings[field] !== null) merged[field] = profileSettings[field];
  }
  const template = String(merged.label_template || "Shahaf");
  const label = String(profileSettings?.alarm_label || template)
    .replaceAll("{public_id}", publicId)
    .replaceAll("{profile_id}", publicId);
  return { ...merged, alarm_label: label.slice(0, 80), public_id: publicId };
}

async function ensureAlarmDefaults(env) {
  const timestamp = now();
  await env.DB.prepare("INSERT OR IGNORE INTO alarm_global_settings(id, settings_json, updated_at, updated_by) VALUES(1, ?1, ?2, 'system')")
    .bind(JSON.stringify(ALARM_DEFAULTS), timestamp).run();
}

async function getGlobalAlarmSettings(env) {
  await ensureAlarmDefaults(env);
  const row = await env.DB.prepare("SELECT settings_json, updated_at, updated_by FROM alarm_global_settings WHERE id=1").first();
  const checked = validateAlarmSettings(parseStoredJson(row?.settings_json, {}));
  return { settings: checked.settings || { ...ALARM_DEFAULTS }, updated_at: row?.updated_at || null, updated_by: row?.updated_by || "system" };
}

async function getProfileAlarmSettings(env, profileId) {
  const row = await env.DB.prepare("SELECT settings_json, updated_at, updated_by FROM alarm_profile_settings WHERE profile_id=?1").bind(profileId).first();
  if (!row) return { settings: {}, updated_at: null, updated_by: null };
  const checked = validateAlarmSettings(parseStoredJson(row.settings_json, {}), { partial: true });
  return { settings: checked.settings || {}, updated_at: row.updated_at, updated_by: row.updated_by };
}

async function getPendingAlarmOverride(env, profileId) {
  const row = await env.DB.prepare("SELECT id, profile_id, target_date, action, wake_at, subject, force, reason, created_at, expires_at, published_at FROM alarm_overrides WHERE profile_id=?1 AND consumed_at IS NULL AND expires_at>=?2 ORDER BY created_at DESC LIMIT 1")
    .bind(profileId, now()).first();
  return row || null;
}

async function writeAudit(env, profileId, action, details, actor = "admin") {
  await env.DB.prepare("INSERT INTO alarm_audit(id, profile_id, action, details_json, created_at, created_by) VALUES(?1, ?2, ?3, ?4, ?5, ?6)")
    .bind(crypto.randomUUID(), profileId || null, action, JSON.stringify(details || {}), now(), actor).run();
}

async function saveSettingsHistory(env, scope, profileId, settings, actor = "admin") {
  await env.DB.prepare("INSERT INTO alarm_settings_history(id, scope, profile_id, settings_json, created_at, created_by) VALUES(?1, ?2, ?3, ?4, ?5, ?6)")
    .bind(crypto.randomUUID(), scope, profileId || null, JSON.stringify(settings || {}), now(), actor).run();
}

function alarmSafeView(settings) {
  const result = { ...settings };
  delete result.public_id;
  delete result.alarm_label;
  delete result.label_template;
  delete result.transit_route_preference;
  return result;
}

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

function decodeHtml(value) {
  return String(value || "")
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, number) => String.fromCodePoint(Number(number)))
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&")
    .replace(/&nbsp;/g, " ");
}

function parseShahafClassOptions(html) {
  const select = String(html || "").match(/<select\b[^>]*\bname\s*=\s*["']cls["'][^>]*>[\s\S]*?<\/select>/i);
  if (!select) return [];
  const options = [];
  for (const match of select[0].matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/gi)) {
    const value = match[1].match(/\bvalue\s*=\s*["']([^"']+)["']/i)?.[1]?.trim() || "";
    const label = decodeHtml(match[2].replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
    if (/^[A-Za-z0-9_-]{1,40}$/.test(value) && label) options.push({ id: value, label });
  }
  return [...new Map(options.map((item) => [item.id, item])).values()];
}

async function shahafClassOptions(env) {
  const source = env.SHAHAF_CLASS_LIST_URL || "https://ostrovsky.shahaf.site/?cls=11&tab=changes";
  try {
    const response = await fetch(source, { headers: { Accept: "text/html", "User-Agent": "shahaf-profile-admin" } });
    if (!response.ok) throw new Error(`Shahaf class list returned HTTP ${response.status}`);
    const options = parseShahafClassOptions(await response.text());
    return { classes: options.length ? options : FALLBACK_SHAHAF_CLASSES, stale: !options.length, source };
  } catch (error) {
    return { classes: FALLBACK_SHAHAF_CLASSES, stale: true, source, error: String(error.message || error) };
  }
}

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
      for (const field of ["subject", "teacher"]) if (typeof row[field] !== "string" || !row[field]) errors.push(`${path} lesson requires ${field}`);
      if (row.room !== null && row.room !== undefined && (typeof row.room !== "string" || !row.room)) errors.push(`${path}.room must be a non-empty string or null`);
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
    shahaf: { class_id: String(shahaf.class_id), class_number: Number(shahaf.class_number), shared_subjects: Array.isArray(shahaf.shared_subjects) ? shahaf.shared_subjects : [], selectors: Array.isArray(shahaf.selectors) ? shahaf.selectors : [], exam_terms: Array.isArray(shahaf.exam_terms) ? shahaf.exam_terms : [], exam_exact_terms: Array.isArray(shahaf.exam_exact_terms) ? shahaf.exam_exact_terms : [] },
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

function profileView(row, origin) {
  const wakeUrl = `${origin}/students/${row.public_id}/wake.json`;
  let packageData = {};
  try { packageData = JSON.parse(row.package_json || "{}"); } catch (_) { packageData = {}; }
  const transit = packageData.transit || {};
  return {
    ...row,
    package_json: undefined,
    active: Boolean(row.active),
    page_url: `${origin}/students/${row.public_id}/`,
    wake_url: wakeUrl,
    shortcut_url: wakeUrl,
    alarm_label: "Shahaf",
    transit_enabled: Boolean(transit.enabled),
    transit_address: transit.origin_address || "",
  };
}

async function publicScheduleHealth(origin, path) {
  try {
    const response = await fetch(`${origin}/${path}`, { headers: { Accept: "application/json", "User-Agent": "shahaf-profile-admin" } });
    if (!response.ok) return { available: false, status: response.status, error: "Public endpoint unavailable" };
    const payload = await response.json();
    const wake = payload.transit_wake || {};
    return {
      available: true,
      stale: Boolean(payload.stale || wake.stale),
      generated_at: payload.generated_at || payload.last_successful_sync || null,
      last_successful_sync: payload.last_successful_sync || null,
      next_school_day: payload.next_school_day || wake.next_school_day || null,
      wake_time: payload.wake_time || wake.wake_time || null,
      shortcut_action: payload.shortcut_action || wake.shortcut_action || null,
      subject: payload.subject || wake.subject || null,
      route_departure: payload.route_departure || wake.route_departure || null,
      route_arrival: payload.route_arrival || wake.route_arrival || null,
      arrival_deadline: payload.arrival_deadline || wake.arrival_deadline || null,
      route: payload.route || wake.route || [],
      route_alternatives: payload.route_alternatives || wake.route_alternatives || [],
      route_preference_used: Boolean(payload.route_preference_used ?? wake.route_preference_used),
      route_preference_fallback: Boolean(payload.route_preference_fallback ?? wake.route_preference_fallback),
      error: payload.error || wake.error || "",
    };
  } catch (error) {
    return { available: false, error: "Public endpoint unavailable" };
  }
}

async function workflowHealth(env) {
  try {
    const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/sync.yml/runs?per_page=1`, {
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": "shahaf-profile-admin",
        ...(env.GITHUB_DISPATCH_TOKEN ? { Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}` } : {}),
      },
    });
    if (!response.ok) return { available: false, error: "GitHub Actions status unavailable" };
    const payload = await response.json();
    const run = payload.workflow_runs?.[0];
    return run ? { available: true, status: run.status, conclusion: run.conclusion, updated_at: run.updated_at, url: run.html_url } : { available: true, status: "no_runs", conclusion: null };
  } catch (error) {
    return { available: false, error: "GitHub Actions status unavailable" };
  }
}

async function alarmAdminProfile(env, row, globalSettings) {
  const override = await getPendingAlarmOverride(env, row.id);
  const profile = await getProfileAlarmSettings(env, row.id);
  const effective = resolveAlarmSettings(globalSettings, profile.settings, row.public_id);
  return {
    id: row.id,
    public_id: row.public_id,
    name: row.name,
    active: Boolean(row.active),
    override: override ? { ...override, force: Boolean(override.force) } : null,
    settings: profile.settings,
    effective,
    updated_at: profile.updated_at,
  };
}

async function dashboardData(env) {
  const origin = env.PUBLIC_SITE_ORIGIN.replace(/\/$/, "");
  const rows = await env.DB.prepare("SELECT id, public_id, name, package_json, active, created_at, updated_at, last_publish_status, last_publish_url FROM profiles ORDER BY created_at DESC").all();
  const profiles = rows.results.map((row) => profileView(row, origin));
  const globalAlarm = await getGlobalAlarmSettings(env);
  const alarmProfiles = await Promise.all(rows.results.map(async (row) => ({
    ...(await alarmAdminProfile(env, row, globalAlarm.settings)),
    live: await publicScheduleHealth(origin, `students/${row.public_id}/wake.json`),
  })));
  const [main, ya1, workflow] = await Promise.all([
    publicScheduleHealth(origin, "data.json"),
    publicScheduleHealth(origin, "ya1/data.json"),
    workflowHealth(env),
  ]);
  return {
    profiles,
    alarm: { global: globalAlarm.settings, global_updated_at: globalAlarm.updated_at, profiles: alarmProfiles },
    health: { main, ya1, workflow, checked_at: now() },
  };
}

async function managedProfileRow(env, profileId) {
  return env.DB.prepare("SELECT id, public_id, name, active FROM profiles WHERE id=?1").bind(profileId).first();
}

async function alarmProfilePayload(env, profileId) {
  const row = await managedProfileRow(env, profileId);
  if (!row) return null;
  const global = await getGlobalAlarmSettings(env);
  const profile = await getProfileAlarmSettings(env, profileId);
  const override = await getPendingAlarmOverride(env, profileId);
  return {
    profile: { id: row.id, public_id: row.public_id, name: row.name, active: Boolean(row.active) },
    global: global.settings,
    global_updated_at: global.updated_at,
    settings: profile.settings,
    settings_updated_at: profile.updated_at,
    effective: resolveAlarmSettings(global.settings, profile.settings, row.public_id),
    override: override ? { ...override, force: Boolean(override.force) } : null,
  };
}

function overrideExpiry(targetDate) {
  // Expiry is the end of the target day in Israel. Resolve the offset instead
  // of hard-coding +03:00 so one-time commands remain correct across DST.
  const noon = new Date(`${targetDate}T12:00:00Z`);
  const zonePart = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Jerusalem", timeZoneName: "shortOffset" })
    .formatToParts(noon).find((part) => part.type === "timeZoneName")?.value || "GMT+3";
  const match = zonePart.match(/^GMT([+-])(\d{1,2})(?::(\d{2}))?$/);
  const offset = match ? `${match[1]}${String(match[2]).padStart(2, "0")}:${match[3] || "00"}` : "+03:00";
  return new Date(`${targetDate}T23:59:59${offset}`).toISOString();
}

function validTargetDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T12:00:00+03:00`);
  if (Number.isNaN(parsed.getTime())) return false;
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Jerusalem", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(parsed);
  const fields = Object.fromEntries(parts.filter((part) => ["year", "month", "day"].includes(part.type)).map((part) => [part.type, part.value]));
  return `${fields.year}-${fields.month}-${fields.day}` === value;
}

function validateAlarmCommand(body) {
  const action = String(body?.action || "");
  const targetDate = String(body?.target_date || "");
  const force = body?.force === true;
  const reason = String(body?.reason || "").trim();
  const errors = [];
  if (!ALARM_ACTIONS.has(action)) errors.push("action must be set, clear, or leave");
  if (!validTargetDate(targetDate)) errors.push("target_date must use YYYY-MM-DD");
  if (action === "set") {
    if (typeof body?.wake_at !== "string" || Number.isNaN(Date.parse(body.wake_at))) errors.push("wake_at must be a valid ISO timestamp for set");
    if (typeof body?.subject !== "undefined" && body.subject !== null && String(body.subject).length > 120) errors.push("subject is too long");
  }
  if (force && reason.length < 8) errors.push("a reason of at least 8 characters is required for a force action");
  return errors.length ? { errors } : { action, targetDate, force, reason, wakeAt: body?.wake_at || null, subject: body?.subject ? String(body.subject).slice(0, 120) : null };
}

const dashboardHtml = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>Shahaf Admin Dashboard</title>
<style>
:root{color-scheme:dark;--bg:#0d1110;--surface:#151b19;--surface-2:#1b2421;--surface-3:#222d29;--line:#30403a;--ink:#f2f6f1;--muted:#9aaba2;--lime:#c9f36b;--pink:#ff8fb2;--red:#ff8e8e;--shadow:0 18px 50px rgba(0,0,0,.24)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 90% -10%,#273a30 0,#0d1110 38%);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input,textarea{font:inherit}button{cursor:pointer}a{color:var(--lime)}.hidden{display:none!important}.shell{width:min(1180px,100%);margin:0 auto;padding:22px 20px 56px}.topbar{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:32px}.brand{display:flex;align-items:center;gap:12px}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:11px;background:var(--lime);color:#111a13;font-weight:900}.brand strong{display:block;font-size:17px;letter-spacing:-.02em}.brand span{display:block;color:var(--muted);font-size:12px}.button{min-height:40px;padding:9px 14px;border:1px solid var(--line);border-radius:10px;background:var(--surface-2);color:var(--ink);font-weight:750}.button:hover{border-color:var(--lime)}.button.primary{background:var(--lime);border-color:var(--lime);color:#15200f}.button.danger{color:var(--red)}.button:disabled{cursor:not-allowed;opacity:.55}.login-wrap{width:min(450px,100%);margin:10vh auto 0}.eyebrow{margin:0 0 8px;color:var(--lime);font-size:11px;font-weight:850;letter-spacing:.14em;text-transform:uppercase}.login-wrap h1{margin:0 0 10px;font-size:clamp(30px,7vw,48px);letter-spacing:-.05em;line-height:1.03}.lede{color:var(--muted);margin:0 0 24px}.panel{background:rgba(21,27,25,.88);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}.login-panel{padding:24px}.field{display:grid;gap:7px;margin:16px 0}.field label,.field-label{font-size:12px;color:var(--muted);font-weight:750}.input,.textarea{width:100%;border:1px solid var(--line);border-radius:10px;background:#0f1513;color:var(--ink);outline:none}.input{height:44px;padding:0 12px}.textarea{min-height:280px;padding:13px;resize:vertical;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}.input:focus,.textarea:focus{border-color:var(--lime);box-shadow:0 0 0 3px rgba(201,243,107,.12)}.error{min-height:20px;color:var(--red);white-space:pre-wrap}.dashboard-head{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:24px}.dashboard-head h1{margin:0;font-size:clamp(29px,5vw,44px);letter-spacing:-.055em;line-height:1.05}.dashboard-head p{margin:8px 0 0;color:var(--muted)}.head-actions{display:flex;gap:8px;flex-wrap:wrap}.health-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:24px}.health-card{padding:17px;background:var(--surface);border:1px solid var(--line);border-radius:12px}.health-label{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:12px;font-weight:750}.health-value{margin:15px 0 4px;font-size:22px;font-weight:850;letter-spacing:-.03em}.health-meta{color:var(--muted);font-size:12px}.status{display:inline-flex;align-items:center;gap:6px;color:var(--lime);font-size:11px;font-weight:850;text-transform:uppercase;letter-spacing:.08em}.status:before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}.status.warn{color:var(--pink)}.status.bad{color:var(--red)}.workspace{display:grid;grid-template-columns:minmax(0,1.18fr) minmax(280px,.82fr);gap:16px;margin-bottom:24px}.edit-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.edit-grid .field{min-width:0}.panel-pad{padding:20px}.section-head{display:flex;justify-content:space-between;align-items:start;gap:16px;margin-bottom:16px}.section-head h2{margin:0;font-size:18px;letter-spacing:-.025em}.section-head p{margin:4px 0 0;color:var(--muted);font-size:13px}.import-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:12px}.file-button{position:relative;overflow:hidden}.file-button input{position:absolute;inset:0;opacity:0;cursor:pointer}.helper{color:var(--muted);font-size:12px}.result{margin:14px 0 0;padding:12px;border-radius:10px;background:#0e1412;border:1px solid var(--line);color:var(--lime);font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere}.result:empty{display:none}.quick-list{display:grid;gap:11px;margin:0;padding:0;list-style:none}.quick-list li{display:flex;gap:10px;color:var(--muted);font-size:13px}.quick-list b{color:var(--pink);font-weight:850}.profiles-panel{padding:20px}.profile-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.profile-card{padding:16px;background:var(--surface-2);border:1px solid var(--line);border-radius:12px}.profile-top{display:flex;justify-content:space-between;gap:12px;align-items:start}.profile-name{font-size:17px;font-weight:850}.profile-id{margin-top:4px;color:var(--muted);font:12px ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}.profile-details{display:grid;gap:6px;margin:15px 0;color:var(--muted);font-size:12px}.profile-details strong{color:var(--ink);font-weight:650}.profile-links{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}.profile-links a{font-size:12px;font-weight:800}.profile-actions{display:flex;gap:8px;margin-top:15px;flex-wrap:wrap}.empty{padding:30px 10px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:10px}.skeleton{height:112px;background:linear-gradient(100deg,var(--surface) 30%,var(--surface-3) 45%,var(--surface) 60%);background-size:200% 100%;animation:shimmer 1.4s infinite;border-radius:12px}@keyframes shimmer{to{background-position:-200% 0}}.toast{position:fixed;right:20px;bottom:20px;max-width:360px;padding:13px 15px;border-radius:10px;background:var(--surface-3);border:1px solid var(--line);box-shadow:var(--shadow);font-size:13px}.toast.bad{border-color:var(--red);color:var(--red)}@media(max-width:820px){.health-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.workspace{grid-template-columns:1fr}.edit-grid{grid-template-columns:1fr 1fr}.profile-list{grid-template-columns:1fr}}@media(max-width:520px){.shell{padding:16px 14px 40px}.topbar{margin-bottom:24px}.dashboard-head{display:block}.head-actions{margin-top:16px}.head-actions .button{flex:1}.health-grid{gap:8px}.health-card{padding:13px}.health-value{font-size:19px}.panel-pad,.profiles-panel{padding:15px}.profile-links a{font-size:11px}.login-wrap{margin-top:6vh}.edit-grid{grid-template-columns:1fr}}
</style></head><body><div class="shell"><header class="topbar"><div class="brand"><div class="brand-mark">S</div><div><strong>Shahaf operator</strong><span>Private schedule control room</span></div></div><button id="logoutBtn" class="button hidden">Log out</button></header>
<main id="loginScreen" class="login-wrap"><p class="eyebrow">Admin access</p><h1>Keep every schedule in sync.</h1><p class="lede">Import a verified timetable package, monitor publishing health, and hand off clean links to students.</p><section class="panel login-panel"><div class="field"><label for="password">Admin passphrase</label><input id="password" class="input" type="password" autocomplete="current-password"></div><button id="loginBtn" class="button primary">Enter dashboard</button><p id="loginMsg" class="error" role="alert"></p></section></main>
<main id="dashboard" class="hidden"><div class="dashboard-head"><div><p class="eyebrow">Operator dashboard</p><h1>Schedules, under control.</h1><p>One place to import, publish, and check the live school feeds.</p></div><div class="head-actions"><button id="refreshBtn" class="button">Refresh status</button><button id="jumpImport" class="button primary">Add student</button></div></div>
<section id="healthGrid" class="health-grid" aria-label="System health"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></section>
<div class="workspace"><section id="importPanel" class="panel panel-pad"><div class="section-head"><div><h2>Import a profile</h2><p>Paste the strict GPT JSON package or load it from a file.</p></div><span class="status">Private</span></div><div class="field"><label for="studentName">Admin-only student name</label><input id="studentName" class="input" placeholder="Example: Alex Cohen" autocomplete="off"><span class="helper">This name stays in the Worker database and is never published.</span></div><div class="field"><label for="classNumber">Shahaf class number</label><input id="classNumber" class="input" type="number" min="1" max="50" step="1" required placeholder="Example: 2"><span class="helper">Used for that student’s Shahaf changes and exams. This field overrides the package value.</span></div><div class="field"><label for="payload">Profile package</label><textarea id="payload" class="textarea" spellcheck="false" placeholder="Paste the complete JSON object here…"></textarea></div><div class="import-actions"><label class="button file-button">Load .json file<input id="file" type="file" accept=".json,application/json"></label><button id="importBtn" class="button primary">Validate and publish</button></div><pre id="result" class="result" aria-live="polite"></pre></section>
<aside class="panel panel-pad"><div class="section-head"><div><h2>Operator notes</h2><p>Safe defaults for every import.</p></div></div><ul class="quick-list"><li><b>01</b><span>Unknown or incomplete periods are rejected before publishing.</span></li><li><b>02</b><span>Repeating the same name updates its profile instead of duplicating it.</span></li><li><b>03</b><span>Public links use random IDs; names and home locations stay private.</span></li><li><b>04</b><span>Publishing is queued through the existing protected workflow.</span></li></ul></aside></div>
<section id="editPanel" class="panel panel-pad hidden"><div class="section-head"><div><h2>Edit profile</h2><p>Change the name, Shahaf settings, transit address, or any timetable row. Saving validates and queues a new Pages deployment.</p></div><button id="cancelEdit" class="button">Close</button></div><div class="edit-grid"><div class="field"><label for="editName">Admin-only student name</label><input id="editName" class="input" autocomplete="off"></div><div class="field"><label for="editClassNumber">Shahaf class number</label><input id="editClassNumber" class="input" type="number" min="1" max="50" step="1"></div></div><div class="field"><label><input id="editTransitEnabled" type="checkbox"> Enable transit-based wake planning</label><span class="helper">Address and coordinates stay private and are never included in the public page.</span></div><div class="edit-grid"><div class="field"><label for="editOriginAddress">Origin address</label><input id="editOriginAddress" class="input" autocomplete="street-address" placeholder="Optional unless transit is enabled"></div><div class="field"><label for="editOriginLat">Origin latitude</label><input id="editOriginLat" class="input" inputmode="decimal" placeholder="Example: 32.184"></div><div class="field"><label for="editOriginLon">Origin longitude</label><input id="editOriginLon" class="input" inputmode="decimal" placeholder="Example: 34.870"></div></div><div class="field"><label for="editPayload">Complete profile JSON</label><textarea id="editPayload" class="textarea" spellcheck="false"></textarea><span class="helper">Use this for manual schedule edits: change the relevant weekly_schedule row, keeping periods 0–13 and valid statuses.</span></div><div class="import-actions"><span id="editId" class="helper"></span><button id="saveEdit" class="button primary">Validate and save</button></div><pre id="editResult" class="result" aria-live="polite"></pre></section>
<section class="panel profiles-panel"><div class="section-head"><div><h2>Managed students</h2><p id="profileSummary">Loading profiles…</p></div><span id="checkedAt" class="helper"></span></div><div id="profiles" class="profile-list"><div class="skeleton"></div><div class="skeleton"></div></div></section></main></div><div id="toast" class="toast hidden" role="status"></div>
<script>
(function(){"use strict";var csrf="";var $=function(id){return document.getElementById(id)};var loginScreen=$("loginScreen"),dashboard=$("dashboard"),logoutBtn=$("logoutBtn");var escapeHtml=function(value){return String(value==null?"":value).replace(/[&<>"']/g,function(ch){if(ch==="&")return "&amp;";if(ch==="<")return "&lt;";if(ch===">")return "&gt;";if(ch==="'")return "&#39;";return "&quot;"})};var formatDate=function(value){if(!value)return "—";var d=new Date(value);return isNaN(d.getTime())?String(value):d.toLocaleString([], {dateStyle:"medium",timeStyle:"short"})};var toast=function(message,bad){var el=$("toast");el.textContent=message;el.className="toast"+(bad?" bad":"");clearTimeout(toast.timer);toast.timer=setTimeout(function(){el.className="toast hidden"},4200)};
async function api(path,options){options=options||{};var headers=Object.assign({"content-type":"application/json"},options.headers||{});if(csrf)headers["X-CSRF-Token"]=csrf;var response=await fetch(path,Object.assign({credentials:"include"},options,{headers:headers}));var body=await response.json().catch(function(){return {}});if(!response.ok)throw new Error(body.error||("HTTP "+response.status));return body}
function statusClass(item){if(!item||!item.available)return "bad";if(item.stale||item.conclusion==="failure")return "warn";return ""}function statusText(item){if(!item||!item.available)return "Unavailable";if(item.stale)return "Stale";if(item.status==="completed"&&item.conclusion==="failure")return "Failed";if(item.status==="in_progress")return "Running";return "Healthy"}
function renderHealth(health){var cards=[{label:"Active profiles",value:String(health.profileCount),meta:String(health.totalProfiles)+" total in D1",status:health.profileCount?"Ready":"Empty",cls:""},{label:"Main schedule",value:statusText(health.main),meta:health.main.available?"Updated "+formatDate(health.main.generated_at):health.main.error,cls:statusClass(health.main)},{label:"Ya1 schedule",value:statusText(health.ya1),meta:health.ya1.available?"Updated "+formatDate(health.ya1.generated_at):health.ya1.error,cls:statusClass(health.ya1)},{label:"GitHub workflow",value:health.workflow.available?(health.workflow.conclusion||health.workflow.status||"Ready"):"Unavailable",meta:health.workflow.available?"Checked "+formatDate(health.workflow.updated_at):health.workflow.error,cls:health.workflow.available&&health.workflow.conclusion==="failure"?"bad":""}];$("healthGrid").innerHTML=cards.map(function(card){return '<article class="health-card"><div class="health-label"><span>'+escapeHtml(card.label)+'</span><span class="status '+card.cls+'">'+escapeHtml(card.status||statusText(card))+'</span></div><div class="health-value">'+escapeHtml(card.value)+'</div><div class="health-meta">'+escapeHtml(card.meta)+'</div></article>'}).join("")}
function renderProfiles(profiles){var active=profiles.filter(function(p){return p.active}).length;$("profileSummary").textContent=profiles.length?active+" active · "+(profiles.length-active)+" disabled":"No profiles yet";if(!profiles.length){$("profiles").innerHTML='<div class="empty">No managed profiles yet. Import the first verified timetable above.</div>';return}$("profiles").innerHTML=profiles.map(function(p){var state=p.active?"Active":"Disabled";return '<article class="profile-card"><div class="profile-top"><div><div class="profile-name">'+escapeHtml(p.name)+'</div><div class="profile-id">'+escapeHtml(p.public_id)+'</div></div><span class="status '+(p.active?"":"warn")+'">'+state+'</span></div><div class="profile-details"><div><strong>Published:</strong> '+escapeHtml(p.last_publish_status||"never")+'</div><div><strong>Updated:</strong> '+escapeHtml(formatDate(p.updated_at))+'</div><div><strong>Alarm:</strong> <code>'+escapeHtml(p.alarm_label)+'</code></div><div><strong>Shortcut URL:</strong> <code>'+escapeHtml(p.shortcut_url)+'</code></div></div><div class="profile-links"><a href="'+escapeHtml(p.page_url)+'" target="_blank" rel="noreferrer">Open schedule ↗</a><a href="'+escapeHtml(p.wake_url)+'" target="_blank" rel="noreferrer">Open Shortcut endpoint ↗</a></div><div class="profile-actions"><button class="button" data-view="'+escapeHtml(p.id)+'">View details</button><button class="button danger" data-disable="'+escapeHtml(p.id)+'" '+(p.active?"":"disabled")+'>Disable</button></div></article>'}).join("");document.querySelectorAll("[data-view]").forEach(function(button){button.onclick=function(){viewProfile(button.getAttribute("data-view"))}});document.querySelectorAll("[data-disable]").forEach(function(button){button.onclick=function(){disableProfile(button.getAttribute("data-disable"))}})}
async function viewProfile(id){try{var data=await api("/api/profiles/"+encodeURIComponent(id));var rows=(data.package.weekly_schedule||[]).filter(function(row){return row.status==="lesson"}).length;var warnings=(data.package.extraction&&data.package.extraction.warnings)||[];$("result").textContent="Profile details\\nLessons in weekly package: "+rows+"\\nWarnings: "+(warnings.length?warnings.join(" | "):"none");$("importPanel").scrollIntoView({behavior:"smooth",block:"start"})}catch(error){toast(error.message,true)}}
async function disableProfile(id){if(!confirm("Disable this profile? Its history stays stored, but it will leave the next public deployment."))return;try{await api("/api/profiles/"+encodeURIComponent(id)+"/disable",{method:"POST",body:"{}"});toast("Profile disabled; publish queued");await refresh()}catch(error){toast(error.message,true)}}
async function refresh(){try{var data=await api("/api/dashboard");data.health.profileCount=data.profiles.filter(function(p){return p.active}).length;data.health.totalProfiles=data.profiles.length;renderHealth(data.health);renderProfiles(data.profiles);$("checkedAt").textContent="Checked "+formatDate(data.health.checked_at)}catch(error){if(/login required|session expired|HTTP 401/.test(error.message)){location.reload();return}toast(error.message,true)}}
$("loginBtn").onclick=async function(){var button=$("loginBtn");button.disabled=true;$("loginMsg").textContent="";try{var response=await fetch("/api/login",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({password:$("password").value})});var body=await response.json().catch(function(){return {}});if(!response.ok)throw new Error(body.error||"Login failed");csrf=body.csrf;loginScreen.classList.add("hidden");dashboard.classList.remove("hidden");logoutBtn.classList.remove("hidden");await refresh()}catch(error){$("loginMsg").textContent=error.message}finally{button.disabled=false}};$("password").addEventListener("keydown",function(event){if(event.key==="Enter")$("loginBtn").click()});logoutBtn.onclick=async function(){try{await api("/api/logout",{method:"POST",body:"{}"})}finally{location.reload()}};$("refreshBtn").onclick=function(){refresh()};$("jumpImport").onclick=function(){$("importPanel").scrollIntoView({behavior:"smooth",block:"start"});setTimeout(function(){$("studentName").focus()},180)};$("file").onchange=function(){var file=$("file").files[0];if(!file)return;var reader=new FileReader();reader.onload=function(){$("payload").value=reader.result};reader.readAsText(file)};$("importBtn").onclick=async function(){var button=$("importBtn");button.disabled=true;$("result").textContent="Validating package and queuing publish…";try{var classNumber=Number($("classNumber").value);if(!Number.isInteger(classNumber)||classNumber<1){throw new Error("Enter a valid Shahaf class number")};var packageData=JSON.parse($("payload").value);var result=await api("/api/profiles/import",{method:"POST",body:JSON.stringify({name:$("studentName").value.trim(),class_number:classNumber,package:packageData})});$("result").textContent="Publish queued\\n\\nPublic ID: "+result.public_id+"\\nSchedule: "+result.page_url+"\\nShortcut URL (paste into Get Contents of URL): "+result.shortcut_url+"\\nAlarm label: "+result.alarm_label+(result.warnings&&result.warnings.length?"\\n\\nWarnings:\\n"+result.warnings.join("\\n"):"");toast("Profile saved and publish queued");await refresh()}catch(error){$("result").textContent=error.message;toast("Import was not published",true)}finally{button.disabled=false}};api("/api/session").then(function(session){csrf=session.csrf;return api("/api/dashboard")}).then(function(data){loginScreen.classList.add("hidden");dashboard.classList.remove("hidden");logoutBtn.classList.remove("hidden");data.health.profileCount=data.profiles.filter(function(p){return p.active}).length;data.health.totalProfiles=data.profiles.length;renderHealth(data.health);renderProfiles(data.profiles);$("checkedAt").textContent="Checked "+formatDate(data.health.checked_at)}).catch(function(){});
})();</script></body></html>`;

const dashboardEnhancements = `<script>
(function(){"use strict";
  var csrfCookie=function(){return (document.cookie.split(";").map(function(part){return part.trim()}).find(function(part){return part.indexOf("shahaf_csrf=")===0})||"").slice("shahaf_csrf=".length)};
  var callApi=async function(path,options){options=options||{};var headers=Object.assign({"content-type":"application/json","X-CSRF-Token":decodeURIComponent(csrfCookie())},options.headers||{});var response=await fetch(path,Object.assign({credentials:"include"},options,{headers:headers}));var body=await response.json().catch(function(){return {}});if(!response.ok)throw new Error(body.error||("HTTP "+response.status));return body};
  var byId=function(id){return document.getElementById(id)};
  var toast=function(message,bad){var el=byId("toast");if(!el)return;el.textContent=message;el.className="toast"+(bad?" bad":"");clearTimeout(toast.timer);toast.timer=setTimeout(function(){el.className="toast hidden"},4200)};
  var setTransitFields=function(){var enabled=byId("editTransitEnabled")&&byId("editTransitEnabled").checked;["editOriginAddress","editOriginLat","editOriginLon"].forEach(function(id){var el=byId(id);if(el)el.disabled=!enabled})};
  var classOptions=[];
  var populateClassPicker=function(id,current){var select=byId(id);if(!select)return;var saved=String(current||select.value||"").trim();select.innerHTML="";var placeholder=document.createElement("option");placeholder.value="";placeholder.textContent=classOptions.length?"Choose the student’s class…":"Class list is loading…";select.appendChild(placeholder);classOptions.forEach(function(item){var option=document.createElement("option");option.value=item.id;option.textContent=item.label;select.appendChild(option)});if(saved&&!classOptions.some(function(item){return item.id===saved})){var savedOption=document.createElement("option");savedOption.value=saved;savedOption.textContent="Saved class";select.appendChild(savedOption)}select.value=saved};
  var populateClassPickers=function(){populateClassPicker("classId");populateClassPicker("editClassId")};
  var addClassPicker=function(beforeId,selectId,labelText){if(byId(selectId))return;var before=byId(beforeId);if(!before)return;var field=document.createElement("div");field.className="field class-picker-field";var label=document.createElement("label");label.setAttribute("for",selectId);label.textContent=labelText;var select=document.createElement("select");select.id=selectId;select.className="input";select.required=true;label.appendChild(select);var helper=document.createElement("span");helper.id=selectId+"Status";helper.className="helper";helper.textContent="Loading Shahaf’s class list…";var reload=document.createElement("button");reload.type="button";reload.className="button";reload.textContent="Reload class list";reload.onclick=function(){loadClassList()};field.appendChild(label);field.appendChild(helper);field.appendChild(reload);before.closest(".field").parentNode.insertBefore(field,before.closest(".field"));populateClassPicker(selectId)};
  var ensureClassIdFields=function(){};
  var loadClassList=async function(){try{var result=await callApi("/api/classes");classOptions=Array.isArray(result.classes)?result.classes:[];populateClassPickers();var suffix=result.stale?" (using the last safe list)":"";["classIdStatus","editClassIdStatus"].forEach(function(id){var el=byId(id);if(el)el.textContent="Choose by label; the internal ID is stored automatically"+suffix})}catch(error){["classIdStatus","editClassIdStatus"].forEach(function(id){var el=byId(id);if(el)el.textContent="Could not load the class list. Tap Reload class list."});toast("Class list unavailable",true)}};
  ensureClassIdFields();
  var classNumberField=byId("classNumber");if(classNumberField){var classNumberWrap=classNumberField.closest(".field");classNumberWrap.querySelector("label").textContent="יא class number";var classNumberHelp=classNumberWrap.querySelector(".helper");if(classNumberHelp)classNumberHelp.textContent="Enter only the visible יא class number. The internal Shahaf class ID is filled automatically."};var editClassNumberField=byId("editClassNumber");if(editClassNumberField)editClassNumberField.closest(".field").querySelector("label").textContent="יא class number";
  byId("file").addEventListener("change",function(){var file=byId("file").files[0];if(!file)return;var reader=new FileReader();reader.onload=function(){byId("payload").value=reader.result;try{var packageData=JSON.parse(reader.result);var classId=String(packageData.shahaf&&packageData.shahaf.class_id||"").trim();if(classId)byId("classId").value=classId}catch(_){}};reader.readAsText(file)});
  byId("importBtn").onclick=async function(){var button=byId("importBtn");button.disabled=true;byId("result").textContent="Validating package and queuing publish…";try{var classNumber=Number(byId("classNumber").value);if(!Number.isInteger(classNumber)||classNumber<1)throw new Error("Enter a valid יא class number");var packageData=JSON.parse(byId("payload").value);var result=await callApi("/api/profiles/import",{method:"POST",body:JSON.stringify({name:byId("studentName").value.trim(),class_number:classNumber,package:packageData})});byId("result").textContent="Publish queued\\n\\nPublic ID: "+result.public_id+"\\nSchedule: "+result.page_url+"\\nShortcut URL (paste into Get Contents of URL): "+result.shortcut_url+"\\nAlarm label: "+result.alarm_label+(result.warnings&&result.warnings.length?"\\n\\nWarnings:\\n"+result.warnings.join("\\n"):"");toast("Profile saved and publish queued");byId("refreshBtn").click()}catch(error){byId("result").textContent=error.message;toast("Import was not published",true)}finally{button.disabled=false}};
  var blockWeekdays=["sunday","monday","tuesday","wednesday","thursday"];var blockLabels={sunday:"Sunday",monday:"Monday",tuesday:"Tuesday",wednesday:"Wednesday",thursday:"Thursday"};var blockPackage=null;var blockWeekday="sunday";
  var blockCss=function(){if(byId("block-editor-css"))return;var style=document.createElement("style");style.id="block-editor-css";style.textContent=".block-editor{margin:18px 0 4px;padding:16px;border:1px solid var(--line);border-radius:12px;background:#101714}.block-editor-head{display:flex;justify-content:space-between;align-items:start;gap:12px;margin-bottom:13px}.block-editor-head h3{margin:0;font-size:17px}.block-editor-head p{margin:4px 0 0;color:var(--muted);font-size:12px}.block-tabs{display:flex;gap:7px;overflow:auto;padding:2px 0 10px;scrollbar-width:none}.block-tabs::-webkit-scrollbar{display:none}.block-tab{flex:0 0 auto;padding:8px 11px;border:1px solid var(--line);border-radius:9px;background:var(--surface-2);color:var(--muted);font-weight:750}.block-tab.active{background:var(--lime);border-color:var(--lime);color:#15200f}.period-editor-list{display:grid;gap:9px}.period-editor-card{padding:12px;border:1px solid var(--line);border-radius:11px;background:var(--surface-2)}.period-editor-card.is-gap{border-color:#53645c}.period-editor-card.is-unknown{border-color:var(--pink)}.period-editor-top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:9px}.period-editor-top strong{font-size:15px}.period-editor-top span{color:var(--muted);font-size:11px}.period-editor-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.period-editor-field{display:grid;gap:4px}.period-editor-field.wide{grid-column:1/-1}.period-editor-field label{color:var(--muted);font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.05em}.period-editor-field input,.period-editor-field select{width:100%;min-height:38px;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:#0f1513;color:var(--ink);font:inherit}.period-editor-field input:disabled{opacity:.55}.block-note{margin:11px 0 0;color:var(--muted);font-size:11px}@media(max-width:520px){.period-editor-grid{grid-template-columns:1fr}.period-editor-field.wide{grid-column:auto}}";document.head.appendChild(style)};
  var blockField=function(label,value,type,disabled){var wrap=document.createElement("div");wrap.className="period-editor-field";var labelNode=document.createElement("label");labelNode.textContent=label;var input=document.createElement("input");input.type=type||"text";input.value=value||"";input.disabled=Boolean(disabled);wrap.appendChild(labelNode);wrap.appendChild(input);return {wrap:wrap,input:input}};
  var applyBlockState=function(card,row,fields){var lesson=row.status==="lesson";card.classList.toggle("is-gap",row.status==="gap");card.classList.toggle("is-unknown",row.status==="unknown");[fields.subject,fields.teacher,fields.room].forEach(function(field){field.input.disabled=!lesson});fields.start.input.disabled=false;fields.end.input.disabled=false;if(row.status==="gap"){row.subject=null;row.teacher=null;row.room=null;fields.subject.input.value="";fields.teacher.input.value="";fields.room.input.value=""}if(row.status==="unknown"){fields.subject.input.value=row.subject||"";fields.teacher.input.value=row.teacher||"";fields.room.input.value=row.room||""}};
  var renderBlockEditor=function(){var host=byId("blockEditor");if(!host||!blockPackage)return;host.innerHTML="";var heading=document.createElement("div");heading.className="block-editor-head";var title=document.createElement("div");var h=document.createElement("h3");h.textContent="Weekly timetable";var p=document.createElement("p");p.textContent="Edit lessons as cards. Gaps remain visible; changes are validated when you save.";title.appendChild(h);title.appendChild(p);heading.appendChild(title);host.appendChild(heading);var rows=Array.isArray(blockPackage.weekly_schedule)?blockPackage.weekly_schedule:[];var available=blockWeekdays.filter(function(day){return rows.some(function(row){return String(row.weekday).toLowerCase()===day})});if(!available.length)available=blockWeekdays.slice();if(available.indexOf(blockWeekday)<0)blockWeekday=available[0];var tabs=document.createElement("div");tabs.className="block-tabs";available.forEach(function(day){var tab=document.createElement("button");tab.type="button";tab.className="block-tab"+(day===blockWeekday?" active":"");tab.textContent=blockLabels[day];tab.onclick=function(){blockWeekday=day;renderBlockEditor()};tabs.appendChild(tab)});host.appendChild(tabs);var list=document.createElement("div");list.className="period-editor-list";var dayRows=rows.filter(function(row){return String(row.weekday).toLowerCase()===blockWeekday}).sort(function(a,b){return Number(a.period)-Number(b.period)});if(!dayRows.length){var empty=document.createElement("p");empty.className="block-note";empty.textContent="This weekday is not represented in the imported package.";list.appendChild(empty)}dayRows.forEach(function(row){var card=document.createElement("article");card.className="period-editor-card";var top=document.createElement("div");top.className="period-editor-top";var period=document.createElement("strong");period.textContent="Period "+row.period;var times=document.createElement("span");times.textContent=(row.start||"—")+" – "+(row.end||"—");top.appendChild(period);top.appendChild(times);card.appendChild(top);var grid=document.createElement("div");grid.className="period-editor-grid";var statusField=blockField("Status",row.status,"text",false);var status=statusField.input;status.type="select-one";var select=document.createElement("select");["lesson","gap","unknown"].forEach(function(value){var option=document.createElement("option");option.value=value;option.textContent=value==="lesson"?"Lesson":value==="gap"?"Gap / free period":"Unknown / needs review";select.appendChild(option)});select.value=row.status;statusField.wrap.replaceChild(select,status);status=select;var start=blockField("Start time",row.start,"time",false);var end=blockField("End time",row.end,"time",false);var subject=blockField("Subject",row.subject,"text",false);var teacher=blockField("Teacher",row.teacher,"text",false);var room=blockField("Room",row.room,"text",false);subject.wrap.classList.add("wide");teacher.wrap.classList.add("wide");room.wrap.classList.add("wide");[statusField.wrap,start.wrap,end.wrap,subject.wrap,teacher.wrap,room.wrap].forEach(function(field){grid.appendChild(field)});card.appendChild(grid);var fields={status:{input:status},start:start,end:end,subject:subject,teacher:teacher,room:room};var update=function(){row.status=status.value;row.start=start.input.value||null;row.end=end.input.value||null;row.subject=subject.input.value||null;row.teacher=teacher.input.value||null;row.room=room.input.value||null;times.textContent=(row.start||"—")+" – "+(row.end||"—");applyBlockState(card,row,fields)};[start.input,end.input,subject.input,teacher.input,room.input].forEach(function(input){input.addEventListener("input",update)});status.addEventListener("change",update);applyBlockState(card,row,fields);list.appendChild(card)});host.appendChild(list);var note=document.createElement("p");note.className="block-note";note.textContent="Tip: set a cancelled period to Gap. Set Unknown only when you still need to resolve missing information.";host.appendChild(note)};
  var ensureBlockEditor=function(){blockCss();var payload=byId("editPayload");if(!payload)return null;var existing=byId("blockEditor");if(existing)return existing;payload.style.display="none";var field=payload.closest(".field");var host=document.createElement("section");host.id="blockEditor";host.className="block-editor";field.parentNode.insertBefore(host,field);return host};
  window.loadBlockEditor=function(pkg){ensureBlockEditor();blockPackage=JSON.parse(JSON.stringify(pkg||{}));blockWeekday="sunday";renderBlockEditor()};window.syncBlockEditor=function(){if(!blockPackage)return null;var payload=byId("editPayload");if(payload)payload.value=JSON.stringify(blockPackage);return blockPackage};
  window.openManagedProfileEditor=async function(id){try{var data=await callApi("/api/profiles/"+encodeURIComponent(id));var pkg=data.package||{};var transit=pkg.transit||{};byId("editId").textContent="Editing "+data.public_id;byId("editId").setAttribute("data-profile-id",id);byId("editName").value=data.name||(pkg.student&&pkg.student.name)||"";byId("editClassNumber").value=(pkg.shahaf&&pkg.shahaf.class_number)||"";byId("editTransitEnabled").checked=Boolean(transit.enabled);byId("editOriginAddress").value=transit.origin_address||"";byId("editOriginLat").value=transit.origin_lat==null?"":transit.origin_lat;byId("editOriginLon").value=transit.origin_lon==null?"":transit.origin_lon;byId("editPayload").value=JSON.stringify(pkg,null,2);byId("editResult").textContent="";byId("editPanel").classList.remove("hidden");setTransitFields();byId("editPanel").scrollIntoView({behavior:"smooth",block:"start"})}catch(error){toast(error.message,true)}};
  window.saveManagedProfile=async function(){var id=byId("editId").getAttribute("data-profile-id");if(!id)return;var button=byId("saveEdit");button.disabled=true;byId("editResult").textContent="Validating and saving…";try{var pkg=JSON.parse(byId("editPayload").value);pkg.student=pkg.student||{};pkg.student.name=byId("editName").value.trim();pkg.shahaf=pkg.shahaf||{};pkg.shahaf.class_number=Number(byId("editClassNumber").value);pkg.transit=pkg.transit||{};pkg.transit.enabled=byId("editTransitEnabled").checked;if(pkg.transit.enabled){pkg.transit.origin_address=byId("editOriginAddress").value.trim();pkg.transit.origin_lat=Number(byId("editOriginLat").value);pkg.transit.origin_lon=Number(byId("editOriginLon").value)}else{pkg.transit.origin_address=null;pkg.transit.origin_lat=null;pkg.transit.origin_lon=null}await callApi("/api/profiles/"+encodeURIComponent(id),{method:"PATCH",body:JSON.stringify({name:pkg.student.name,class_number:pkg.shahaf.class_number,package:pkg})});byId("editResult").textContent="Saved. Publish queued.";toast("Profile saved; publish queued");setTimeout(function(){byId("editPanel").classList.add("hidden");byId("refreshBtn").click()},700)}catch(error){byId("editResult").textContent=error.message;toast("Profile was not saved",true)}finally{button.disabled=false}};
  window.toggleManagedProfile=async function(id,active){var action=active?"disable":"enable";if(!confirm((active?"Disable":"Enable")+" this profile?"))return;try{await callApi("/api/profiles/"+encodeURIComponent(id)+"/"+action,{method:"POST",body:"{}"});toast("Profile "+(active?"disabled":"enabled")+"; publish queued");byId("refreshBtn").click()}catch(error){toast(error.message,true)}};
  window.deleteManagedProfile=async function(id){if(!confirm("Permanently delete this profile from D1 and remove its public page on the next successful deployment? This cannot be undone."))return;try{await callApi("/api/profiles/"+encodeURIComponent(id),{method:"DELETE",body:"{}"});byId("editPanel").classList.add("hidden");toast("Profile deleted; publish queued");byId("refreshBtn").click()}catch(error){toast(error.message,true)}};
  window.publishManagedProfile=async function(id){try{await callApi("/api/publish/"+encodeURIComponent(id),{method:"POST",body:"{}"});toast("Publish queued");byId("refreshBtn").click()}catch(error){toast(error.message,true)}};
  var enhance=function(){document.querySelectorAll("[data-view], [data-disable]").forEach(function(oldButton){var id=oldButton.getAttribute("data-view")||oldButton.getAttribute("data-disable");var isDisable=oldButton.hasAttribute("data-disable");var active=isDisable&&!oldButton.disabled;var button=document.createElement("button");button.className=oldButton.className;button.setAttribute("data-profile-id",id);button.textContent=isDisable?(active?"Disable":"Enable"):"Edit";if(isDisable&&active)button.classList.add("danger");button.onclick=function(){return isDisable?window.toggleManagedProfile(id,active):window.openManagedProfileEditor(id)};oldButton.replaceWith(button)});document.querySelectorAll(".profile-actions").forEach(function(actions){if(actions.dataset.extraActions)return;var edit=actions.querySelector("[data-profile-id]");if(!edit)return;var id=edit.getAttribute("data-profile-id");actions.dataset.extraActions="1";var publish=document.createElement("button");publish.className="button";publish.textContent="Publish now";publish.onclick=function(){window.publishManagedProfile(id)};var remove=document.createElement("button");remove.className="button danger";remove.textContent="Delete";remove.onclick=function(){window.deleteManagedProfile(id)};actions.appendChild(publish);actions.appendChild(remove)});};
  var originalOpen=window.openManagedProfileEditor;window.openManagedProfileEditor=async function(id){await originalOpen(id);var payload=byId("editPayload");if(payload)window.loadBlockEditor(JSON.parse(payload.value))};var originalSave=window.saveManagedProfile;window.saveManagedProfile=async function(){window.syncBlockEditor();return originalSave()};
  var observer=new MutationObserver(enhance);var profiles=byId("profiles");if(profiles)observer.observe(profiles,{childList:true});enhance();byId("cancelEdit").onclick=function(){byId("editPanel").classList.add("hidden")};byId("saveEdit").onclick=window.saveManagedProfile;byId("editTransitEnabled").onchange=setTransitFields;setTransitFields();
})();</script>`;

const alarmDashboardEnhancements = `<script>
(function(){"use strict";
  var hostId="alarm-control-center";
  var escapeHtml=function(value){return String(value==null?"":value).replace(/[&<>"']/g,function(ch){if(ch==="&")return "&amp;";if(ch==="<")return "&lt;";if(ch===">")return "&gt;";if(ch==="'")return "&#39;";return "&quot;"})};
  var csrfCookie=function(){return (document.cookie.split(";").map(function(part){return part.trim()}).find(function(part){return part.indexOf("shahaf_csrf=")===0})||"").slice("shahaf_csrf=".length)};
  var api=async function(path,options){options=options||{};var headers=Object.assign({"content-type":"application/json","X-CSRF-Token":decodeURIComponent(csrfCookie())},options.headers||{});var response=await fetch(path,Object.assign({credentials:"include"},options,{headers:headers}));var body=await response.json().catch(function(){return {}});if(!response.ok)throw new Error(body.error||("HTTP "+response.status));return body};
  var byId=function(id){return document.getElementById(id)};
  var toast=function(message,bad){var el=byId("toast");if(!el)return;el.textContent=message;el.className="toast"+(bad?" bad":"");clearTimeout(toast.timer);toast.timer=setTimeout(function(){el.className="toast hidden"},4200)};
  var formatDate=function(value){if(!value)return "—";var d=new Date(value);return isNaN(d.getTime())?String(value):d.toLocaleString([], {dateStyle:"medium",timeStyle:"short"})};
  var valueOr=function(value,fallback){return value===null||value===undefined?fallback:value};
  var css=function(){if(byId("alarm-control-css"))return;var style=document.createElement("style");style.id="alarm-control-css";style.textContent=".alarm-control-panel{margin:0 0 24px;padding:20px}.alarm-head{display:flex;justify-content:space-between;align-items:start;gap:16px;margin-bottom:16px}.alarm-head h2{margin:0;font-size:21px}.alarm-head p{margin:5px 0 0;color:var(--muted);font-size:13px}.alarm-badge{display:inline-flex;padding:6px 9px;border-radius:999px;background:#26352c;color:var(--lime);font-size:10px;font-weight:850;text-transform:uppercase;letter-spacing:.07em}.alarm-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,.8fr);gap:16px}.alarm-settings-card,.alarm-bulk-card{padding:15px;border:1px solid var(--line);border-radius:12px;background:var(--surface-2)}.alarm-settings-card h3,.alarm-bulk-card h3{margin:0 0 12px;font-size:15px}.alarm-form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.alarm-form-field{display:grid;gap:5px}.alarm-form-field.wide{grid-column:1/-1}.alarm-form-field label{color:var(--muted);font-size:11px;font-weight:750}.alarm-form-field input,.alarm-form-field select{width:100%;min-height:38px;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:#0f1513;color:var(--ink);font:inherit}.alarm-form-field input[type=checkbox]{width:18px;min-height:18px;accent-color:var(--lime)}.alarm-help{margin:11px 0 0;color:var(--muted);font-size:11px;line-height:1.4}.alarm-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}.alarm-profiles{display:grid;gap:10px;margin-top:16px}.alarm-profile{padding:15px;border:1px solid var(--line);border-radius:12px;background:#111815}.alarm-profile-top{display:flex;justify-content:space-between;align-items:start;gap:10px}.alarm-profile-name{font-weight:850;font-size:16px}.alarm-profile-id{color:var(--muted);font:11px ui-monospace,SFMono-Regular,Menlo,monospace;margin-top:3px;overflow-wrap:anywhere}.alarm-profile-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:13px 0}.alarm-stat{padding:9px;border-radius:9px;background:var(--surface-2)}.alarm-stat span{display:block;color:var(--muted);font-size:10px}.alarm-stat strong{display:block;margin-top:3px;font-size:13px;overflow-wrap:anywhere}.alarm-profile-details{margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}.alarm-profile-details summary{cursor:pointer;color:var(--lime);font-size:12px;font-weight:800}.alarm-profile-details[open] summary{margin-bottom:12px}.alarm-profile-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.alarm-route-summary,.alarm-route-legs,.alarm-route-alternatives{margin:7px 0;color:var(--muted);font-size:11px;line-height:1.4}.alarm-route-summary{color:var(--ink);font-weight:750}.alarm-route-legs{overflow-wrap:anywhere}.alarm-route-alternatives{color:var(--lime)}.alarm-audit{max-height:260px;overflow:auto;margin-top:12px;padding:10px;border-radius:9px;background:#0d1311;color:var(--muted);font-size:11px}.alarm-audit-row{padding:7px 0;border-bottom:1px solid var(--line)}.alarm-audit-row:last-child{border-bottom:0}.alarm-preview{margin-top:12px;padding:11px;border:1px dashed var(--line);border-radius:9px;color:var(--muted);font-size:12px;white-space:pre-wrap}.alarm-danger{color:var(--red)}.alarm-muted{color:var(--muted)}@media(max-width:820px){.alarm-grid{grid-template-columns:1fr}.alarm-form-grid{grid-template-columns:1fr 1fr}.alarm-profile-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:520px){.alarm-control-panel{padding:15px}.alarm-head{display:block}.alarm-badge{margin-top:10px}.alarm-form-grid{grid-template-columns:1fr}.alarm-form-field.wide{grid-column:auto}.alarm-profile-summary{grid-template-columns:1fr 1fr}}";document.head.appendChild(style)};
  var field=function(label,id,type,value,extra){return '<div class="alarm-form-field '+(extra||"")+'"><label for="'+id+'">'+label+'</label><input id="'+id+'" type="'+(type||"text")+'" value="'+escapeHtml(valueOr(value,""))+'"></div>'};
  var select=function(label,id,value,options,extra){return '<div class="alarm-form-field '+(extra||"")+'"><label for="'+id+'">'+label+'</label><select id="'+id+'">'+options.map(function(option){return '<option value="'+escapeHtml(option[0])+'" '+(String(option[0])===String(value)?"selected":"")+'>'+escapeHtml(option[1])+'</option>'}).join("")+"</select></div>"};
  var checkbox=function(label,id,value){return '<div class="alarm-form-field wide"><label><input id="'+id+'" type="checkbox" '+(value?"checked":"")+'> '+label+'</label></div>'};
  var dateInput=function(value){return value||new Date().toISOString().slice(0,10)};
  var model={data:null,audit:[]};
  var ensureHost=function(){css();var existing=byId(hostId);if(existing)return existing;var dashboard=byId("dashboard");if(!dashboard)return null;var workspace=dashboard.querySelector(".workspace");if(!workspace)return null;var host=document.createElement("section");host.id=hostId;host.className="panel alarm-control-panel";workspace.parentNode.insertBefore(host,workspace);return host};
  var globalHtml=function(settings){settings=settings||{};return '<div class="alarm-settings-card"><h3>Alarm defaults</h3><div class="alarm-form-grid">'+checkbox("Enable managed alarm synchronization","alarmGlobalEnabled",settings.enabled!==false)+field("Minutes before first class","alarmGlobalBuffer","number",valueOr(settings.wake_buffer_minutes,75))+field("Backup time","alarmGlobalFallback","time",valueOr(settings.fallback_wake_time,"07:15"))+field("Earliest wake time (optional)","alarmGlobalMin","time",settings.min_wake_time,"wide")+field("Latest wake time (optional)","alarmGlobalMax","time",settings.max_wake_time,"wide")+select("Rounding","alarmGlobalRound",valueOr(settings.round_to_minutes,1),[["1","No rounding"],["5","5 minutes"],["10","10 minutes"],["15","15 minutes"]])+select("If schedule is unavailable","alarmGlobalStale",valueOr(settings.stale_policy,"leave"),[["leave","Keep current alarm"],["set_fixed","Use backup time"]])+select("If there is no school","alarmGlobalNoLessons",valueOr(settings.no_lessons_policy,"clear"),[["clear","Clear this profile's alarm"],["leave","Keep current alarm"]])+field("Alarm name","alarmGlobalLabel","text",valueOr(settings.label_template,"Shahaf"),"wide")+field("Transit safety gap (minutes)","alarmGlobalTransitMargin","number",valueOr(settings.transit_min_arrival_margin,5))+field("Extra walking time (minutes)","alarmGlobalTransitWalk","number",valueOr(settings.transit_walk_buffer_minutes,0))+ '</div><p class="alarm-help">These settings apply only to added students. Ya‑1 and Ya‑2 are unchanged. Use <code>{public_id}</code> or <code>{profile_id}</code> in a label template if needed.</p><div class="alarm-actions"><button id="alarmSaveGlobal" class="button primary">Save</button><button id="alarmPreviewGlobal" class="button">Preview</button><button id="alarmRollbackGlobal" class="button">Undo last change</button></div><div id="alarmGlobalPreview" class="alarm-preview hidden"></div></div>'};
  var bulkHtml=function(){return '<div class="alarm-bulk-card"><h3>Change several alarms</h3><p class="alarm-help">Tick students below, choose what to do, and apply it.</p><div class="alarm-form-grid">'+select("Action","alarmBulkAction","pause",[["pause","Pause alarms"],["resume","Resume alarms"],["reset","Use defaults"],["set","Set alarm"],["clear","Clear alarm"],["leave","Keep as-is"]],"wide")+field("Date","alarmBulkDate","date",dateInput())+field("Wake time (only for Set alarm)","alarmBulkWake","time","07:15")+field("Why are you forcing this?","alarmBulkReason","text","","wide")+checkbox("Force this change (advanced)","alarmBulkForce",false)+'</div><div class="alarm-actions"><button id="alarmBulkPreview" class="button">Preview</button><button id="alarmBulkApply" class="button danger">Apply</button></div><div id="alarmBulkResult" class="alarm-preview hidden"></div></div>'};
  var liveText=function(live){if(!live||!live.available)return "Unavailable";if(live.stale)return "Stale";return live.wake_time||"Ready"};
  var renderProfiles=function(profiles){return (profiles||[]).map(function(item){var live=item.live||{};var effective=item.effective||{};var override=item.override;var state=item.active?"Active":"Disabled";var overrideText=override?(override.action+" on "+override.target_date):"None";var routeIds=item.settings&&item.settings.transit_route_preference&&Array.isArray(item.settings.transit_route_preference.route_ids)?item.settings.transit_route_preference.route_ids.join(","):"";return '<article class="alarm-profile"><div class="alarm-profile-top"><label><input class="alarm-select" type="checkbox" value="'+escapeHtml(item.id)+'"> <span class="alarm-profile-name">'+escapeHtml(item.name)+'</span></label><span class="alarm-badge">'+state+'</span></div><div class="alarm-profile-id">'+escapeHtml(item.public_id)+'</div><div class="alarm-profile-summary"><div class="alarm-stat"><span>Wake time</span><strong>'+escapeHtml(liveText(live))+'</strong></div><div class="alarm-stat"><span>Action</span><strong>'+escapeHtml(live.available?(live.shortcut_action||"set"):"unknown")+'</strong></div><div class="alarm-stat"><span>Label</span><strong>'+escapeHtml(effective.alarm_label||"Shahaf")+'</strong></div><div class="alarm-stat"><span>One-time change</span><strong>'+escapeHtml(overrideText)+'</strong></div></div><details class="alarm-profile-details"><summary>Alarm settings</summary><div class="alarm-form-grid">'+checkbox("Alarm on","alarmEnabled_"+item.id,effective.enabled!==false)+field("Minutes before class (blank = default)","alarmBuffer_"+item.id,"number",valueOr(item.settings.wake_buffer_minutes,""))+field("Alarm name (blank = default)","alarmLabel_"+item.id,"text",valueOr(item.settings.alarm_label,""),"wide")+field("Earliest wake time (optional)","alarmMin_"+item.id,"time",valueOr(item.settings.min_wake_time,""))+field("Latest wake time (optional)","alarmMax_"+item.id,"time",valueOr(item.settings.max_wake_time,""))+select("Round wake time","alarmRound_"+item.id,valueOr(item.settings.round_to_minutes,""),[["","Use default"],["1","No rounding"],["5","5 minutes"],["10","10 minutes"],["15","15 minutes"]])+select("If schedule is missing","alarmStale_"+item.id,valueOr(item.settings.stale_policy,""),[["","Use default"],["leave","Keep current alarm"],["set_fixed","Use backup time"]])+select("If there is no school","alarmNoLessons_"+item.id,valueOr(item.settings.no_lessons_policy,""),[["","Use default"],["clear","Clear this profile"],["leave","Keep current alarm"]])+field("Transit safety gap (minutes)","alarmTransitMargin_"+item.id,"number",valueOr(item.settings.transit_min_arrival_margin,""))+field("Extra walking time (minutes)","alarmTransitWalk_"+item.id,"number",valueOr(item.settings.transit_walk_buffer_minutes,""))+field("Preferred route IDs (advanced)","alarmTransitRoutes_"+item.id,"text",routeIds,"wide")+'</div><div class="alarm-actions"><button class="button primary alarm-save-profile" data-id="'+escapeHtml(item.id)+'">Save</button><button class="button alarm-reset-profile" data-id="'+escapeHtml(item.id)+'">Use defaults</button><button class="button alarm-history-profile" data-id="'+escapeHtml(item.id)+'">History</button><button class="button alarm-rollback-profile" data-id="'+escapeHtml(item.id)+'">Undo</button></div><div class="alarm-form-grid">'+field("One-time change date","alarmCommandDate_"+item.id,"date",dateInput(override&&override.target_date))+select("One-time action","alarmCommandAction_"+item.id,"set",[["set","Set alarm"],["clear","Clear primary alarm"],["leave","Keep current alarm"]])+field("One-time wake time","alarmCommandWake_"+item.id,"time",override&&override.wake_at?new Date(override.wake_at).toTimeString().slice(0,5):"07:15")+field("Why are you forcing this?","alarmCommandReason_"+item.id,"text","","wide")+checkbox("Force this change (advanced)","alarmCommandForce_"+item.id,false)+'</div><div class="alarm-actions"><button class="button danger alarm-command-profile" data-id="'+escapeHtml(item.id)+'">Save one-time change</button></div><div id="alarmHistory_'+escapeHtml(item.id)+'" class="alarm-audit hidden"></div></details></article>'}).join("")||'<div class="empty">No managed profiles available.</div>'};
  var renderRouteSummary=function(profiles){document.querySelectorAll(".alarm-profile").forEach(function(card,index){var live=(profiles[index]||{}).live||{};if(!live.route_departure&&!live.route_arrival)return;var details=card.querySelector(".alarm-profile-details");if(!details)return;var summary=document.createElement("p");summary.className="alarm-route-summary";summary.textContent="Route: leave "+(live.route_departure||"—")+" · arrive "+(live.route_arrival||"—")+" · deadline "+(live.arrival_deadline||"—")+(live.route_preference_fallback?" · pinned route unavailable; automatic route used":"");details.insertBefore(summary,details.firstChild);var legs=(live.route||[]).map(function(leg){if(leg.type==="transit")return (leg.route||"Bus")+" "+(leg.departure||"")+"–"+(leg.arrival||"");if(leg.type==="walk")return "Walk "+(leg.minutes||0)+" min";return "Transfer"}).join(" · ");if(legs){var legLine=document.createElement("p");legLine.className="alarm-route-legs";legLine.textContent=legs;details.insertBefore(legLine,details.firstChild.nextSibling)}var alternatives=live.route_alternatives||[];if(alternatives.length){var altLine=document.createElement("p");altLine.className="alarm-route-alternatives";altLine.textContent="Earlier safe options: "+alternatives.map(function(item){return (item.route_departure||"—")+"→"+(item.route_arrival||"—")}).join(", ");details.insertBefore(altLine,details.firstChild.nextSibling)}})};
  var render=function(){var host=ensureHost();if(!host||!model.data)return;var alarm=model.data.alarm||{};host.innerHTML='<div class="alarm-head"><div><h2>Alarm control center</h2><p>Simple alarm settings for added students.</p></div><span class="alarm-badge">Applies on next Shortcut run</span></div><div class="alarm-grid">'+globalHtml(alarm.global||{})+bulkHtml()+'</div><div class="alarm-profiles"><h3>Per-profile controls</h3>'+renderProfiles(alarm.profiles||[])+'</div>';renderRouteSummary(alarm.profiles||[])};
  var settingsFromGlobal=function(){return {enabled:byId("alarmGlobalEnabled").checked,wake_buffer_minutes:Number(byId("alarmGlobalBuffer").value),fallback_wake_time:byId("alarmGlobalFallback").value,min_wake_time:byId("alarmGlobalMin").value||null,max_wake_time:byId("alarmGlobalMax").value||null,round_to_minutes:Number(byId("alarmGlobalRound").value),stale_policy:byId("alarmGlobalStale").value,no_lessons_policy:byId("alarmGlobalNoLessons").value,label_template:byId("alarmGlobalLabel").value,transit_min_arrival_margin:Number(byId("alarmGlobalTransitMargin").value),transit_walk_buffer_minutes:Number(byId("alarmGlobalTransitWalk").value)}};
  var settingsFromProfile=function(id){var nullable=function(value){return value===""?null:value};var routeText=byId("alarmTransitRoutes_"+id).value.trim();var routePreference=routeText?{route_ids:routeText.split(",").map(function(value){return value.trim()}).filter(Boolean)}:null;return {enabled:byId("alarmEnabled_"+id).checked,wake_buffer_minutes:nullable(byId("alarmBuffer_"+id).value)==null?null:Number(byId("alarmBuffer_"+id).value),alarm_label:nullable(byId("alarmLabel_"+id).value),min_wake_time:nullable(byId("alarmMin_"+id).value),max_wake_time:nullable(byId("alarmMax_"+id).value),round_to_minutes:nullable(byId("alarmRound_"+id).value)==null?null:Number(byId("alarmRound_"+id).value),stale_policy:nullable(byId("alarmStale_"+id).value),no_lessons_policy:nullable(byId("alarmNoLessons_"+id).value),transit_min_arrival_margin:nullable(byId("alarmTransitMargin_"+id).value)==null?null:Number(byId("alarmTransitMargin_"+id).value),transit_walk_buffer_minutes:nullable(byId("alarmTransitWalk_"+id).value)==null?null:Number(byId("alarmTransitWalk_"+id).value),transit_route_preference:routePreference}};
  var selected=function(){return Array.prototype.slice.call(document.querySelectorAll(".alarm-select:checked")).map(function(input){return input.value})};
  var confirmDanger=function(message,force){if(force)return window.confirm(message+"\\n\\nThis can intentionally bypass normal alarm safety. Continue?");return window.confirm(message)};
  var bind=function(){var saveGlobal=byId("alarmSaveGlobal");if(saveGlobal)saveGlobal.onclick=async function(){try{saveGlobal.disabled=true;await api("/api/alarm-settings",{method:"PATCH",body:JSON.stringify({settings:settingsFromGlobal()})});toast("Global managed-profile defaults saved; publish queued");await load()}catch(error){toast(error.message,true)}finally{saveGlobal.disabled=false}};var previewGlobal=byId("alarmPreviewGlobal");if(previewGlobal)previewGlobal.onclick=function(){var box=byId("alarmGlobalPreview");box.textContent=JSON.stringify(settingsFromGlobal(),null,2);box.classList.remove("hidden")};var rollbackGlobal=byId("alarmRollbackGlobal");if(rollbackGlobal)rollbackGlobal.onclick=async function(){if(!confirmDanger("Rollback the most recent global settings version?"))return;try{await api("/api/alarm-settings/rollback",{method:"POST",body:"{}"});toast("Global settings rolled back; publish queued");await load()}catch(error){toast(error.message,true)}};var bulkPreview=byId("alarmBulkPreview");if(bulkPreview)bulkPreview.onclick=function(){var box=byId("alarmBulkResult");box.textContent="Selected profiles: "+selected().length+"\\nAction: "+byId("alarmBulkAction").value+"\\nTarget date: "+byId("alarmBulkDate").value;box.classList.remove("hidden")};var bulkApply=byId("alarmBulkApply");if(bulkApply)bulkApply.onclick=async function(){var ids=selected(),action=byId("alarmBulkAction").value,force=byId("alarmBulkForce").checked;if(!ids.length){toast("Select at least one profile",true);return}if(!confirmDanger("Apply "+action+" to "+ids.length+" managed profile(s)?",force))return;try{bulkApply.disabled=true;var body={profile_ids:ids,action:action,force:force,reason:byId("alarmBulkReason").value,target_date:byId("alarmBulkDate").value};if(action==="set")body.wake_at=byId("alarmBulkDate").value+"T"+byId("alarmBulkWake").value+":00+03:00";await api("/api/alarm-bulk",{method:"POST",body:JSON.stringify(body)});toast("Bulk action queued");await load()}catch(error){toast(error.message,true)}finally{bulkApply.disabled=false}};document.querySelectorAll(".alarm-save-profile").forEach(function(button){button.onclick=async function(){var id=button.dataset.id;try{button.disabled=true;await api("/api/profiles/"+encodeURIComponent(id)+"/alarm-settings",{method:"PATCH",body:JSON.stringify({settings:settingsFromProfile(id)})});toast("Profile alarm settings saved; publish queued");await load()}catch(error){toast(error.message,true)}finally{button.disabled=false}}});document.querySelectorAll(".alarm-reset-profile").forEach(function(button){button.onclick=async function(){if(!confirmDanger("Reset this profile to global defaults?"))return;try{await api("/api/profiles/"+encodeURIComponent(button.dataset.id)+"/alarm-settings/reset",{method:"POST",body:"{}"});toast("Profile reset; publish queued");await load()}catch(error){toast(error.message,true)}}});document.querySelectorAll(".alarm-history-profile").forEach(function(button){button.onclick=async function(){var box=byId("alarmHistory_"+button.dataset.id);try{var result=await api("/api/profiles/"+encodeURIComponent(button.dataset.id)+"/alarm-history");var rows=(result.audit||[]).map(function(row){return '<div class="alarm-audit-row"><strong>'+escapeHtml(row.action)+'</strong><br>'+escapeHtml(formatDate(row.created_at))+'<br>'+escapeHtml(JSON.stringify(row.details||{}))+'</div>'}).join("");box.innerHTML=rows||"No history yet";box.classList.remove("hidden")}catch(error){toast(error.message,true)}}});document.querySelectorAll(".alarm-rollback-profile").forEach(function(button){button.onclick=async function(){if(!confirmDanger("Rollback this profile’s last alarm settings version?"))return;try{await api("/api/profiles/"+encodeURIComponent(button.dataset.id)+"/alarm-settings/rollback",{method:"POST",body:"{}"});toast("Profile rolled back; publish queued");await load()}catch(error){toast(error.message,true)}}});document.querySelectorAll(".alarm-command-profile").forEach(function(button){button.onclick=async function(){var id=button.dataset.id,force=byId("alarmCommandForce_"+id).checked,action=byId("alarmCommandAction_"+id).value,date=byId("alarmCommandDate_"+id).value;if(!confirmDanger("Queue a one-time "+action+" command for "+date+"?",force))return;try{button.disabled=true;var body={action:action,target_date:date,force:force,reason:byId("alarmCommandReason_"+id).value};if(action==="set")body.wake_at=date+"T"+byId("alarmCommandWake_"+id).value+":00+03:00";await api("/api/profiles/"+encodeURIComponent(id)+"/alarm-command",{method:"POST",body:JSON.stringify(body)});toast("One-time alarm command queued");await load()}catch(error){toast(error.message,true)}finally{button.disabled=false}}})};
  var installBulkPreview=function(){var button=byId("alarmBulkPreview");if(!button)return;button.onclick=async function(){var box=byId("alarmBulkResult"),ids=selected(),action=byId("alarmBulkAction").value;if(!ids.length){toast("Select at least one profile",true);return}try{button.disabled=true;var body={profile_ids:ids,action:action,target_date:byId("alarmBulkDate").value,force:byId("alarmBulkForce").checked,reason:byId("alarmBulkReason").value};if(action==="set")body.wake_at=byId("alarmBulkDate").value+"T"+byId("alarmBulkWake").value+":00+03:00";var result=await api("/api/alarm-preview",{method:"POST",body:JSON.stringify(body)});box.textContent=JSON.stringify(result.preview,null,2);box.classList.remove("hidden")}catch(error){toast(error.message,true)}finally{button.disabled=false}}};
  var installHistoryRestore=function(){document.querySelectorAll(".alarm-history-profile").forEach(function(button){button.onclick=async function(){var id=button.dataset.id,box=byId("alarmHistory_"+id);try{var result=await api("/api/profiles/"+encodeURIComponent(id)+"/alarm-history"),versions=(result.history||[]).map(function(row){return '<div class="alarm-audit-row"><strong>Settings version</strong><br>'+escapeHtml(formatDate(row.created_at))+'<br><button class="button alarm-restore-history" data-profile="'+escapeHtml(id)+'" data-history="'+escapeHtml(row.id)+'">Restore this version</button></div>'}).join(""),audit=(result.audit||[]).map(function(row){return '<div class="alarm-audit-row"><strong>'+escapeHtml(row.action)+'</strong><br>'+escapeHtml(formatDate(row.created_at))+'<br>'+escapeHtml(JSON.stringify(row.details||{}))+'</div>'}).join("");box.innerHTML=(versions||"No saved settings versions")+(audit?'<div class="alarm-help">Audit log</div>'+audit:"");box.classList.remove("hidden");box.querySelectorAll(".alarm-restore-history").forEach(function(restore){restore.onclick=async function(){if(!confirmDanger("Restore this saved settings version?"))return;try{await api("/api/profiles/"+encodeURIComponent(restore.dataset.profile)+"/alarm-settings/rollback",{method:"POST",body:JSON.stringify({history_id:restore.dataset.history})});toast("Saved settings version restored; publish queued");await load()}catch(error){toast(error.message,true)}}})}catch(error){toast(error.message,true)}}})};
  var originalBind=bind;bind=function(){originalBind();installBulkPreview();installHistoryRestore()};
  var simplifyControls=function(){var moveToMore=function(grid,ids,title){if(!grid||grid.dataset.simple)return;var nodes=ids.map(function(id){var input=byId(id);return input&&input.closest(".alarm-form-field")}).filter(Boolean);if(!nodes.length)return;var details=document.createElement("details");details.className="alarm-advanced";var summary=document.createElement("summary");summary.textContent=title;details.appendChild(summary);var inner=document.createElement("div");inner.className="alarm-form-grid";nodes.forEach(function(node){inner.appendChild(node)});details.appendChild(inner);grid.parentNode.insertBefore(details,grid.nextSibling);grid.dataset.simple="1"};moveToMore(byId("alarmGlobalEnabled")&&byId("alarmGlobalEnabled").closest(".alarm-form-grid"),["alarmGlobalFallback","alarmGlobalMin","alarmGlobalMax","alarmGlobalRound","alarmGlobalLabel","alarmGlobalTransitMargin","alarmGlobalTransitWalk"],"More settings");moveToMore(byId("alarmBulkAction")&&byId("alarmBulkAction").closest(".alarm-form-grid"),["alarmBulkReason","alarmBulkForce"],"More options")};
  var load=async function(){try{model.data=await api("/api/dashboard");render();simplifyControls();bind()}catch(error){if(!/login required|session expired|HTTP 401/.test(error.message))toast(error.message,true)}};
  var init=function(){ensureHost();var refresh=byId("refreshBtn");if(refresh)refresh.addEventListener("click",function(){setTimeout(load,100)});var login=byId("loginBtn");if(login)login.addEventListener("click",function(){setTimeout(load,800)});load()};if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();</script>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") return new Response(dashboardHtml.replace("</body></html>", dashboardEnhancements + alarmDashboardEnhancements + "</body></html>"), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
    if (url.pathname === "/api/login" && request.method === "POST") {
      if (!originOK(request, env, true) || !(await rateLimit(env, `login:${request.headers.get("CF-Connecting-IP") || "unknown"}`, 8, 900))) return json({ error: "too many login attempts" }, 429);
      const body = await request.json().catch(() => ({}));
      if (!(await verifyPassword(body.password || "", env.ADMIN_PASSWORD_HASH))) return json({ error: "invalid passphrase" }, 401);
      const session = randomToken(); const csrf = randomToken(); const expires = new Date(Date.now() + MAX_AGE * 1000).toISOString();
      await env.DB.prepare("INSERT INTO sessions(token_hash, csrf_hash, created_at, expires_at) VALUES(?1, ?2, ?3, ?4)").bind(await hash(session), await hash(csrf), now(), expires).run();
      const response = json({ csrf }, 200, { "set-cookie": `__Host-shahaf_session=${encodeURIComponent(session)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${MAX_AGE}` });
      response.headers.append("set-cookie", `shahaf_csrf=${encodeURIComponent(csrf)}; Path=/; Secure; SameSite=Strict; Max-Age=${MAX_AGE}`);
      return response;
    }
    if (url.pathname === "/api/logout" && request.method === "POST") {
      const check = await auth(request, env, true); if (check.error) return check.error;
      const session = cookie(request, "__Host-shahaf_session"); await env.DB.prepare("DELETE FROM sessions WHERE token_hash=?1").bind(await hash(session)).run();
      const response = json({ ok: true }, 200, { "set-cookie": "__Host-shahaf_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0" });
      response.headers.append("set-cookie", "shahaf_csrf=; Path=/; Secure; SameSite=Strict; Max-Age=0");
      return response;
    }
    if (url.pathname === "/internal/profiles" && request.method === "GET") {
      if (!env.PROFILE_SYNC_TOKEN || request.headers.get("Authorization") !== `Bearer ${env.PROFILE_SYNC_TOKEN}`) return json({ error: "unauthorized" }, 401);
      const globalAlarm = await getGlobalAlarmSettings(env);
      const rows = await env.DB.prepare("SELECT public_id, package_json, active FROM profiles WHERE active=1 ORDER BY created_at").all();
      const profiles = await Promise.all(rows.results.map(async (row) => {
        const profileRow = await env.DB.prepare("SELECT id, public_id, name, active FROM profiles WHERE public_id=?1").bind(row.public_id).first();
        const profileAlarm = await alarmAdminProfile(env, profileRow, globalAlarm.settings);
        return {
          public_id: row.public_id,
          active: Boolean(row.active),
          package: JSON.parse(row.package_json),
          alarm_settings: profileAlarm.effective,
          alarm_override: profileAlarm.override,
        };
      }));
      return json({ profiles });
    }
    if (url.pathname === "/internal/alarm-commands/ack" && request.method === "POST") {
      if (!env.PROFILE_SYNC_TOKEN || request.headers.get("Authorization") !== `Bearer ${env.PROFILE_SYNC_TOKEN}`) return json({ error: "unauthorized" }, 401);
      const body = await request.json().catch(() => ({}));
      const ids = Array.isArray(body.ids) ? body.ids.filter((value) => typeof value === "string" && value.length <= 80).slice(0, 200) : [];
      if (!ids.length) return json({ acknowledged: 0 });
      const timestamp = now();
      let acknowledged = 0;
      for (const id of ids) {
        const result = await env.DB.prepare("UPDATE alarm_overrides SET published_at=?1 WHERE id=?2 AND consumed_at IS NULL").bind(timestamp, id).run();
        acknowledged += Number(result.meta?.changes || 0);
      }
      return json({ acknowledged });
    }
    const check = await auth(request, env, csrfRequired(request)); if (check.error) return check.error;
    if (url.pathname === "/api/classes" && request.method === "GET") {
      const result = await shahafClassOptions(env);
      return json(result, 200, { "cache-control": "private, max-age=300" });
    }
    if (url.pathname === "/api/session" && request.method === "GET") {
      const existingCsrf = cookie(request, "shahaf_csrf");
      if (existingCsrf && same(await hash(existingCsrf), check.row.csrf_hash)) return json({ csrf: existingCsrf }, 200, { "cache-control": "no-store" });
      const csrf = randomToken();
      await env.DB.prepare("UPDATE sessions SET csrf_hash=?1 WHERE token_hash=?2").bind(await hash(csrf), check.row.token_hash).run();
      const response = json({ csrf }, 200, { "cache-control": "no-store" });
      response.headers.append("set-cookie", `shahaf_csrf=${encodeURIComponent(csrf)}; Path=/; Secure; SameSite=Strict; Max-Age=${MAX_AGE}`);
      return response;
    }
    if (url.pathname === "/api/dashboard" && request.method === "GET") {
      try { return json(await dashboardData(env), 200, { "cache-control": "no-store" }); }
      catch (error) { return json({ error: "Dashboard data unavailable" }, 503, { "cache-control": "no-store" }); }
    }
    if (url.pathname === "/api/alarm-settings" && request.method === "GET") {
      const global = await getGlobalAlarmSettings(env);
      return json({ settings: global.settings, updated_at: global.updated_at, updated_by: global.updated_by });
    }
    if (url.pathname === "/api/alarm-settings" && request.method === "PATCH") {
      if (!(await rateLimit(env, `alarm-settings:${await hash(cookie(request, "__Host-shahaf_session"))}`, 30, 3600))) return json({ error: "alarm settings rate limit reached" }, 429);
      const current = await getGlobalAlarmSettings(env);
      const body = await request.json().catch(() => ({}));
      const candidate = body.settings && typeof body.settings === "object" ? body.settings : body;
      const checked = validateAlarmSettings({ ...current.settings, ...candidate });
      if (checked.errors) return json({ error: checked.errors.join("\n") }, 400);
      await saveSettingsHistory(env, "global", null, current.settings);
      await env.DB.prepare("UPDATE alarm_global_settings SET settings_json=?1, updated_at=?2, updated_by='admin' WHERE id=1").bind(JSON.stringify(checked.settings), now()).run();
      await writeAudit(env, null, "global-settings-updated", { settings: checked.settings });
      try { await triggerPublish(env, "global-alarm-settings-updated"); } catch (error) { return json({ error: `Global settings saved but publish failed: ${error.message}` }, 502); }
      return json({ settings: checked.settings, status: "queued" });
    }
    if (url.pathname === "/api/alarm-settings/rollback" && request.method === "POST") {
      if (!(await rateLimit(env, `alarm-settings:${await hash(cookie(request, "__Host-shahaf_session"))}`, 20, 3600))) return json({ error: "alarm settings rate limit reached" }, 429);
      const body = await request.json().catch(() => ({}));
      const history = body.history_id
        ? await env.DB.prepare("SELECT id, settings_json FROM alarm_settings_history WHERE id=?1 AND scope='global'").bind(String(body.history_id)).first()
        : await env.DB.prepare("SELECT id, settings_json FROM alarm_settings_history WHERE scope='global' ORDER BY created_at DESC LIMIT 1").first();
      if (!history) return json({ error: "no global settings history exists" }, 404);
      const checked = validateAlarmSettings(parseStoredJson(history.settings_json, {}));
      if (checked.errors) return json({ error: "stored settings history is invalid" }, 500);
      const current = await getGlobalAlarmSettings(env);
      await saveSettingsHistory(env, "global", null, current.settings);
      await env.DB.prepare("UPDATE alarm_global_settings SET settings_json=?1, updated_at=?2, updated_by='admin' WHERE id=1").bind(JSON.stringify(checked.settings), now()).run();
      await writeAudit(env, null, "global-settings-rollback", { history_id: history.id });
      try { await triggerPublish(env, "global-alarm-settings-rollback"); } catch (error) { return json({ error: `Global settings rolled back but publish failed: ${error.message}` }, 502); }
      return json({ settings: checked.settings, status: "rolled_back" });
    }
    if (url.pathname === "/api/alarm-audit" && request.method === "GET") {
      const limit = Math.min(Math.max(Number(url.searchParams.get("limit") || 100), 1), 200);
      const rows = await env.DB.prepare("SELECT id, profile_id, action, details_json, created_at, created_by FROM alarm_audit ORDER BY created_at DESC LIMIT ?1").bind(limit).all();
      return json({ audit: rows.results.map((row) => ({ ...row, details: parseStoredJson(row.details_json, {}) })) });
    }
    if (url.pathname === "/api/alarm-preview" && request.method === "POST") {
      if (!(await rateLimit(env, `alarm-preview:${await hash(cookie(request, "__Host-shahaf_session"))}`, 30, 3600))) return json({ error: "alarm preview rate limit reached" }, 429);
      const body = await request.json().catch(() => ({}));
      const ids = Array.isArray(body.profile_ids) ? [...new Set(body.profile_ids.filter((value) => typeof value === "string"))].slice(0, 100) : [];
      const action = String(body.action || "");
      if (!ids.length) return json({ error: "select at least one managed profile" }, 400);
      if (!["pause", "resume", "reset", "set", "clear", "leave"].includes(action)) return json({ error: "invalid bulk action" }, 400);
      const command = ["set", "clear", "leave"].includes(action) ? validateAlarmCommand(body) : null;
      if (command?.errors) return json({ error: command.errors.join("\n") }, 400);
      const global = await getGlobalAlarmSettings(env);
      const rows = [];
      for (const id of ids) {
        const row = await managedProfileRow(env, id);
        if (row) rows.push(row);
      }
      if (!rows.length) return json({ error: "no selected managed profiles were found" }, 404);
      const preview = await Promise.all(rows.map(async (row) => {
        const profile = await getProfileAlarmSettings(env, row.id);
        const before = resolveAlarmSettings(global.settings, profile.settings, row.public_id);
        let after = before;
        if (action === "pause" || action === "resume") after = resolveAlarmSettings(global.settings, { ...profile.settings, enabled: action === "resume" }, row.public_id);
        if (action === "reset") after = resolveAlarmSettings(global.settings, {}, row.public_id);
        return {
          id: row.id,
          public_id: row.public_id,
          name: row.name,
          active: Boolean(row.active),
          action,
          before: { enabled: before.enabled, wake_buffer_minutes: before.wake_buffer_minutes, alarm_label: before.alarm_label },
          after: { enabled: after.enabled, wake_buffer_minutes: after.wake_buffer_minutes, alarm_label: after.alarm_label },
          target_date: command?.targetDate || null,
          wake_at: command?.wakeAt || null,
          force: command?.force || false,
        };
      }));
      return json({ action, requested: ids.length, found: preview.length, preview });
    }
    const alarmProfileMatch = url.pathname.match(/^\/api\/profiles\/([^/]+)\/alarm-settings$/);
    if (alarmProfileMatch && request.method === "GET") {
      const payload = await alarmProfilePayload(env, alarmProfileMatch[1]);
      return payload ? json(payload) : json({ error: "not found" }, 404);
    }
    if (alarmProfileMatch && request.method === "PATCH") {
      if (!(await rateLimit(env, `alarm-settings:${await hash(cookie(request, "__Host-shahaf_session"))}`, 30, 3600))) return json({ error: "alarm settings rate limit reached" }, 429);
      const row = await managedProfileRow(env, alarmProfileMatch[1]);
      if (!row) return json({ error: "not found" }, 404);
      const current = await getProfileAlarmSettings(env, row.id);
      const body = await request.json().catch(() => ({}));
      const candidate = body.settings && typeof body.settings === "object" ? body.settings : body;
      const checked = validateAlarmSettings(candidate, { partial: true });
      if (checked.errors) return json({ error: checked.errors.join("\n") }, 400);
      const next = { ...current.settings, ...checked.settings };
      await saveSettingsHistory(env, "profile", row.id, current.settings);
      await env.DB.prepare("INSERT INTO alarm_profile_settings(profile_id, settings_json, updated_at, updated_by) VALUES(?1, ?2, ?3, 'admin') ON CONFLICT(profile_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at, updated_by='admin'").bind(row.id, JSON.stringify(next), now()).run();
      await writeAudit(env, row.id, "profile-settings-updated", { settings: checked.settings });
      try { await triggerPublish(env, row.id); } catch (error) { return json({ error: `Settings saved but publish failed: ${error.message}` }, 502); }
      return json({ ...(await alarmProfilePayload(env, row.id)), status: "queued" });
    }
    const alarmProfileReset = url.pathname.match(/^\/api\/profiles\/([^/]+)\/alarm-settings\/reset$/);
    if (alarmProfileReset && request.method === "POST") {
      if (!(await rateLimit(env, `alarm-settings:${await hash(cookie(request, "__Host-shahaf_session"))}`, 30, 3600))) return json({ error: "alarm settings rate limit reached" }, 429);
      const row = await managedProfileRow(env, alarmProfileReset[1]);
      if (!row) return json({ error: "not found" }, 404);
      const current = await getProfileAlarmSettings(env, row.id);
      await saveSettingsHistory(env, "profile", row.id, current.settings);
      await env.DB.prepare("DELETE FROM alarm_profile_settings WHERE profile_id=?1").bind(row.id).run();
      await writeAudit(env, row.id, "profile-settings-reset", {});
      try { await triggerPublish(env, row.id); } catch (error) { return json({ error: `Settings reset but publish failed: ${error.message}` }, 502); }
      return json({ ...(await alarmProfilePayload(env, row.id)), status: "queued" });
    }
    const alarmProfileRollback = url.pathname.match(/^\/api\/profiles\/([^/]+)\/alarm-settings\/rollback$/);
    if (alarmProfileRollback && request.method === "POST") {
      if (!(await rateLimit(env, `alarm-settings:${await hash(cookie(request, "__Host-shahaf_session"))}`, 20, 3600))) return json({ error: "alarm settings rate limit reached" }, 429);
      const row = await managedProfileRow(env, alarmProfileRollback[1]);
      if (!row) return json({ error: "not found" }, 404);
      const body = await request.json().catch(() => ({}));
      const history = body.history_id
        ? await env.DB.prepare("SELECT id, settings_json FROM alarm_settings_history WHERE id=?1 AND scope='profile' AND profile_id=?2").bind(String(body.history_id), row.id).first()
        : await env.DB.prepare("SELECT id, settings_json FROM alarm_settings_history WHERE scope='profile' AND profile_id=?1 ORDER BY created_at DESC LIMIT 1").bind(row.id).first();
      if (!history) return json({ error: "no profile settings history exists" }, 404);
      const checked = validateAlarmSettings(parseStoredJson(history.settings_json, {}), { partial: true });
      if (checked.errors) return json({ error: "stored settings history is invalid" }, 500);
      const current = await getProfileAlarmSettings(env, row.id);
      await saveSettingsHistory(env, "profile", row.id, current.settings);
      await env.DB.prepare("INSERT INTO alarm_profile_settings(profile_id, settings_json, updated_at, updated_by) VALUES(?1, ?2, ?3, 'admin') ON CONFLICT(profile_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at, updated_by='admin'").bind(row.id, JSON.stringify(checked.settings), now()).run();
      await writeAudit(env, row.id, "profile-settings-rollback", { history_id: history.id });
      try { await triggerPublish(env, row.id); } catch (error) { return json({ error: `Settings rolled back but publish failed: ${error.message}` }, 502); }
      return json({ ...(await alarmProfilePayload(env, row.id)), status: "queued" });
    }
    const alarmCommand = url.pathname.match(/^\/api\/profiles\/([^/]+)\/alarm-command$/);
    if (alarmCommand && request.method === "POST") {
      if (!(await rateLimit(env, `alarm-command:${await hash(cookie(request, "__Host-shahaf_session"))}`, 30, 3600))) return json({ error: "alarm command rate limit reached" }, 429);
      const row = await managedProfileRow(env, alarmCommand[1]);
      if (!row) return json({ error: "not found" }, 404);
      const body = await request.json().catch(() => ({}));
      const command = validateAlarmCommand(body);
      if (command.errors) return json({ error: command.errors.join("\n") }, 400);
      const timestamp = now();
      const id = crypto.randomUUID();
      await env.DB.prepare("INSERT INTO alarm_overrides(id, profile_id, target_date, action, wake_at, subject, force, reason, created_at, expires_at) VALUES(?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10) ON CONFLICT(profile_id, target_date) DO UPDATE SET id=excluded.id, action=excluded.action, wake_at=excluded.wake_at, subject=excluded.subject, force=excluded.force, reason=excluded.reason, created_at=excluded.created_at, expires_at=excluded.expires_at, consumed_at=NULL")
        .bind(id, row.id, command.targetDate, command.action, command.wakeAt, command.subject, command.force ? 1 : 0, command.reason, timestamp, overrideExpiry(command.targetDate)).run();
      await writeAudit(env, row.id, `alarm-command-${command.action}`, { target_date: command.targetDate, force: command.force, reason: command.reason });
      try { await triggerPublish(env, row.id); } catch (error) { return json({ error: `Command saved but publish failed: ${error.message}` }, 502); }
      return json({ ...(await alarmProfilePayload(env, row.id)), status: "queued", command_id: id });
    }
    const alarmHistory = url.pathname.match(/^\/api\/profiles\/([^/]+)\/alarm-history$/);
    if (alarmHistory && request.method === "GET") {
      const row = await managedProfileRow(env, alarmHistory[1]);
      if (!row) return json({ error: "not found" }, 404);
      const history = await env.DB.prepare("SELECT id, settings_json, created_at, created_by FROM alarm_settings_history WHERE scope='profile' AND profile_id=?1 ORDER BY created_at DESC LIMIT 50").bind(row.id).all();
      const audit = await env.DB.prepare("SELECT id, action, details_json, created_at, created_by FROM alarm_audit WHERE profile_id=?1 ORDER BY created_at DESC LIMIT 100").bind(row.id).all();
      return json({ history: history.results.map((item) => ({ ...item, settings: parseStoredJson(item.settings_json, {}) })), audit: audit.results.map((item) => ({ ...item, details: parseStoredJson(item.details_json, {}) })) });
    }
    if (url.pathname === "/api/alarm-bulk" && request.method === "POST") {
      if (!(await rateLimit(env, `alarm-bulk:${await hash(cookie(request, "__Host-shahaf_session"))}`, 10, 3600))) return json({ error: "bulk alarm rate limit reached" }, 429);
      const body = await request.json().catch(() => ({}));
      const ids = Array.isArray(body.profile_ids) ? [...new Set(body.profile_ids.filter((value) => typeof value === "string"))].slice(0, 100) : [];
      const action = String(body.action || "");
      if (!ids.length) return json({ error: "select at least one managed profile" }, 400);
      if (!["pause", "resume", "reset", "set", "clear", "leave"].includes(action)) return json({ error: "invalid bulk action" }, 400);
      const command = ["set", "clear", "leave"].includes(action) ? validateAlarmCommand(body) : null;
      if (command?.errors) return json({ error: command.errors.join("\n") }, 400);
      const rows = [];
      for (const id of ids) { const row = await managedProfileRow(env, id); if (row) rows.push(row); }
      if (!rows.length) return json({ error: "no selected managed profiles were found" }, 404);
      const timestamp = now();
      for (const row of rows) {
        if (["pause", "resume"].includes(action)) {
          const current = await getProfileAlarmSettings(env, row.id);
          await saveSettingsHistory(env, "profile", row.id, current.settings);
          const settings = { ...current.settings, enabled: action === "resume" };
          await env.DB.prepare("INSERT INTO alarm_profile_settings(profile_id, settings_json, updated_at, updated_by) VALUES(?1, ?2, ?3, 'admin') ON CONFLICT(profile_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at, updated_by='admin'").bind(row.id, JSON.stringify(settings), timestamp).run();
        } else if (action === "reset") {
          const current = await getProfileAlarmSettings(env, row.id);
          await saveSettingsHistory(env, "profile", row.id, current.settings);
          await env.DB.prepare("DELETE FROM alarm_profile_settings WHERE profile_id=?1").bind(row.id).run();
        } else {
          const id = crypto.randomUUID();
          await env.DB.prepare("INSERT INTO alarm_overrides(id, profile_id, target_date, action, wake_at, subject, force, reason, created_at, expires_at) VALUES(?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10) ON CONFLICT(profile_id, target_date) DO UPDATE SET id=excluded.id, action=excluded.action, wake_at=excluded.wake_at, subject=excluded.subject, force=excluded.force, reason=excluded.reason, created_at=excluded.created_at, expires_at=excluded.expires_at, consumed_at=NULL").bind(id, row.id, command.targetDate, command.action, command.wakeAt, command.subject, command.force ? 1 : 0, command.reason, timestamp, overrideExpiry(command.targetDate)).run();
        }
        await writeAudit(env, row.id, `bulk-${action}`, { target_date: command?.targetDate || null, force: command?.force || false, reason: command?.reason || "" });
      }
      try { await triggerPublish(env, "bulk-managed-profiles"); } catch (error) { return json({ error: `Bulk action saved but publish failed: ${error.message}` }, 502); }
      return json({ status: "queued", affected: rows.length });
    }
    if (url.pathname === "/api/profiles" && request.method === "GET") {
      const rows = await env.DB.prepare("SELECT id, public_id, name, package_json, active, created_at, updated_at, last_publish_status, last_publish_url FROM profiles ORDER BY created_at DESC").all();
      const origin = env.PUBLIC_SITE_ORIGIN.replace(/\/$/, "");
      return json({ profiles: rows.results.map((row) => profileView(row, origin)) });
    }
    const match = url.pathname.match(/^\/api\/profiles\/([^/]+)$/);
    if (match && request.method === "GET") {
      const row = await env.DB.prepare("SELECT id, public_id, name, package_json, active, created_at, updated_at, last_publish_status, last_publish_url FROM profiles WHERE id=?1").bind(match[1]).first();
      return row ? json({ ...row, package: JSON.parse(row.package_json), active: Boolean(row.active) }) : json({ error: "not found" }, 404);
    }
    if (url.pathname === "/api/profiles/import" && request.method === "POST") {
      if (!(await rateLimit(env, `import:${await hash(cookie(request, "__Host-shahaf_session"))}`, 20, 3600))) return json({ error: "publish rate limit reached" }, 429);
      const body = await request.json().catch(() => ({}));
      const classNumber = Number(body.class_number);
      if (!Number.isInteger(classNumber) || classNumber < 1) return json({ error: "shahaf.class_number must be supplied as a positive integer" }, 400);
      const classId = YA_CLASS_IDS[String(classNumber)] || "";
      if (!classId) return json({ error: "That יא class number is not in Shahaf’s current class list. Use 1–9, 11, or 12." }, 400);
      const packageInput = body.package && typeof body.package === "object" && !Array.isArray(body.package)
        ? { ...body.package, shahaf: { ...(body.package.shahaf || {}), class_id: classId, class_number: classNumber } }
        : body.package;
      const checked = validatePackage(packageInput); if (checked.errors) return json({ error: checked.errors.join("\n") }, 400);
      const name = String(body.name || checked.package.student.name || "").trim(); if (!name) return json({ error: "Enter the admin-only student name" }, 400);
      checked.package.student.name = name;
      const existing = await env.DB.prepare("SELECT id, public_id FROM profiles WHERE name=?1").bind(name).first();
      const id = existing?.id || crypto.randomUUID(); const publicId = existing?.public_id || randomToken(16); const timestamp = now();
      await env.DB.prepare("INSERT INTO profiles(id, public_id, name, package_json, active, created_at, updated_at, last_publish_status) VALUES(?1, ?2, ?3, ?4, 1, ?5, ?5, 'queued') ON CONFLICT(id) DO UPDATE SET package_json=excluded.package_json, active=1, updated_at=excluded.updated_at, last_publish_status='queued'").bind(id, publicId, name, JSON.stringify(checked.package), timestamp).run();
      try { await triggerPublish(env, id); } catch (error) { await env.DB.prepare("UPDATE profiles SET last_publish_status='publish_failed', updated_at=?1 WHERE id=?2").bind(now(), id).run(); return json({ error: `Profile saved but publish failed: ${error.message}` }, 502); }
      const origin = env.PUBLIC_SITE_ORIGIN.replace(/\/$/, ""); const wakeUrl = `${origin}/students/${publicId}/wake.json`; return json({ id, public_id: publicId, page_url: `${origin}/students/${publicId}/`, wake_url: wakeUrl, shortcut_url: wakeUrl, alarm_label: "Shahaf", warnings: checked.warnings || [], status: "queued" });
    }
    if (match && request.method === "PATCH") {
      if (!(await rateLimit(env, `publish:${await hash(cookie(request, "__Host-shahaf_session"))}`, 20, 3600))) return json({ error: "publish rate limit reached" }, 429);
      const current = await env.DB.prepare("SELECT id, name, package_json FROM profiles WHERE id=?1").bind(match[1]).first();
      if (!current) return json({ error: "not found" }, 404);
      const body = await request.json().catch(() => ({}));
      let currentPackage = {};
      try { currentPackage = JSON.parse(current.package_json); } catch (_) { return json({ error: "stored profile data is malformed" }, 500); }
      const incoming = body.package && typeof body.package === "object" && !Array.isArray(body.package) ? body.package : currentPackage;
      const classNumber = body.class_number ?? incoming.shahaf?.class_number ?? currentPackage.shahaf?.class_number;
      const classId = YA_CLASS_IDS[String(classNumber)] || String(body.class_id ?? incoming.shahaf?.class_id ?? currentPackage.shahaf?.class_id ?? "").trim();
      const packageInput = {
        ...incoming,
        student: { ...(incoming.student || {}), name: String(body.name ?? incoming.student?.name ?? current.name).trim() },
        shahaf: { ...(incoming.shahaf || {}), class_id: classId, class_number: classNumber },
      };
      const checked = validatePackage(packageInput); if (checked.errors) return json({ error: checked.errors.join("\n") }, 400);
      const name = checked.package.student.name || current.name;
      checked.package.student.name = name;
      await env.DB.prepare("UPDATE profiles SET name=?1, package_json=?2, updated_at=?3, last_publish_status='queued' WHERE id=?4").bind(name, JSON.stringify(checked.package), now(), match[1]).run();
      try { await triggerPublish(env, match[1]); } catch (error) { await env.DB.prepare("UPDATE profiles SET last_publish_status='publish_failed', updated_at=?1 WHERE id=?2").bind(now(), match[1]).run(); return json({ error: `Profile saved but publish failed: ${error.message}` }, 502); }
      return json({ status: "queued", id: match[1] });
    }
    const disable = url.pathname.match(/^\/api\/profiles\/([^/]+)\/disable$/);
    if (disable && request.method === "POST") {
      if (!(await rateLimit(env, `publish:${await hash(cookie(request, "__Host-shahaf_session"))}`, 20, 3600))) return json({ error: "publish rate limit reached" }, 429);
      const current = await env.DB.prepare("SELECT id FROM profiles WHERE id=?1").bind(disable[1]).first();
      if (!current) return json({ error: "not found" }, 404);
      await env.DB.prepare("UPDATE profiles SET active=0, updated_at=?1, last_publish_status='queued' WHERE id=?2").bind(now(), disable[1]).run();
      try { await triggerPublish(env, disable[1]); } catch (error) { return json({ error: `Disabled locally but publish failed: ${error.message}` }, 502); }
      return json({ status: "queued" });
    }
    const enable = url.pathname.match(/^\/api\/profiles\/([^/]+)\/enable$/);
    if (enable && request.method === "POST") {
      if (!(await rateLimit(env, `publish:${await hash(cookie(request, "__Host-shahaf_session"))}`, 20, 3600))) return json({ error: "publish rate limit reached" }, 429);
      const current = await env.DB.prepare("SELECT id FROM profiles WHERE id=?1").bind(enable[1]).first();
      if (!current) return json({ error: "not found" }, 404);
      await env.DB.prepare("UPDATE profiles SET active=1, updated_at=?1, last_publish_status='queued' WHERE id=?2").bind(now(), enable[1]).run();
      try { await triggerPublish(env, enable[1]); } catch (error) { return json({ error: `Enabled locally but publish failed: ${error.message}` }, 502); }
      return json({ status: "queued" });
    }
    if (match && request.method === "DELETE") {
      if (!(await rateLimit(env, `publish:${await hash(cookie(request, "__Host-shahaf_session"))}`, 20, 3600))) return json({ error: "publish rate limit reached" }, 429);
      const current = await env.DB.prepare("SELECT id, public_id, name FROM profiles WHERE id=?1").bind(match[1]).first();
      if (!current) return json({ error: "not found" }, 404);
      await env.DB.prepare("DELETE FROM profiles WHERE id=?1").bind(match[1]).run();
      try { await triggerPublish(env, match[1]); } catch (error) { return json({ error: `Profile deleted locally but publish failed: ${error.message}` }, 502); }
      return json({ status: "queued", deleted: true, public_id: current.public_id });
    }
    const publishPost = url.pathname.match(/^\/api\/publish\/([^/]+)$/);
    if (publishPost && request.method === "POST") {
      if (!(await rateLimit(env, `publish:${await hash(cookie(request, "__Host-shahaf_session"))}`, 20, 3600))) return json({ error: "publish rate limit reached" }, 429);
      const current = await env.DB.prepare("SELECT id FROM profiles WHERE id=?1").bind(publishPost[1]).first();
      if (!current) return json({ error: "not found" }, 404);
      await env.DB.prepare("UPDATE profiles SET updated_at=?1, last_publish_status='queued' WHERE id=?2").bind(now(), publishPost[1]).run();
      try { await triggerPublish(env, publishPost[1]); } catch (error) { await env.DB.prepare("UPDATE profiles SET last_publish_status='publish_failed', updated_at=?1 WHERE id=?2").bind(now(), publishPost[1]).run(); return json({ error: `Publish failed: ${error.message}` }, 502); }
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
