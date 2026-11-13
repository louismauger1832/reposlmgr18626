#!/usr/bin/env python3
"""Génère docs/index.html (autonome, sans dépendance externe) depuis data/*.csv."""
import csv, os, html, statistics
from collections import defaultdict
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
ALERT_DROP = 0.07   # baisse >= 7 % vs médiane des 7 derniers jours => pointer vers Amazon
GAP_HOURS = 4       # relevés toutes les 3 h : au-delà, on signale un trou


def rd(path):
    p = os.path.join(ROOT, path)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


prices, runs = rd("data/prices.csv"), rd("data/runs.csv")
products = {r["id"]: r for r in rd("config/products.csv")}
configs = rd("config/configs.csv")
fmt = lambda v: "—" if v is None else f"{v:,.2f} €".replace(",", " ").replace(".", ",")
pct = lambda v: "n/d" if v is None else f"{v:+.1f} %".replace(".", ",")
esc = html.escape

# --- séries : meilleur prix par produit à chaque relevé -------------------------------------------------
by_ts = defaultdict(lambda: defaultdict(list))
for r in prices:
    by_ts[r["horodatage"]][r["produit_id"]].append(r)
stamps = sorted(by_ts)
best = {}      # (ts, pid) -> row
for ts in stamps:
    for pid, rows in by_ts[ts].items():
        best[(ts, pid)] = min(rows, key=lambda r: (r["marketplace"] == "1", r["en_stock"] == "0", float(r["prix_eur"])))
series = defaultdict(list)  # pid -> [(datetime, prix)]
for ts in stamps:
    for pid in products:
        if (ts, pid) in best:
            series[pid].append((datetime.fromisoformat(ts), float(best[(ts, pid)]["prix_eur"])))

cfg_series = {}
for c in configs:
    comp = c["composants"].split("|")
    last, pts = {}, []
    for ts in stamps:
        for pid in comp:
            if (ts, pid) in best:
                last[pid] = float(best[(ts, pid)]["prix_eur"])
        if all(pid in last for pid in comp):
            pts.append((datetime.fromisoformat(ts), sum(last[p] for p in comp)))
    cfg_series[c["config_id"]] = pts


def stats(pts):
    if not pts:
        return None
    now_dt, cur = pts[-1]
    vals = [v for _, v in pts]

    def ago(days):
        ref = [v for d, v in pts if d <= now_dt - timedelta(days=days)]
        return None if not ref else (cur / ref[-1] - 1) * 100
    prev7 = [v for d, v in pts[:-1] if d >= now_dt - timedelta(days=7)]
    drop = None
    if len(prev7) >= 3:
        med = statistics.median(prev7)
        if cur <= med * (1 - ALERT_DROP):
            drop = (cur / med - 1) * 100
    return dict(cur=cur, mn=min(vals), mx=max(vals), d7=ago(7), d30=ago(30), n=len(pts), drop=drop)


def chart(pts, w=640, h=170):
    if not pts:
        return '<p class="muted">Pas encore de données.</p>'
    px, py0, py1 = 44, 14, 28
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or max(hi * 0.02, 1)
    lo, hi = lo - pad, hi + pad
    t0, t1 = pts[0][0].timestamp(), pts[-1][0].timestamp()
    X = lambda d: px + ((w - px - 10) * (d.timestamp() - t0) / (t1 - t0) if t1 > t0 else (w - px - 10) / 2)
    Y = lambda v: py0 + (h - py0 - py1) * (1 - (v - lo) / (hi - lo))
    g = []
    for k in range(3):
        v = lo + (hi - lo) * k / 2
        g.append(f'<line class="grid" x1="{px}" x2="{w-10}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 f'<text class="ax" x="{px-6}" y="{Y(v)+4:.1f}" text-anchor="end">{v:,.0f}</text>'.replace(",", " "))
    d = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in pts)
    area = f"{X(pts[0][0]):.1f},{h-py1} {d} {X(pts[-1][0]):.1f},{h-py1}"
    dots = "".join(f'<circle class="dot" cx="{X(a):.1f}" cy="{Y(b):.1f}" r="{3 if len(pts) < 60 else 1.6}"><title>{a:%d/%m %H:%M} · {fmt(b)}</title></circle>' for a, b in pts)
    lab = (f'<text class="ax" x="{px}" y="{h-8}">{pts[0][0]:%d/%m/%y}</text>'
           f'<text class="ax" x="{w-10}" y="{h-8}" text-anchor="end">{pts[-1][0]:%d/%m/%y %Hh}</text>')
    line = f'<polyline class="area" points="{area}"/><polyline class="line" points="{d}"/>' if len(pts) > 1 else ""
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Évolution du prix">{"".join(g)}{line}{dots}{lab}</svg>'


