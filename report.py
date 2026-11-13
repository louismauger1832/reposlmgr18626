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
SHOP_CLS = {"LDLC": "s1", "Materiel.net": "s2", "Rue du Commerce": "s3"}
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
_gid = [0]


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
    _gid[0] += 1
    gid = f"g{_gid[0]}"
    out = [f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--acc);stop-opacity:.22"/>'
           f'<stop offset="1" style="stop-color:var(--acc);stop-opacity:0"/></linearGradient></defs>']
    for k in range(3):
        v = lo + (hi - lo) * k / 2
        out.append(f'<line class="grid" x1="{px}" x2="{w-10}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                   f'<text class="ax" x="{px-7}" y="{Y(v)+4:.1f}" text-anchor="end">{v:,.0f}</text>'.replace(",", " "))
    for i, (label, pts, cls) in enumerate(lines):
        if not pts:
            continue
        d = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in pts)
        if i == 0 and cls == "line" and len(pts) > 1:
            out.append(f'<polyline class="area" fill="url(#{gid})" points="{X(pts[0][0]):.1f},{h-py1} {d} {X(pts[-1][0]):.1f},{h-py1}"/>')
        if len(pts) > 1:
            out.append(f'<polyline class="{cls}" points="{d}"/>')
        r = 3.2 if len(pts) < 60 else 1.6
        dcls = " ".join(t for t in cls.split() if t != "line")
        out.append("".join(f'<circle class="dot {dcls}" cx="{X(a):.1f}" cy="{Y(b):.1f}" r="{r}"><title>{esc(label)} · {a:%d/%m %H:%M} · {fmt(b)}</title></circle>' for a, b in pts))
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
            tbl += (f'<tr><td class="nw"><span class="sd {SHOP_CLS.get(sh, "s1")}"></span>{shoplabel(r)}{stale}</td><td><a href="{esc(r["url"])}" target="_blank" rel="noopener">{esc(r["titre"][:80])}</a></td>'
                    f'<td class="num"><b>{fmt(float(r["prix_eur"]))}</b></td><td class="num muted">{diff}</td></tr>')
        shop_lines = [(sh, shop_rows[(pid, sh)], f"line {SHOP_CLS.get(sh, 's1')}") for sh in shops]
        legend = "".join(f'<span class="lg {SHOP_CLS.get(sh, "s1")}"><i></i>{esc(sh)}</span>' for sh in shops)
        panels += f'''<article class="pp card" data-pid="{pid}" data-cat="{slug(cat)}"><header><h3>{esc(products[pid]["libelle"])}</h3>
          <div class="tags"><span class="tag">{esc(products[pid]["gamme"])}</span><span class="tag soft">{esc(cat)}</span>{badge(s)}</div></header>
          {statline(s)}<h4>Meilleur prix</h4>{chart(lines)}
          <h4>Par boutique</h4><div class="legend">{legend}</div>{chart(shop_lines, h=170)}
          <div class="tw"><table><thead><tr><th>Boutique</th><th>Offre retenue</th><th class="num">Prix</th><th class="num">Écart</th></tr></thead>{tbl}</table></div></article>'''

alert_box = (f'<div class="notice alert"><b>Baisse notable détectée — pense à regarder les prix sur Amazon.</b><br>'
             + "<br>".join(esc(a) for a in alerts) + "</div>") if alerts else ""
warn_box = f'<div class="notice warn">{"<br>".join(esc(w) for w in warn)}</div>' if warn else ""
last_txt = f"{datetime.fromisoformat(last_ts):%d/%m/%Y à %H:%M}" if last_ts else "aucun relevé"
_now = datetime.now(ZoneInfo("Europe/Paris"))
gen_txt = _now.strftime("%d/%m/%Y à %H:%M")
gen_short = _now.strftime("%d/%m %H:%M")
last_short = f"{datetime.fromisoformat(last_ts):%d/%m · %H:%M}" if last_ts else "—"
age_txt = (f"il y a {int(age.total_seconds() // 3600)} h {int(age.total_seconds() % 3600 // 60):02d}" if age else "aucun relevé")
shops_ok = sum(1 for _, st in health if st == "ok")
shops_bad = shops_ok != len(health)
n_cfg = len(configs)

