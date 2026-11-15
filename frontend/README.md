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

Le jeton organisateur reste dans le stockage local du navigateur qui a créé la tontine. Ne partage pas cet appareil ni ses données de navigateur avec d’autres personnes.

## Intégration de l’API

| Action | Requête |
|---|---|
| Créer une tontine | `POST /tontines` |
| Voir une tontine et sa situation | `GET /tontines/{id}` |
| Rejoindre avec le lien d’invitation | `POST /rejoindre/{code}` |
| Tirer l’ordre de passage au sort | `POST /tontines/{id}/tirage` |
| Démarrer | `POST /tontines/{id}/demarrer` |
| Obtenir la facture à afficher en QR code | `POST /tontines/{id}/membres/{membre_id}/facture` |

## Limites du MVP

- L’actualisation utilise le polling; le WebSocket et les rappels automatiques restent à intégrer.
- Le registre Nostr et l’historique détaillé ne sont pas encore connectés à l’interface.
- Le QR code est généré localement dans le navigateur à partir de la facture Lightning.
- Le parcours de paiement doit être testé avec un backend et un nœud Lightning adaptés au réseau choisi pour la démo.
