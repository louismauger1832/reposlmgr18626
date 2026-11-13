#!/usr/bin/env python3
"""Génère docs/index.html (autonome, sans dépendance externe) depuis data/*.csv et config/*.csv."""
import csv, os, html, statistics
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
ALERT_DROP = 0.07   # baisse >= 7 % vs médiane des 7 derniers jours => pointer vers Amazon
GAP_HOURS = 4       # relevés toutes les 3 h : au-delà, on signale un trou
CAT_ORDER = ["CPU", "GPU", "Carte mère", "RAM", "Stockage", "Alimentation", "Boîtier", "Refroidissement"]
GAMME_ORDER = {"bas": 0, "base": 0, "milieu": 1, "haut": 2}


def rd(path):
    p = os.path.join(ROOT, path)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


prices, runs = rd("data/prices.csv"), rd("data/runs.csv")
products = {r["id"]: r for r in rd("config/products.csv")}
configs = rd("config/configs.csv")
esc = html.escape
fmt = lambda v: "—" if v is None else f"{v:,.2f} €".replace(",", " ").replace(".", ",")
pct = lambda v: "n/d" if v is None else f"{v:+.1f} %".replace(".", ",")
slug = lambda t: "".join(c if c.isalnum() else "-" for c in t.lower().replace("é", "e").replace("è", "e").replace("î", "i"))

# --- séries ------------------------------------------------------------------------------------------------
by_ts = defaultdict(lambda: defaultdict(list))
shop_rows = defaultdict(list)      # (pid, boutique) -> [(datetime, prix)]
latest_shop = {}                   # (pid, boutique) -> dernière ligne
for r in prices:
    by_ts[r["horodatage"]][r["produit_id"]].append(r)
    shop_rows[(r["produit_id"], r["boutique"])].append((datetime.fromisoformat(r["horodatage"]), float(r["prix_eur"])))
    latest_shop[(r["produit_id"], r["boutique"])] = r
stamps = sorted(by_ts)
best, last_best = {}, {}
for ts in stamps:
    for pid, rows in by_ts[ts].items():
        best[(ts, pid)] = last_best[pid] = min(rows, key=lambda r: (r["marketplace"] == "1", r["en_stock"] == "0", float(r["prix_eur"])))
series = defaultdict(list)
for ts in stamps:
    for pid in products:
        if (ts, pid) in best:
            series[pid].append((datetime.fromisoformat(ts), float(best[(ts, pid)]["prix_eur"])))
cfg_series = {}
for c in configs:
    comp, last, pts = c["composants"].split("|"), {}, []
    for ts in stamps:
        for pid in comp:
            if (ts, pid) in best:
                last[pid] = float(best[(ts, pid)]["prix_eur"])
        if all(p in last for p in comp):
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


