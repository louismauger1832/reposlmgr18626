#!/usr/bin/env python3
"""Génère docs/index.html (autonome, sans dépendance externe) depuis data/*.csv."""
import csv, os, html, statistics, itertools
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
latest = {}  # pid -> dernière ligne retenue
for ts in stamps:
    for pid in products:
        if (ts, pid) in best:
            latest[pid] = best[(ts, pid)]


def resolve(tokens):
    """tokens : 'a' = produit fixe, 'a/b' = le moins cher des deux (à chaque relevé). Retourne (points, lignes)."""
    groups = [t.split("/") for t in tokens]
    last, pts = {}, []
    for ts in stamps:
        for g in groups:
            for pid in g:
                if (ts, pid) in best:
                    last[pid] = float(best[(ts, pid)]["prix_eur"])
        if all(any(p in last for p in g) for g in groups):
            pts.append((datetime.fromisoformat(ts), sum(min(last[p] for p in g if p in last) for g in groups)))
    rows = ""
    for g in groups:
        have = [p for p in g if p in latest]
        if not have:
            continue
        pid = min(have, key=lambda p: float(latest[p]["prix_eur"]))
        r = latest[pid]
        rows += (f'<tr><td class="cat">{esc(products[pid]["categorie"])}</td><td>{esc(products[pid]["libelle"])}</td>'
                 f'<td class="shop">{esc(r["boutique"])}{" · marketplace" if r["marketplace"]=="1" else ""}{" · rupture" if r["en_stock"]=="0" else ""}</td>'
                 f'<td class="num">{fmt(float(r["prix_eur"]))}</td></tr>')
    return pts, rows


cfg_groups = defaultdict(list)
overview = []
for c in configs:
    bmin, bmax = int(c["budget_min"]), int(c["budget_max"])
    toks = c["composants"].split("|")
    opts = [t.split("~") for t in toks]
    panels, btns = "", ""
    variants = list(itertools.product(*opts))
    for vi, v in enumerate(variants):
        pts, rows = resolve(list(v))
        s = stats(pts)
        vlabel = " · ".join(products[p]["libelle"] for t, o in zip(v, opts) if len(o) > 1 for p in [t.split("/")[0]]) if len(variants) > 1 else ""
        if s and s["drop"] is not None:
            alerts.append(f'{c["libelle"]}{" (" + vlabel + ")" if vlabel else ""} : {pct(s["drop"])}')
        inb = "" if not s else ('<span class="tag">Dans le budget</span>' if bmin <= s["cur"] <= bmax else '<span class="tag off">Hors budget</span>')
        panels += (f'<div class="panel" data-v="{vi}"{"" if vi == 0 else " hidden"}><div class="tags">{inb}{badge(s)}</div>'
                   f'<div class="total">{fmt(s["cur"]) if s else "—"}</div>{statline(s)}{chart(pts)}'
                   f'<details><summary>Détail de la configuration (dernier relevé)</summary><table>{rows}</table></details></div>')
        if len(variants) > 1:
            btns += f'<button type="button" class="seg{" on" if vi == 0 else ""}" data-v="{vi}">{esc(vlabel)}</button>'
        if vi == 0:
            first = s
    cpu_name = products[opts[0][0].split("/")[0]]["libelle"]
    card = (f'<article class="card cfg"><header><h3>{esc(c["libelle"])}</h3>'
            f'<div class="tags"><span class="tag soft">budget {bmin}–{bmax} €</span></div>'
            f'{"<div class=segs>" + btns + "</div>" if btns else ""}</header>{panels}</article>')
    cfg_groups[cpu_name].append(card)
    if first:
        overview.append((c["libelle"], first["cur"]))

cfg_html = "".join(
    f'<details class="group" open><summary><span>{esc(cpu)}</span><span class="count">{len(cards)} configurations</span></summary>'
    f'<div class="cfgs">{"".join(cards)}</div></details>' for cpu, cards in cfg_groups.items())

# --- onglet composants : sélecteur + une fiche par composant ------------------------------------------------
cats = defaultdict(list)
for pid, p in products.items():
    cats[p["categorie"]].append(pid)
