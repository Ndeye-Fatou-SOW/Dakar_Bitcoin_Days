# Registre Nostr, suivi et tests – Abdoulaye Diouf

Ce dossier contient le registre sur Nostr et l'historique des tours. Tu t'occupes aussi des entretiens, des tests avec un vrai groupe et de la vidéo de démo.

## À faire

- [ ] Choisir la bibliothèque Nostr
- [ ] Publier une preuve signée de chaque paiement et de chaque versement, sur plusieurs relais
- [ ] Afficher l'historique des tours : bénéficiaires et montants
- [ ] Interroger 3 à 5 personnes qui gèrent déjà une tontine, et leur demander si elles accepteraient d'utiliser Bitcoin
- [ ] Tester avec un vrai groupe
- [ ] Tourner la vidéo de démo

## Les données disponibles

`GET /tontines/{id}` renvoie les tours, avec pour chacun :

| Donnée | Champ |
|---|---|
| Preuve d'une cotisation | `cotisations[...].payment_hash` et `cotisations[...].preimage` |
| Montant de la cotisation | `cotisations[...].montant_sats` |
| Preuve du versement | `versement_preimage` |
| Montant du versement | `versement_sats` |
| Graine du tirage au sort, pour le vérifier | `graine_tirage` (au niveau de la tontine) |

## Règle de confidentialité

Le registre public ne doit contenir **ni nom ni numéro de téléphone**. Pour identifier un membre, utilise la fonction `empreinte_anonyme(membre_id, sel)` de `backend/app/tontine.py`. Le `sel` doit rester secret : il ne doit jamais être envoyé sur le dépôt.

## Activer la publication

La publication est désactivée par défaut, car ce qui part sur des relais publics ne se retire pas. Pour l'activer, sous Windows PowerShell :

```
cd nostr
python generer_secrets.py
cd ..\backend
python -m pip install -r requirements-nostr.txt
$env:NOSTR_MODE="actif"
python -m uvicorn app.main:app --reload
```

`registre_nostr/publieur.py` publie alors automatiquement chaque cotisation et chaque versement, dans l'ordre. Si les relais sont injoignables, il réessaie, et il reprend au bon endroit après un redémarrage.

Les retards ne sont pas publiés tant que l'équipe n'a pas décidé. Pour les publier : `$env:NOSTR_PUBLIER_RETARDS="oui"`.

## Retrouver une preuve

- `GET /registre` donne la clé publique du service, les relais et le kind.
- `GET /tontines/{id}` donne `identifiant_registre`. Les preuves de la tontine portent l'étiquette `tl-<identifiant_registre>`.
