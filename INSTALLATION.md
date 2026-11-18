# Tontine Lightning : guide d'installation

Tontine Lightning est une application de tontine payée en Bitcoin Lightning. Chaque paiement est vérifié auprès du nœud Lightning, et une preuve signée et anonyme est publiée sur Nostr.

Ce guide propose trois façons de lancer le projet :

| Option | Ce qu'on voit | Il faut | Durée |
|---|---|---|---|
| **A. Démo complète** (recommandée) | L'application entière dans Docker : écrans, API et vrais paiements Lightning sur un réseau de test local | Docker et Python | 15 min la première fois |
| **B. Essai rapide sans Docker** | Les écrans et l'API, avec un faux Lightning | Python et Node.js | 5 min |
| **C. Registre Nostr** | Les preuves publiées sur de vrais relais Nostr | Option A ou B, et Internet | 5 min de plus |

## Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `backend/` | Moteur de la tontine et API (Python, FastAPI, SQLite ou PostgreSQL) |
| `frontend/` | Interface web pour téléphone (React, TypeScript, Vite) |
| `lightning/` | Couche Lightning : adaptateur LNbits, pont de vérification des paiements, réseau de test et application complète dans Docker |
| `nostr/` | Registre Nostr : preuves signées et anonymes, publication sur plusieurs relais |

## Prérequis

- **Git**, pour récupérer le code.
- **Python 3.10 ou plus récent.** Le projet a été testé avec Python 3.14.
- **Docker Desktop**, démarré, pour l'option A.
- **Node.js 22**, pour l'option B seulement (l'interface).
- **Une connexion Internet** : le cours du bitcoin est demandé à CoinGecko, et l'option C publie sur des relais Nostr.

Les commandes sont écrites pour **Windows PowerShell**. Les différences pour macOS et Linux sont indiquées.

```powershell
git clone https://github.com/Ndeye-Fatou-SOW/Dakar_Bitcoin_Days.git
cd Dakar_Bitcoin_Days
```

## Option A : démo complète dans Docker (recommandée)

Une seule commande lance un **vrai réseau Bitcoin et Lightning local** (regtest) et toute l'application : bitcoind, deux nœuds LND, LNbits, le pont, l'API et l'interface. Les sats y sont de test et n'ont pas de valeur. Docker Desktop doit être démarré.

```powershell
cd lightning
python scripts\regtest.py init
```

La première fois, Docker télécharge et construit les images : comptez une dizaine de minutes. La commande peut être relancée sans risque. Ensuite :

| Quoi | Adresse |
|---|---|
| **Interface de l'application** | http://127.0.0.1:5173 |
| Documentation de l'API | http://127.0.0.1:8000/docs |
| LNbits | http://127.0.0.1:5000 |

### Jouer un tour complet

**Avec le script** (depuis `lightning/`) :

```powershell
python scripts\demo_tour.py
```

Il crée une tontine de 3 membres, tire l'ordre de passage, paie les 3 cotisations en Lightning, puis attend que le pont les confirme et que le backend verse la cagnotte. Résultat attendu, à la fin :

```
Tour complet réussi : création, inscriptions, tirage, 3 paiements Lightning, confirmation par le pont, versement.
```

**Avec l'interface :** créer une tontine sur http://127.0.0.1:5173, partager le lien d'invitation, tirer l'ordre au sort, démarrer, puis afficher la facture d'un membre en QR code. Pour simuler le paiement par un membre, copier la facture et lancer depuis `lightning/` :

```powershell
python scripts\regtest.py payer <facture>
```

En regtest, utiliser des adresses Lightning de la forme **`nom@regtest.local`** : elles sont servies par le pont et reçoivent vraiment la cagnotte.

### Commandes utiles (dans `lightning/`)

