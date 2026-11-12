#!/usr/bin/env python3
"""Relevé des prix (LDLC, Materiel.net, Rue du Commerce). Écriture en append uniquement."""
import csv, re, sys, time, urllib.parse, urllib.request, urllib.error, os
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.abspath(__file__))
PRICES = os.path.join(ROOT, "data", "prices.csv")
RUNS = os.path.join(ROOT, "data", "runs.csv")
PRICE_COLS = ["horodatage", "date", "creneau", "produit_id", "boutique", "titre", "prix_eur", "en_stock", "marketplace", "nb_offres_valides", "url"]
RUN_COLS = ["horodatage", "creneau", "boutique", "statut", "nb_produits_page", "nb_offres_valides", "detail"]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
USED = re.compile(r"occasion|reconditionn|reconditionné|open ?box|seconde main", re.I)
NOT_IN_STOCK = re.compile(r"rupture|indisponible|épuis|prochainement|bientôt|sous \d|réappro|non disponible", re.I)


def parse_price(txt):
    t = re.sub(r"[\s  ]", "", txt or "")
    m = re.search(r"(\d+)(?:,(\d{1,2})|€(\d{2}))?", t)
    if not m:
        return None
    dec = m.group(2) or m.group(3) or "0"
    return float(f"{m.group(1)}.{dec.ljust(2, '0')}")


def fetch(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except (urllib.error.URLError, TimeoutError) as e:
            err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"échec réseau: {err}")


def _items(soup, sel, base, title_sel, link_sel, mp_attr=None):
    out = []
    for li in soup.select(sel):
        title_el = li.select_one(title_sel)
        price_el = li.select_one(".price, .o-product__price")
        if not title_el or not price_el:
            continue
        a = li.select_one(link_sel)
        href = a.get("href", "") if a else ""
        mp = bool(li.select_one('[data-is-marketplace="1"]')) or li.get("data-is-marketplace") == "1"
        stock_el = li.select_one(".stock, .o-availability__value, [class*=availability]")
        stock_txt = stock_el.get_text(" ", strip=True) if stock_el else ""
        d = li.select_one(".desc, .c-product__description, .listing-product__desc")
        out.append(dict(desc=d.get_text(" ", strip=True) if d else "", titre=title_el.get_text(" ", strip=True), prix=parse_price(price_el.get_text("", strip=True)),
                        url=urllib.parse.urljoin(base, href), marketplace=mp, stock_txt=stock_txt))
    return out


SHOPS = {
    "LDLC": dict(url="https://www.ldlc.com/recherche/{q}/", base="https://www.ldlc.com",
                 sel="li.pdt-item", title="h3.title-3, .title-3", link="h3 a, .pic a"),
    "Materiel.net": dict(url="https://www.materiel.net/recherche/{q}/", base="https://www.materiel.net",
                         sel="li.c-products-list__item", title=".c-product__title", link="a.c-product__link"),
    "Rue du Commerce": dict(url="https://www.rueducommerce.fr/recherche/{q}", base="https://www.rueducommerce.fr",
                            sel="li.pdt-item", title=".title-3, h3, h2", link="a[href]"),
}


def main():
    tz = ZoneInfo("Europe/Paris")
    now = datetime.now(tz)
    slot = sys.argv[1] if len(sys.argv) > 1 else ("matin" if now.hour < 12 else "soir")
    ts = now.isoformat(timespec="seconds")
    products = list(csv.DictReader(open(os.path.join(ROOT, "config", "products.csv"), encoding="utf-8")))
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    price_rows, run_rows = [], []
    for shop, cfg in SHOPS.items():
        n_page = n_valid = 0
        errs = []
        for p in products:
            time.sleep(2)
            try:
                html = fetch(cfg["url"].format(q=urllib.parse.quote(p["requete"])))
                soup = BeautifulSoup(html, "lxml")
                items = _items(soup, cfg["sel"], cfg["base"], cfg["title"], cfg["link"])
            except Exception as e:
                errs.append(f'{p["id"]}: {e}')
                continue
            n_page += len(items)
            inc, exc = re.compile(p["inclure"], re.I), re.compile(p["exclure"], re.I) if p["exclure"] else None
            def ok(i):
                txt = i["titre"] + " " + i["desc"]
                return (i["prix"] and not USED.search(txt) and inc.search(txt)
                        and not (exc and exc.search(i["titre"])))
            valid = [i for i in items if ok(i)]
            for i in valid:
                i["en_stock"] = 0 if NOT_IN_STOCK.search(i["stock_txt"]) else 1
            n_valid += len(valid)
            direct = [i for i in valid if not i["marketplace"]]
            pool = direct or valid  # repli marketplace seulement si aucune offre directe
            if pool:
                best = min(pool, key=lambda i: (1 - i["en_stock"], i["prix"]))
                price_rows.append([ts, now.date().isoformat(), slot, p["id"], shop, best["titre"], f'{best["prix"]:.2f}',
                                   best["en_stock"], int(best["marketplace"]), len(pool), best["url"]])
        statut = "erreur" if errs and n_page == 0 else ("alerte_0_produit" if n_page == 0 else ("partiel" if errs else "ok"))
        run_rows.append([ts, slot, shop, statut, n_page, n_valid, " | ".join(errs)[:500]])
    for path, cols, rows in ((PRICES, PRICE_COLS, price_rows), (RUNS, RUN_COLS, run_rows)):
        new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(cols)
            w.writerows(rows)
    for r in run_rows:
        print(r)
    print(f"{len(price_rows)} prix ajoutés")


if __name__ == "__main__":
    main()
