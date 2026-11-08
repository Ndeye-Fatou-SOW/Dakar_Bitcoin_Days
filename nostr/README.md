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

## À décider avec Fatou

Le moteur ne publie encore rien sur Nostr. Il reste à choisir comment le prévenir de publier une preuve après chaque paiement et chaque versement.
