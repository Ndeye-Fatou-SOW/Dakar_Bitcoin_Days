# Interface et temps réel – Malick Fall

Ce dossier contient les écrans, la mise à jour en temps réel des statuts, les rappels et le déploiement.

## À faire

- [ ] Choisir React ou Flutter avec l'équipe
- [ ] Écrans : créer une tontine, rejoindre, ordre de passage, payer par QR code, suivi des membres
- [ ] Mise à jour en temps réel des statuts (notifications Lightning et WebSocket)
- [ ] Rappels avant la date limite et affichage des amendes
- [ ] Reprise après une panne, déploiement et démo en direct

## Utiliser l'API

Pour lancer le backend, suis le README à la racine du dépôt. La documentation complète s'ouvre ensuite sur http://127.0.0.1:8000/docs

| Action | Requête |
|---|---|
| Créer une tontine | `POST /tontines` |
| Voir une tontine et sa situation | `GET /tontines/{id}` |
| Rejoindre avec le lien d'invitation | `POST /rejoindre/{code}` |
| Tirer l'ordre de passage au sort | `POST /tontines/{id}/tirage` |
| Choisir l'ordre à la main | `POST /tontines/{id}/ordre` |
| Démarrer | `POST /tontines/{id}/demarrer` |
| Obtenir la facture à afficher en QR code | `POST /tontines/{id}/membres/{membre_id}/facture` |
| Exclure un membre en retard | `POST /tontines/{id}/membres/{membre_id}/exclure` |
| Relancer un versement en échec | `POST /tontines/{id}/versement/relancer` |

## Bon à savoir

- `POST /tontines` renvoie un `jeton_organisateur`. Garde-le uniquement sur l'appareil de l'organisateur : il est demandé pour le tirage, l'ordre, le démarrage, l'exclusion et la relance.
- Le QR code se fabrique à partir du champ `payment_request` de la facture.
- `GET /tontines/{id}` renvoie un champ `situation` avec, pour chaque membre : `nom`, `statut`, `en_defaut` et `montant_du_fcfa`. C'est ce qu'il faut afficher dans la liste.

## À décider avec Fatou

La détection des retards et le calcul des amendes sont déjà dans le moteur. Il reste à se mettre d'accord sur le partage : par exemple, les rappels et l'affichage de ton côté.
