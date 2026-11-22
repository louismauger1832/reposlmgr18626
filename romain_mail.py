#!/usr/bin/env python3
"""Prépare le mail de suivi pour Romain, uniquement si un prix a bougé depuis le dernier mail envoyé.

  python3 romain_mail.py               -> affiche « RIEN » (pas de mail à envoyer) ou un JSON {to, subject, html, text}
  python3 romain_mail.py --enregistrer -> à lancer APRÈS l'envoi réussi : ajoute une ligne à data/mails_romain.csv

data/mails_romain.csv est en ajout uniquement : c'est la mémoire des prix déjà annoncés à Romain.
Quand la liste des pièces change, une nouvelle ligne d'en-tête (commençant par « envoye_le ») est ajoutée
avant la ligne suivante : les lignes d'avant gardent leur en-tête, rien n'est réécrit.

Messages perso : data/notes_romain.csv (colonnes ajoutee_le,texte,url), modifiable à la main, en ajout uniquement.
Chaque note ajoutée après le dernier mail envoyé est glissée en tête du prochain mail, une seule fois.
"""
import csv, html as htmlmod, json, os, sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
TO = "romain.dufour06@gmail.com"
PAGE_URL = "https://louismauger1832.github.io/reposlmgr18626/#romain"
# Il reste à Romain : UNE carte graphique GeForce RTX 5060 (mise à jour du 22/11/2026, avant : GPU au choix + disque dur)
PID, NAME = "gpu-rtx5060", "GeForce RTX 5060"
PIDS = {PID: NAME}
LOG = os.path.join(ROOT, "data", "mails_romain.csv")
NOTES = os.path.join(ROOT, "data", "notes_romain.csv")


def notes_perso(depuis):
    """Messages perso écrits dans data/notes_romain.csv après `depuis` (date du dernier mail) -> (html, texte)."""
    if not os.path.exists(NOTES):
        return "", ""
    notes = [n for n in csv.DictReader(open(NOTES, encoding="utf-8"))
             if n.get("texte") and (depuis is None or datetime.fromisoformat(n["ajoutee_le"]) > depuis)]
    esc = htmlmod.escape
    h = "".join(f'<p>{esc(n["texte"])}' + (f' : <a href="{esc(n["url"])}">{esc(n["url"])}</a>' if n.get("url") else "")
                + "</p>\n" for n in notes)
    t = "".join(n["texte"] + (f' : {n["url"]}' if n.get("url") else "") + "\n\n" for n in notes)
    return h, t

fmt = lambda v: f"{v:,.2f} €".replace(",", " ").replace(".", ",")


def load():
    """Par relevé : {boutique: ligne retenue} pour la RTX 5060."""
    by = {}
    for r in csv.DictReader(open(os.path.join(ROOT, "data", "prices.csv"), encoding="utf-8")):
        if r["produit_id"] == PID:
            by.setdefault(r["horodatage"], {})[r["boutique"]] = r
    return by


pick = lambda rows: min(rows, key=lambda r: (r["marketplace"] == "1", r["en_stock"] == "0", float(r["prix_eur"])))
by_ts = load()
if not by_ts:
    print("RIEN (aucun relevé RTX 5060)")
    sys.exit(0)
last_ts = max(by_ts)
cur = by_ts[last_ts]
best = pick(cur.values())
price = float(best["prix_eur"])
shops = sorted(cur, key=lambda sh: (cur[sh]["en_stock"] == "0", float(cur[sh]["prix_eur"])))
LOG_COLS = ["envoye_le", "releve", PID] + [f"{PID}@{sh}" for sh in sorted(cur)]


def read_log():
    """Lignes du journal sous forme de dict ; une ligne commençant par « envoye_le » est un nouvel en-tête."""
    rows, head = [], None
    if os.path.exists(LOG):
        for r in csv.reader(open(LOG, encoding="utf-8")):
            if not r:
                continue
            if r[0] == "envoye_le":
                head = r
            elif head:
                rows.append(dict(zip(head, r)))
    return rows, head


sent, log_head = read_log()
prev = sent[-1] if sent else None

