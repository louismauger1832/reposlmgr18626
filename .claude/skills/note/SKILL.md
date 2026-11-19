---
name: note
description: Écrire le message perso à glisser dans le prochain mail de suivi des prix envoyé à Romain. À utiliser quand l'utilisateur tape /note, avec ou sans texte.
argument-hint: "[message] [lien facultatif]"
---

# /note : message perso pour le prochain mail à Romain

La boîte « note » = les lignes de `data/notes_romain.csv` ajoutées **après** le dernier mail envoyé
(dernière valeur `envoye_le` de `data/mails_romain.csv`). `romain_mail.py` (fonction `notes_perso()`) les place
en tête du prochain mail, juste après « Salut Romain ». Dès que le mail est envoyé et enregistré
(`python3 romain_mail.py --enregistrer`), la boîte est vide : elle se réinitialise d'elle-même, sans rien effacer.

## Étapes

1. Se placer à la racine du dépôt, sur `main` à jour : `git checkout main && git pull --rebase origin main`.

2. Montrer la boîte actuelle : lire la dernière date `envoye_le` de `data/mails_romain.csv`, puis afficher les notes
   de `data/notes_romain.csv` dont `ajoutee_le` est postérieure. Si aucune : « La boîte est vide. »

3. Récupérer le message :
   - Si `/note` est suivi d'un texte (`$ARGUMENTS`), c'est le message. Une URL `http(s)://…` qu'il contient va dans
     la colonne `url` et est retirée du texte.
   - Sinon, ouvrir une boîte de dialogue : utiliser l'outil AskUserQuestion s'il est disponible (question
     « Quel message pour Romain ? », la réponse libre est le message) ; sinon poser la question dans le chat et
     **attendre** la réponse. Ne rien inventer.
   - Si l'utilisateur répond « vider » ou « annuler », ne rien écrire et s'arrêter.

4. Nettoyer un lien Amazon : `https://www.amazon.fr/.../dp/XXXXXXXXXX/...?...` devient
   `https://www.amazon.fr/dp/XXXXXXXXXX` (retire les paramètres de suivi et jetons de session). Corriger les fautes
   de frappe évidentes sans changer le sens ni le ton. Montrer le texte final.

5. Ajouter **une ligne** à la fin de `data/notes_romain.csv` (fichier en ajout uniquement : ne jamais modifier ni
   supprimer une ligne existante) avec le module `csv` de Python pour gérer guillemets et virgules :
   `ajoutee_le` = maintenant au format ISO **avec fuseau** (`datetime.now().astimezone().isoformat(timespec="seconds")`),
   `texte`, `url` (vide si aucun). Pour remplacer une note en attente, on ajoute la nouvelle et on prévient que
   les deux partiront ; il n'y a pas de suppression.

6. Vérifier : `git diff --numstat data/notes_romain.csv` doit montrer 0 ligne supprimée.

7. Commit `Note Romain AAAA-MM-JJ HHh` (heure Europe/Paris) avec uniquement `data/notes_romain.csv`, puis
   `git push origin main` (en cas de rejet : `git pull --rebase origin main` puis nouveau push).

8. Répondre : le texte et le lien enregistrés, et rappeler qu'ils partiront avec le prochain mail à Romain
   (envoyé seulement si un prix suivi bouge), après quoi la boîte sera vide.

Ne pas envoyer de mail depuis /note : l'envoi reste fait par la tâche planifiée du relevé.