# --- graphiques SVG ---------------------------------------------------------------------------------------
def chart(lines, w=560, h=190):
    """lines : [(libellé, [(datetime, prix)], classe)]"""
    allp = [p for _, pts, _ in lines for p in pts]
    if not allp:
        return '<p class="muted">Pas encore de données.</p>'
    px, py0, py1 = 50, 14, 30
    vals = [v for _, v in allp]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or max(hi * 0.02, 1)
    lo, hi = lo - pad, hi + pad
    t0, t1 = min(d for d, _ in allp).timestamp(), max(d for d, _ in allp).timestamp()
    X = lambda d: px + ((w - px - 10) * (d.timestamp() - t0) / (t1 - t0) if t1 > t0 else (w - px - 10) / 2)
    Y = lambda v: py0 + (h - py0 - py1) * (1 - (v - lo) / (hi - lo))
    out = []
    for k in range(3):
        v = lo + (hi - lo) * k / 2
        out.append(f'<line class="grid" x1="{px}" x2="{w-10}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                   f'<text class="ax" x="{px-7}" y="{Y(v)+4:.1f}" text-anchor="end">{v:,.0f}</text>'.replace(",", " "))
    for i, (label, pts, cls) in enumerate(lines):
        if not pts:
            continue
        d = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in pts)
        if i == 0 and len(pts) > 1:
            out.append(f'<polyline class="area" points="{X(pts[0][0]):.1f},{h-py1} {d} {X(pts[-1][0]):.1f},{h-py1}"/>')
        if len(pts) > 1:
            out.append(f'<polyline class="{cls}" points="{d}"/>')
        r = 3.2 if len(pts) < 60 else 1.6
        out.append("".join(f'<circle class="dot {cls}" cx="{X(a):.1f}" cy="{Y(b):.1f}" r="{r}"><title>{esc(label)} · {a:%d/%m %H:%M} · {fmt(b)}</title></circle>' for a, b in pts))
    d0, d1 = min(d for d, _ in allp), max(d for d, _ in allp)
    out.append(f'<text class="ax" x="{px}" y="{h-9}">{d0:%d/%m/%y %Hh}</text><text class="ax" x="{w-10}" y="{h-9}" text-anchor="end">{d1:%d/%m/%y %Hh}</text>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Évolution du prix">{"".join(out)}</svg>'


def spark(pts, w=84, h=22):
    if len(pts) < 2:
        return '<span class="muted">—</span>'
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    t0, t1 = pts[0][0].timestamp(), pts[-1][0].timestamp()
    X = lambda d: 2 + (w - 4) * (d.timestamp() - t0) / (t1 - t0 or 1)
    Y = lambda v: h / 2 if hi == lo else 2 + (h - 4) * (1 - (v - lo) / (hi - lo))
    return f'<svg class="spark" viewBox="0 0 {w} {h}"><polyline class="line" points="{" ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in pts)}"/></svg>'


def statline(s):
    if not s:
        return ""
    cell = lambda k, v: f'<div><span>{k}</span><b>{v}</b></div>'
    return ('<div class="stats">' + cell("Actuel", fmt(s["cur"])) + cell("Min", fmt(s["mn"])) + cell("Max", fmt(s["mx"]))
            + cell("7 j", pct(s["d7"])) + cell("30 j", pct(s["d30"])) + cell("Relevés", s["n"]) + "</div>")


def badge(s):
    return (f'<span class="tag alert">Baisse {abs(s["drop"]):.0f} % · à vérifier sur Amazon</span>'
            if s and s["drop"] is not None else "")


def shoplabel(r):
    return esc(r["boutique"]) + (" · marketplace" if r["marketplace"] == "1" else "") + (" · rupture" if r["en_stock"] == "0" else "")


# --- santé ------------------------------------------------------------------------------------------------
health, last_ts, age = [], None, None
if runs:
    last_ts = max(r["horodatage"] for r in runs)
    health = [(r["boutique"], r["statut"]) for r in runs if r["horodatage"] == last_ts]
    age = datetime.now(datetime.fromisoformat(last_ts).tzinfo) - datetime.fromisoformat(last_ts)
warn = []
if age and age > timedelta(hours=GAP_HOURS):
    warn.append(f"Dernier relevé il y a {age.total_seconds()/3600:.0f} h : un relevé a peut-être été manqué.")
warn += [f"{b} : {s}" for b, s in health if s != "ok"]
alerts = []

# --- onglet Configurations ----------------------------------------------------------------------------------
groups = []
for c in configs:
    if c["groupe"] not in groups:
        groups.append(c["groupe"])
cfg_html = ""
for g in groups:
    cards = ""
    for c in [c for c in configs if c["groupe"] == g]:
        pts = cfg_series[c["config_id"]]
        s = stats(pts)
        if s and s["drop"] is not None:
            alerts.append(f'{c["libelle"]} : {pct(s["drop"])}')
        bmin, bmax = int(c["budget_min"]), int(c["budget_max"])
        inb = "" if not s else ('<span class="tag">Dans le budget</span>' if bmin <= s["cur"] <= bmax else '<span class="tag off">Hors budget</span>')
        rows, missing = "", []
        for pid in c["composants"].split("|"):
            if pid not in last_best:
                missing.append(products[pid]["libelle"])
                continue
            r = last_best[pid]
            st = stats(series[pid])
            rows += (f'<tr><td><a href="{esc(r["url"])}" target="_blank" rel="noopener" title="{esc(r["titre"])}">{esc(products[pid]["libelle"])}</a>'
                     f'<small>{esc(products[pid]["categorie"])}</small></td><td class="nw">{shoplabel(r)}</td>'
                     f'<td>{spark(series[pid])}</td><td class="num">{pct(st["d7"]) if st else "n/d"}</td>'
                     f'<td class="num"><b>{fmt(float(r["prix_eur"]))}</b></td></tr>')
        total = f'<tr class="tot"><td colspan="4">Total</td><td class="num"><b>{fmt(s["cur"]) if s else "—"}</b></td></tr>' if s else ""
        miss = f'<p class="muted">Sans offre pour l’instant : {esc(", ".join(missing))}. Le total apparaît dès que tout est disponible.</p>' if missing else ""
        cards += f'''<article class="card"><header><h3>{esc(c["libelle"])}</h3>
          <div class="tags"><span class="tag">{bmin}–{bmax} €</span>{inb}{badge(s)}</div></header>
          {statline(s)}{chart([("Total", pts, "line")])}
          <details><summary>Dérouler la configuration complète</summary>{miss}
          <div class="tw"><table><thead><tr><th>Composant</th><th>Boutique</th><th>Tendance</th><th class="num">7 j</th><th class="num">Prix</th></tr></thead>{rows}{total}</table></div></details></article>'''
    cfg_html += f'<h3 class="grp">{esc(g)}</h3><div class="cfgs">{cards}</div>'

# --- onglet Composants -------------------------------------------------------------------------------------
cats = defaultdict(list)
for pid, p in products.items():
    cats[p["categorie"]].append(pid)
cat_names = [c for c in CAT_ORDER if c in cats] + [c for c in cats if c not in CAT_ORDER]
cat_btns, plists, panels = "", "", ""
for cat in cat_names:
    pids = sorted(cats[cat], key=lambda x: (GAMME_ORDER.get(products[x]["gamme"], 9), products[x]["libelle"]))
    cat_btns += f'<button type="button" data-cat="{slug(cat)}">{esc(cat)}</button>'
    plists += f'<div class="pl" data-cat="{slug(cat)}">' + "".join(
        f'<button type="button" data-pid="{pid}">{esc(products[pid]["libelle"])}</button>' for pid in pids) + "</div>"
    for pid in pids:
        s = stats(series[pid])
        if s and s["drop"] is not None:
            alerts.append(f'{products[pid]["libelle"]} : {pct(s["drop"])}')
        shops = sorted({sh for (p, sh) in latest_shop if p == pid})
        lines = [("Meilleur prix", series[pid], "line")]
        tbl = ""
        for sh in shops:
            r = latest_shop[(pid, sh)]
            ref = float(last_best[pid]["prix_eur"]) if pid in last_best else None
            diff = "" if ref is None else (f"+{float(r['prix_eur'])-ref:.2f} €".replace(".", ",") if float(r["prix_eur"]) > ref else "meilleur")
            stale = "" if r["horodatage"] == max(x["horodatage"] for x in prices if x["produit_id"] == pid) else " · ancien relevé"
            tbl += (f'<tr><td>{shoplabel(r)}{stale}</td><td><a href="{esc(r["url"])}" target="_blank" rel="noopener">{esc(r["titre"][:80])}</a></td>'
                    f'<td class="num"><b>{fmt(float(r["prix_eur"]))}</b></td><td class="num muted">{diff}</td></tr>')
        shop_lines = [(sh, shop_rows[(pid, sh)], f"line s{i+1}") for i, sh in enumerate(shops)]
        legend = "".join(f'<span class="lg s{i+1}">{esc(sh)}</span>' for i, sh in enumerate(shops))
        panels += f'''<article class="pp card" data-pid="{pid}" data-cat="{slug(cat)}"><header><h3>{esc(products[pid]["libelle"])}</h3>
          <div class="tags"><span class="tag">{esc(products[pid]["gamme"])}</span><span class="tag soft">{esc(cat)}</span>{badge(s)}</div></header>
          {statline(s)}<h4>Meilleur prix</h4>{chart(lines)}
          <h4>Par boutique</h4><div class="legend">{legend}</div>{chart(shop_lines, h=170)}
          <div class="tw"><table><thead><tr><th>Boutique</th><th>Offre retenue</th><th class="num">Prix</th><th class="num">Écart</th></tr></thead>{tbl}</table></div></article>'''

alert_box = (f'<div class="notice alert"><b>Baisse notable détectée — pense à regarder les prix sur Amazon.</b><br>'
             + "<br>".join(esc(a) for a in alerts) + "</div>") if alerts else ""
warn_box = f'<div class="notice warn">{"<br>".join(esc(w) for w in warn)}</div>' if warn else ""
last_txt = f"{datetime.fromisoformat(last_ts):%d/%m/%Y à %H:%M}" if last_ts else "aucun relevé"
gen_txt = datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M")

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1f2a37;--mut:#6b7785;--acc:#4a6785;--soft:#a9bccd;--line:#e5e9ee;--alert:#b4553a}
@media(prefers-color-scheme:dark){:root{--bg:#12171d;--card:#1a2129;--ink:#e6ebf0;--mut:#8b97a4;--acc:#8fb0d0;--soft:#4a6785;--line:#27303a;--alert:#e08a6d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:40px 16px 64px}a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:26px;font-weight:600;letter-spacing:-.01em;margin:0 0 4px}h3{font-size:17px;font-weight:600;margin:0}h4{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:18px 0 4px}
h3.grp{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.09em;color:var(--mut);margin:34px 0 12px}.muted{color:var(--mut)}small{display:block;color:var(--mut);font-size:12px}
.cfgs{display:grid;grid-template-columns:repeat(auto-fill,minmax(500px,1fr));gap:16px;align-items:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 18px 12px}
header{display:flex;flex-direction:column;gap:8px;margin-bottom:12px}.tags{display:flex;flex-wrap:wrap;gap:6px}
.tag{font-size:11.5px;padding:2px 9px;border-radius:99px;border:1px solid var(--soft);color:var(--acc)}.tag.soft{border-color:var(--line);color:var(--mut)}.tag.off{border-style:dashed}.tag.alert{border-color:var(--alert);color:var(--alert)}
.stats{display:flex;flex-wrap:wrap;gap:6px 22px;margin-bottom:6px}.stats span{display:block;font-size:11px;color:var(--mut)}.stats b{font-weight:600;font-variant-numeric:tabular-nums;font-size:14px}
svg{width:100%;height:auto;display:block}.line{fill:none;stroke:var(--acc);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}.area{fill:var(--soft);opacity:.18;stroke:none}
.dot{fill:var(--acc);stroke:none}line.grid{stroke:var(--line)}.ax{fill:var(--mut);font-size:13px}
.line.s1,.dot.s1{stroke:var(--acc);fill:var(--acc)}.line.s2,.dot.s2{stroke:var(--soft);fill:var(--soft)}.line.s3,.dot.s3{stroke:var(--mut);fill:var(--mut);stroke-dasharray:5 4}.dot.s3{stroke:none}.line.s1,.line.s2,.line.s3{fill:none}
.legend{display:flex;gap:16px;font-size:12.5px;color:var(--mut);margin-bottom:2px}.lg::before{content:"";display:inline-block;width:14px;height:2px;margin-right:6px;vertical-align:middle;background:var(--acc)}.lg.s2::before{background:var(--soft)}.lg.s3::before{background:var(--mut)}
details{margin:8px 0 6px;font-size:13.5px}summary{cursor:pointer;color:var(--acc);padding:6px 0}.tw{overflow-x:auto}
table{width:100%;border-collapse:collapse;margin-top:6px;font-size:13.5px}th{font-size:11px;font-weight:600;color:var(--mut);text-align:left;text-transform:uppercase;letter-spacing:.05em;padding:4px}td{padding:7px 4px;border-top:1px solid var(--line);vertical-align:middle}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}th.num{text-align:right}tr.tot td{border-top:2px solid var(--line)}.spark{width:64px;height:22px}td.nw{white-space:nowrap}.pl{flex-wrap:wrap;gap:6px}.cfgs>*{min-width:0}
.notice{border:1px solid var(--line);border-left:3px solid var(--acc);background:var(--card);border-radius:10px;padding:12px 16px;margin:18px 0;font-size:14px}.notice.alert{border-left-color:var(--alert)}.notice.warn{border-left-color:var(--mut)}
nav.top{display:flex;gap:6px;margin:26px 0 0;border-bottom:1px solid var(--line)}
nav.top button{font:inherit;font-size:15px;font-weight:600;background:none;border:0;border-bottom:2px solid transparent;color:var(--mut);padding:10px 18px;cursor:pointer;transition:color .2s,border-color .2s}
nav.top button:hover{color:var(--ink)}nav.top button[aria-selected=true]{color:var(--acc);border-bottom-color:var(--acc)}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0 0}.pills.sub{margin-top:10px}
.pills button{font:inherit;font-size:13px;background:none;border:1px solid var(--line);color:var(--mut);border-radius:99px;padding:5px 14px;cursor:pointer;transition:all .2s}
.pills button:hover{border-color:var(--soft);color:var(--ink)}.pills button[aria-selected=true]{background:var(--acc);border-color:var(--acc);color:var(--card)}
.pp{margin-top:22px;max-width:760px}
.js .view,.js .pl,.js .pp{display:none}.js .view.on,.js .pl.on,.js .pp.on{display:block}.js .pl.on{display:flex}
footer{margin-top:56px;font-size:12.5px;color:var(--mut);max-width:780px}
@media(max-width:560px){.cfgs{grid-template-columns:1fr}main{padding-top:24px}nav.top button{padding:10px 12px}}
"""
JS = """
(function(){
 var $=function(s,r){return [].slice.call((r||document).querySelectorAll(s))};
 var views=$('.view'),top=document.querySelector('nav.top');if(!views.length||!top)return;
 document.documentElement.classList.add('js');
 var cats=$('.pills.cats button'),pls=$('.pl'),pps=$('.pp'),state={v:'configurations',c:null,p:null};
 function sel(btns,key,val){btns.forEach(function(b){b.setAttribute('aria-selected',b.dataset[key]===val)})}
 function render(){
  views.forEach(function(v){v.classList.toggle('on',v.id===state.v)});sel($('button',top),'v',state.v);
  if(state.v==='composants'){
   if(!cats.some(function(b){return b.dataset.cat===state.c}))state.c=cats[0].dataset.cat;
   var pl=pls.filter(function(x){return x.dataset.cat===state.c})[0];
   if(!pl.querySelector('[data-pid="'+state.p+'"]'))state.p=pl.children[0].dataset.pid;
   pls.forEach(function(x){x.classList.toggle('on',x===pl)});sel(cats,'cat',state.c);sel($('button',pl),'pid',state.p);
   pps.forEach(function(x){x.classList.toggle('on',x.dataset.pid===state.p)});
  }
  try{history.replaceState(null,'','#'+(state.v==='composants'?'composants/'+state.c+'/'+state.p:state.v))}catch(e){}
 }
 function fromHash(){var h=location.hash.slice(1).split('/');state.v=h[0]==='composants'?'composants':'configurations';state.c=h[1]||state.c;state.p=h[2]||state.p;render()}
 $('button',top).forEach(function(b){b.onclick=function(){state.v=b.dataset.v;render()}});
 cats.forEach(function(b){b.onclick=function(){state.c=b.dataset.cat;state.p=null;render()}});
 $('.pl button').forEach(function(b){b.onclick=function(){state.p=b.dataset.pid;render()}});
 window.addEventListener('hashchange',fromHash);fromHash();
})();
"""
page = f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Suivi prix hardware AM4</title><style>{CSS}</style></head><body><main>
<h1>Suivi prix hardware · AM4 / DDR4</h1>
<p class="muted">Dernier relevé : {last_txt} · {len(stamps)} relevé(s) · LDLC, Materiel.net, Rue du Commerce · rapport généré le {gen_txt}</p>
{alert_box}{warn_box}
<nav class="top" role="tablist"><button type="button" role="tab" data-v="configurations">Configurations</button><button type="button" role="tab" data-v="composants">Composants</button></nav>
<section class="view" id="configurations">{cfg_html}</section>
<section class="view" id="composants"><div class="pills cats">{cat_btns}</div><div class="pills sub">{plists}</div>{panels}</section>
<footer><p>Chaque courbe suit le meilleur prix trouvé parmi les boutiques suivies (offres en stock et vendues par la boutique en priorité ; une offre marketplace n’est retenue que si aucune offre directe n’existe, et elle est alors signalée). Le total d’une configuration est la somme des meilleurs prix de ses composants, boutiques mélangées, livraison non incluse. Stockage de toutes les configurations : SSD SATA 250 Go + disque dur 3,5" 7200 tr/min. Cartes mères : B550 ASUS ou Gigabyte uniquement. Seule la première page de résultats de chaque boutique est lue : pour les catégories génériques, « le moins cher » est celui de cette page, pas forcément du catalogue. Amazon n’est pas suivi : une baisse d’au moins {int(ALERT_DROP*100)} % par rapport à la médiane des 7 derniers jours déclenche un rappel d’aller y regarder.</p></footer>
</main><script>{JS}</script></body></html>'''
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
open(os.path.join(ROOT, "docs", "index.html"), "w", encoding="utf-8").write(page)
print("rapport généré :", len(page) // 1024, "Ko")
