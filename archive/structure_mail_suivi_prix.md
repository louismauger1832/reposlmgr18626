# Archive : structure du mail de suivi des prix (anonymisée)

Le script d'envoi a été supprimé le 27/11/2026 (le suivi est terminé, le site est désormais personnel).
On garde seulement la structure, sans destinataire ni données personnelles, au cas où il faudrait refaire
un mail de suivi pour quelqu'un.

## Principe
- Script lancé après chaque relevé, sur un ou plusieurs composants suivis (`produit_id` de `config/products.csv`).
- Il affiche « RIEN … » quand il n'y a rien à envoyer, sinon un JSON `{to, subject, html, text}` que la routine envoie tel quel avec Gmail.
- Après un envoi réussi, `--enregistrer` ajoute une ligne à un journal CSV en ajout uniquement
  (`envoye_le, releve, <pid>, <pid>@<boutique>…`). Si la liste des pièces change, on ajoute une nouvelle ligne d'en-tête commençant par `envoye_le` au lieu de réécrire le fichier.
- On n'envoie rien si :
  - aucun nouveau relevé depuis le dernier mail ;
  - le meilleur prix a bougé de moins de 0,01 €.
- Notes perso facultatives : CSV `ajoutee_le,texte,url`. Chaque note ajoutée après le dernier envoi passe une seule fois, en tête du mail suivant.

## Choix du meilleur prix
Pour chaque relevé : offre vendue par la boutique avant les offres marketplace, puis offre en stock, puis prix le plus bas.

## Contenu du mail
- **Objet :** `<Composant> — <prix> chez <boutique> — relevé du JJ/MM`
- **Corps** (HTML + version texte) :
  1. Salutation, puis « Le prix de … a bougé » (ou « Voici où en est le prix de … » au premier envoi), avec la date et l'heure du relevé.
  2. Les notes perso éventuelles.
  3. Le meilleur prix, la boutique et le lien vers l'offre, puis l'écart depuis le dernier mail et sur 7 jours.
  4. Un tableau par boutique : Boutique | Modèle | Prix (★ = le moins cher) | Depuis le dernier mail | Sur 7 jours.
     Les mentions « (vendeur tiers) » et « — rupture » sont signalées.
  5. Le lien vers l'onglet du site, puis le pied de mail : « Prix relevés sur …, hors livraison. Amazon n'est pas suivi. »
