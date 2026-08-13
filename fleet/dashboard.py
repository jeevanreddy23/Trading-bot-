"""Self-contained HTML dashboard rendered from state/state.json.

Design: dataviz reference palette (validated instance) — single-series equity
line (series-1 blue, 2px, crosshair+tooltip), reserved status colors always
paired with icon+label, all text in ink tokens, tables for every dataset,
light/dark via CSS custom properties. Auto-refreshes while the fleet runs.
"""
from __future__ import annotations

import json
import os

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="20">
<title>Aussie Agent Fleet</title>
<style>
  .viz-root {
    color-scheme: light;
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
    --s1:#2a78d6; --good:#0ca30c; --good-text:#006300; --warn:#fab219;
    --serious:#ec835a; --crit:#d03b3b;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
      --s1:#3987e5; --good:#0ca30c; --good-text:#0ca30c; --warn:#fab219;
      --serious:#ec835a; --crit:#d03b3b;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --s1:#3987e5; --good:#0ca30c; --good-text:#0ca30c; --warn:#fab219;
    --serious:#ec835a; --crit:#d03b3b;
  }
  * { box-sizing: border-box; }
  body.viz-root { margin:0; background:var(--page); color:var(--ink);
    font:14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; padding:20px; }
  .wrap { max-width:1180px; margin:0 auto; }
  header { display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin-bottom:16px; }
  h1 { font-size:17px; margin:0 12px 0 0; font-weight:650; }
  .chip { border:1px solid var(--border); border-radius:999px; padding:3px 10px;
    font-size:12px; color:var(--ink2); background:var(--surface); }
  .chip b { font-weight:650; color:var(--ink); }
  .chip.warnc { border-color:var(--warn); }
  .chip.livec { border-color:var(--crit); }
  .chip.haltc { border-color:var(--crit); color:var(--ink); }
  .meta { margin-left:auto; font-size:12px; color:var(--muted); }
  .tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px,1fr));
    gap:12px; margin-bottom:12px; }
  .tile { background:var(--surface); border:1px solid var(--border); border-radius:10px;
    padding:12px 14px; }
  .tile .lbl { font-size:11px; letter-spacing:.04em; text-transform:uppercase;
    color:var(--muted); margin-bottom:4px; }
  .tile .val { font-size:24px; font-weight:650; }
  .tile .sub { font-size:12px; color:var(--ink2); margin-top:2px; }
  .up   { color:var(--good-text); }
  .down { color:var(--crit); }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  @media (max-width:900px){ .grid2 { grid-template-columns:1fr; } }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:10px;
    padding:14px 16px; margin-bottom:12px; }
  .card h2 { font-size:13px; font-weight:650; margin:0 0 10px; color:var(--ink); }
  .card h2 .note { font-weight:400; color:var(--muted); font-size:12px; }
  svg text { font:11px system-ui, -apple-system, "Segoe UI", sans-serif;
    fill:var(--muted); font-variant-numeric: tabular-nums; }
  table { width:100%; border-collapse:collapse; font-size:12.5px; }
  th { text-align:left; color:var(--muted); font-weight:500; font-size:11px;
    letter-spacing:.03em; text-transform:uppercase; padding:4px 8px 6px;
    border-bottom:1px solid var(--grid); }
  td { padding:5px 8px; border-bottom:1px solid var(--grid); color:var(--ink2);
    font-variant-numeric: tabular-nums; }
  td.sym { color:var(--ink); font-weight:550; }
  tr:last-child td { border-bottom:none; }
  .num { text-align:right; }
  th.num { text-align:right; }
  .empty { color:var(--muted); font-size:12.5px; padding:8px 0; }
  .agents { display:grid; gap:6px; }
  .agent { display:flex; gap:8px; align-items:baseline; font-size:12.5px; }
  .agent .dot { width:8px; height:8px; border-radius:50%; background:var(--s1);
    flex:none; align-self:center; }
  .agent .nm { color:var(--ink); font-weight:550; min-width:130px; }
  .agent .nt { color:var(--muted); overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; }
  .events { max-height:220px; overflow-y:auto; font-size:12px; color:var(--ink2); }
  .events div { padding:2px 0; border-bottom:1px dashed var(--grid); }
  .risk { display:flex; flex-wrap:wrap; gap:8px; }
  #tip { position:fixed; display:none; background:var(--surface); color:var(--ink);
    border:1px solid var(--border); border-radius:8px; padding:6px 10px; font-size:12px;
    pointer-events:none; box-shadow:0 4px 14px rgba(0,0,0,.18); z-index:10;
    font-variant-numeric: tabular-nums; }
  footer { color:var(--muted); font-size:11.5px; margin-top:14px; }
