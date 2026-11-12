# Suivi prix hardware (AM4 / DDR4)

Relevés automatiques LDLC, Materiel.net et Rue du Commerce, 2 fois par jour (6h00 et 18h00, Europe/Paris). Amazon n'est pas suivi (voir le rappel dans le rapport).

- `config/products.csv` : composants suivis (gamme bas/milieu/haut, requête, filtres regex)
- `config/configs.csv` : configurations (budget, composants)
- `data/prices.csv` : historique des prix. **Append uniquement, ne jamais modifier ni supprimer de lignes.**
- `data/runs.csv` : statut de chaque relevé par boutique (`ok`, `partiel`, `alerte_0_produit`, `erreur`)
- `docs/index.html` : rapport généré (graphiques par configuration et par composant, stats 7 j / 30 j)

Lancer à la main :

    pip install -r requirements.txt
    python3 collect.py && python3 report.py

Limites connues : seule la première page de résultats est lue ; une offre marketplace n'est retenue que si aucune offre directe n'existe (colonne `marketplace`) ; les prix hors livraison.
