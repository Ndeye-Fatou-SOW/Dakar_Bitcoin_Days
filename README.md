# Tontine Lightning – Dakar Bitcoin Days

Application de tontine payée en Bitcoin Lightning, avec une preuve de chaque paiement publiée sur Nostr.
Projet pour le Hackathon #4 des Dakar Bitcoin Days (dépôt avant le 20 novembre 2026).

## Qui fait quoi

| Dossier | Responsable | Contenu |
|---|---|---|
| `backend/` | Ndèye Fatou Sow | Logique de la tontine, conversion FCFA → sats, API Python |
| `lightning/` | Alassane Ndour | Nœud / LNbits, réception des paiements et versements |
| `frontend/` | Malick Fall | Écrans, temps réel, rappels et amendes, déploiement |
| `nostr/` | Abdoulaye Diouf | Registre Nostr, historique, tests, vidéo de démo |

## Règles pour travailler à 4 sur `main`

1. **Chacun travaille dans son propre dossier.** Si tu dois modifier le dossier d'un autre, préviens-le d'abord.
2. **Avant de commencer et avant chaque envoi, fais `git pull`.**
3. **Envoie souvent de petits morceaux**, et seulement du code qui fonctionne :

```
git pull
git add .
git commit -m "ce que j'ai fait"
git push
```

## Lancer le backend

```
cd backend
python -m pip install -r requirements.txt
python -m pytest
python -m uvicorn app.main:app --reload
```

La documentation de l'API s'ouvre ensuite sur http://127.0.0.1:8000/docs

Par défaut, le backend utilise un faux Lightning : pas besoin de Docker pour travailler sur le reste.

## Lancer le backend avec le vrai Lightning

Il faut d'abord démarrer le réseau de test (voir [lightning/README.md](lightning/README.md)), puis, sous Windows PowerShell :

```
cd backend
python -m pip install -r requirements-lightning.txt
$env:LIGHTNING_MODE="lnbits"; $env:LIGHTNING_ENV_FILE="..\lightning\.env"
python -m uvicorn app.main:app --reload
```

Dans ce mode, le backend refuse de démarrer sans `PONT_JETON_BACKEND`, que le fichier `lightning/.env` fournit.
