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
PIDS = {"gpu-rtx5060": "GeForce RTX 5060", "gpu-rtx3060-12g": "GeForce RTX 3060 12 Go",
        "hdd-1to-7200": "HDD 1 To 7200 tr/min", "hdd-2to-7200": "HDD 2 To 7200 tr/min"}
GROUPES = [("Cartes graphiques", "gpu-"), ("Disques durs", "hdd-")]
LOG = os.path.join(ROOT, "data", "mails_romain.csv")
LOG_COLS = ["envoye_le", "releve"] + list(PIDS)
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


def best_rows():
    """Meilleure offre par produit et par relevé (même règle que report.py : boutique directe et en stock d'abord)."""
    by = {}
    for r in csv.DictReader(open(os.path.join(ROOT, "data", "prices.csv"), encoding="utf-8")):
        if r["produit_id"] in PIDS:
            by.setdefault(r["horodatage"], {}).setdefault(r["produit_id"], []).append(r)
    return {ts: {pid: min(rs, key=lambda r: (r["marketplace"] == "1", r["en_stock"] == "0", float(r["prix_eur"])))
                 for pid, rs in d.items()} for ts, d in by.items()}


best = best_rows()
if not best:
    print("RIEN (aucun relevé pour ces pièces)")
    sys.exit(0)
last_ts = max(best)
cur = {pid: best[last_ts].get(pid) for pid in PIDS}
if any(v is None for v in cur.values()):
    print("RIEN (une des pièces n'a pas de prix dans le dernier relevé)")
    sys.exit(0)
price = {pid: float(r["prix_eur"]) for pid, r in cur.items()}

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
        w.writerow([datetime.now().astimezone().isoformat(timespec="seconds"), last_ts] + [f"{price[p]:.2f}" for p in PIDS])
    print("enregistré")
    sys.exit(0)

if prev and prev["releve"] == last_ts:
    print("RIEN (pas de nouveau relevé depuis le dernier mail)")
    sys.exit(0)
old = {pid: float(prev[pid]) if prev.get(pid) else None for pid in PIDS} if prev else None
moved = [pid for pid in PIDS if old is None or old[pid] is None or abs(price[pid] - old[pid]) >= 0.01]
if not moved:
    print("RIEN (aucun mouvement de prix depuis le dernier mail)")
    sys.exit(0)


def ago7(pid):
    now = datetime.fromisoformat(last_ts)
    ref = [ts for ts in sorted(best) if datetime.fromisoformat(ts) <= now - timedelta(days=7) and pid in best[ts]]
    return float(best[ref[-1]][pid]["prix_eur"]) if ref else None


def delta(new, before):
    if before is None:
        return ""
    d = new - before
    return "inchangé" if abs(d) < 0.01 else (f"{'+' if d > 0 else '−'}{fmt(abs(d))}")


when = datetime.fromisoformat(last_ts)
creneau = "matin" if when.hour < 14 else "soir"
subject = f"Prix cartes graphiques + HDD — relevé du {when:%d/%m} ({creneau})"
blocs_html, blocs_txt = "", []
for titre, pfx in GROUPES:
    rows_html, rows_txt = "", []
    for pid, name in PIDS.items():
        if not pid.startswith(pfx):
            continue
        r = cur[pid]
        shop = r["boutique"] + (" (vendeur tiers)" if r["marketplace"] == "1" else "")
        chg = ("nouveau" if old[pid] is None else delta(price[pid], old[pid])) if old else "premier envoi"
        w7 = ago7(pid)
        s7 = delta(price[pid], w7) if w7 is not None else "n/d"
        rows_html += (f'<tr><td><a href="{r["url"]}">{name}</a></td><td>{shop}</td><td align="right"><b>{fmt(price[pid])}</b></td>'
                      f'<td align="right">{chg}</td><td align="right">{s7}</td></tr>')
        rows_txt.append(f"- {name} : {fmt(price[pid])} chez {shop} ({chg} depuis le dernier mail, {s7} sur 7 jours)")
    blocs_html += (f'<p><b>{titre}</b></p><table cellpadding="6" style="border-collapse:collapse;border:2px solid #000">'
                   '<tr style="background:#000;color:#fff"><th align="left">Pièce</th><th align="left">Meilleure offre</th>'
                   '<th align="right">Prix</th><th align="right">Depuis le dernier mail</th><th align="right">Sur 7 jours</th></tr>'
                   f'{rows_html}</table>')
    blocs_txt.append(f"{titre} :\n" + "\n".join(rows_txt))

notes_html, notes_txt = notes_perso(datetime.fromisoformat(prev["envoye_le"]) if prev else None)
intro = "Il y a du mouvement sur les prix que tu suis" if old else "Voici où en sont les prix des pièces que tu suis"
html = f"""<p>Salut Romain,</p>
<p>{intro} (relevé du {when:%d/%m/%Y à %H:%M}).</p>
{notes_html}{blocs_html}
<p>Courbes et détail par boutique : <a href="{PAGE_URL}">{PAGE_URL}</a></p>
<p style="color:#555;font-size:12px">Prix relevés sur LDLC, Materiel.net et Rue du Commerce, hors livraison. Amazon n'est pas suivi.</p>"""
text = (f"Salut Romain,\n\n{intro} (relevé du {when:%d/%m/%Y à %H:%M}).\n\n" + notes_txt
        + "\n\n".join(blocs_txt) + f"\n\nCourbes et détail : {PAGE_URL}\n\nPrix hors livraison, LDLC / Materiel.net / Rue du Commerce.")
print(json.dumps({"to": [TO], "subject": subject, "html": html, "text": text}, ensure_ascii=False))