def statline(s):
    if not s:
        return ""
    cell = lambda k, v: f'<div><span>{k}</span><b>{v}</b></div>'
    return ('<div class="stats">' + cell("Actuel", fmt(s["cur"])) + cell("Min", fmt(s["mn"])) + cell("Max", fmt(s["mx"]))
            + cell("7 j", pct(s["d7"])) + cell("30 j", pct(s["d30"])) + cell("Relevés", s["n"]) + "</div>")


def badge(s):
    return (f'<span class="tag alert">Baisse {abs(s["drop"]):.0f} % · à vérifier sur Amazon</span>'
            if s and s["drop"] is not None else "")


# --- santé des relevés ------------------------------------------------------------------------------------
health = []
if runs:
    last_ts = max(r["horodatage"] for r in runs)
    for r in runs:
        if r["horodatage"] == last_ts:
            health.append((r["boutique"], r["statut"], r["nb_offres_valides"], r["detail"]))
    age = datetime.now(datetime.fromisoformat(last_ts).tzinfo) - datetime.fromisoformat(last_ts)
else:
    last_ts, age = None, None
warn = []
if age and age > timedelta(hours=GAP_HOURS):
    warn.append(f"Dernier relevé il y a {age.total_seconds()/3600:.0f} h : un relevé a peut-être été manqué.")
warn += [f"{b} : {s}" for b, s, _, _ in health if s != "ok"]

alerts = []
cfg_html = []
for c in configs:
    pts = cfg_series[c["config_id"]]
    s = stats(pts)
    if s and s["drop"] is not None:
        alerts.append(f'{c["libelle"]} : {pct(s["drop"])}')
    bmin, bmax = int(c["budget_min"]), int(c["budget_max"])
    inb = "" if not s else ('<span class="tag">Dans le budget</span>' if bmin <= s["cur"] <= bmax else '<span class="tag off">Hors budget</span>')
    rows = ""
    for pid in c["composants"].split("|"):
        if not series[pid]:
            continue
        r = best[(stamps[[i for i, t in enumerate(stamps) if (t, pid) in best][-1]], pid)]
        rows += (f'<tr><td>{esc(products[pid]["categorie"])}</td><td>{esc(products[pid]["libelle"])}</td>'
                 f'<td>{esc(r["boutique"])}{" · marketplace" if r["marketplace"]=="1" else ""}{" · rupture" if r["en_stock"]=="0" else ""}</td>'
                 f'<td class="num">{fmt(float(r["prix_eur"]))}</td></tr>')
    cfg_html.append(f'''<article class="card"><header><h3>{esc(c["libelle"])}</h3>
      <div class="tags"><span class="tag">{bmin}–{bmax} €</span>{inb}{badge(s)}</div></header>
      {statline(s)}{chart(pts)}
      <details><summary>Composition (dernier relevé)</summary><table>{rows}</table></details></article>''')
    if s and s["drop"] is not None:
        pass

comp_html = []
slug = lambda t: ''.join(ch if ch.isalnum() else '-' for ch in t.lower().replace('é','e').replace('è','e').replace('î','i'))
cats = defaultdict(list)
for pid, p in products.items():
    cats[p["categorie"]].append(pid)
