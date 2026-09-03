const WEEKDAYS = new Set(["sunday", "monday", "tuesday", "wednesday", "thursday"]);
const MAX_AGE = 8 * 60 * 60;

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

async function dashboardData(env) {
  const origin = env.PUBLIC_SITE_ORIGIN.replace(/\/$/, "");
  const rows = await env.DB.prepare("SELECT id, public_id, name, package_json, active, created_at, updated_at, last_publish_status, last_publish_url FROM profiles ORDER BY created_at DESC").all();
  const profiles = rows.results.map((row) => profileView(row, origin));
  const [main, ya1, workflow] = await Promise.all([
    publicScheduleHealth(origin, "data.json"),
    publicScheduleHealth(origin, "ya1/data.json"),
    workflowHealth(env),
  ]);
  return { profiles, health: { main, ya1, workflow, checked_at: now() } };
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
  var ensureClassIdFields=function(){addClassPicker("classNumber","classNumber","classId","Shahaf class — choose the visible class label");addClassPicker("editClassNumber","editClassNumber","editClassId","Shahaf class — choose the visible class label")};
  var loadClassList=async function(){try{var result=await callApi("/api/classes");classOptions=Array.isArray(result.classes)?result.classes:[];populateClassPickers();var suffix=result.stale?" (using the last safe list)":"";["classIdStatus","editClassIdStatus"].forEach(function(id){var el=byId(id);if(el)el.textContent="Choose by label; the internal ID is stored automatically"+suffix})}catch(error){["classIdStatus","editClassIdStatus"].forEach(function(id){var el=byId(id);if(el)el.textContent="Could not load the class list. Tap Reload class list."});toast("Class list unavailable",true)}};
  ensureClassIdFields();
  byId("file").addEventListener("change",function(){var file=byId("file").files[0];if(!file)return;var reader=new FileReader();reader.onload=function(){byId("payload").value=reader.result;try{var packageData=JSON.parse(reader.result);var classId=String(packageData.shahaf&&packageData.shahaf.class_id||"").trim();if(classId)byId("classId").value=classId}catch(_){}};reader.readAsText(file)});
  byId("importBtn").onclick=async function(){var button=byId("importBtn");button.disabled=true;byId("result").textContent="Validating package and queuing publish…";try{if(!classOptions.length)await loadClassList();var classNumber=Number(byId("classNumber").value);if(!Number.isInteger(classNumber)||classNumber<1)throw new Error("Enter a valid Shahaf class number");var packageData=JSON.parse(byId("payload").value);var classId=String(byId("classId").value||"").trim();if(!classId)throw new Error("Choose the student’s class from the Shahaf class list.");var result=await callApi("/api/profiles/import",{method:"POST",body:JSON.stringify({name:byId("studentName").value.trim(),class_id:classId,class_number:classNumber,package:packageData})});byId("result").textContent="Publish queued\n\nPublic ID: "+result.public_id+"\nSchedule: "+result.page_url+"\nShortcut URL (paste into Get Contents of URL): "+result.shortcut_url+"\nAlarm label: "+result.alarm_label+(result.warnings&&result.warnings.length?"\n\nWarnings:\n"+result.warnings.join("\n"):"");toast("Profile saved and publish queued");byId("refreshBtn").click()}catch(error){byId("result").textContent=error.message;toast("Import was not published",true)}finally{button.disabled=false}};
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
  var originalLogin=byId("loginBtn").onclick;byId("loginBtn").onclick=async function(){await originalLogin();if(!byId("loginScreen").classList.contains("hidden"))return;await loadClassList()};
  var classLoadTimer=setInterval(function(){if(!byId("dashboard").classList.contains("hidden")){clearInterval(classLoadTimer);loadClassList()}},500);
  var originalOpen=window.openManagedProfileEditor;window.openManagedProfileEditor=async function(id){await originalOpen(id);var payload=byId("editPayload");if(payload){var pkg=JSON.parse(payload.value);populateClassPicker("editClassId",String(pkg.shahaf&&pkg.shahaf.class_id||""));window.loadBlockEditor(pkg)}};var originalSave=window.saveManagedProfile;window.saveManagedProfile=async function(){window.syncBlockEditor();var payload=byId("editPayload");if(payload){var pkg=JSON.parse(payload.value);pkg.shahaf=pkg.shahaf||{};pkg.shahaf.class_id=String(byId("editClassId").value||"").trim();payload.value=JSON.stringify(pkg)}return originalSave()};
  var observer=new MutationObserver(enhance);var profiles=byId("profiles");if(profiles)observer.observe(profiles,{childList:true});enhance();byId("cancelEdit").onclick=function(){byId("editPanel").classList.add("hidden")};byId("saveEdit").onclick=window.saveManagedProfile;byId("editTransitEnabled").onchange=setTransitFields;setTransitFields();
})();</script>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") return new Response(dashboardHtml.replace("</body></html>", dashboardEnhancements + "</body></html>"), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
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
      const rows = await env.DB.prepare("SELECT public_id, package_json, active FROM profiles WHERE active=1 ORDER BY created_at").all();
      return json({ profiles: rows.results.map((row) => ({ public_id: row.public_id, active: Boolean(row.active), package: JSON.parse(row.package_json) })) });
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
      const classId = String(body.class_id ?? body.package?.shahaf?.class_id ?? "").trim();
      if (!classId) return json({ error: "shahaf.class_id must be supplied. Enter the Shahaf class ID (the cls value), not only the class number." }, 400);
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
      const classId = String(body.class_id ?? incoming.shahaf?.class_id ?? currentPackage.shahaf?.class_id ?? "").trim();
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
