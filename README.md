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

## Brancher Lightning (pour Alassane)

Le moteur passe par l'interface `Lightning` de [backend/app/lightning.py](backend/app/lightning.py), qui contient deux méthodes :

- `creer_facture(montant_sats, description)` renvoie la facture BOLT11 et son `payment_hash`.
- `payer(adresse_lightning, montant_sats, description)` renvoie la preimage du versement.

Quand LNbits reçoit un paiement, il doit appeler `POST /paiements/confirmation` avec le `payment_hash` et la `preimage`.
Pour l'instant, le backend utilise un faux service (`LightningFactice`) : il suffit de le remplacer dans `backend/app/main.py`.
