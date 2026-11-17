"""Logique de la tontine : creation, inscription, ordre de passage, tours, retards, versement."""

import hashlib
import logging
import queue
import random
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

from .conversion import fcfa_vers_sats
from .lightning import Lightning, preimage_valide

try:
    from tontine_lightning import ErreurLightning, ErreurLNbits, VersementEnAttente
except ImportError:     # paquet d'Alassane absent : le faux service n'en a pas besoin
    class ErreurLightning(Exception): ...
    class ErreurLNbits(ErreurLightning): ...
    class VersementEnAttente(ErreurLightning): ...

SECONDES_PAR_JOUR = 86_400
MARGE_EXPIRATION_S = 60     # on attend un peu apres l'expiration avant de refaire une facture
journal = logging.getLogger(__name__)


def adresse_valide(adresse: str) -> bool:
    """Controle simple : une adresse Lightning a la forme nom@domaine, sans espace."""
    nom, arobase, domaine = adresse.strip().partition("@")
    return bool(arobase and nom and domaine and "@" not in domaine and not any(c.isspace() for c in adresse.strip()))


class ErreurTontine(Exception):
    """Action refusee par les regles de la tontine."""


class ErreurAcces(ErreurTontine):
    """La personne n'a pas le jeton qui lui donne acces a cette tontine."""


class Statut(str, Enum):
    INSCRIPTION = "inscription"
    EN_COURS = "en_cours"
    TERMINEE = "terminee"


class StatutCotisation(str, Enum):
    EN_ATTENTE = "en_attente"
    PAYE = "paye"


class StatutMembre(str, Enum):
    ACTIF = "actif"
    EXCLU = "exclu"


class StatutVersement(str, Enum):
    AUCUN = "aucun"
    EN_COURS = "en_cours"   # issue pas encore connue : on peut reprendre sans repayer
    FAIT = "fait"
    ECHEC = "echec"


@dataclass
class Membre:
    id: str
    nom: str
    adresse_lightning: str
    statut: StatutMembre = StatutMembre.ACTIF
    amendes_dues_fcfa: int = 0
    jeton: str = ""     # secret : donne uniquement au membre, jamais affiche aux autres


@dataclass
class Cotisation:
    membre_id: str
    statut: StatutCotisation = StatutCotisation.EN_ATTENTE
    en_retard: bool = False
    amende_fcfa: int = 0    # amende incluse dans la facture de cette cotisation
    montant_sats: int | None = None
    payment_request: str | None = None
    payment_hash: str | None = None
    preimage: str | None = None
    facture_creee_le: float | None = None
    # Factures expirees remplacees : un paiement fait juste avant l'expiration reste reconnu.
    anciennes_factures: list[str] = field(default_factory=list)


@dataclass
class Tour:
    numero: int
    beneficiaire_id: str
    date_limite: float
    cotisations: dict[str, Cotisation]
    versement_statut: StatutVersement = StatutVersement.AUCUN
    versement_sats: int | None = None
    versement_preimage: str | None = None

    @property
    def complet(self) -> bool:
        return all(c.statut == StatutCotisation.PAYE for c in self.cotisations.values())


@dataclass
class Evenement:
    """Ce qui vient de se passer. Jamais de nom ni d'adresse : seulement des identifiants."""
    tontine_id: str
    numero: int      # 1, 2, 3... dans chaque tontine, pour reprendre apres une coupure
    type: str
    date: float
    tour: int | None
    donnees: dict


@dataclass
class Tontine:
    id: str
    nom: str
    montant_fcfa: int
    frequence: str
    nombre_membres: int
    organisateur_id: str
    jeton_organisateur: str   # secret : donne uniquement a l'organisateur
    code_invitation: str
    delai_jours: int = 7
    amende_fcfa: int = 0
    membres: list[Membre] = field(default_factory=list)
    ordre: list[str] = field(default_factory=list)
    graine_tirage: str | None = None   # publiee pour que chacun puisse refaire le tirage
    tours: list[Tour] = field(default_factory=list)
    statut: Statut = Statut.INSCRIPTION
    evenements: list[Evenement] = field(default_factory=list)

    def membre(self, membre_id: str) -> Membre:
        for m in self.membres:
            if m.id == membre_id:
                return m
        raise ErreurTontine("Membre inconnu")

    @property
    def tour_actuel(self) -> Tour | None:
        return self.tours[-1] if self.tours else None


