"""Local report viewer backed by the generated JSON reconciliation report."""

from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DATA = Path(__file__).resolve().parent / "data"


def render_report(report: dict[str, object]) -> bytes:
    """Render a self-contained HTML page with the report embedded as JSON."""
    data = json.dumps(report, separators=(",", ":"), ensure_ascii=False).replace(
        "</", "<\\/"
    )
    summary = report["summary"]
    categories = sorted(summary["classification_counts"])
    options = "".join(
        f'<option value="{html.escape(category, quote=True)}">'
        f"{html.escape(category)}</option>"
        for category in categories
    )
    initial_platform = summary["platform_total_cents"]
    initial_bank = summary["bank_total_cents"]
    initial_explained = summary["explained_delta_cents"]
    initial_rounding = summary["rounding_residual_cents"]
    initial_unexplained = summary["unexplained_delta_cents"]
    initial_status = "PASS" if summary["conservation_holds"] else "CHECK"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Payments reconciliation</title>
<style>
:root{{color-scheme:light;--ink:#172033;--muted:#586174;--line:#dce1e8;--blue:#1769aa;--orange:#c55a11}}
body{{font:16px system-ui,sans-serif;max-width:1180px;margin:2rem auto;padding:0 1rem;color:var(--ink)}}
h1,h2{{margin-bottom:.5rem}}.muted{{color:var(--muted)}}.status{{font-weight:700}}
.status.pass{{color:#087443}}.status.check{{color:#a12622}}
.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.8rem}}
.card{{padding:1rem;border:1px solid var(--line);border-radius:8px}}.card small{{display:block;color:var(--muted)}}
.controls{{display:flex;flex-wrap:wrap;gap:.7rem;align-items:center;margin:1rem 0}}
input,select,button{{font:inherit;padding:.45rem .6rem;border:1px solid #aeb8c6;border-radius:4px;background:white}}
button{{cursor:pointer}}button:hover{{background:#edf4fa}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}td,th{{text-align:left;padding:.6rem;border-bottom:1px solid var(--line);vertical-align:top}}
th button{{font-weight:700;border:0;padding:0;background:transparent;text-align:left}}
.table-wrap{{overflow:auto;max-height:620px}}.review{{color:#a12622;font-weight:700}}
.bridge{{display:grid;gap:.5rem;margin:1rem 0 2rem}}.bridge-row{{display:grid;grid-template-columns:190px minmax(100px,1fr) 150px 150px;gap:.7rem;align-items:center}}
.track{{height:20px;background:#edf0f5;border-radius:4px;overflow:hidden}}.bar{{height:100%;background:var(--blue)}}
.step{{height:100%;background:var(--orange)}}.bridge-head{{font-weight:700;border-bottom:1px solid var(--line);padding-bottom:.5rem}}
@media(max-width:680px){{.bridge-row{{grid-template-columns:110px 1fr 100px}}.bridge-row .impact{{display:none}}}}
</style></head><body>
<h1>Payments reconciliation</h1>
<p class="muted">Reporting cohorts: {html.escape(", ".join(summary["months"])) or "none"} · USD · UTC month-end</p>
<p class="status {'pass' if initial_status == 'PASS' else 'check'}">Conservation: {initial_status} · unexplained {html.escape(summary["unexplained_delta"])} USD</p>
<section class="summary" aria-label="Summary totals">
<div class="card"><small>Platform total</small><strong>{html.escape(summary["platform_total"])} USD</strong></div>
<div class="card"><small>Bank total</small><strong>{html.escape(summary["bank_total"])} USD</strong></div>
<div class="card"><small>Variance</small><strong>{html.escape(summary["variance"])} USD</strong></div>
<div class="card"><small>Unexplained</small><strong>{html.escape(summary["unexplained_delta"])} USD</strong></div>
</section>
<h2>Variance waterfall</h2>
<p class="muted">Start with the platform total, subtract each explained amount, and arrive at the bank total.</p>
<div id="waterfall" class="bridge" aria-label="Variance waterfall"></div>
<h2>Findings</h2>
<div class="controls">
<label for="category">Category</label><select id="category"><option value="">All categories</option>{options}</select>
<label for="search">Transaction ID</label><input id="search" type="search" placeholder="Search txn ID">
<label for="download-category">CSV category</label><select id="download-category"><option value="">Choose category</option>{options}</select>
<button id="download" type="button">Download category CSV</button>
<span id="row-count" class="muted"></span>
</div>
<div class="table-wrap"><table id="findings"><thead><tr>
<th><button data-sort="category">Category ↕</button></th>
<th><button data-sort="txn_ids">Transaction ID(s) ↕</button></th>
<th><button data-sort="amount_impact_cents">Impact ↕</button></th>
<th><button data-sort="rule_fired">Rule ↕</button></th>
<th>Reason</th><th><button data-sort="confidence">Confidence ↕</button></th><th>Human review</th>
</tr></thead><tbody></tbody></table></div>
<p class="muted">Static page: all report data and code are embedded; no external requests or libraries.</p>
<script id="report-data" type="application/json">{data}</script>
<script>
const report=JSON.parse(document.getElementById('report-data').textContent);
const findings=report.classifications;
const escapeHtml=value=>String(value).replace(/[&<>"']/g,char=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char]));
const dollars=cents=>{{const sign=cents<0?'-':'';const absolute=Math.abs(cents);return sign+Math.trunc(absolute/100)+'.'+String(absolute%100).padStart(2,'0')}};
const waterfallSteps=[
  {{label:'Platform total',amount:report.summary.platform_total_cents,impact:null}},
  {{label:'After explained deltas',amount:report.summary.platform_total_cents-report.summary.explained_delta_cents,impact:-report.summary.explained_delta_cents}},
  {{label:'After batch rounding',amount:report.summary.platform_total_cents-report.summary.explained_delta_cents-report.summary.rounding_residual_cents,impact:-report.summary.rounding_residual_cents}},
  {{label:'After unexplained residual',amount:report.summary.platform_total_cents-report.summary.explained_delta_cents-report.summary.rounding_residual_cents-report.summary.unexplained_delta_cents,impact:-report.summary.unexplained_delta_cents}},
  {{label:'Bank total',amount:report.summary.bank_total_cents,impact:null}}
];
const maxAmount=Math.max(1,...waterfallSteps.map(step=>Math.abs(step.amount)));
document.getElementById('waterfall').innerHTML=
  '<div class="bridge-row bridge-head"><span>Step</span><span>Remaining balance</span><span>Balance</span><span class="impact">Adjustment</span></div>'+
  waterfallSteps.map(step=>{{const width=Math.min(100,Math.trunc(Math.abs(step.amount)*100/maxAmount));const adjustment=step.impact===null?'—':dollars(step.impact)+' USD';return '<div class="bridge-row"><span>'+escapeHtml(step.label)+'</span><div class="track"><div class="'+(step.impact===null?'bar':'step')+'" style="width:'+width+'%"></div></div><strong>'+dollars(step.amount)+' USD</strong><span class="impact">'+adjustment+'</span></div>'}}).join('');
let sortKey='category',sortDirection=1;
function renderRows(){{
  const category=document.getElementById('category').value;
  const query=document.getElementById('search').value.trim().toLowerCase();
  const selected=findings.filter(row=>(!category||row.category===category)&&(!query||row.txn_ids.join(' ').toLowerCase().includes(query)));
  selected.sort((left,right)=>{{const a=left[sortKey],b=right[sortKey];const cmp=typeof a==='number'&&typeof b==='number'?a-b:String(Array.isArray(a)?a.join(','):a??'').localeCompare(String(Array.isArray(b)?b.join(','):b??''));return cmp*sortDirection}});
  document.querySelector('#findings tbody').innerHTML=selected.map(row=>'<tr><td>'+escapeHtml(row.category)+'</td><td>'+escapeHtml(row.txn_ids.join(', ')||'—')+'</td><td>'+dollars(row.amount_impact_cents)+' USD</td><td>'+escapeHtml(row.rule_fired)+'</td><td>'+escapeHtml(row.reason)+'</td><td>'+escapeHtml(row.confidence)+'</td><td class="'+(row.needs_human_review?'review':'')+'">'+(row.needs_human_review?'Yes':'No')+'</td></tr>').join('');
  document.getElementById('row-count').textContent=selected.length+' finding(s)';
}}
document.querySelectorAll('[data-sort]').forEach(button=>button.addEventListener('click',()=>{{const key=button.dataset.sort;if(sortKey===key)sortDirection=-sortDirection;else{{sortKey=key;sortDirection=1}}renderRows()}}));
document.getElementById('category').addEventListener('change',renderRows);
document.getElementById('search').addEventListener('input',renderRows);
document.getElementById('download').addEventListener('click',()=>{{
  const category=document.getElementById('download-category').value;
  if(!category){{alert('Choose a category first.');return}}
  const columns=['category','txn_ids','amount_impact','rule_fired','reason','confidence','needs_human_review','platform_row_id','bank_row_id','batch_id'];
  const quote=value=>'"'+String(value??'').replace(/"/g,'""')+'"';
  const content=[columns.join(','),...findings.filter(row=>row.category===category).map(row=>columns.map(key=>quote(key==='txn_ids'?row.txn_ids.join('|'):key==='amount_impact'?dollars(row.amount_impact_cents):row[key])).join(','))].join('\\r\\n');
  const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([content],{{type:'text/csv;charset=utf-8'}}));link.download=category.toLowerCase()+'.csv';link.click();URL.revokeObjectURL(link.href);
}});
renderRows();
</script></body></html>"""
    return page.encode("utf-8")


def page() -> bytes:
    report_path = DATA / "reconciliation_report.json"
    if not report_path.exists():
        raise FileNotFoundError("Run `python demo.py` before starting the report UI.")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return render_report(report)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if urlparse(self.path).path not in ("/", "/index.html"):
            self.send_error(404)
            return
        body = page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    server = ThreadingHTTPServer((arguments.host, arguments.port), Handler)
    print(f"Serving report at http://{arguments.host}:{arguments.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping report server.")
        server.server_close()
