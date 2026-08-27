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
        banner = '<div class="warning"><strong>הנתונים מסומנים כמיושנים.</strong> הסנכרון האחרון לא הצליח; לוח השנה לא שונה.</div>'
    else:
        banner = '<div class="ok">הסנכרון האחרון הסתיים בהצלחה.</div>'
    if error:
        banner += f'<pre class="error">{escape(error)}</pre>'
    if changes:
        rows = "".join(
            f"<tr><td>{escape(item.date.isoformat())}</td><td>{item.period}</td>"
            f"<td>{escape(item.subject)}</td><td>{escape(item.kind)}</td><td>{escape(item.detail)}</td></tr>"
            for item in changes
        )
        changes_html = (
            "<table><thead><tr><th>תאריך</th><th>שעה</th><th>מקצוע</th><th>סוג</th><th>פרטים</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        changes_html = "<p>לא נמצאו שינויים עבור לוח הזמנים הקרוב.</p>"
    html = f"""<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;background:#f7f8fb;color:#172033}}
main{{background:white;border-radius:14px;padding:1.5rem;box-shadow:0 8px 30px #16213d16}}
h1{{margin-top:0}}.ok,.warning{{padding:.8rem 1rem;border-radius:8px;margin:1rem 0}}.ok{{background:#e7f7ee;color:#14532d}}.warning{{background:#fff3cd;color:#664d03}}.error{{white-space:pre-wrap;background:#fff0f0;padding:.8rem;border-radius:8px;color:#991b1b}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:.7rem;border-bottom:1px solid #e5e7eb;text-align:right}}th{{background:#f1f5f9}}
small{{color:#586174}}
</style></head><body><main>
<h1>{escape(title)}</h1>{banner}
<p><small>נוצר: {escape(generated_at)}<br>סנכרון מוצלח אחרון: {escape(last_successful_sync or "לא ידוע")}<br>עדכון מקור: {escape(source_updated or "לא ידוע")}</small></p>
{changes_html}
<p><small>מקור: <a href="{escape(source_url)}">Shahaf</a></small></p>
</main></body></html>
"""
    (output_dir / "index.html").write_text(html, encoding="utf-8")