CSS = """
:root{--bg:#f3f5f8;--bg2:#e6edf6;--card:#fff;--card2:#f9fafc;--chip:#f0f3f7;--ink:#1b2634;--mut:#66758a;--acc:#35597f;--soft:#a9bccd;--line:#e3e8ee;--alert:#b4553a;--ok:#2f9e6e;
--s1:#1f3f66;--s2:#14917f;--s3:#d9822b;--sh:0 1px 2px rgba(18,32,52,.06),0 10px 28px -14px rgba(18,32,52,.28);--sh2:0 2px 4px rgba(18,32,52,.08),0 20px 40px -16px rgba(18,32,52,.38)}
@media(prefers-color-scheme:dark){:root{--bg:#0f141a;--bg2:#16202b;--card:#18202a;--card2:#151c25;--chip:#1f2833;--ink:#e7edf3;--mut:#8d9aab;--acc:#8fb4da;--soft:#3f5f80;--line:#27313d;--alert:#e08a6d;--ok:#4cc38a;
--s1:#8db3ee;--s2:#4fd1bf;--s3:#f2a95c;--sh:0 1px 2px rgba(0,0,0,.4),0 10px 28px -14px rgba(0,0,0,.7);--sh2:0 2px 4px rgba(0,0,0,.5),0 20px 40px -16px rgba(0,0,0,.8)}}
*{box-sizing:border-box}body{margin:0;color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:radial-gradient(1200px 460px at 50% -140px,var(--bg2),transparent) no-repeat,var(--bg)}
main{max-width:1100px;margin:0 auto;padding:36px 16px 64px}a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.hero{position:relative;overflow:hidden;display:flex;flex-wrap:wrap;gap:22px 32px;align-items:center;justify-content:space-between;padding:26px 30px;border-radius:22px;border:1px solid var(--line);background:linear-gradient(135deg,var(--card) 0%,var(--card2) 55%,var(--bg2) 100%);box-shadow:var(--sh)}
.hero::before{content:"";position:absolute;inset:0 auto 0 0;width:5px;background:linear-gradient(var(--s1),var(--s2))}
.brand{display:flex;gap:18px;align-items:center}.logo{flex:none;width:56px;height:56px;border-radius:16px;display:grid;place-items:center;background:linear-gradient(145deg,var(--s1),var(--acc));box-shadow:0 10px 22px -10px var(--s1)}
.logo svg{width:30px;height:30px;fill:none;stroke:#fff;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
h1{font-size:28px;font-weight:650;letter-spacing:-.02em;line-height:1.15;margin:0}.sub{margin:4px 0 0;color:var(--mut);font-size:14px}
.kpis{display:flex;flex-wrap:wrap;gap:10px}.kpi{min-width:120px;padding:11px 15px;border-radius:14px;background:var(--chip);border:1px solid var(--line);box-shadow:inset 0 1px 0 rgba(255,255,255,.4)}
.kpi span{display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut)}.kpi b{display:block;font-size:17px;font-variant-numeric:tabular-nums;margin-top:1px}.kpi small{font-size:12px}
.dotst{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--ok);margin-right:7px;box-shadow:0 0 0 3px color-mix(in srgb,var(--ok) 25%,transparent)}.dotst.bad{background:var(--alert);box-shadow:0 0 0 3px color-mix(in srgb,var(--alert) 25%,transparent)}
h3{font-size:17px;font-weight:600;margin:0}h4{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:20px 0 4px}
h3.grp{display:flex;align-items:center;gap:10px;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.09em;color:var(--mut);margin:38px 0 14px}
h3.grp::before{content:"";width:22px;height:3px;border-radius:3px;background:linear-gradient(90deg,var(--s1),var(--s2))}.muted{color:var(--mut)}small{display:block;color:var(--mut);font-size:12px}
.cfgs{display:grid;grid-template-columns:repeat(auto-fill,minmax(500px,1fr));gap:18px;align-items:start}.cfgs>*{min-width:0}
.card{background:linear-gradient(180deg,var(--card),var(--card2));border:1px solid var(--line);border-radius:18px;padding:20px 20px 14px;box-shadow:var(--sh);transition:transform .25s,box-shadow .25s,border-color .25s}
.cfgs .card:hover{transform:translateY(-3px);box-shadow:var(--sh2);border-color:var(--soft)}
.card header{display:flex;flex-direction:column;gap:9px;margin-bottom:14px}.tags{display:flex;flex-wrap:wrap;gap:6px}
.tag{font-size:11.5px;padding:2px 10px;border-radius:99px;border:1px solid var(--soft);color:var(--acc);background:color-mix(in srgb,var(--soft) 12%,transparent)}.tag.soft{border-color:var(--line);color:var(--mut);background:none}.tag.off{border-style:dashed}.tag.alert{border-color:var(--alert);color:var(--alert);background:color-mix(in srgb,var(--alert) 10%,transparent)}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px}.stats>div{padding:6px 12px;border-radius:11px;background:var(--chip);border:1px solid var(--line)}
.stats span{display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}.stats b{font-weight:600;font-variant-numeric:tabular-nums;font-size:14px}
svg{width:100%;height:auto;display:block}.line{fill:none;stroke:var(--acc);stroke-width:2.4;stroke-linejoin:round;stroke-linecap:round}.area{stroke:none}
.dot{fill:var(--acc);stroke:var(--card);stroke-width:1.5}line.grid{stroke:var(--line);stroke-dasharray:2 5}.ax{fill:var(--mut);font-size:13px}
.line.s1{stroke:var(--s1)}.line.s2{stroke:var(--s2);stroke-dasharray:9 5}.line.s3{stroke:var(--s3);stroke-dasharray:.1 6.5;stroke-width:3.4}
.dot.s1{fill:var(--s1)}.dot.s2{fill:var(--s2)}.dot.s3{fill:var(--s3)}
.legend{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 2px}.lg{display:inline-flex;align-items:center;gap:9px;padding:4px 13px 4px 11px;border-radius:99px;background:var(--chip);border:1px solid var(--line);font-size:13px;font-weight:500}
.lg i{display:block;width:24px;height:0;border-top:3.5px solid var(--s1);border-radius:3px}.lg.s2 i{border-top:3.5px dashed var(--s2)}.lg.s3 i{border-top:3.5px dotted var(--s3)}
.sd{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;background:var(--s1)}.sd.s2{background:var(--s2)}.sd.s3{background:var(--s3)}
details{margin:10px 0 6px;font-size:13.5px}summary{cursor:pointer;color:var(--acc);font-weight:500;padding:8px 2px}summary:hover{text-decoration:underline}.tw{overflow-x:auto;border-radius:12px}
table{width:100%;border-collapse:collapse;margin-top:6px;font-size:13.5px}th{font-size:11px;font-weight:600;color:var(--mut);text-align:left;text-transform:uppercase;letter-spacing:.05em;padding:6px 6px}td{padding:8px 6px;border-top:1px solid var(--line);vertical-align:middle}
tbody tr:hover td,table tr:hover td{background:color-mix(in srgb,var(--soft) 9%,transparent)}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}th.num{text-align:right}tr.tot td{border-top:2px solid var(--line);font-size:14.5px}.spark{width:64px;height:22px}td.nw{white-space:nowrap}
.notice{border:1px solid var(--line);border-left:4px solid var(--acc);background:var(--card);border-radius:12px;padding:13px 18px;margin:18px 0;font-size:14px;box-shadow:var(--sh)}.notice.alert{border-left-color:var(--alert)}.notice.warn{border-left-color:var(--mut)}
nav.top{display:inline-flex;gap:4px;padding:5px;margin:26px 0 0;border-radius:15px;background:var(--chip);border:1px solid var(--line);box-shadow:inset 0 1px 3px rgba(0,0,0,.06)}
nav.top button{font:inherit;font-size:14.5px;font-weight:600;background:none;border:0;border-radius:11px;color:var(--mut);padding:9px 22px;cursor:pointer;transition:all .22s}
nav.top button:hover{color:var(--ink)}nav.top button[aria-selected=true]{background:var(--card);color:var(--acc);box-shadow:var(--sh)}
.pills{display:flex;flex-wrap:wrap;gap:7px;margin:18px 0 0}.pills.sub{margin-top:10px}
.pills button{font:inherit;font-size:13px;background:var(--card);border:1px solid var(--line);color:var(--mut);border-radius:99px;padding:6px 15px;cursor:pointer;box-shadow:0 1px 2px rgba(18,32,52,.05);transition:all .2s}
.pills button:hover{border-color:var(--soft);color:var(--ink);transform:translateY(-1px)}.pills button[aria-selected=true]{background:linear-gradient(135deg,var(--acc),var(--s1));border-color:transparent;color:var(--card);box-shadow:0 6px 14px -6px var(--s1)}
.pp{margin-top:24px;max-width:780px}
.js .view,.js .pl,.js .pp{display:none}.js .view.on,.js .pl.on,.js .pp.on{display:block}.js .pl.on{display:flex}.pl{flex-wrap:wrap;gap:7px}
footer{margin-top:56px;font-size:12.5px;color:var(--mut);max-width:780px}
@media(max-width:560px){.cfgs{grid-template-columns:1fr}main{padding-top:20px}.hero{padding:20px}h1{font-size:23px}.kpi{min-width:calc(50% - 5px);flex:1}nav.top button{padding:9px 14px}}
"""
JS = """
(function(){
 var $=function(s,r){return [].slice.call((r||document).querySelectorAll(s))};
 var views=$('.view'),top=document.querySelector('nav.top');if(!views.length||!top)return;
 document.documentElement.classList.add('js');
 var cats=$('.pills.cats button'),pls=$('.pl'),pps=$('.pp'),state={v:'configurations',c:null,p:null};
 function sel(btns,key,val){btns.forEach(function(b){b.setAttribute('aria-selected',b.dataset[key]===val)})}
 function render(){
  views.forEach(function(v){v.classList.toggle('on',v.id==='v-'+state.v)});sel($('button',top),'v',state.v);
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
<div class="hero"><div class="brand"><div class="logo"><svg viewBox="0 0 24 24"><path d="M3 17l5-6 4 3 8-9"/><path d="M15 5h5v5"/></svg></div>
<div><h1>Suivi prix hardware</h1><p class="sub">PC AM4 · DDR4 · LDLC, Materiel.net, Rue du Commerce</p></div></div>
<div class="kpis"><div class="kpi"><span>Dernier relevé</span><b>{last_short}</b><small class="muted">{age_txt}</small></div>
<div class="kpi"><span>Relevés</span><b>{len(stamps)}</b><small class="muted">{n_cfg} configs · {len(products)} composants</small></div>
<div class="kpi"><span>Boutiques</span><b><i class="dotst{" bad" if shops_bad else ""}"></i>{shops_ok}/{len(health)} ok</b><small class="muted">généré {gen_short}</small></div></div></div>
{alert_box}{warn_box}
<nav class="top" role="tablist"><button type="button" role="tab" data-v="configurations">Configurations</button><button type="button" role="tab" data-v="composants">Composants</button></nav>
<section class="view" id="v-configurations">{cfg_html}</section>
<section class="view" id="v-composants"><div class="pills cats">{cat_btns}</div><div class="pills sub">{plists}</div>{panels}</section>
<footer><p>Chaque courbe suit le meilleur prix trouvé parmi les boutiques suivies (offres en stock et vendues par la boutique en priorité ; une offre marketplace n’est retenue que si aucune offre directe n’existe, et elle est alors signalée). Le total d’une configuration est la somme des meilleurs prix de ses composants, boutiques mélangées, livraison non incluse. Stockage de toutes les configurations : SSD SATA 250 Go + disque dur 3,5" 7200 tr/min. Cartes mères : B550 ASUS ou Gigabyte uniquement. Seule la première page de résultats de chaque boutique est lue : pour les catégories génériques, « le moins cher » est celui de cette page, pas forcément du catalogue. Amazon n’est pas suivi : une baisse d’au moins {int(ALERT_DROP*100)} % par rapport à la médiane des 7 derniers jours déclenche un rappel d’aller y regarder.</p></footer>
</main><script>{JS}</script></body></html>'''
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
open(os.path.join(ROOT, "docs", "index.html"), "w", encoding="utf-8").write(page)
print("rapport généré :", len(page) // 1024, "Ko")