opts_html, comp_cards = "", ""
for cat, pids in cats.items():
    opts_html += f'<optgroup label="{esc(cat)}">'
    for pid in pids:
        s = stats(series[pid])
        if s and s["drop"] is not None:
            alerts.append(f'{products[pid]["libelle"]} : {pct(s["drop"])}')
        shop = ""
        if pid in latest:
            r = latest[pid]
            shop = f'{esc(r["boutique"])}{" · marketplace" if r["marketplace"]=="1" else ""}'
            link = f'<a href="{esc(r["url"])}" rel="noopener" target="_blank">{esc(r["titre"])}</a>'
        else:
            link = ""
        opts_html += f'<option value="{pid}">{esc(products[pid]["libelle"])}</option>'
        comp_cards += (f'<article class="card comp" data-id="{pid}" hidden><header><h3>{esc(products[pid]["libelle"])}</h3>'
                       f'<div class="tags"><span class="tag">{esc(cat)}</span><span class="tag soft">{shop}</span>{badge(s)}</div></header>'
                       f'<div class="total">{fmt(s["cur"]) if s else "—"}</div>{statline(s)}{chart(series[pid], h=190)}'
                       f'<p class="muted small">{link}</p></article>')
    opts_html += "</optgroup>"

alert_box = (f'<div class="notice alert"><b>Baisse notable détectée — pense à regarder les prix sur Amazon.</b><br>'
             + "<br>".join(esc(a) for a in alerts) + "</div>") if alerts else ""
warn_box = f'<div class="notice warn">{"<br>".join(esc(w) for w in warn)}</div>' if warn else ""
last_txt = f"{datetime.fromisoformat(last_ts):%d/%m/%Y à %H:%M}" if last_ts else "aucun relevé"
cheapest = min(overview, key=lambda x: x[1]) if overview else None
kpis = (f'<div class="kpis"><div><span>Config la moins chère</span><b>{fmt(cheapest[1])}</b><small>{esc(cheapest[0])}</small></div>'
        f'<div><span>Configurations</span><b>{len(configs)}</b><small>{len(cfg_groups)} processeurs</small></div>'
        f'<div><span>Composants suivis</span><b>{len(products)}</b><small>{len(cats)} catégories</small></div>'
        f'<div><span>Relevés</span><b>{len(stamps)}</b><small>dernier : {last_txt}</small></div></div>') if cheapest else ""

