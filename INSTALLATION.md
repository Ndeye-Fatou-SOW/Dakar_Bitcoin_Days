# Tontine Lightning : guide d'installation

Tontine Lightning est une application de tontine payée en Bitcoin Lightning. Chaque paiement est vérifié auprès du nœud Lightning, et une preuve signée et anonyme est publiée sur Nostr.

Ce guide propose trois façons de lancer le projet, de la plus simple à la plus complète :

| Option | Ce qu'on voit | Il faut | Durée |
|---|---|---|---|
| **A. Essai rapide** | L'API, avec un faux Lightning | Python | 5 min |
| **B. Démo complète** | Un tour complet payé en vrai Lightning, sur un réseau de test local | Python et Docker | 15 min |
| **C. Registre Nostr** | Les preuves publiées sur de vrais relais Nostr | Option A ou B, et Internet | 5 min de plus |

## Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `backend/` | Moteur de la tontine et API (Python, FastAPI, SQLite) |
| `lightning/` | Couche Lightning : adaptateur LNbits, pont de vérification des paiements, réseau de test Docker |
| `nostr/` | Registre Nostr : preuves signées et anonymes, publication sur plusieurs relais |
| `frontend/` | Interface de l'application |

## Prérequis

- **Git**, pour récupérer le code.
- **Python 3.10 ou plus récent.** Le projet a été testé avec Python 3.14.
- **Docker Desktop**, démarré, pour l'option B seulement.
- **Une connexion Internet** : le cours du bitcoin est demandé à CoinGecko, et l'option C publie sur des relais Nostr.

Les commandes sont écrites pour **Windows PowerShell**. Les différences pour macOS et Linux sont indiquées.

```powershell
git clone https://github.com/Ndeye-Fatou-SOW/Dakar_Bitcoin_Days.git
cd Dakar_Bitcoin_Days
python -m venv .venv
.venv\Scripts\activate
```

Sous macOS ou Linux : `source .venv/bin/activate`. Si PowerShell refuse d'activer l'environnement, lancer d'abord `Set-ExecutionPolicy -Scope Process Bypass`.

## Option A : essai rapide, sans Docker

Le backend utilise ici un **faux service Lightning** : aucun argent ne circule, même de test.

```powershell
cd backend
python -m pip install -r requirements.txt
python -m pytest
python -m uvicorn app.main:app --reload
```

Les tests doivent tous réussir. Ouvrir ensuite **http://127.0.0.1:8000/docs** : chaque requête de l'API peut y être essayée directement.

**Parcours conseillé dans la page `/docs` :**

1. `POST /tontines` : créer une tontine de 2 membres. Noter `jeton_organisateur`, `jeton_membre` et le code à la fin de `lien_invitation`.
2. `POST /rejoindre/{code}` : inscrire un deuxième membre, avec une adresse Lightning de la forme `nom@domaine`.
3. `POST /tontines/{id}/tirage`, puis `POST /tontines/{id}/demarrer`, avec le `jeton_organisateur`.
4. `GET /tontines/{id}`, avec l'en-tête `X-Jeton` : voir la tontine, l'ordre de passage et le champ `situation` (qui a payé).
5. `POST /tontines/{id}/membres/{membre_id}/facture` : obtenir la facture du membre. Le champ `payment_request` est ce qui s'affiche en QR code.

Avec le faux Lightning, les factures ne peuvent pas être payées depuis un portefeuille. Le paiement et le versement de la cagnotte sont vérifiés par les tests automatiques, et en vrai dans l'option B.

## Option B : démo complète en Lightning

Cette option lance un **vrai réseau Bitcoin et Lightning local** (regtest) dans Docker : bitcoind, deux nœuds LND, LNbits et le pont. Les sats y sont de test et n'ont pas de valeur. Docker Desktop doit être démarré.

**1. Démarrer le réseau Lightning (terminal 1)**

```powershell
cd lightning
python -m pip install -e ".[dev]"
python scripts\regtest.py init
python scripts\regtest.py verifier
```

`init` crée les conteneurs, mine les blocs, ouvre les canaux, crée le portefeuille LNbits et écrit le fichier `lightning\.env`. Il peut être relancé sans risque. `verifier` fait une vraie cotisation et un vrai versement pour contrôler que tout fonctionne.

**2. Lancer le backend en mode Lightning (terminal 2)**

```powershell
cd backend
python -m pip install -r requirements-lightning.txt
$env:LIGHTNING_MODE="lnbits"
$env:LIGHTNING_ENV_FILE="..\lightning\.env"
python -m uvicorn app.main:app
```

Sous macOS ou Linux, remplacer les lignes `$env:` par `export LIGHTNING_MODE=lnbits` et `export LIGHTNING_ENV_FILE=../lightning/.env`. Sous Linux, ajouter `--host 0.0.0.0` à la dernière commande, pour que le pont, dans Docker, puisse joindre le backend.