if "--enregistrer" in sys.argv:
    with open(LOG, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if log_head != LOG_COLS:
            w.writerow(LOG_COLS)
        w.writerow([datetime.now().astimezone().isoformat(timespec="seconds"), last_ts, f"{price:.2f}"]
                   + [cur[sh]["prix_eur"] for sh in sorted(cur)])
    print("enregistré")
    sys.exit(0)

if prev and prev["releve"] == last_ts:
    print("RIEN (pas de nouveau relevé depuis le dernier mail)")
    sys.exit(0)
num = lambda v: float(v) if v not in (None, "") else None
old = num(prev.get(PID)) if prev else None
if old is not None and abs(price - old) < 0.01:
    print("RIEN (meilleur prix RTX 5060 inchangé depuis le dernier mail)")
    sys.exit(0)


def ago7(shop=None):
    lim = datetime.fromisoformat(last_ts) - timedelta(days=7)
    ref = [ts for ts in sorted(by_ts) if datetime.fromisoformat(ts) <= lim and (shop is None or shop in by_ts[ts])]
    if not ref:
        return None
    rows = by_ts[ref[-1]]
    return float((rows[shop] if shop else pick(rows.values()))["prix_eur"])


def delta(new, before):
    if before is None:
        return "n/d"
    d = new - before
    return "inchangé" if abs(d) < 0.01 else (f"{'+' if d > 0 else '−'}{fmt(abs(d))}")


esc = htmlmod.escape
when = datetime.fromisoformat(last_ts)
subject = f"RTX 5060 — {fmt(price)} chez {best['boutique']} — relevé du {when:%d/%m}"
shop_lbl = lambda r: r["boutique"] + (" (vendeur tiers)" if r["marketplace"] == "1" else "") + (" — rupture" if r["en_stock"] == "0" else "")
chg = delta(price, old) if prev else "premier envoi"
w7 = ago7()
head_html = (f'<p><b>Meilleur prix RTX 5060 : {fmt(price)}</b> chez {esc(shop_lbl(best))} '
             f'(<a href="{esc(best["url"])}">{esc(best["titre"])}</a>).<br>'
             f'Depuis le dernier mail : {chg} · sur 7 jours : {delta(price, w7)}.</p>')
head_txt = (f"Meilleur prix RTX 5060 : {fmt(price)} chez {shop_lbl(best)} ({best['titre']}).\n"
            f"Depuis le dernier mail : {chg} · sur 7 jours : {delta(price, w7)}.\n{best['url']}\n\n")
rows_html, rows_txt = "", []
for sh in shops:
    r = cur[sh]
    p = float(r["prix_eur"])
    prev_rows = by_ts.get(prev["releve"], {}) if prev else {}  # prix de la boutique au relevé annoncé dans le dernier mail
    o = float(prev_rows[sh]["prix_eur"]) if sh in prev_rows else None
    c = ("nouveau" if o is None else delta(p, o)) if prev else "premier envoi"
    s7 = delta(p, ago7(sh))
    star = " ★" if r is best else ""
    rows_html += (f'<tr><td>{esc(shop_lbl(r))}</td><td><a href="{esc(r["url"])}">{esc(r["titre"][:70])}</a></td>'
                  f'<td align="right"><b>{fmt(p)}</b>{star}</td><td align="right">{c}</td><td align="right">{s7}</td></tr>')
    rows_txt.append(f"- {shop_lbl(r)} : {fmt(p)}{star} — {r['titre'][:70]} ({c} depuis le dernier mail, {s7} sur 7 jours)")
table_html = ('<p><b>Meilleure RTX 5060 par boutique</b></p><table cellpadding="6" style="border-collapse:collapse;border:2px solid #000">'
              '<tr style="background:#000;color:#fff"><th align="left">Boutique</th><th align="left">Modèle</th>'
              '<th align="right">Prix</th><th align="right">Depuis le dernier mail</th><th align="right">Sur 7 jours</th></tr>'
              f'{rows_html}</table><p style="color:#555;font-size:12px">★ = le moins cher (en stock et vendu par la boutique en priorité)</p>')
sources = ", ".join(sorted(cur))

notes_html, notes_txt = notes_perso(datetime.fromisoformat(prev["envoye_le"]) if prev else None)
intro = "Le prix de la RTX 5060 a bougé" if prev else "Voici où en est le prix de la RTX 5060"
html = f"""<p>Salut Romain,</p>
<p>{intro} (relevé du {when:%d/%m/%Y à %H:%M}).</p>
{notes_html}{head_html}{table_html}
<p>Courbes et détail par boutique : <a href="{PAGE_URL}">{PAGE_URL}</a></p>
<p style="color:#555;font-size:12px">Prix relevés sur {esc(sources)}, hors livraison. Amazon n'est pas suivi.</p>"""
text = (f"Salut Romain,\n\n{intro} (relevé du {when:%d/%m/%Y à %H:%M}).\n\n" + notes_txt + head_txt
        + "Meilleure RTX 5060 par boutique :\n" + "\n".join(rows_txt) + "\n\n★ = le moins cher"
        + f"\n\nCourbes et détail : {PAGE_URL}\n\nPrix hors livraison, {sources}.")
print(json.dumps({"to": [TO], "subject": subject, "html": html, "text": text}, ensure_ascii=False))
