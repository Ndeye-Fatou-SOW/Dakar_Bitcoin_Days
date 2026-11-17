# Tontine Lightning – Dakar Bitcoin Days

Application de tontine payée en Bitcoin Lightning, avec une preuve de chaque paiement publiée sur Nostr.
Projet pour le Hackathon #4 des Dakar Bitcoin Days (dépôt avant le 20 novembre 2026).

**Pour installer et essayer le projet, voir le [guide d'installation](INSTALLATION.md).**

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

## Lancer toute l'application avec Docker

Prérequis : Docker Desktop démarré. Depuis PowerShell, pour la première initialisation du regtest :

```powershell
cd lightning
python scripts\regtest.py init
```

Cette commande initialise le réseau Bitcoin/Lightning local puis construit et démarre LNbits, le pont, l'API et le front dans Docker. L'application est disponible sur :

- Front responsive : http://127.0.0.1:5173
- API : http://127.0.0.1:8000/docs
- LNbits : http://127.0.0.1:5000

Les données de la tontine, du portefeuille et du réseau sont conservées dans des volumes Docker. Pour les démarrages suivants, depuis `lightning` :

```powershell
docker compose --profile pont --profile app up -d
```

Pour arrêter les conteneurs sans effacer les données :

```powershell
docker compose --profile pont --profile app stop
```

Le mode Lightning fictif reste disponible pour le développement backend hors Docker. Pour les étapes de démo regtest et le paiement d'une facture, voir [lightning/README.md](lightning/README.md).
