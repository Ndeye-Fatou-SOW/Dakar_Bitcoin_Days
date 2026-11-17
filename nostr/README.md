# Registre Nostr, suivi et tests – Abdoulaye Diouf

Ce dossier contient le registre public Nostr. Le backend publie les événements signés et le front peut les retrouver sur les relais et vérifier localement la signature et la cohérence hash/préimage.

## Fonctionnalités disponibles

- Événements Nostr kind `7860`, signés par la clé du service et publiés sur plusieurs relais.
- Anonymisation de l’identifiant du groupe et des membres ; aucun nom ni numéro de téléphone dans les événements.
- Curseur persistant et reprise de publication après panne.
- Le front interroge les relais à la demande, vérifie la signature avec la clé publique du service, puis vérifie `SHA-256(preimage) == payment_hash` pour les paiements et versements.

Les éléments qui restent hors du MVP :
- [ ] Interroger 3 à 5 personnes qui gèrent déjà une tontine, et leur demander si elles accepteraient d'utiliser Bitcoin
- [ ] Tester avec un vrai groupe
- [ ] Tourner la vidéo de démo

> Les événements Nostr sont publics et difficiles à retirer. Ils incluent la préimage ; la signature atteste que le service a publié le contenu, mais ne prouve pas à elle seule qu’un paiement Lightning a été reçu. Le backend vérifie la réception avant de publier.

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
cd backend
python -m pip install -r requirements-nostr.txt
cd ..\nostr
python generer_secrets.py
cd ..\backend
$env:NOSTR_MODE="actif"
python -m uvicorn app.main:app --reload
```

`registre_nostr/publieur.py` publie alors automatiquement chaque cotisation et chaque versement, dans l'ordre. Si les relais sont injoignables, il réessaie, et il reprend au bon endroit après un redémarrage.

Les retards ne sont pas publiés tant que l'équipe n'a pas décidé. Pour les publier : `$env:NOSTR_PUBLIER_RETARDS="oui"`.

## Retrouver une preuve

- `GET /registre` donne la clé publique du service, les relais et le kind.
- `GET /tontines/{id}` donne `identifiant_registre`. Les preuves de la tontine portent l'étiquette `tl-<identifiant_registre>`.
- Dans le front, « Consulter les preuves » recherche cette étiquette sur les relais configurés et ignore les événements dont la signature ou le contenu ne correspond pas au groupe.
