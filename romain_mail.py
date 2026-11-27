#!/usr/bin/env python3
"""Mail de suivi pour Romain : ARRÊTÉ le 27/11/2026, Romain a tout acheté.

Le script ne prépare plus aucun mail : il affiche toujours « RIEN », pour que la routine planifiée
(qui lance encore `python3 romain_mail.py`) ne plante pas avant la mise à jour de son prompt.
L'historique des mails envoyés reste dans data/mails_romain.csv (non modifié).
"""
import sys

if "--enregistrer" in sys.argv:
    print("RIEN à enregistrer (mail Romain arrêté le 27/11/2026)")
else:
    print("RIEN (mail Romain arrêté le 27/11/2026 : Romain a tout acheté)")
