from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any

from .reconcile import ChangeRecord


def _record_to_dict(record: ChangeRecord) -> dict[str, Any]:
    return {
        "kind": record.kind,
        "date": record.date.isoformat(),
        "period": record.period,
        "subject": record.subject,
        "detail": record.detail,
    }


def _pretty_date(value: str) -> str:
    """Return a compact Israeli date while keeping malformed input harmless."""
    try:
        year, month, day = value.split("-", 2)
        return f"{day}.{month}.{year}"
    except ValueError:
        return value


def _pretty_timestamp(value: str) -> str:
    if not value:
        return "לא ידוע"
    try:
        date_part, time_part = value.split("T", 1)
        return f"{_pretty_date(date_part)} · {time_part[:5]}"
    except ValueError:
        return value


def _kind_label(kind: str) -> tuple[str, str, str]:
    return {
        "cancelled": ("בוטל", "ביטול", "cancelled"),
        "changed": ("עודכן", "שינוי", "changed"),
        "added": ("נוסף", "שיעור חדש", "added"),
    }.get(kind, (kind, "עדכון", "changed"))


def render_site(
    output_dir: Path,
    *,
    title: str,
    generated_at: str,
    source_url: str,
    source_updated: str,
    changes: list[ChangeRecord],
    stale: bool,
    last_successful_sync: str = "",
    error: str = "",
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "title": title,
        "generated_at": generated_at,
        "source_url": source_url,
        "source_updated": source_updated,
        "last_successful_sync": last_successful_sync,
        "stale": stale,
        "error": error,
        "changes": [_record_to_dict(item) for item in changes],
    }
    (output_dir / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if stale:
        banner = '<div class="status-banner stale"><span class="status-icon">!</span><div><strong>הנתונים מסומנים כמיושנים · נדרש לבדוק את הסנכרון</strong><span>לוח השנה לא שונה. מוצג המידע האחרון שנשמר.</span></div></div>'
    else:
        banner = '<div class="status-banner fresh"><span class="status-icon">✓</span><div><strong>הכול מסונכרן</strong><span>השינויים האחרונים נבדקו בהצלחה מול Shahaf.</span></div></div>'
    if error:
        banner += f'<details class="error"><summary>פרטי התקלה</summary><pre>{escape(error)}</pre></details>'
    if changes:
        cards = []
        for item in changes:
            label, sublabel, css_kind = _kind_label(item.kind)
            detail = item.detail or "פורסם עדכון לשיעור הזה"
            cards.append(
                f'''<article class="change-card {css_kind}">
  <div class="change-date"><span>{escape(_pretty_date(item.date.isoformat()))}</span><small>שעה {item.period}</small></div>
  <div class="change-main"><div class="change-topline"><span class="change-kind">{escape(label)}</span><span class="change-subkind">{escape(sublabel)}</span></div>
  <h3>{escape(item.subject)}</h3><p>{escape(detail)}</p></div>
  <span class="change-arrow" aria-hidden="true">←</span>
</article>'''
            )
        changes_html = '<section class="changes-section" aria-labelledby="changes-title"><div class="section-heading"><div><p class="eyebrow">21 הימים הקרובים</p><h2 id="changes-title">מה השתנה?</h2></div><span class="count-pill">{} עדכונים</span></div><div class="change-list">{}</div></section>'.format(len(changes), "".join(cards))
    else:
        changes_html = '''<section class="empty-state" aria-label="אין שינויים">
  <div class="empty-icon" aria-hidden="true">✓</div><div><p class="eyebrow">הכול רגיל</p><h2>אין שינויים בינתיים</h2><p>לא נמצאו ביטולים או עדכונים במערכת ל־21 הימים הקרובים.</p></div>
</section>'''
    count_label = "עדכון אחד" if len(changes) == 1 else f"{len(changes)} עדכונים"
    sync_display = _pretty_timestamp(last_successful_sync or generated_at)
    source_display = _pretty_timestamp(source_updated) if source_updated else "לא ידוע"
    html = f"""<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#10233f">
<meta name="description" content="לוח שינויים מסונכרן לכיתה י״א 8">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="המערכת שלי">
<meta name="last-successful-sync" content="{escape(last_successful_sync or generated_at)}">
<link rel="manifest" href="./manifest.webmanifest">
<link rel="apple-touch-icon" href="./icon.svg">
<title>{escape(title)}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;600;700;800&family=Rubik:wght@500;600;700&display=swap');
:root{{color-scheme:light;--ink:#10233f;--muted:#64748b;--line:#e6ebf2;--cream:#f7f8f5;--card:#ffffff;--teal:#0b8f82;--teal-soft:#e5f6f2;--coral:#e86d5c;--coral-soft:#fff0ec;--blue-soft:#eaf1ff;}}
*{{box-sizing:border-box}}html{{background:var(--cream)}}body{{margin:0;min-height:100vh;background:var(--cream);color:var(--ink);font-family:'Heebo',system-ui,sans-serif;line-height:1.5;padding-bottom:env(safe-area-inset-bottom)}}
body::before{{content:"";display:block;height:9px;background:linear-gradient(90deg,#0b8f82 0 28%,#f4b860 28% 51%,#e86d5c 51% 73%,#6c7df7 73%)}}
.shell{{width:min(1100px,calc(100% - 32px));margin:0 auto;padding:28px 0 54px}}
.topbar{{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:42px}}
.brand{{display:flex;align-items:center;gap:12px;color:inherit;text-decoration:none;font-weight:800;letter-spacing:-.02em}}
.brand-mark{{display:grid;place-items:center;width:42px;height:42px;border-radius:13px;background:var(--ink);color:#fff;font-family:Rubik,sans-serif;font-size:18px;box-shadow:0 8px 18px #10233f22}}
.brand-copy{{display:flex;flex-direction:column;line-height:1.15}}.brand-copy small{{color:var(--muted);font-size:12px;font-weight:500;margin-top:4px}}
.source-link{{display:inline-flex;align-items:center;gap:8px;color:var(--ink);font-size:14px;font-weight:600;text-decoration:none;border:1px solid var(--line);background:#fff;padding:9px 14px;border-radius:999px;transition:.2s ease}}
.source-link:hover{{border-color:#b8c7d8;transform:translateY(-1px)}}.source-link span{{font-size:16px;color:var(--teal)}}
.hero{{display:grid;grid-template-columns:1.2fr .8fr;gap:28px;align-items:stretch;margin-bottom:26px}}
.hero-copy{{padding:14px 0 10px}}.eyebrow{{margin:0 0 8px;color:var(--teal);font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}}
h1,h2,h3,p{{margin-top:0}}h1{{font-family:Rubik,'Heebo',sans-serif;font-size:clamp(36px,5vw,62px);letter-spacing:-.06em;line-height:1.04;margin-bottom:17px;max-width:650px}}
.hero-copy>p:not(.eyebrow){{color:var(--muted);font-size:18px;max-width:540px;margin-bottom:24px}}
.hero-note{{display:flex;align-items:center;gap:9px;color:var(--muted);font-size:13px}}.pulse{{width:8px;height:8px;border-radius:50%;background:var(--teal);box-shadow:0 0 0 5px var(--teal-soft)}}
.hero-panel{{position:relative;overflow:hidden;background:var(--ink);color:#fff;border-radius:24px;padding:26px;min-height:215px;display:flex;flex-direction:column;justify-content:space-between;box-shadow:0 18px 40px #10233f24}}
.hero-panel::after{{content:"";position:absolute;width:190px;height:190px;border-radius:50%;border:1px solid #ffffff20;left:-55px;bottom:-100px;box-shadow:0 0 0 22px #ffffff09,0 0 0 44px #ffffff06}}
.panel-label{{color:#a9c8d0;font-size:13px;font-weight:600}}.panel-status{{display:flex;align-items:center;gap:12px;font-size:28px;font-family:Rubik,'Heebo',sans-serif;letter-spacing:-.04em;margin-top:9px}}.panel-status-icon{{display:grid;place-items:center;width:38px;height:38px;border-radius:50%;background:var(--teal);color:white;font-size:20px}}
.panel-meta{{position:relative;z-index:1;color:#b7c3d1;font-size:13px;margin:0}}.panel-meta strong{{color:#fff;font-size:16px;font-weight:600;display:block}}
.status-banner{{display:flex;align-items:center;gap:13px;border-radius:16px;padding:14px 17px;margin-bottom:26px;border:1px solid transparent}}.status-banner strong,.status-banner span{{display:block}}.status-banner strong{{font-size:15px}}.status-banner span:not(.status-icon){{font-size:13px;margin-top:2px;opacity:.8}}.status-icon{{display:grid;place-items:center;flex:0 0 31px;height:31px;border-radius:50%;font-weight:800}}
.fresh{{background:var(--teal-soft);color:#11665e;border-color:#ccece5}}.fresh .status-icon{{background:var(--teal);color:white}}.stale{{background:#fff4df;color:#85530c;border-color:#f3dcad}}.stale .status-icon{{background:#e9a93f;color:white}}
.error{{margin:-12px 0 26px;padding:12px 15px;border:1px solid #f2c5c0;border-radius:12px;background:#fff7f6;color:#9b4237;font-size:13px}}.error summary{{cursor:pointer;font-weight:700}}.error pre{{white-space:pre-wrap;margin:10px 0 0;font:12px/1.5 ui-monospace,monospace}}
.meta-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:45px}}.meta-card{{background:var(--card);border:1px solid var(--line);border-radius:15px;padding:16px 17px;min-height:88px}}.meta-card .meta-label{{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}}.meta-card strong{{font-size:17px;font-weight:700;display:block}}.meta-card .meta-icon{{float:left;font-size:20px;color:var(--teal);margin-top:4px}}
.section-heading{{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:15px}}h2{{font-family:Rubik,'Heebo',sans-serif;font-size:30px;letter-spacing:-.04em;margin-bottom:0}}.count-pill{{background:var(--ink);color:#fff;padding:7px 12px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}}
.change-list{{display:grid;gap:11px}}.change-card{{display:grid;grid-template-columns:120px 1fr 28px;align-items:center;gap:20px;background:var(--card);border:1px solid var(--line);border-right:4px solid var(--teal);border-radius:16px;padding:17px 19px;min-height:100px;transition:transform .2s ease,box-shadow .2s ease}}
.change-card:hover{{transform:translateY(-2px);box-shadow:0 10px 24px #10233f0e}}.change-card.cancelled{{border-right-color:var(--coral)}}.change-card.added{{border-right-color:#6c7df7}}
.change-date{{display:flex;flex-direction:column;gap:2px;color:var(--ink);font-weight:800;font-size:18px;letter-spacing:-.02em}}.change-date small{{color:var(--muted);font-size:12px;font-weight:600;letter-spacing:0}}.change-main{{min-width:0}}.change-topline{{display:flex;align-items:center;gap:8px;margin-bottom:3px}}.change-kind{{font-size:11px;font-weight:800;padding:3px 8px;border-radius:999px;background:var(--teal-soft);color:#167268}}.cancelled .change-kind{{background:var(--coral-soft);color:#b84c3c}}.added .change-kind{{background:var(--blue-soft);color:#4d5ac5}}.change-subkind{{font-size:12px;color:var(--muted)}}.change-card h3{{font-size:20px;margin-bottom:0;letter-spacing:-.02em}}.change-card p{{font-size:13px;color:var(--muted);margin:1px 0 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.change-arrow{{font-size:22px;color:#a8b4c4;transition:transform .2s ease}}.change-card:hover .change-arrow{{transform:translateX(-4px);color:var(--teal)}}
.empty-state{{display:flex;align-items:center;gap:20px;padding:30px 28px;background:var(--card);border:1px solid var(--line);border-radius:20px}}.empty-icon{{display:grid;place-items:center;width:58px;height:58px;border-radius:18px;background:var(--teal-soft);color:var(--teal);font-size:29px;font-weight:800;flex:0 0 auto}}.empty-state h2{{font-size:26px;margin-bottom:3px}}.empty-state p:last-child{{color:var(--muted);margin-bottom:0;font-size:14px}}
.footer{{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-top:44px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}}.footer a{{color:var(--ink);font-weight:700}}.ltr{{direction:ltr;unicode-bidi:embed}}
@media (max-width:700px){{.shell{{width:min(100% - 24px,520px);padding-top:max(20px,env(safe-area-inset-top));padding-bottom:calc(34px + env(safe-area-inset-bottom))}}.topbar{{margin-bottom:30px}}.brand-mark{{width:38px;height:38px;border-radius:11px}}.brand-copy{{font-size:14px}}.source-link{{font-size:0;width:42px;height:42px;justify-content:center;padding:0;flex:0 0 42px}}.source-link span{{font-size:18px}}.hero{{display:block}}.hero-copy{{padding:0;margin-bottom:22px}}h1{{font-size:42px}}.hero-copy>p:not(.eyebrow){{font-size:16px}}.hero-panel{{min-height:185px;border-radius:20px;padding:21px}}.panel-status{{font-size:24px}}.meta-grid{{grid-template-columns:1fr 1fr;margin-bottom:34px}}.meta-card:last-child{{grid-column:span 2}}.meta-card{{min-height:76px;padding:13px 14px}}.section-heading{{align-items:center}}h2{{font-size:26px}}.change-card{{grid-template-columns:82px 1fr;gap:12px;padding:14px 14px;min-height:94px}}.change-arrow{{display:none}}.change-date{{font-size:15px}}.change-card h3{{font-size:18px}}.change-card p{{font-size:12px}}.footer{{display:block;line-height:1.8}}.footer span{{display:block}}.empty-state{{align-items:flex-start;padding:23px 18px;gap:14px}}.empty-icon{{width:48px;height:48px;border-radius:14px;font-size:23px}}}}
@media (prefers-reduced-motion:reduce){{*,*::before,*::after{{transition:none!important}}}}
</style></head><body><main>
<div class="shell"><header class="topbar"><a class="brand" href="."><span class="brand-mark">י״א</span><span class="brand-copy">המערכת שלי<small>אוסטרובסקי · י״א 8</small></span></a><a class="source-link" href="{escape(source_url)}" target="_blank" rel="noreferrer"><span>↗</span>מקור Shahaf</a></header>
<section class="hero"><div class="hero-copy"><p class="eyebrow">לוח שינויים יומי</p><h1>מה קורה<br>במערכת?</h1><p>כל הביטולים, ההחלפות והשינויים החשובים שלך — במקום אחד, מעודכנים אוטומטית.</p><div class="hero-note"><span class="pulse"></span>בדיקה אוטומטית פעילה</div></div><aside class="hero-panel"><div><span class="panel-label">סטטוס הסנכרון</span><div class="panel-status"><span class="panel-status-icon">✓</span>{"מעודכן" if not stale else "ממתין לבדיקה"}</div></div><p class="panel-meta">סנכרון מוצלח אחרון<strong>{escape(sync_display)}</strong></p></aside></section>
{banner}
<section class="meta-grid" aria-label="פרטי המערכת"><div class="meta-card"><span class="meta-icon">↻</span><span class="meta-label">עדכון אחרון</span><strong>{escape(sync_display)}</strong></div><div class="meta-card"><span class="meta-icon">✦</span><span class="meta-label">מה נמצא</span><strong>{escape(count_label)}</strong></div><div class="meta-card"><span class="meta-icon">◷</span><span class="meta-label">עדכון מקור Shahaf</span><strong>{escape(source_display)}</strong></div></section>
{changes_html}
<footer class="footer"><span>נוצר ב־{escape(_pretty_timestamp(generated_at))} · חלון בדיקה: 21 ימים</span><a href="{escape(source_url)}" target="_blank" rel="noreferrer">פתיחת Shahaf ↗</a></footer></div>
</main><script>if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js"));</script></body></html>
"""
    (output_dir / "index.html").write_text(html, encoding="utf-8")