</style>
</head>
<body class="viz-root">
<div class="wrap">
  <header id="hdr"></header>
  <div class="tiles" id="tiles"></div>
  <div class="card">
    <h2>Equity — paper account, AUD <span class="note" id="eqnote"></span></h2>
    <div id="chart" style="position:relative"></div>
  </div>
  <div class="grid2">
    <div class="card"><h2>Open positions</h2><div id="positions"></div></div>
    <div class="card"><h2>Arb monitor <span class="note">best cross-venue spread, net of both venues' taker fees + slippage</span></h2><div id="arb"></div></div>
  </div>
  <div class="grid2">
    <div class="card"><h2>Agents</h2><div class="agents" id="agents"></div></div>
    <div class="card"><h2>Risk limits</h2><div class="risk" id="risk"></div></div>
  </div>
  <div class="card"><h2>LangGraph 40-agent shadow ensemble <span class="note">30 symbol specialists + 10 portfolio challengers</span></h2><div id="langgraph"></div></div>
  <div class="card"><h2>Recent trades</h2><div id="trades"></div></div>
  <div class="card"><h2>Event log</h2><div class="events" id="events"></div></div>
  <footer>Not financial advice. Paper results include modelled fees + slippage but
  not every real-world cost. State generated <span id="gen"></span> (Sydney time).</footer>
</div>
<div id="tip"></div>
<script>
const S = __STATE__;
const aud = new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'});
const audS = v => (v>=0?'+':'') + aud.format(v).replace('$','A$');
const fmt = v => aud.format(v).replace('$','A$');
const el = (id) => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const t2s = ts => new Date(ts*1000).toLocaleTimeString('en-AU',{timeZone:'Australia/Sydney',hour12:false});

/* header */
(function(){
  const h = [];
  h.push('<h1>Aussie Agent Fleet</h1>');
  if (S.mode === 'LIVE') h.push('<span class="chip livec"><b>&#9679; LIVE</b> real orders</span>');
  else h.push('<span class="chip"><b>PAPER</b> simulated fills</span>');
  if (S.simulated_data) h.push('<span class="chip warnc"><b>&#9888; SYNTHETIC DATA</b> offline sim feed</span>');
  else h.push('<span class="chip"><b>DATA</b> ' + esc(Object.values(S.data_sources).join(' · ')) + '</span>');
  if (S.halted) h.push('<span class="chip haltc"><b>&#9632; HALTED</b> drawdown kill-switch</span>');
  h.push('<span class="meta">auto-refreshes every 20s</span>');
  el('hdr').innerHTML = h.join('');
})();

/* stat tiles */
(function(){
  const day = S.day_pnl_aud, tot = S.equity_aud - S.starting_equity;
  const cls = v => v > 0 ? 'up' : (v < 0 ? 'down' : '');
  const arrow = v => v > 0 ? '&#9650; ' : (v < 0 ? '&#9660; ' : '');
  el('tiles').innerHTML = `
    <div class="tile"><div class="lbl">Equity</div><div class="val">${fmt(S.equity_aud)}</div>
      <div class="sub ${cls(tot)}">${arrow(tot)}${audS(tot)} since start</div></div>
    <div class="tile"><div class="lbl">Day P&amp;L (Sydney)</div>
      <div class="val ${cls(day)}">${arrow(day)}${audS(day)}</div>
      <div class="sub">limit -${S.risk.max_daily_loss_pct}%/day</div></div>
    <div class="tile"><div class="lbl">Open positions</div><div class="val">${S.positions.length}</div>
      <div class="sub">max ${S.risk.max_open_positions}</div></div>
    <div class="tile"><div class="lbl">Cash</div><div class="val">${fmt(S.cash_aud)}</div>
      <div class="sub">gross leverage cap ${S.risk.max_gross_leverage}&times;</div></div>`;
})();