order = {"bas": 0, "milieu": 1, "haut": 2}
for cat, pids in cats.items():
    cards = ""
    for pid in sorted(pids, key=lambda x: order.get(products[x]["gamme"], 9)):
        s = stats(series[pid])
        if s and s["drop"] is not None:
            alerts.append(f'{products[pid]["libelle"]} : {pct(s["drop"])}')
        shop = ""
        if series[pid]:
            r = best[(stamps[[i for i, t in enumerate(stamps) if (t, pid) in best][-1]], pid)]
            shop = f'{esc(r["boutique"])}{" · marketplace" if r["marketplace"]=="1" else ""}'
        cards += (f'<article class="card small"><header><h4>{esc(products[pid]["libelle"])}</h4>'
                  f'<div class="tags"><span class="tag">{esc(products[pid]["gamme"])}</span>'
                  f'<span class="tag soft">{shop}</span>{badge(s)}</div></header>{statline(s)}{chart(series[pid], h=140)}</article>')
    comp_html.append(f'<section class="tab" id="t-{slug(cat)}" data-label="{esc(cat)}"><h2>{esc(cat)}</h2><div class="grid">{cards}</div></section>')

alert_box = (f'<div class="notice alert"><b>Baisse notable détectée — pense à regarder les prix sur Amazon.</b><br>'
             + "<br>".join(esc(a) for a in alerts) + "</div>") if alerts else ""
warn_box = f'<div class="notice warn">{"<br>".join(esc(w) for w in warn)}</div>' if warn else ""
last_txt = f"{datetime.fromisoformat(last_ts):%d/%m/%Y à %H:%M}" if last_ts else "aucun relevé"
from zoneinfo import ZoneInfo
gen_txt = datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M")