**3. Jouer un tour complet (terminal 3)**

```powershell
cd lightning
python scripts\demo_tour.py
```

Le script crée une tontine de 3 membres, tire l'ordre de passage, paie les 3 cotisations en Lightning, puis attend que le pont les confirme et que le backend verse la cagnotte. Résultat attendu, à la fin :

```
Tour complet réussi : création, inscriptions, tirage, 3 paiements Lightning, confirmation par le pont, versement.
```

| Commande (dans `lightning/`) | Usage |
|---|---|
| `python scripts\regtest.py payer <facture>` | Un membre paie une facture affichée en QR code |
| `python scripts\regtest.py soldes` | Soldes des canaux et du portefeuille |
| `docker compose logs -f pont` | Suivre les paiements confirmés au backend |
| `docker compose down -v` | Tout effacer et repartir de zéro |

## Option C : activer le registre Nostr

> **Attention :** ce qui est publié sur des relais Nostr publics ne peut pas être retiré. Les preuves ne contiennent ni nom ni numéro de téléphone, mais il vaut mieux utiliser une tontine de test.

```powershell
cd nostr
python generer_secrets.py
cd ..\backend
python -m pip install -r requirements-nostr.txt
$env:NOSTR_MODE="actif"
python -m uvicorn app.main:app
```

`generer_secrets.py` crée l'identité du registre dans `nostr\.env`. Ce fichier contient une clé privée : il ne doit jamais être partagé ni envoyé sur GitHub. Il n'est pas écrasé s'il existe déjà. Pour combiner avec l'option B, garder aussi les lignes `$env:LIGHTNING_...` avant de lancer le backend.

**Vérifier les preuves :**

- `GET /registre` donne la clé publique du service, la liste des relais et le type de message (kind 7860).
- `GET /tontines/{id}` donne `identifiant_registre`. Toutes les preuves de la tontine portent l'étiquette `tl-<identifiant_registre>`.
- Chaque preuve est signée : toute modification se voit. Pour une cotisation, le membre qui a payé retrouve sa preuve grâce à l'empreinte du paiement (`payment_hash`) de sa facture.

## Lancer tous les tests

| Partie | Commandes | Résultat attendu |
|---|---|---|
| Backend | `cd backend` puis `python -m pytest` | 32 tests réussis |
| Registre Nostr | `python -m pip install -r nostr\requirements.txt`, `cd nostr` puis `python -m pytest` | 23 tests réussis |
| Lightning | `cd lightning` puis `python -m pytest` | 74 tests réussis, dont des tests sur le vrai backend |

Ces tests n'ont besoin ni de Docker ni d'Internet : Lightning et Nostr y sont simulés.

## Utiliser l'API

- `POST /tontines` renvoie un `jeton_organisateur` et un `jeton_membre`. `POST /rejoindre/{code}` renvoie le `jeton_membre` du nouveau membre.
- Les actions de l'organisateur (tirage, ordre, démarrage, exclusion, relance d'un versement) demandent le `jeton_organisateur` dans le corps de la requête.
- La lecture d'une tontine, de son journal et des factures demande l'en-tête `X-Jeton`, avec le jeton d'un membre ou de l'organisateur. Sans lui, l'API répond 403.
- Un membre ne peut demander que sa propre facture. Il peut corriger son adresse Lightning avec `PUT /tontines/{id}/membres/{membre_id}/adresse`.
- Seul le pont Lightning peut confirmer un paiement (`POST /paiements/confirmation`, avec l'en-tête `X-Jeton-Pont`).

## En cas de problème

| Message ou symptôme | Solution |
|---|---|
| `PONT_JETON_BACKEND manque` au démarrage | Lancer d'abord `python scripts\regtest.py init`, et vérifier le chemin de `LIGHTNING_ENV_FILE` |
| Réponse 403 de l'API | Ajouter l'en-tête `X-Jeton` avec un jeton de cette tontine |
| Réponse 503 « Cours du bitcoin indisponible » | Vérifier la connexion Internet, puis réessayer |
| `demo_tour.py` : « Backend injoignable » | Lancer le backend en mode Lightning (option B, étape 2) |
| Erreurs Docker pendant `init` | Vérifier que Docker Desktop est démarré, puis relancer `init` |
| Le port 8000 est déjà utilisé | Fermer le programme qui l'utilise : le pont Lightning appelle le backend sur le port 8000. Pour l'option A seule, on peut ajouter `--port 8001` à uvicorn |

## Limites connues

- Les paiements ont été testés sur un **réseau de test local**, pas avec de vrais sats.
- Dans cette version, le service **garde la cagnotte** jusqu'au versement. Le paiement direct au bénéficiaire est la prochaine étape.
- La valeur des sats peut **baisser** pendant que la cagnotte attend le dernier paiement. Les factures sont recalculées au cours du moment quand elles expirent.