def tirer_ordre(membre_ids: list[str], graine: str) -> list[str]:
    """Tirage au sort reproductible : la meme graine donne toujours le meme ordre."""
    ordre = sorted(membre_ids)
    random.Random(graine).shuffle(ordre)
    return ordre


class Moteur:
    """Applique les regles et enregistre chaque changement."""

    def __init__(self, lightning: Lightning, source_cours, stockage=None, horloge=time.time,
                 validite_facture_s: float | None = None):
        self.lightning = lightning
        self.source_cours = source_cours
        self.stockage = stockage
        self.horloge = horloge
        # Duree de vie des factures chez Lightning. Une facture expiree est remplacee par une
        # nouvelle, au cours du moment. None : la facture est gardee jusqu'au paiement.
        self.validite_facture_s = validite_facture_s
        self.tontines: dict[str, Tontine] = {}
        self._factures: dict[str, tuple[str, int, str]] = {}  # hash -> (tontine, tour, membre)
        self._verrou = threading.RLock()
        self._abonnes = []
        self._a_diffuser: list[Evenement] = []
        self._file: queue.Queue[Evenement] = queue.Queue()
        self._diffuseur: threading.Thread | None = None
        if stockage is not None:
            for t in stockage.charger():
                self.tontines[t.id] = t
                for tour in t.tours:
                    for c in tour.cotisations.values():
                        for payment_hash in [c.payment_hash, *c.anciennes_factures]:
                            if payment_hash:
                                self._factures[payment_hash] = (t.id, tour.numero, c.membre_id)

    def _sauver(self, t: Tontine):
        if self.stockage is not None:
            self.stockage.sauver(t)
        # Les signaux ne partent qu'une fois l'evenement enregistre.
        if self._abonnes:
            for e in self._a_diffuser:
                self._file.put(e)
        self._a_diffuser.clear()

    # --- Signaux ---

    def abonner(self, fonction):
        """Appelle fonction(evenement) a chaque evenement, sans ralentir les paiements."""
        with self._verrou:
            self._abonnes.append(fonction)
            if self._diffuseur is None:
                self._diffuseur = threading.Thread(target=self._diffuser, daemon=True)
                self._diffuseur.start()

    def attendre_diffusion(self):
        """Attend que tous les signaux en attente soient partis."""
        self._file.join()

    def evenements(self, tontine_id: str, depuis: int = 0) -> list[Evenement]:
        """Journal de la tontine : les evenements dont le numero est superieur a depuis."""
        with self._verrou:
            return [e for e in self.tontine(tontine_id).evenements if e.numero > depuis]

    def _emettre(self, t: Tontine, type_evenement: str, tour: int | None = None, **donnees):
        e = Evenement(t.id, len(t.evenements) + 1, type_evenement, self.horloge(), tour, donnees)
        t.evenements.append(e)
        self._a_diffuser.append(e)

    def _diffuser(self):
        while True:
            e = self._file.get()
            for fonction in list(self._abonnes):
                try:
                    fonction(e)
                except Exception:   # un abonne en panne ne doit pas bloquer les autres
                    journal.exception("Echec de l'abonne pour l'evenement %s", e.type)
            self._file.task_done()

    # --- Creation et inscription ---

    def creer_tontine(self, nom: str, montant_fcfa: int, frequence: str, nombre_membres: int,
                      nom_organisateur: str, adresse_organisateur: str,
                      delai_jours: int = 7, amende_fcfa: int = 0) -> Tontine:
        if nombre_membres < 2:
            raise ErreurTontine("Il faut au moins 2 membres")
        if montant_fcfa <= 0:
            raise ErreurTontine("Le montant doit etre positif")
        if delai_jours < 1 or amende_fcfa < 0:
            raise ErreurTontine("Delai ou amende invalide")
        if not adresse_valide(adresse_organisateur):
            raise ErreurTontine("Adresse Lightning invalide : elle doit avoir la forme nom@domaine")
        with self._verrou:
            organisateur = Membre(secrets.token_hex(8), nom_organisateur, adresse_organisateur.strip(),
                                  jeton=secrets.token_urlsafe(24))
            t = Tontine(id=secrets.token_hex(8), nom=nom, montant_fcfa=montant_fcfa,
                        frequence=frequence, nombre_membres=nombre_membres,
                        organisateur_id=organisateur.id,
                        jeton_organisateur=secrets.token_urlsafe(24),
                        code_invitation=secrets.token_urlsafe(6),
                        delai_jours=delai_jours, amende_fcfa=amende_fcfa,
                        membres=[organisateur])
            self.tontines[t.id] = t
            self._sauver(t)
            return t

    def identifiants_tontines(self) -> list[str]:
        with self._verrou:
            return list(self.tontines)

    def tontine(self, tontine_id: str) -> Tontine:
        t = self.tontines.get(tontine_id)
        if t is None:
            raise ErreurTontine("Tontine introuvable")
        return t

    def verifier_acces(self, tontine_id: str, jeton: str, membre_id: str | None = None) -> Tontine:
        """Accepte le jeton de l'organisateur, ou celui d'un membre (de ce membre-la si membre_id est donne)."""
        t = self.tontine(tontine_id)
        egal = lambda secret: bool(secret) and secrets.compare_digest(jeton.encode(), secret.encode())
        membres = [t.membre(membre_id)] if membre_id else t.membres
        if egal(t.jeton_organisateur) or any(egal(m.jeton) for m in membres):
            return t
        raise ErreurAcces("Acces reserve aux membres de la tontine")

    def etat(self, tontine_id: str) -> Tontine:
        """Renvoie la tontine apres avoir pris en compte les retards."""
        with self._verrou:
            t = self.tontine(tontine_id)
            self._actualiser_retards(t)
            return t

    def rejoindre(self, code_invitation: str, nom: str, adresse_lightning: str) -> tuple[Tontine, Membre]:
        with self._verrou:
            t = next((t for t in self.tontines.values() if t.code_invitation == code_invitation), None)
            if t is None:
                raise ErreurTontine("Lien d'invitation invalide")
            if t.statut != Statut.INSCRIPTION:
                raise ErreurTontine("Les inscriptions sont fermees")
            if len(t.membres) >= t.nombre_membres:
                raise ErreurTontine("La tontine est complete")
            if not adresse_valide(adresse_lightning):
                raise ErreurTontine("Adresse Lightning invalide : elle doit avoir la forme nom@domaine")
            m = Membre(secrets.token_hex(8), nom, adresse_lightning.strip(), jeton=secrets.token_urlsafe(24))
            t.membres.append(m)
            self._emettre(t, "membre_inscrit", membre_id=m.id)
            self._sauver(t)
            return t, m

    def changer_adresse(self, tontine_id: str, membre_id: str, jeton: str, adresse: str) -> Tontine:
        """Le membre corrige son adresse Lightning, par exemple apres un versement refuse."""
        with self._verrou:
            t = self.tontine(tontine_id)
            m = t.membre(membre_id)
            if not secrets.compare_digest(jeton.encode(), m.jeton.encode()) or not m.jeton:
                raise ErreurTontine("Seul le membre lui-meme peut changer son adresse")
            if not adresse_valide(adresse):
                raise ErreurTontine("Adresse Lightning invalide : elle doit avoir la forme nom@domaine")
            tour = t.tour_actuel
            if (tour is not None and tour.beneficiaire_id == membre_id
                    and tour.versement_statut == StatutVersement.EN_COURS):
                # Un versement est peut-etre deja parti vers l'ancienne adresse.
                raise ErreurTontine("Versement en cours vers cette adresse : attendez son resultat")
            m.adresse_lightning = adresse.strip()
            self._emettre(t, "adresse_modifiee", tour.numero if tour else None, membre_id=membre_id)
            self._sauver(t)
            return t

    # --- Ordre de passage ---

    def _verifier_jeton(self, t: Tontine, jeton: str):
        if not secrets.compare_digest(jeton.encode(), t.jeton_organisateur.encode()):
            raise ErreurTontine("Seul l'organisateur peut faire cette action")

    def _verifier_inscription(self, t: Tontine, jeton: str):
        self._verifier_jeton(t, jeton)
        if t.statut != Statut.INSCRIPTION:
            raise ErreurTontine("La tontine a deja commence")

    def fixer_ordre(self, tontine_id: str, jeton: str, ordre: list[str]) -> Tontine:
        with self._verrou:
            t = self.tontine(tontine_id)
            self._verifier_inscription(t, jeton)
            if sorted(ordre) != sorted(m.id for m in t.membres):
                raise ErreurTontine("L'ordre doit contenir chaque membre une seule fois")
            t.ordre, t.graine_tirage = list(ordre), None
            self._emettre(t, "ordre_fixe", ordre=t.ordre, graine_tirage=None)
            self._sauver(t)
            return t

    def tirer_au_sort(self, tontine_id: str, jeton: str) -> Tontine:
        with self._verrou:
            t = self.tontine(tontine_id)
            self._verifier_inscription(t, jeton)
            t.graine_tirage = secrets.token_hex(16)
            t.ordre = tirer_ordre([m.id for m in t.membres], t.graine_tirage)
            self._emettre(t, "ordre_fixe", ordre=t.ordre, graine_tirage=t.graine_tirage)
            self._sauver(t)
            return t

    # --- Deroulement des tours ---

    def demarrer(self, tontine_id: str, jeton: str) -> Tontine:
        with self._verrou:
            t = self.tontine(tontine_id)
            self._verifier_inscription(t, jeton)
            if len(t.membres) != t.nombre_membres:
                raise ErreurTontine(f"Il manque {t.nombre_membres - len(t.membres)} membre(s)")
            if sorted(t.ordre) != sorted(m.id for m in t.membres):
                raise ErreurTontine("L'ordre de passage n'est pas fixe pour tous les membres")
            t.statut = Statut.EN_COURS
            self._nouveau_tour(t)
            self._sauver(t)
            return t

    def _nouveau_tour(self, t: Tontine):
        numero = len(t.tours) + 1
        actifs = [m for m in t.membres if m.statut == StatutMembre.ACTIF]
        t.tours.append(Tour(numero=numero, beneficiaire_id=t.ordre[numero - 1],
                            date_limite=self.horloge() + t.delai_jours * SECONDES_PAR_JOUR,
                            cotisations={m.id: Cotisation(m.id) for m in actifs}))
        self._emettre(t, "nouveau_tour", numero, beneficiaire_id=t.ordre[numero - 1],
                      date_limite=t.tours[-1].date_limite)

    def _actualiser_retards(self, t: Tontine):
        """Apres la date limite, marque les retards et ajoute l'amende au prochain montant du."""
        if t.statut != Statut.EN_COURS or self.horloge() <= t.tour_actuel.date_limite:
            return
        change = False
        for c in t.tour_actuel.cotisations.values():
            if c.statut == StatutCotisation.EN_ATTENTE and not c.en_retard:
                c.en_retard = True
                t.membre(c.membre_id).amendes_dues_fcfa += t.amende_fcfa
                self._emettre(t, "membre_en_defaut", t.tour_actuel.numero,
                              membre_id=c.membre_id, amende_fcfa=t.amende_fcfa)
                change = True
        if change:
            self._sauver(t)

    def situation(self, t: Tontine) -> list[dict]:
        """Ce que tous les membres voient : qui est en defaut et combien chacun doit."""
        tour = t.tour_actuel
        lignes = []
        for m in t.membres:
            c = tour.cotisations.get(m.id) if tour else None
            en_attente = c is not None and c.statut == StatutCotisation.EN_ATTENTE
            lignes.append({
                "membre_id": m.id,
                "nom": m.nom,
                "statut": m.statut.value,
                "en_defaut": en_attente and c.en_retard,
                "montant_du_fcfa": t.montant_fcfa + m.amendes_dues_fcfa if en_attente else 0,
            })
        return lignes

    def facture_cotisation(self, tontine_id: str, membre_id: str) -> Cotisation:
        """Cree (ou renvoie) la facture Lightning du membre pour le tour en cours."""
        with self._verrou:
            t = self.tontine(tontine_id)
            if t.statut != Statut.EN_COURS:
                raise ErreurTontine("La tontine n'est pas en cours")
            self._actualiser_retards(t)
            tour = t.tour_actuel
            c = tour.cotisations.get(membre_id)
            if c is None:
                raise ErreurTontine("Membre inconnu")
            if c.statut == StatutCotisation.PAYE:
                raise ErreurTontine("Cotisation deja payee")
            if (c.payment_hash is not None and self.validite_facture_s is not None
                    and c.facture_creee_le is not None
                    and self.horloge() > c.facture_creee_le + self.validite_facture_s + MARGE_EXPIRATION_S):
                # Facture expiree : elle ne peut plus etre payee. On en refait une au cours du moment,
                # en gardant l'ancienne connue au cas ou un paiement serait arrive juste avant.
                c.anciennes_factures.append(c.payment_hash)
                c.payment_hash = None
            if c.payment_hash is None:
                amende = t.membre(membre_id).amendes_dues_fcfa
                sats = fcfa_vers_sats(t.montant_fcfa + amende, self.source_cours.cours_btc_eur())
                f = self.lightning.creer_facture(sats, f"{t.nom} - tour {tour.numero}")
                c.amende_fcfa = amende
                c.montant_sats, c.payment_request, c.payment_hash = sats, f.payment_request, f.payment_hash
                c.facture_creee_le = self.horloge()
                self._factures[f.payment_hash] = (t.id, tour.numero, membre_id)
                self._sauver(t)
            return c

    def confirmer_paiement(self, payment_hash: str, preimage: str) -> Tontine:
        """Appelee quand Lightning signale un paiement. Un paiement n'est compte qu'une fois."""
        with self._verrou:
            ref = self._factures.get(payment_hash)
            if ref is None:
                raise ErreurTontine("Facture inconnue")
            if not preimage_valide(preimage, payment_hash):
                raise ErreurTontine("Preimage invalide")
            tontine_id, numero, membre_id = ref
            t = self.tontine(tontine_id)
            tour = t.tours[numero - 1]
            c = tour.cotisations[membre_id]
            if c.statut == StatutCotisation.PAYE:
                return t  # notification repetee : on l'ignore
            # LNbits connait la preimage des la creation de la facture : elle ne prouve rien
            # a elle seule. Seule la reception constatee par Lightning prouve le paiement.
            if not self.lightning.cotisation_recue(payment_hash):
                raise ErreurTontine("Paiement non recu par le noeud Lightning")
            c.statut, c.preimage = StatutCotisation.PAYE, preimage
            m = t.membre(membre_id)
            m.amendes_dues_fcfa = max(0, m.amendes_dues_fcfa - c.amende_fcfa)
            self._emettre(t, "cotisation_payee", numero, membre_id=membre_id,
                          montant_sats=c.montant_sats, payment_hash=payment_hash, preimage=preimage)
            self._sauver(t)
            if tour.complet and tour.versement_statut == StatutVersement.AUCUN:
                self._verser(t)
            return t

    def exclure(self, tontine_id: str, jeton: str, membre_id: str) -> Tontine:
        """Exclut un membre en retard ; le tour peut alors se terminer sans lui."""
        with self._verrou:
            t = self.tontine(tontine_id)
            self._verifier_jeton(t, jeton)
            if t.statut != Statut.EN_COURS:
                raise ErreurTontine("La tontine n'est pas en cours")
            self._actualiser_retards(t)
            tour = t.tour_actuel
            m = t.membre(membre_id)
            c = tour.cotisations.get(membre_id)
            if c is None or c.statut != StatutCotisation.EN_ATTENTE or not c.en_retard:
                raise ErreurTontine("Seul un membre en retard sur ce tour peut etre exclu")
            if membre_id == tour.beneficiaire_id:
                raise ErreurTontine("Le beneficiaire du tour en cours ne peut pas etre exclu")
            m.statut = StatutMembre.EXCLU
            if membre_id in t.ordre[tour.numero:]:
                t.ordre.remove(membre_id)   # il ne recevra pas de cagnotte
            del tour.cotisations[membre_id]
            for payment_hash in [c.payment_hash, *c.anciennes_factures]:
                if payment_hash:
                    self._factures.pop(payment_hash, None)
            self._emettre(t, "membre_exclu", tour.numero, membre_id=membre_id)
            self._sauver(t)
            if tour.complet and tour.versement_statut == StatutVersement.AUCUN:
                self._verser(t)
            return t

    def relancer_versement(self, tontine_id: str, jeton: str) -> Tontine:
        """Reessaie un versement en echec ou en cours. payer() ne repaie jamais un versement parti."""
        with self._verrou:
            t = self.tontine(tontine_id)
            self._verifier_jeton(t, jeton)
            if t.tour_actuel is None or t.tour_actuel.versement_statut not in (
                    StatutVersement.ECHEC, StatutVersement.EN_COURS):
                raise ErreurTontine("Aucun versement a relancer")
            self._verser(t)
            return t

    def reprendre_versements(self):
        """Au demarrage : termine les versements interrompus par une panne."""
        with self._verrou:
            for t in self.tontines.values():
                if (t.statut == Statut.EN_COURS
                        and t.tour_actuel.versement_statut == StatutVersement.EN_COURS):
                    self._verser(t)

    def _verser(self, t: Tontine):
        tour = t.tour_actuel
        beneficiaire = t.membre(tour.beneficiaire_id)
        total = sum(c.montant_sats for c in tour.cotisations.values())
        # Enregistre avant de payer, pour pouvoir reprendre ce versement apres une panne.
        tour.versement_statut = StatutVersement.EN_COURS
        self._sauver(t)
        # La description identifie le versement : elle doit etre unique et ne jamais changer.
        description = f"{t.nom} - cagnotte du tour {tour.numero} ({t.id})"
        try:
            preimage = self.lightning.payer(beneficiaire.adresse_lightning, total, description)
        except (VersementEnAttente, ErreurLNbits):
            return      # issue inconnue : reste EN_COURS, ce n'est pas un echec
        except Exception:
            tour.versement_statut = StatutVersement.ECHEC
            self._emettre(t, "versement_echec", tour.numero,
                          beneficiaire_id=beneficiaire.id, montant_sats=total)
            self._sauver(t)
            return
        tour.versement_preimage, tour.versement_sats = preimage, total
        tour.versement_statut = StatutVersement.FAIT
        self._emettre(t, "versement_fait", tour.numero, beneficiaire_id=beneficiaire.id,
                      montant_sats=total, preimage=preimage)
        if tour.numero == len(t.ordre):
            t.statut = Statut.TERMINEE
            self._emettre(t, "tontine_terminee", tour.numero)
        else:
            self._nouveau_tour(t)
        self._sauver(t)


def empreinte_anonyme(membre_id: str, sel: str) -> str:
    """Identifiant public d'un membre pour le registre Nostr (ni nom ni telephone)."""
    return hashlib.sha256(f"{sel}:{membre_id}".encode()).hexdigest()[:16]