/* equity line chart — single series, crosshair + tooltip */
(function(){
  const pts = S.equity_series || [];
  const box = el('chart');
  if (pts.length < 2){ box.innerHTML = '<div class="empty">Collecting equity history&hellip;</div>'; return; }
  const W = Math.min(1120, box.clientWidth || 1120), H = 220;
  const m = {l:10, r:88, t:12, b:24};
  const xs = pts.map(p=>p[0]), ys = pts.map(p=>p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = Math.max((y1-y0)*0.08, Math.max(1, y1*0.0004)); y0-=pad; y1+=pad;
  const X = t => m.l + (t-x0)/(x1-x0||1)*(W-m.l-m.r);
  const Y = v => m.t + (1-(v-y0)/(y1-y0||1))*(H-m.t-m.b);
  let path='', area='';
  pts.forEach((p,i)=>{ const c=`${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`;
    path += (i?'L':'M')+c; });
  area = path + `L${X(x1).toFixed(1)},${(H-m.b).toFixed(1)}L${X(x0).toFixed(1)},${(H-m.b).toFixed(1)}Z`;
  const ticks = [y0+pad, (y0+y1)/2, y1-pad];
  let g = '';
  ticks.forEach(v=>{ const y=Y(v).toFixed(1);
    g += `<line x1="${m.l}" x2="${W-m.r}" y1="${y}" y2="${y}" stroke="var(--grid)" stroke-width="1"/>`;
    g += `<text x="${W-m.r+6}" y="${(+y+4)}">${fmt(v)}</text>`; });
  const nx = 4;
  for (let i=0;i<=nx;i++){ const t=x0+(x1-x0)*i/nx;
    const anc = i===0 ? 'start' : (i===nx ? 'end' : 'middle');
    g += `<text x="${X(t).toFixed(1)}" y="${H-6}" text-anchor="${anc}">${t2s(t)}</text>`; }
  box.innerHTML = `<svg id="eqsvg" width="${W}" height="${H}" role="img"
      aria-label="Equity over time, ${fmt(ys[0])} to ${fmt(ys[ys.length-1])}">
    ${g}
    <line x1="${m.l}" x2="${W-m.r}" y1="${H-m.b}" y2="${H-m.b}" stroke="var(--axis)" stroke-width="1"/>
    <path d="${area}" fill="var(--s1)" opacity="0.08"/>
    <path d="${path}" fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round"/>
    <line id="xh" x1="0" x2="0" y1="${m.t}" y2="${H-m.b}" stroke="var(--axis)" stroke-width="1" opacity="0"/>
    <circle id="dot" r="4" fill="var(--s1)" stroke="var(--surface)" stroke-width="2" opacity="0"/>
    <rect x="${m.l}" y="${m.t}" width="${W-m.l-m.r}" height="${H-m.t-m.b}" fill="transparent"/>
  </svg>`;
  el('eqnote').textContent = `${pts.length} snapshots`;
  const svg = el('eqsvg'), tip = el('tip'), xh = el('xh'), dot = el('dot');
  svg.addEventListener('mousemove', ev=>{
    const r = svg.getBoundingClientRect(); const mx = ev.clientX - r.left;
    let best=0, bd=1e18;
    pts.forEach((p,i)=>{ const d=Math.abs(X(p[0])-mx); if(d<bd){bd=d;best=i;} });
    const p = pts[best], px=X(p[0]), py=Y(p[1]);
    xh.setAttribute('x1',px); xh.setAttribute('x2',px); xh.setAttribute('opacity',1);
    dot.setAttribute('cx',px); dot.setAttribute('cy',py); dot.setAttribute('opacity',1);
    tip.style.display='block';
    tip.style.left=(ev.clientX+14)+'px'; tip.style.top=(ev.clientY-12)+'px';
    tip.innerHTML = `${t2s(p[0])} &nbsp; <b>${fmt(p[1])}</b>`;
  });
  svg.addEventListener('mouseleave', ()=>{ tip.style.display='none';
    xh.setAttribute('opacity',0); dot.setAttribute('opacity',0); });
})();

/* positions */
(function(){
  const P = S.positions;
  if (!P.length){ el('positions').innerHTML = '<div class="empty">None open.</div>'; return; }
  P.sort((a,b)=>Math.abs(b.upnl_aud)-Math.abs(a.upnl_aud));
  el('positions').innerHTML = `<table><thead><tr>
    <th>Symbol</th><th>Side</th><th class="num">Qty</th><th class="num">Avg</th>
    <th class="num">Mark</th><th class="num">U-P&amp;L</th><th>Agent</th></tr></thead><tbody>` +
    P.map(p=>{ const side = p.qty>0?'long':'short';
      const cls = p.upnl_aud>0?'up':(p.upnl_aud<0?'down':'');
      const ven = p.venue?` <span style="color:var(--muted)">@${esc(p.venue)}</span>`:'';
      return `<tr><td class="sym">${esc(p.symbol)}${ven}</td><td>${side}</td>
      <td class="num">${(+p.qty).toPrecision(6)}</td>
      <td class="num">${(+p.avg_price).toLocaleString('en-AU',{maximumFractionDigits:6})}</td>
      <td class="num">${(+p.mark).toLocaleString('en-AU',{maximumFractionDigits:6})}</td>
      <td class="num ${cls}">${audS(p.upnl_aud)}</td>
      <td>${esc(p.agent)}${p.tag&&!String(p.tag).startsWith('arb')?' ('+esc(p.tag)+')':''}</td></tr>`; }).join('')
    + '</tbody></table>';
})();

/* arb monitor */
(function(){
  const A = S.arb || [];
  if (!A.length){ el('arb').innerHTML = '<div class="empty">No venue quotes this cycle.</div>'; return; }
  el('arb').innerHTML = `<table><thead><tr><th>Pair</th><th>Buy at</th><th>Sell at</th>
    <th class="num">Gross</th><th class="num">Net of fees</th></tr></thead><tbody>` +
    A.map(r=>{ const pos = r.net_bps>0;
      return `<tr><td class="sym">${esc(r.symbol)}</td>
      <td>${esc(r.buy_venue)}</td><td>${esc(r.sell_venue)}</td>
      <td class="num">${r.gross_bps>0?'+':''}${r.gross_bps} bps</td>
      <td class="num ${pos?'up':''}">${pos?'&#9650; ':''}${r.net_bps>0?'+':''}${r.net_bps} bps${pos?' — window!':''}</td></tr>`; }).join('')
    + '</tbody></table><div class="empty">Net &le; 0 means the gap is smaller than the round-trip costs — the normal state.</div>';
})();

/* agents */
(function(){
  el('agents').innerHTML = (S.agents||[]).map(a=>`
    <div class="agent"><span class="dot"></span><span class="nm">${esc(a.name)}</span>
    <span style="color:var(--muted);flex:none">${a.interval}s</span>
    <span class="nt" title="${esc(a.note)}">${esc(a.note)||'—'}</span></div>`).join('');
})();

/* risk */
(function(){
  const r = S.risk;
  el('risk').innerHTML = [
    `daily loss stop ${r.max_daily_loss_pct}%`,
    `kill-switch drawdown ${r.kill_drawdown_pct}%`,
    `gross leverage &le; ${r.max_gross_leverage}&times;`,
    `position cap ${r.max_position_pct_equity}% of equity`,
    `max ${r.max_open_positions} open`,
    `manual kill: <b>touch state/KILL</b>`,
  ].map(t=>`<span class="chip">${t}</span>`).join('');
})();

/* LangGraph shadow ensemble */
(function(){
  const g = S.langgraph || {};
  if (!g.agent_count){ el('langgraph').innerHTML = '<div class="empty">Waiting for the first graph cycle.</div>'; return; }
  const failed = (g.checks||[]).filter(x=>!x.passed);
  el('langgraph').innerHTML = `<div class="risk">
    <span class="chip"><b>${g.agent_count}</b> nodes</span><span class="chip"><b>${esc(g.mode)}</b></span>
    <span class="chip">checkpoints: <b>${esc(g.persistence)}</b></span>
    <span class="chip">challenger failures: <b>${failed.length}</b></span></div>
    <table><thead><tr><th>Rank</th><th>Symbol</th><th>Action</th><th class="num">Probability</th>
    <th class="num">EV</th><th>Graph gate</th></tr></thead><tbody>${(g.decisions||[]).map(d=>`
    <tr><td>${d.rank}</td><td class="sym">${esc(d.symbol)}</td><td>${esc(d.action)}</td>
    <td class="num">${(+d.probability).toFixed(3)}</td><td class="num">${(+d.expected_value_pct).toFixed(3)}%</td>
    <td class="${d.risk_gate==='PASS'?'up':'down'}">${esc(d.risk_gate)}</td></tr>`).join('')}</tbody></table>
    <div class="empty">Shadow proposals cannot call the executor; deterministic portfolio risk remains downstream.</div>`;
})();

/* trades */
(function(){
  const T = (S.recent_trades||[]).slice().reverse();
  if (!T.length){ el('trades').innerHTML = '<div class="empty">No trades yet.</div>'; return; }
  el('trades').innerHTML = `<table><thead><tr><th>Time</th><th>Mode</th><th>Agent</th>
    <th>Action</th><th>Symbol</th><th class="num">Qty</th><th class="num">Price</th>
    <th class="num">Fee</th><th class="num">P&amp;L</th><th>Reason</th></tr></thead><tbody>` +
    T.map(t=>{ const pnl = t.pnl_aud;
      const cls = pnl>0?'up':(pnl<0?'down':'');
      return `<tr><td>${t2s(t.ts)}</td><td>${esc(t.mode)}</td><td>${esc(t.agent)}</td>
      <td>${esc(t.action)}</td><td class="sym">${esc(t.symbol)}${t.venue?' <span style="color:var(--muted)">@'+esc(t.venue)+'</span>':''}</td>
      <td class="num">${(+t.qty).toPrecision(5)}</td>
      <td class="num">${(+t.price).toLocaleString('en-AU',{maximumFractionDigits:6})}</td>
      <td class="num">${(+t.fee_aud).toFixed(2)}</td>
      <td class="num ${cls}">${pnl==null?'—':audS(pnl)}</td>
      <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="${esc(t.reason)}">${esc(t.reason)}</td></tr>`; }).join('') + '</tbody></table>';
})();

/* events */
(function(){
  el('events').innerHTML = (S.events||[]).slice().reverse().map(e=>`<div>${esc(e)}</div>`).join('')
    || '<div class="empty">No events.</div>';
  el('gen').textContent = S.generated_syd || '';
})();
</script>
</body>
</html>
"""


def render_dashboard(state_path: str, out_path: str = "dashboard.html"):
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)
    else:
        state = {"mode": "PAPER", "simulated_data": True, "data_sources": {},
                 "equity_aud": 0, "cash_aud": 0, "day_pnl_aud": 0, "starting_equity": 0,
                 "positions": [], "equity_series": [], "arb": [], "agents": [], "langgraph": {},
                 "recent_trades": [], "events": [], "halted": False,
                 "generated_syd": "", "risk": {"max_daily_loss_pct": 0,
                 "kill_drawdown_pct": 0, "max_gross_leverage": 0,
                 "max_position_pct_equity": 0, "max_open_positions": 0}}
    blob = json.dumps(state).replace("</", "<\\/")
    html = TEMPLATE.replace("__STATE__", blob)
    with open(out_path, "w") as f:
        f.write(html)
    return out_path
