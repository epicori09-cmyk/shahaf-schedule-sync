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

function profileView(row, origin) {
  const wakeUrl = `${origin}/students/${row.public_id}/wake.json`;
  return {
    ...row,
    active: Boolean(row.active),
    page_url: `${origin}/students/${row.public_id}/`,
    wake_url: wakeUrl,
    shortcut_url: wakeUrl,
    alarm_label: `Shahaf Wake - ${row.public_id.slice(0, 6).toUpperCase()}`,
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
  const rows = await env.DB.prepare("SELECT id, public_id, name, active, created_at, updated_at, last_publish_status, last_publish_url FROM profiles ORDER BY created_at DESC").all();
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
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 90% -10%,#273a30 0,#0d1110 38%);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input,textarea{font:inherit}button{cursor:pointer}a{color:var(--lime)}.hidden{display:none!important}.shell{width:min(1180px,100%);margin:0 auto;padding:22px 20px 56px}.topbar{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:32px}.brand{display:flex;align-items:center;gap:12px}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:11px;background:var(--lime);color:#111a13;font-weight:900}.brand strong{display:block;font-size:17px;letter-spacing:-.02em}.brand span{display:block;color:var(--muted);font-size:12px}.button{min-height:40px;padding:9px 14px;border:1px solid var(--line);border-radius:10px;background:var(--surface-2);color:var(--ink);font-weight:750}.button:hover{border-color:var(--lime)}.button.primary{background:var(--lime);border-color:var(--lime);color:#15200f}.button.danger{color:var(--red)}.button:disabled{cursor:not-allowed;opacity:.55}.login-wrap{width:min(450px,100%);margin:10vh auto 0}.eyebrow{margin:0 0 8px;color:var(--lime);font-size:11px;font-weight:850;letter-spacing:.14em;text-transform:uppercase}.login-wrap h1{margin:0 0 10px;font-size:clamp(30px,7vw,48px);letter-spacing:-.05em;line-height:1.03}.lede{color:var(--muted);margin:0 0 24px}.panel{background:rgba(21,27,25,.88);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}.login-panel{padding:24px}.field{display:grid;gap:7px;margin:16px 0}.field label,.field-label{font-size:12px;color:var(--muted);font-weight:750}.input,.textarea{width:100%;border:1px solid var(--line);border-radius:10px;background:#0f1513;color:var(--ink);outline:none}.input{height:44px;padding:0 12px}.textarea{min-height:280px;padding:13px;resize:vertical;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}.input:focus,.textarea:focus{border-color:var(--lime);box-shadow:0 0 0 3px rgba(201,243,107,.12)}.error{min-height:20px;color:var(--red);white-space:pre-wrap}.dashboard-head{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:24px}.dashboard-head h1{margin:0;font-size:clamp(29px,5vw,44px);letter-spacing:-.055em;line-height:1.05}.dashboard-head p{margin:8px 0 0;color:var(--muted)}.head-actions{display:flex;gap:8px;flex-wrap:wrap}.health-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:24px}.health-card{padding:17px;background:var(--surface);border:1px solid var(--line);border-radius:12px}.health-label{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:12px;font-weight:750}.health-value{margin:15px 0 4px;font-size:22px;font-weight:850;letter-spacing:-.03em}.health-meta{color:var(--muted);font-size:12px}.status{display:inline-flex;align-items:center;gap:6px;color:var(--lime);font-size:11px;font-weight:850;text-transform:uppercase;letter-spacing:.08em}.status:before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}.status.warn{color:var(--pink)}.status.bad{color:var(--red)}.workspace{display:grid;grid-template-columns:minmax(0,1.18fr) minmax(280px,.82fr);gap:16px;margin-bottom:24px}.panel-pad{padding:20px}.section-head{display:flex;justify-content:space-between;align-items:start;gap:16px;margin-bottom:16px}.section-head h2{margin:0;font-size:18px;letter-spacing:-.025em}.section-head p{margin:4px 0 0;color:var(--muted);font-size:13px}.import-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:12px}.file-button{position:relative;overflow:hidden}.file-button input{position:absolute;inset:0;opacity:0;cursor:pointer}.helper{color:var(--muted);font-size:12px}.result{margin:14px 0 0;padding:12px;border-radius:10px;background:#0e1412;border:1px solid var(--line);color:var(--lime);font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere}.result:empty{display:none}.quick-list{display:grid;gap:11px;margin:0;padding:0;list-style:none}.quick-list li{display:flex;gap:10px;color:var(--muted);font-size:13px}.quick-list b{color:var(--pink);font-weight:850}.profiles-panel{padding:20px}.profile-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.profile-card{padding:16px;background:var(--surface-2);border:1px solid var(--line);border-radius:12px}.profile-top{display:flex;justify-content:space-between;gap:12px;align-items:start}.profile-name{font-size:17px;font-weight:850}.profile-id{margin-top:4px;color:var(--muted);font:12px ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}.profile-details{display:grid;gap:6px;margin:15px 0;color:var(--muted);font-size:12px}.profile-details strong{color:var(--ink);font-weight:650}.profile-links{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}.profile-links a{font-size:12px;font-weight:800}.profile-actions{display:flex;gap:8px;margin-top:15px}.empty{padding:30px 10px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:10px}.skeleton{height:112px;background:linear-gradient(100deg,var(--surface) 30%,var(--surface-3) 45%,var(--surface) 60%);background-size:200% 100%;animation:shimmer 1.4s infinite;border-radius:12px}@keyframes shimmer{to{background-position:-200% 0}}.toast{position:fixed;right:20px;bottom:20px;max-width:360px;padding:13px 15px;border-radius:10px;background:var(--surface-3);border:1px solid var(--line);box-shadow:var(--shadow);font-size:13px}.toast.bad{border-color:var(--red);color:var(--red)}@media(max-width:820px){.health-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.workspace{grid-template-columns:1fr}.profile-list{grid-template-columns:1fr}}@media(max-width:520px){.shell{padding:16px 14px 40px}.topbar{margin-bottom:24px}.dashboard-head{display:block}.head-actions{margin-top:16px}.head-actions .button{flex:1}.health-grid{gap:8px}.health-card{padding:13px}.health-value{font-size:19px}.panel-pad,.profiles-panel{padding:15px}.profile-links a{font-size:11px}.login-wrap{margin-top:6vh}}
</style></head><body><div class="shell"><header class="topbar"><div class="brand"><div class="brand-mark">S</div><div><strong>Shahaf operator</strong><span>Private schedule control room</span></div></div><button id="logoutBtn" class="button hidden">Log out</button></header>
<main id="loginScreen" class="login-wrap"><p class="eyebrow">Admin access</p><h1>Keep every schedule in sync.</h1><p class="lede">Import a verified timetable package, monitor publishing health, and hand off clean links to students.</p><section class="panel login-panel"><div class="field"><label for="password">Admin passphrase</label><input id="password" class="input" type="password" autocomplete="current-password"></div><button id="loginBtn" class="button primary">Enter dashboard</button><p id="loginMsg" class="error" role="alert"></p></section></main>
<main id="dashboard" class="hidden"><div class="dashboard-head"><div><p class="eyebrow">Operator dashboard</p><h1>Schedules, under control.</h1><p>One place to import, publish, and check the live school feeds.</p></div><div class="head-actions"><button id="refreshBtn" class="button">Refresh status</button><button id="jumpImport" class="button primary">Add student</button></div></div>
<section id="healthGrid" class="health-grid" aria-label="System health"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></section>
<div class="workspace"><section id="importPanel" class="panel panel-pad"><div class="section-head"><div><h2>Import a profile</h2><p>Paste the strict GPT JSON package or load it from a file.</p></div><span class="status">Private</span></div><div class="field"><label for="studentName">Admin-only student name</label><input id="studentName" class="input" placeholder="Example: Alex Cohen" autocomplete="off"><span class="helper">This name stays in the Worker database and is never published.</span></div><div class="field"><label for="classNumber">Shahaf class number</label><input id="classNumber" class="input" type="number" min="1" max="50" step="1" required placeholder="Example: 2"><span class="helper">Used for that student’s Shahaf changes and exams. This field overrides the package value.</span></div><div class="field"><label for="payload">Profile package</label><textarea id="payload" class="textarea" spellcheck="false" placeholder="Paste the complete JSON object here…"></textarea></div><div class="import-actions"><label class="button file-button">Load .json file<input id="file" type="file" accept=".json,application/json"></label><button id="importBtn" class="button primary">Validate and publish</button></div><pre id="result" class="result" aria-live="polite"></pre></section>
<aside class="panel panel-pad"><div class="section-head"><div><h2>Operator notes</h2><p>Safe defaults for every import.</p></div></div><ul class="quick-list"><li><b>01</b><span>Unknown or incomplete periods are rejected before publishing.</span></li><li><b>02</b><span>Repeating the same name updates its profile instead of duplicating it.</span></li><li><b>03</b><span>Public links use random IDs; names and home locations stay private.</span></li><li><b>04</b><span>Publishing is queued through the existing protected workflow.</span></li></ul></aside></div>
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") return new Response(dashboardHtml, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
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
      const rows = await env.DB.prepare("SELECT id, public_id, name, active, created_at, updated_at, last_publish_status, last_publish_url FROM profiles ORDER BY created_at DESC").all();
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
      const packageInput = body.package && typeof body.package === "object" && !Array.isArray(body.package)
        ? { ...body.package, shahaf: { ...(body.package.shahaf || {}), class_number: classNumber } }
        : body.package;
      const checked = validatePackage(packageInput); if (checked.errors) return json({ error: checked.errors.join("\n") }, 400);
      const name = String(body.name || checked.package.student.name || "").trim(); if (!name) return json({ error: "Enter the admin-only student name" }, 400);
      checked.package.student.name = name;
      const existing = await env.DB.prepare("SELECT id, public_id FROM profiles WHERE name=?1").bind(name).first();
      const id = existing?.id || crypto.randomUUID(); const publicId = existing?.public_id || randomToken(16); const timestamp = now();
      await env.DB.prepare("INSERT INTO profiles(id, public_id, name, package_json, active, created_at, updated_at, last_publish_status) VALUES(?1, ?2, ?3, ?4, 1, ?5, ?5, 'queued') ON CONFLICT(id) DO UPDATE SET package_json=excluded.package_json, active=1, updated_at=excluded.updated_at, last_publish_status='queued'").bind(id, publicId, name, JSON.stringify(checked.package), timestamp).run();
      try { await triggerPublish(env, id); } catch (error) { await env.DB.prepare("UPDATE profiles SET last_publish_status='publish_failed', updated_at=?1 WHERE id=?2").bind(now(), id).run(); return json({ error: `Profile saved but publish failed: ${error.message}` }, 502); }
      const origin = env.PUBLIC_SITE_ORIGIN.replace(/\/$/, ""); const wakeUrl = `${origin}/students/${publicId}/wake.json`; return json({ id, public_id: publicId, page_url: `${origin}/students/${publicId}/`, wake_url: wakeUrl, shortcut_url: wakeUrl, alarm_label: `Shahaf Wake - ${publicId.slice(0, 6).toUpperCase()}`, warnings: checked.warnings || [], status: "queued" });
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