page = f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Suivi prix hardware AM4</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#1f2a37;--mut:#6b7785;--acc:#4a6785;--soft:#a9bccd;--line:#e5e9ee;--alert:#b4553a}}
@media(prefers-color-scheme:dark){{:root{{--bg:#12171d;--card:#1a2129;--ink:#e6ebf0;--mut:#8b97a4;--acc:#8fb0d0;--soft:#4a6785;--line:#27303a;--alert:#e08a6d}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:32px 16px 64px}}
h1{{font-size:26px;font-weight:600;letter-spacing:-.01em;margin:0 0 4px}}h3{{font-size:17px;font-weight:600;margin:0}}.muted{{color:var(--mut)}}.small{{font-size:12.5px;margin:6px 0 10px}}.small a{{color:inherit}}
.tabs{{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:22px 0 20px}}
.tab{{background:none;border:0;border-bottom:2px solid transparent;color:var(--mut);font:inherit;font-weight:600;padding:10px 16px;cursor:pointer;margin-bottom:-1px}}.tab.on{{color:var(--ink);border-bottom-color:var(--acc)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:22px}}
.kpis div{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px}}.kpis span{{display:block;font-size:11.5px;color:var(--mut)}}.kpis b{{font-size:22px;font-variant-numeric:tabular-nums;font-weight:600}}.kpis small{{display:block;font-size:12px;color:var(--mut)}}
.group{{margin-bottom:18px}}.group>summary{{display:flex;justify-content:space-between;align-items:baseline;cursor:pointer;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.09em;color:var(--mut);padding:8px 0 12px;border-bottom:1px solid var(--line);margin-bottom:14px}}.count{{font-weight:400;text-transform:none;letter-spacing:0;font-size:12.5px}}
.cfgs{{display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 18px 10px}}.card.comp{{max-width:720px}}
header{{display:flex;flex-direction:column;gap:8px;margin-bottom:12px}}.tags{{display:flex;flex-wrap:wrap;gap:6px}}
.tag{{font-size:11.5px;padding:2px 9px;border-radius:99px;border:1px solid var(--soft);color:var(--acc)}}.tag.soft{{border-color:var(--line);color:var(--mut)}}.tag.off{{border-style:dashed}}.tag.alert{{border-color:var(--alert);color:var(--alert)}}
.segs{{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;align-self:flex-start}}.seg{{background:none;border:0;border-right:1px solid var(--line);color:var(--mut);font:inherit;font-size:12.5px;padding:4px 12px;cursor:pointer}}.seg:last-child{{border-right:0}}.seg.on{{background:var(--acc);color:var(--card)}}
.total{{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums;margin:8px 0 2px}}
.stats{{display:flex;flex-wrap:wrap;gap:6px 20px;margin-bottom:6px}}.stats span{{display:block;font-size:11px;color:var(--mut)}}.stats b{{font-weight:600;font-variant-numeric:tabular-nums;font-size:14px}}
svg{{width:100%;height:auto;display:block}}.line{{fill:none;stroke:var(--acc);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}}.area{{fill:var(--soft);opacity:.18;stroke:none}}
.dot{{fill:var(--acc)}}line.grid{{stroke:var(--line)}}.ax{{fill:var(--mut);font-size:10.5px}}
.card details{{margin:6px 0 8px;font-size:13px}}.card summary{{cursor:pointer;color:var(--mut);padding:4px 0}}table{{width:100%;border-collapse:collapse;margin-top:6px}}td{{padding:5px 4px;border-top:1px solid var(--line)}}.num{{text-align:right;font-variant-numeric:tabular-nums}}td.cat{{color:var(--mut);white-space:nowrap}}td.shop{{color:var(--mut)}}
select{{font:inherit;padding:8px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);min-width:min(100%,360px);margin-bottom:16px}}
.notice{{border:1px solid var(--line);border-left:3px solid var(--acc);background:var(--card);border-radius:10px;padding:12px 16px;margin:18px 0;font-size:14px}}.notice.alert{{border-left-color:var(--alert)}}.notice.warn{{border-left-color:var(--mut)}}
footer{{margin-top:56px;font-size:12.5px;color:var(--mut);max-width:760px}}[hidden]{{display:none!important}}@media(max-width:560px){{.cfgs{{grid-template-columns:1fr}}main{{padding-top:20px}}}}
</style></head><body><main>
<h1>Suivi prix hardware · AM4 / DDR4</h1>
<p class="muted">LDLC, Materiel.net, Rue du Commerce · cartes mères B550 ASUS / Gigabyte · SSD SATA 250 Go + HDD 7200 tr/min</p>
{alert_box}{warn_box}
<nav class="tabs"><button type="button" class="tab on" data-tab="cfg">Configurations</button><button type="button" class="tab" data-tab="comp">Composants</button></nav>
<section id="cfg">{kpis}{cfg_html}</section>
<section id="comp" hidden><select id="pick" aria-label="Choisir un composant">{opts_html}</select><div>{comp_cards}</div></section>
<footer><p>Chaque courbe suit le meilleur prix trouvé parmi les boutiques suivies (offres en stock et vendues par la boutique en priorité ; une offre marketplace n’est retenue que si aucune offre directe n’existe, et elle est alors signalée). Le total d’une configuration est la somme des meilleurs prix de ses composants, boutiques mélangées, livraison non incluse ; la carte mère est la moins chère entre ASUS et Gigabyte (MSI écarté). Seule la première page de résultats de chaque boutique est lue : pour les catégories génériques (alimentation, boîtier), « le moins cher » est celui de cette page, pas forcément du catalogue. Amazon n’est pas suivi : une baisse d’au moins {int(ALERT_DROP*100)} % par rapport à la médiane des 7 derniers jours déclenche un rappel d’aller y regarder.</p></footer>
</main><script>
(function(){{
var S=function(k,v){{try{{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}}catch(e){{}}}};
var tabs=document.querySelectorAll('.tab');
function showTab(t){{tabs.forEach(function(b){{b.classList.toggle('on',b.dataset.tab===t)}});document.getElementById('cfg').hidden=t!=='cfg';document.getElementById('comp').hidden=t!=='comp';S('tab',t)}}
tabs.forEach(function(b){{b.onclick=function(){{showTab(b.dataset.tab)}}}});
var pick=document.getElementById('pick');
function showComp(id){{document.querySelectorAll('.comp').forEach(function(c){{c.hidden=c.dataset.id!==id}});S('comp',id)}}
pick.onchange=function(){{showComp(pick.value)}};
var c0=S('comp');if(c0&&pick.querySelector('option[value="'+c0+'"]'))pick.value=c0;showComp(pick.value);
showTab(S('tab')==='comp'?'comp':'cfg');
document.querySelectorAll('.cfg').forEach(function(card){{card.querySelectorAll('.seg').forEach(function(b){{b.onclick=function(){{
card.querySelectorAll('.seg').forEach(function(x){{x.classList.toggle('on',x===b)}});
card.querySelectorAll('.panel').forEach(function(p){{p.hidden=p.dataset.v!==b.dataset.v}})}}}})}});
}})();
</script></body></html>'''
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
open(os.path.join(ROOT, "docs", "index.html"), "w", encoding="utf-8").write(page)
print("rapport généré :", len(page) // 1024, "Ko")
