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
| Corriger son adresse Lightning | `PUT /tontines/{id}/membres/{membre_id}/adresse` |
| Journal des événements | `GET /tontines/{id}/evenements?depuis=<numero>` |
| Infos du registre Nostr | `GET /registre` |

## Bon à savoir

- `POST /tontines` renvoie un `jeton_organisateur`. Garde-le uniquement sur l'appareil de l'organisateur : il est demandé pour le tirage, l'ordre, le démarrage, l'exclusion et la relance.
- `POST /tontines` et `POST /rejoindre/{code}` renvoient aussi un `jeton_membre`, propre à chaque membre. Garde-le sur son appareil.
- **Lecture réservée aux membres** : `GET /tontines/{id}`, `GET /tontines/{id}/evenements` et la demande de facture exigent l'en-tête `X-Jeton` avec le `jeton_membre` (ou le `jeton_organisateur`). Sans lui, l'API répond 403. Un membre ne peut demander que sa propre facture ; l'organisateur peut demander celle de n'importe quel membre.
- Les factures expirent (1 heure prévue). Redemander la facture renvoie la même tant qu'elle est valable, puis une nouvelle au cours du moment : affiche toujours le dernier `payment_request` reçu.
- Le QR code se fabrique à partir du champ `payment_request` de la facture.
- `GET /tontines/{id}` renvoie un champ `situation` avec, pour chaque membre : `nom`, `statut`, `en_defaut` et `montant_du_fcfa`. C'est ce qu'il faut afficher dans la liste.

## Temps réel

Dans `backend/app/main.py`, `moteur.abonner(ta_fonction)` appelle ta fonction à chaque événement : c'est là que tu peux envoyer le message WebSocket. La fonction tourne dans un fil séparé, hors de la boucle `asyncio` de FastAPI.

Types d'événements : `membre_inscrit`, `ordre_fixe`, `nouveau_tour`, `membre_en_defaut`, `cotisation_payee`, `membre_exclu`, `versement_fait`, `versement_echec`, `tontine_terminee`.

Après une coupure, l'écran récupère ce qu'il a manqué avec `GET /tontines/{id}/evenements?depuis=<dernier numero reçu>`.

## À décider avec Fatou

La détection des retards et le calcul des amendes sont déjà dans le moteur. Il reste à se mettre d'accord sur le partage : par exemple, les rappels et l'affichage de ton côté.
