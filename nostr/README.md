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

## Publier une preuve à chaque événement

Le moteur signale ce qui se passe. Pour recevoir ces signaux, branche ta fonction dans `backend/app/main.py` :

```python
moteur.abonner(publier_sur_nostr)   # appelée avec chaque événement
```

Pour le registre, les événements utiles sont `cotisation_payee` et `versement_fait`. Ils contiennent `preimage` et `montant_sats` dans `evenement.donnees`, et `cotisation_payee` contient aussi `payment_hash`.

Les événements contiennent le `membre_id`, qu'il faut passer dans `empreinte_anonyme` avant de publier.

Si Nostr est injoignable, le signal n'est pas renvoyé. Garde le dernier `numero` publié et récupère la suite avec `GET /tontines/{id}/evenements?depuis=<numero>`.