| Commande | Usage |
|---|---|
| `docker compose --profile pont --profile app up -d` | Redémarrer l'application, les fois suivantes |
| `docker compose --profile pont --profile app stop` | Arrêter sans effacer les données |
| `python scripts\regtest.py soldes` | Soldes des canaux et du portefeuille |
| `docker compose logs -f pont` | Suivre les paiements confirmés au backend |
| `docker compose down -v` | Tout effacer et repartir de zéro |

## Option B : essai rapide sans Docker

Le backend utilise ici un **faux service Lightning** : aucun argent ne circule, même de test. Les factures s'affichent mais ne peuvent pas être payées. Le paiement réel se voit dans l'option A.

**Terminal 1, le backend :**

```powershell
python -m venv .venv
.venv\Scripts\activate
cd backend
python -m pip install -r requirements.txt
python -m pytest
python -m uvicorn app.main:app --reload
```

Sous macOS ou Linux : `source .venv/bin/activate`. Si PowerShell refuse d'activer l'environnement, lancer d'abord `Set-ExecutionPolicy -Scope Process Bypass`.

**Terminal 2, l'interface :**

```powershell
cd frontend
npm install
npm run dev
```

Ouvrir l'adresse affichée par Vite (en général http://localhost:5173). L'interface appelle l'API sur `http://127.0.0.1:8000`. Pour une autre adresse, créer `frontend\.env` avec `VITE_API_URL=<adresse de l'API>`.

La documentation de l'API est sur **http://127.0.0.1:8000/docs** : chaque requête peut y être essayée directement.

## Option C : activer le registre Nostr

> **Attention :** ce qui est publié sur des relais Nostr publics ne peut pas être retiré. Les preuves ne contiennent ni nom ni numéro de téléphone, mais il vaut mieux utiliser une tontine de test.

**1. Créer l'identité du registre** (une seule fois, depuis la racine du dépôt) :

```powershell
python -m pip install -r nostr\requirements.txt
python nostr\generer_secrets.py
```

`generer_secrets.py` crée l'identité du registre dans `nostr\.env`. Ce fichier contient une clé privée : il ne doit jamais être partagé ni envoyé sur GitHub. Il n'est pas écrasé s'il existe déjà.

**2a. Avec Docker (option A) :** ajouter la ligne `NOSTR_MODE=actif` dans `lightning\.env`, puis, depuis `lightning/` :

```powershell
docker compose --profile pont --profile app up -d
```

Le backend lit `nostr\.env` sans le copier dans l'image.

**2b. Sans Docker (option B) :**

```powershell
cd backend
python -m pip install -r requirements-nostr.txt
$env:NOSTR_MODE="actif"
python -m uvicorn app.main:app
```

Pour vérifier que c'est actif : http://127.0.0.1:8000/registre doit répondre `"actif": true`.

**Vérifier les preuves :**

- Dans l'interface, « Consulter les preuves » cherche les preuves de la tontine sur les relais et vérifie leur signature et leur empreinte.
- `GET /registre` donne la clé publique du service, la liste des relais et le type de message (kind 7860).
- `GET /tontines/{id}` donne `identifiant_registre`. Toutes les preuves de la tontine portent l'étiquette `tl-<identifiant_registre>`.

## Mettre le backend en ligne sur Render (démo sans paiement réel)

Render ne peut pas faire tourner le réseau Lightning de test (plusieurs conteneurs Docker). En ligne, le backend utilise donc le **faux Lightning** : les écrans fonctionnent, mais les factures ne peuvent pas être payées. Il faut l'indiquer sur la page de démo.

1. Sur Render, créer une base **PostgreSQL**, puis copier son adresse interne (*Internal Database URL*).
2. Créer un **Web Service** relié au dépôt GitHub, avec :

| Réglage | Valeur |
|---|---|
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Variable d'environnement | `DATABASE_URL` = l'adresse copiée à l'étape 1 |

Avec `DATABASE_URL`, les tontines sont enregistrées dans PostgreSQL et ne sont plus effacées au redémarrage. Sans cette variable, le backend utilise un fichier SQLite. L'interface doit ensuite être construite avec `VITE_API_URL` égal à l'adresse du service Render.

## Lancer tous les tests

| Partie | Commandes | Résultat attendu |
|---|---|---|
| Backend | `cd backend` puis `python -m pytest` | 34 tests réussis, 3 ignorés (ceux de PostgreSQL, voir `backend/tests/test_stockage.py` pour les lancer) |
| Registre Nostr | `python -m pip install -r nostr\requirements.txt`, `cd nostr` puis `python -m pytest` | 23 tests réussis |
| Lightning | `cd lightning`, `python -m pip install -e ".[dev]"` puis `python -m pytest` | 74 tests réussis, dont des tests sur le vrai backend |
| Interface | `cd frontend`, `npm install` puis `npm run build` | Construction sans erreur |

Les tests Python n'ont besoin ni de Docker ni d'Internet : Lightning et Nostr y sont simulés.

## Utiliser l'API

- `POST /tontines` renvoie un `jeton_organisateur` et un `jeton_membre`. `POST /rejoindre/{code}` renvoie le `jeton_membre` du nouveau membre.
- Les actions de l'organisateur (tirage, ordre, démarrage, exclusion, relance d'un versement) demandent le `jeton_organisateur` dans le corps de la requête.
- La lecture d'une tontine, de son journal et des factures demande l'en-tête `X-Jeton`, avec le jeton d'un membre ou de l'organisateur. Sans lui, l'API répond 403.
- Un membre ne peut demander que sa propre facture. Il peut corriger son adresse Lightning avec `PUT /tontines/{id}/membres/{membre_id}/adresse`.
- Seul le pont Lightning peut confirmer un paiement (`POST /paiements/confirmation`, avec l'en-tête `X-Jeton-Pont`).

## En cas de problème

| Message ou symptôme | Solution |
|---|---|
| Erreurs Docker pendant `init` | Vérifier que Docker Desktop est démarré, puis relancer `init` |
| Le port 8000, 5000 ou 5173 est déjà utilisé | Fermer le programme qui l'utilise, ou changer `BACKEND_PORT`, `LNBITS_PORT` ou `FRONTEND_PORT` dans `lightning\.env` |
| Réponse 403 de l'API | Ajouter l'en-tête `X-Jeton` avec un jeton de cette tontine |
| Réponse 503 « Cours du bitcoin indisponible » | Vérifier la connexion Internet, puis réessayer |
| `demo_tour.py` : « Backend injoignable » | Lancer d'abord `python scripts\regtest.py init` (option A) |
| Après un redémarrage de Docker ou du PC : 503 « Service Lightning indisponible » | Depuis `lightning/` : `python scripts\regtest.py init`, puis `python scripts\regtest.py miner 1`. Si `init` s'arrête sur « canaux actifs », reconnecter les deux nœuds : `docker compose exec lnd-tontine lncli --network=regtest connect <clé du nœud membres>@lnd-membres:9735` (la clé est l'`identity_pubkey` de `docker compose exec lnd-membres lncli --network=regtest getinfo`) |
| Après un redémarrage de Docker : 503 « Cours du bitcoin indisponible » alors qu'Internet marche | `docker compose restart backend` dans `lightning/` |
| Interface : « Le registre Nostr n'est pas activé » | Suivre l'option C |
| Les données d'une ancienne démo gênent | `docker compose down -v` dans `lightning/`, puis relancer `init` |

## Limites connues

- Les paiements ont été testés sur un **réseau de test local**, pas avec de vrais sats.
- Dans cette version, le service **garde la cagnotte** jusqu'au versement. Le paiement direct au bénéficiaire est la prochaine étape.
- La valeur des sats peut **baisser** pendant que la cagnotte attend le dernier paiement. Les factures sont recalculées au cours du moment quand elles expirent.
