# Interface web responsive – Malick Fall

Application web React + TypeScript, conçue d’abord pour les téléphones. Elle se connecte à l’API FastAPI du dossier `backend/`.

## Lancer l’application

Depuis ce dossier :

```powershell
npm install
npm run dev
```

Le serveur Vite affiche l’adresse locale dans le terminal. Lance aussi le backend FastAPI sur `http://127.0.0.1:8000` en suivant le README à la racine du dépôt.

Pour pointer vers une autre API, définis `VITE_API_URL` dans un fichier `.env` local :

```env
VITE_API_URL=http://127.0.0.1:8000
```

Vérification de production :

```powershell
npm run build
```

## Parcours actuellement disponibles

- Créer une tontine et enregistrer l’organisateur sur cet appareil.
- Partager un lien d’invitation, ou rejoindre avec un code.
- Suivre les membres et l’état des cotisations.
- Tirer l’ordre au sort et démarrer un tour (organisateur).
- Demander et afficher la facture Lightning du membre courant sous forme de QR code.
- Actualiser l’état depuis l’API toutes les cinq secondes.

Les jetons organisateur et membre restent dans le stockage local du navigateur. Ne partage pas cet appareil ni ses données de navigateur avec d’autres personnes.

## Intégration de l’API

| Action | Requête |
|---|---|
| Créer une tontine | `POST /tontines` |
| Voir une tontine et sa situation | `GET /tontines/{id}` |
| Rejoindre avec le lien d’invitation | `POST /rejoindre/{code}` |
| Tirer l’ordre de passage au sort | `POST /tontines/{id}/tirage` |
| Démarrer | `POST /tontines/{id}/demarrer` |
| Obtenir la facture à afficher en QR code | `POST /tontines/{id}/membres/{membre_id}/facture` |
<<<<<<< HEAD
=======
| Exclure un membre en retard | `POST /tontines/{id}/membres/{membre_id}/exclure` |
| Relancer un versement en échec | `POST /tontines/{id}/versement/relancer` |
| Corriger son adresse Lightning | `PUT /tontines/{id}/membres/{membre_id}/adresse` |
| Journal des événements | `GET /tontines/{id}/evenements?depuis=<numero>` |
| Infos du registre Nostr | `GET /registre` |
>>>>>>> 7fb66d9245f00d3276775fc431efacd04ca7e509

## Limites du MVP

<<<<<<< HEAD
- L’actualisation utilise le polling; le WebSocket et les rappels automatiques restent à intégrer.
- Le registre Nostr se consulte à la demande : le front interroge les relais configurés, vérifie les signatures du service et la cohérence SHA-256 des préimages publiées.
- Une signature Nostr prouve l’origine du message, pas à elle seule qu’un paiement Lightning a eu lieu. Les événements et préimages relayés sont publics.
- Le QR code est généré localement dans le navigateur à partir de la facture Lightning.
- Le parcours de paiement doit être testé avec un backend et un nœud Lightning adaptés au réseau choisi pour la démo.
=======
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
>>>>>>> 7fb66d9245f00d3276775fc431efacd04ca7e509