page = f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Suivi prix hardware AM4</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#1f2a37;--mut:#6b7785;--acc:#4a6785;--soft:#a9bccd;--line:#e5e9ee;--alert:#b4553a}}
@media(prefers-color-scheme:dark){{:root{{--bg:#12171d;--card:#1a2129;--ink:#e6ebf0;--mut:#8b97a4;--acc:#8fb0d0;--soft:#4a6785;--line:#27303a;--alert:#e08a6d}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:40px 16px 64px}}
h1{{font-size:26px;font-weight:600;letter-spacing:-.01em;margin:0 0 4px}}h2{{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.09em;color:var(--mut);margin:44px 0 14px}}
h3{{font-size:17px;font-weight:600;margin:0}}h4{{font-size:14px;font-weight:600;margin:0}}.muted{{color:var(--mut)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}}.cfgs{{display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 18px 10px;transition:border-color .2s}}.card:hover{{border-color:var(--soft)}}
header{{display:flex;flex-direction:column;gap:8px;margin-bottom:12px}}.tags{{display:flex;flex-wrap:wrap;gap:6px}}
.tag{{font-size:11.5px;padding:2px 9px;border-radius:99px;border:1px solid var(--soft);color:var(--acc)}}.tag.soft{{border-color:var(--line);color:var(--mut)}}.tag.off{{border-style:dashed}}.tag.alert{{border-color:var(--alert);color:var(--alert)}}
.stats{{display:flex;flex-wrap:wrap;gap:6px 20px;margin-bottom:6px}}.stats span{{display:block;font-size:11px;color:var(--mut)}}.stats b{{font-weight:600;font-variant-numeric:tabular-nums;font-size:14px}}
svg{{width:100%;height:auto;display:block}}.line{{fill:none;stroke:var(--acc);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}}.area{{fill:var(--soft);opacity:.18;stroke:none}}
.dot{{fill:var(--acc)}}.grid line,line.grid{{stroke:var(--line)}}.ax{{fill:var(--mut);font-size:10.5px}}
details{{margin:6px 0 8px;font-size:13px}}summary{{cursor:pointer;color:var(--mut);padding:4px 0}}table{{width:100%;border-collapse:collapse;margin-top:6px}}td{{padding:5px 4px;border-top:1px solid var(--line)}}.num{{text-align:right;font-variant-numeric:tabular-nums}}
.notice{{border:1px solid var(--line);border-left:3px solid var(--acc);background:var(--card);border-radius:10px;padding:12px 16px;margin:18px 0;font-size:14px}}.notice.alert{{border-left-color:var(--alert)}}.notice.warn{{border-left-color:var(--mut)}}
nav.tabs{{display:flex;gap:4px;overflow-x:auto;border-bottom:1px solid var(--line);margin:28px 0 0;scrollbar-width:none}}nav.tabs::-webkit-scrollbar{{display:none}}
nav.tabs button{{flex:none;font:inherit;font-size:14px;background:none;border:0;border-bottom:2px solid transparent;color:var(--mut);padding:10px 14px;cursor:pointer;transition:color .2s,border-color .2s}}
nav.tabs button:hover{{color:var(--ink)}}nav.tabs button[aria-selected=true]{{color:var(--acc);border-bottom-color:var(--acc)}}
.js .tab{{display:none}}.js .tab.on{{display:block}}.tab>h2:first-child{{margin-top:28px}}
footer{{margin-top:56px;font-size:12.5px;color:var(--mut);max-width:760px}}@media(max-width:560px){{.cfgs{{grid-template-columns:1fr}}main{{padding-top:24px}}}}
</style></head><body><main>
<h1>Suivi prix hardware · AM4 / DDR4</h1>
<p class="muted">Dernier relevé : {last_txt} · {len(stamps)} relevé(s) · LDLC, Materiel.net, Rue du Commerce · rapport généré le {gen_txt}</p>
{alert_box}{warn_box}
<nav class="tabs" role="tablist" aria-label="Sections"></nav>
<section class="tab" id="t-configurations" data-label="Configurations"><h2>Configurations</h2><div class="cfgs">{"".join(cfg_html)}</div></section>
{"".join(comp_html)}
<footer><p>Chaque courbe suit le meilleur prix trouvé parmi les boutiques suivies (offres en stock et vendues par la boutique en priorité ; une offre marketplace n’est retenue que si aucune offre directe n’existe, et elle est alors signalée). Le total d’une configuration est la somme des meilleurs prix de ses composants, boutiques mélangées, livraison non incluse. Seule la première page de résultats de chaque boutique est lue : pour les catégories génériques (carte mère, alimentation, boîtier), « le moins cher » est celui de cette page, pas forcément du catalogue. Amazon n’est pas suivi : une baisse d’au moins {int(ALERT_DROP*100)} % par rapport à la médiane des 7 derniers jours déclenche un rappel d’aller y regarder.</p></footer>
</main>
<script>
(function(){{
 var secs=[].slice.call(document.querySelectorAll('section.tab')),nav=document.querySelector('nav.tabs');
 if(!secs.length||!nav)return; document.documentElement.classList.add('js');
 function show(id){{ if(!secs.some(function(s){{return s.id===id}}))id=secs[0].id;
  secs.forEach(function(s){{s.classList.toggle('on',s.id===id)}});
  [].forEach.call(nav.children,function(b){{b.setAttribute('aria-selected',b.dataset.id===id)}});
  try{{history.replaceState(null,'','#'+id)}}catch(e){{}} }}
 secs.forEach(function(s){{var b=document.createElement('button');b.type='button';b.setAttribute('role','tab');
  b.dataset.id=s.id;b.textContent=s.dataset.label;b.onclick=function(){{show(s.id)}};nav.appendChild(b)}});
 show(location.hash.slice(1)||secs[0].id);
 window.addEventListener('hashchange',function(){{show(location.hash.slice(1))}});
}})();
</script></body></html>'''
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
open(os.path.join(ROOT, "docs", "index.html"), "w", encoding="utf-8").write(page)
print("rapport généré :", len(page) // 1024, "Ko")
