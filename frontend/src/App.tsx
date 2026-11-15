import { useEffect, useMemo, useState, type FormEvent } from "react";
import { QRCodeSVG } from "qrcode.react";

const API_BASE = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const SESSION_KEY = "tontine-lightning-session";

type Page = "home" | "create" | "join";
type TontineStatus = "inscription" | "en_cours" | "terminee";

interface Member {
  id: string;
  nom: string;
  statut: "actif" | "exclu";
  adresse_lightning: string;
}

interface Cotisation {
  membre_id: string;
  statut: "en_attente" | "paye";
  en_retard: boolean;
  montant_sats: number | null;
  payment_request: string | null;
}

interface Tour {
  numero: number;
  beneficiaire_id: string;
  date_limite: number;
  cotisations: Record<string, Cotisation>;
  versement_statut: "aucun" | "en_cours" | "fait" | "echec";
  versement_sats: number | null;
}

interface SituationMembre {
  membre_id: string;
  nom: string;
  statut: "actif" | "exclu";
  en_defaut: boolean;
  montant_du_fcfa: number;
}

interface Tontine {
  id: string;
  nom: string;
  montant_fcfa: number;
  frequence: string;
  nombre_membres: number;
  organisateur_id: string;
  code_invitation: string;
  delai_jours: number;
  amende_fcfa: number;
  membres: Member[];
  ordre: string[];
  tours: Tour[];
  statut: TontineStatus;
  situation: SituationMembre[];
}

interface Session {
  tontineId: string;
  memberId: string;
  organizerToken?: string;
  invitationCode: string;
}

interface Invoice {
  payment_request: string;
  payment_hash: string;
  montant_sats: number;
}

interface CreateResponse {
  tontine: Tontine;
  jeton_organisateur: string;
  lien_invitation: string;
}

interface JoinResponse {
  tontine_id: string;
  membre_id: string;
}

function readSession(): Session | null {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null) return null;
    const candidate = value as Partial<Session>;
    if (
      typeof candidate.tontineId !== "string" ||
      typeof candidate.memberId !== "string" ||
      typeof candidate.invitationCode !== "string"
    ) return null;
    return candidate as Session;
  } catch {
    return null;
  }
}

function errorDetail(value: unknown): string | null {
  if (typeof value !== "object" || value === null || !("detail" in value)) return null;
  const detail = value.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => typeof item === "object" && item !== null && "msg" in item ? String(item.msg) : "")
      .filter(Boolean)
      .join(", ");
  }
  return null;
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new Error(`Impossible de joindre l’API (${API_BASE}). Vérifiez que le backend est lancé.`);
  }
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error("Le serveur a renvoyé une réponse illisible.");
    }
  }
  if (!response.ok) {
    throw new Error(errorDetail(payload) ?? `Erreur du serveur (${response.status}).`);
  }
  return payload as T;
}

function formatFcfa(amount: number): string {
  return new Intl.NumberFormat("fr-FR").format(amount);
}

function dateLabel(timestamp: number): string {
  return new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long" }).format(new Date(timestamp * 1000));
}

function App() {
  const inviteFromUrl = window.location.pathname.match(/^\/rejoindre\/([^/]+)/)?.[1] ?? "";
  const [page, setPage] = useState<Page>(inviteFromUrl ? "join" : "home");
  const [inviteCode, setInviteCode] = useState(inviteFromUrl);
  const [session, setSession] = useState<Session | null>(readSession);
  const [tontine, setTontine] = useState<Tontine | null>(null);
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  const currentTour = tontine?.tours.at(-1) ?? null;
  const currentMember = useMemo(
    () => tontine?.membres.find((member) => member.id === session?.memberId) ?? null,
    [tontine, session],
  );
  const beneficiary = tontine?.membres.find((member) => member.id === currentTour?.beneficiaire_id);
  const paidCount = tontine && currentTour
    ? tontine.membres.filter((member) => currentTour.cotisations[member.id]?.statut === "paye").length
    : 0;
  const isOrganizer = Boolean(session?.organizerToken);

  useEffect(() => {
    if (!session) {
      setTontine(null);
      return;
    }
    let active = true;
    const refresh = async () => {
      try {
        const fresh = await api<Tontine>(`/tontines/${encodeURIComponent(session.tontineId)}`);
        if (active) {
          setTontine(fresh);
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Impossible de charger la tontine.");
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [session?.tontineId]);

  function persistSession(next: Session) {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(next));
    setSession(next);
    setInvoice(null);
    setSuccess("");
    setError("");
    setPage("home");
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = {
      nom: String(form.get("nom") ?? "").trim(),
      montant_fcfa: Number(form.get("montant_fcfa")),
      frequence: String(form.get("frequence")),
      nombre_membres: Number(form.get("nombre_membres")),
      delai_jours: Number(form.get("delai_jours")),
      amende_fcfa: Number(form.get("amende_fcfa")),
      nom_organisateur: String(form.get("nom_organisateur") ?? "").trim(),
      adresse_lightning: String(form.get("adresse_lightning") ?? "").trim(),
    };
    setLoading(true);
    setError("");
    try {
      const result = await api<CreateResponse>("/tontines", { method: "POST", body: JSON.stringify(body) });
      persistSession({
        tontineId: result.tontine.id,
        memberId: result.tontine.organisateur_id,
        organizerToken: result.jeton_organisateur,
        invitationCode: result.tontine.code_invitation,
      });
      setTontine(result.tontine);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "La création a échoué.");
    } finally {
      setLoading(false);
    }
  }

  async function handleJoin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const code = String(form.get("code") ?? inviteCode).trim();
    setLoading(true);
    setError("");
    try {
      const result = await api<JoinResponse>(`/rejoindre/${encodeURIComponent(code)}`, {
        method: "POST",
        body: JSON.stringify({
          nom: String(form.get("nom") ?? "").trim(),
          adresse_lightning: String(form.get("adresse_lightning") ?? "").trim(),
        }),
      });
      persistSession({ tontineId: result.tontine_id, memberId: result.membre_id, invitationCode: code });
      setInviteCode(code);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impossible de rejoindre cette tontine.");
    } finally {
      setLoading(false);
    }
  }

  async function runOrganizerAction(path: string, successMessage: string) {
    if (!session?.organizerToken) return;
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const fresh = await api<Tontine>(path, {
        method: "POST",
        body: JSON.stringify({ jeton_organisateur: session.organizerToken }),
      });
      setTontine(fresh);
      setSuccess(successMessage);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Cette action a échoué.");
    } finally {
      setLoading(false);
    }
  }

  async function requestInvoice() {
    if (!session || !currentMember) return;
    setLoading(true);
    setError("");
    try {
      const result = await api<Invoice>(
        `/tontines/${encodeURIComponent(session.tontineId)}/membres/${encodeURIComponent(currentMember.id)}/facture`,
        { method: "POST" },
      );
      setInvoice(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impossible de créer la facture Lightning.");
    } finally {
      setLoading(false);
    }
  }

  async function copyInvitation() {
    const url = `${window.location.origin}/rejoindre/${encodeURIComponent(session?.invitationCode ?? "")}`;
    try {
      await navigator.clipboard.writeText(url);
      setSuccess("Lien d’invitation copié.");
    } catch {
      setError("Copie impossible dans ce navigateur. Sélectionnez et copiez le lien affiché.");
    }
  }

  function leaveTontine() {
    window.localStorage.removeItem(SESSION_KEY);
    setSession(null);
    setTontine(null);
    setInvoice(null);
    setSuccess("");
    setError("");
  }

  const inviteUrl = `${window.location.origin}/rejoindre/${encodeURIComponent(session?.invitationCode ?? "")}`;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" onClick={(event) => { event.preventDefault(); setPage("home"); }}>
          <span className="brand-mark">t.</span>
          <span>Tontine<span className="brand-light">.</span></span>
        </a>
        <div className="workspace-label">ESPACE DU GROUPE</div>
        <nav className="side-nav" aria-label="Navigation principale">
          <button className={`nav-item ${page === "home" ? "active" : ""}`} onClick={() => setPage("home")}>
            <span className="nav-icon">⌂</span> Ma tontine
          </button>
          <button className={`nav-item ${page === "create" ? "active" : ""}`} onClick={() => setPage("create")}>
            <span className="nav-icon">＋</span> Créer une tontine
          </button>
          <button className={`nav-item ${page === "join" ? "active" : ""}`} onClick={() => setPage("join")}>
            <span className="nav-icon">↗</span> Rejoindre un groupe
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <span className="note-icon">✳</span>
            <strong>Ensemble, en confiance.</strong>
            <p>Les paiements sont suivis par le groupe, tour après tour.</p>
          </div>
          <div className="network-status"><span className="status-dot" /> Lightning {API_BASE.includes("127.0.0.1") || API_BASE.includes("localhost") ? "local" : "connecté"}</div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="mobile-brand"><span className="brand-mark">t.</span><strong>Tontine<span className="brand-light">.</span></strong></div>
          <div className="breadcrumb">Dakar Bitcoin Days <span>/</span> <strong>{page === "create" ? "Nouvelle tontine" : page === "join" ? "Rejoindre un groupe" : "Espace tontine"}</strong></div>
          <div className="topbar-right">
            <span className="secure-tag"><span>●</span> Paiement Lightning</span>
            {session && <button className="avatar" title="Quitter cette tontine" onClick={leaveTontine}>{currentMember?.nom?.slice(0, 1).toUpperCase() ?? "M"}</button>}
          </div>
        </header>

        <div className="page-content">
          {(error || success) && (
            <div className={`notice ${error ? "notice-error" : "notice-success"}`} role="status">
              <span>{error ? "!" : "✓"}</span><p>{error || success}</p>
              <button onClick={() => { setError(""); setSuccess(""); }} aria-label="Fermer">×</button>
            </div>
          )}

          {page === "create" && (
            <section className="form-page">
              <div className="eyebrow"><span className="eyebrow-dot" /> POUR COMMENCER</div>
              <h1>Créer une <em>tontine.</em></h1>
              <p className="page-intro">Définissez les règles du groupe. Vous pourrez ensuite partager un lien d’invitation aux membres.</p>
              <form className="form-card" onSubmit={handleCreate}>
                <div className="form-section-title"><span>01</span><div><strong>Le groupe</strong><small>Les informations principales de votre tontine</small></div></div>
                <label>Nom de la tontine<input name="nom" placeholder="Ex. Les femmes de Sandaga" required maxLength={80} /></label>
                <div className="form-grid">
                  <label>Votre nom<input name="nom_organisateur" placeholder="Ex. Awa Ndiaye" required /></label>
                  <label>Nombre de membres<input name="nombre_membres" type="number" min="2" max="100" defaultValue="3" required /></label>
                  <label>Cotisation par tour <span className="input-unit">FCFA</span><input name="montant_fcfa" type="number" min="1" placeholder="10 000" required /></label>
                  <label>Fréquence<select name="frequence" defaultValue="mensuelle"><option value="hebdomadaire">Hebdomadaire</option><option value="bimensuelle">Toutes les deux semaines</option><option value="mensuelle">Mensuelle</option></select></label>
                  <label>Délai de paiement<input name="delai_jours" type="number" min="1" defaultValue="7" required /></label>
                  <label>Amende de retard <span className="input-unit">FCFA</span><input name="amende_fcfa" type="number" min="0" defaultValue="0" required /></label>
                </div>
                <div className="form-section-title section-spaced"><span>02</span><div><strong>Votre portefeuille</strong><small>Adresse Lightning qui recevra la cagnotte de votre tour</small></div></div>
                <label>Adresse Lightning<input name="adresse_lightning" placeholder="nom@wallet.com" required /></label>
                <div className="form-footnote"><span>i</span> La démo utilise un service de paiement. Ne saisissez pas une adresse contenant des informations sensibles.</div>
                <button className="button button-primary button-wide" type="submit" disabled={loading}>{loading ? "Création en cours…" : "Créer ma tontine"} <span>→</span></button>
              </form>
            </section>
          )}

          {page === "join" && (
            <section className="form-page">
              <div className="eyebrow"><span className="eyebrow-dot" /> INVITATION</div>
              <h1>Rejoindre le <em>groupe.</em></h1>
              <p className="page-intro">Inscrivez-vous avec le code partagé par l’organisateur. Vérifiez les règles du groupe avant de continuer.</p>
              <form className="form-card join-card" onSubmit={handleJoin}>
                <div className="form-section-title"><span>01</span><div><strong>Vos informations</strong><small>Votre nom sera visible par les autres membres</small></div></div>
                <label>Code d’invitation<input name="code" value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} placeholder="Collez votre code d’invitation" required /></label>
                <label>Votre nom<input name="nom" placeholder="Ex. Aminata Diop" required /></label>
                <label>Votre adresse Lightning<input name="adresse_lightning" placeholder="nom@wallet.com" required /></label>
                <div className="form-footnote"><span>i</span> En rejoignant, vous acceptez le montant et les règles fixés par le groupe.</div>
                <button className="button button-primary button-wide" type="submit" disabled={loading}>{loading ? "Inscription…" : "Rejoindre la tontine"} <span>→</span></button>
              </form>
            </section>
          )}

          {page === "home" && !session && (
            <section className="welcome">
              <div className="hero-copy">
                <div className="eyebrow"><span className="eyebrow-dot" /> LA TONTINE, EN TOUTE CONFIANCE</div>
                <h1>Votre groupe.<br />Vos règles.<br /><em>Ensemble.</em></h1>
                <p>Une façon plus simple de suivre les cotisations et de faire tourner la cagnotte. Tout le monde voit où en est le groupe.</p>
                <div className="hero-actions">
                  <button className="button button-primary" onClick={() => setPage("create")}>Créer une tontine <span>→</span></button>
                  <button className="button button-secondary" onClick={() => setPage("join")}>J’ai un code d’invitation</button>
                </div>
                <div className="hero-footnote"><span>✦</span> Propulsé par Bitcoin Lightning <i /> Pensé pour les tontines d’ici</div>
              </div>
              <div className="hero-art">
                <div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" />
                <div className="coin coin-back">₣</div><div className="coin coin-front">₿</div>
                <div className="floating-card card-top"><span className="mini-avatar avatar-sun">A</span><span><strong>La cotisation d’Awa</strong><small>vient d’arriver</small></span><b>✓</b></div>
                <div className="floating-card card-bottom"><span className="mini-icon">↗</span><span><strong>Tour 02</strong><small>La cagnotte tourne</small></span><span className="mini-sats">+ 30k sats</span></div>
                <div className="art-caption"><span className="caption-line" /> Une tontine transparente, simplement.</div>
              </div>
              <div className="feature-strip">
                <div><span className="feature-icon icon-peach">01</span><span><strong>Tout le monde suit</strong><small>Un statut clair pour chaque membre.</small></span></div>
                <div><span className="feature-icon icon-green">02</span><span><strong>Payez avec Lightning</strong><small>Rapide, directement depuis votre portefeuille.</small></span></div>
                <div><span className="feature-icon icon-blue">03</span><span><strong>À tour de rôle</strong><small>L’ordre de passage est visible par le groupe.</small></span></div>
              </div>
            </section>
          )}

          {page === "home" && session && (
            <section className="dashboard">
              {!tontine ? (
                <div className="loading-card"><span className="spinner" /> Chargement de votre tontine…</div>
              ) : (
                <>
                  <div className="dashboard-heading">
                    <div><div className="eyebrow"><span className="eyebrow-dot" /> VOTRE ESPACE</div><h1>{tontine.nom}<span className={`status-pill status-${tontine.statut}`}>{tontine.statut === "inscription" ? "Inscriptions" : tontine.statut === "en_cours" ? "En cours" : "Terminée"}</span></h1><p className="page-intro">Bonjour {currentMember?.nom ?? "membre"}, voici la situation de votre groupe.</p></div>
                    <button className="button button-secondary hide-mobile" onClick={() => void copyInvitation()}>＋ Inviter un membre</button>
                  </div>
                  <div className="summary-grid">
                    <article className="summary-card"><span className="summary-label">COTISATION / TOUR</span><strong>{formatFcfa(tontine.montant_fcfa)} <small>FCFA</small></strong><span className="summary-sub">{tontine.frequence}</span></article>
                    <article className="summary-card"><span className="summary-label">MEMBRES INSCRITS</span><strong>{tontine.membres.length}<small> / {tontine.nombre_membres}</small></strong><span className="summary-sub">{tontine.nombre_membres - tontine.membres.length > 0 ? `${tontine.nombre_membres - tontine.membres.length} place(s) restante(s)` : "Le groupe est au complet"}</span></article>
                    <article className="summary-card summary-accent"><span className="summary-label">{currentTour ? `TOUR ${String(currentTour.numero).padStart(2, "0")}` : "PROCHAIN TOUR"}</span><strong>{currentTour ? `${paidCount} / ${Object.keys(currentTour.cotisations).length}` : "—"}</strong><span className="summary-sub">{currentTour ? "cotisations reçues" : "En attente du démarrage"}</span></article>
                  </div>
                  <div className="dashboard-columns">
                    <div className="main-column">
                      <article className="panel members-panel">
                        <div className="panel-heading"><div><h2>Les membres</h2><p>Le suivi des cotisations, visible par tous.</p></div><span className="member-count">{tontine.membres.length} membres</span></div>
                        <div className="member-list">
                          {tontine.membres.map((member, index) => {
                            const contribution = currentTour?.cotisations[member.id];
                            const paid = contribution?.statut === "paye";
                            const isBeneficiary = currentTour?.beneficiaire_id === member.id;
                            const position = tontine.ordre.indexOf(member.id);
                            return (
                              <div className="member-row" key={member.id}>
                                <span className={`member-avatar avatar-color-${index % 4}`}>{member.nom.slice(0, 1).toUpperCase()}</span>
                                <div className="member-info"><strong>{member.nom}{member.id === session.memberId && <small className="you-tag">Vous</small>}</strong><span>{position >= 0 ? `Passage ${position + 1}` : member.id === tontine.organisateur_id ? "Organisateur" : "Membre"}</span></div>
                                {isBeneficiary && <span className="beneficiary-tag">Bénéficiaire</span>}
                                {tontine.statut === "inscription" ? <span className="member-status waiting"><i /> Inscrit</span> : member.statut === "exclu" ? <span className="member-status late">Exclu</span> : <span className={`member-status ${paid ? "paid" : "waiting"}`}><i /> {paid ? "Payé" : contribution?.en_retard ? "En retard" : "En attente"}</span>}
                              </div>
                            );
                          })}
                        </div>
                      </article>
                      <article className="panel progress-panel">
                        <div className="panel-heading"><div><h2>{currentTour ? "Tour en cours" : "Prochaines étapes"}</h2><p>{currentTour ? `La cagnotte sera versée à ${beneficiary?.nom ?? "un membre"} après réception des cotisations.` : "Le tour démarre quand le groupe est prêt."}</p></div>{currentTour && <span className="tour-number">T{String(currentTour.numero).padStart(2, "0")}</span>}</div>
                        {currentTour ? (
                          <div className="tour-progress">
                            <div className="progress-meta"><span>{paidCount} sur {Object.keys(currentTour.cotisations).length} cotisations</span><strong>{Object.keys(currentTour.cotisations).length ? Math.round((paidCount / Object.keys(currentTour.cotisations).length) * 100) : 0}%</strong></div>
                            <div className="progress-track"><span style={{ width: `${Object.keys(currentTour.cotisations).length ? (paidCount / Object.keys(currentTour.cotisations).length) * 100 : 0}%` }} /></div>
                            <div className="deadline-line"><span>◷ &nbsp;Échéance : {dateLabel(currentTour.date_limite)}</span><span>Amende : {formatFcfa(tontine.amende_fcfa)} FCFA</span></div>
                          </div>
                        ) : (
                          <div className="steps-row"><div className="step-done"><span>✓</span><div><strong>Inviter le groupe</strong><small>{tontine.membres.length} / {tontine.nombre_membres} membres</small></div></div><div className={tontine.ordre.length ? "step-done" : "step-next"}><span>{tontine.ordre.length ? "✓" : "02"}</span><div><strong>Fixer l’ordre</strong><small>Tirage transparent ou choix manuel</small></div></div><div className="step-next"><span>03</span><div><strong>Lancer le premier tour</strong><small>Les membres pourront cotiser</small></div></div></div>
                        )}
                      </article>
                    </div>
                    <aside className="action-column">
                      {tontine.statut === "inscription" && (
                        <article className="action-card">
                          <div className="action-card-icon">✳</div><span className="summary-label">PROCHAINE ACTION</span>
                          {tontine.membres.length < tontine.nombre_membres ? (
                            <><h3>Invitez votre groupe</h3><p>Il manque {tontine.nombre_membres - tontine.membres.length} membre(s) avant de pouvoir fixer l’ordre.</p><div className="invite-link"><span>{inviteUrl}</span><button onClick={() => void copyInvitation()} aria-label="Copier le lien">⧉</button></div><button className="button button-secondary button-wide" onClick={() => void copyInvitation()}>Copier le lien d’invitation</button></>
                          ) : isOrganizer ? (
                            <><h3>Le groupe est prêt</h3><p>Tirez l’ordre de passage, puis lancez le premier tour.</p><button className="button button-secondary button-wide" disabled={loading} onClick={() => void runOrganizerAction(`/tontines/${tontine.id}/tirage`, "L’ordre de passage a été tiré.")}>Tirer l’ordre au sort</button><button className="button button-primary button-wide start-button" disabled={loading || !tontine.ordre.length} onClick={() => void runOrganizerAction(`/tontines/${tontine.id}/demarrer`, "La tontine a démarré.")}>Démarrer la tontine <span>→</span></button></>
                          ) : (
                            <><h3>Le groupe est prêt</h3><p>L’organisateur peut maintenant tirer l’ordre de passage et lancer le premier tour.</p></>
                          )}
                          {!isOrganizer && <p className="permission-note">L’organisateur doit lancer le tirage et le tour.</p>}
                        </article>
                      )}
                      {tontine.statut === "en_cours" && (
                        <article className="action-card payment-card">
                          <div className="action-card-icon payment-icon">↗</div><span className="summary-label">VOTRE COTISATION</span>
                          <h3>{currentTour?.cotisations[session.memberId]?.statut === "paye" ? "Cotisation reçue" : "C’est votre tour de cotiser"}</h3>
                          <p>{currentTour?.cotisations[session.memberId]?.statut === "paye" ? "Votre paiement est confirmé. Le statut du groupe se met à jour automatiquement." : "Créez une facture Lightning et payez-la depuis votre portefeuille."}</p>
                          {currentTour?.cotisations[session.memberId]?.statut !== "paye" && <button className="button button-primary button-wide" disabled={loading || !currentTour?.cotisations[session.memberId]} onClick={() => void requestInvoice()}>{loading ? "Préparation…" : "Afficher mon QR de paiement"} <span>→</span></button>}
                          {!currentTour?.cotisations[session.memberId] && <p className="permission-note">Aucune cotisation n’est attendue de votre compte pour ce tour.</p>}
                        </article>
                      )}
                      {tontine.statut === "terminee" && <article className="action-card"><div className="action-card-icon">✓</div><span className="summary-label">CYCLE TERMINÉ</span><h3>Bravo au groupe</h3><p>Tous les tours de la tontine sont terminés.</p></article>}
                      {invoice && <article className="panel qr-panel"><div className="panel-heading"><div><h2>Votre facture</h2><p>Scannez ce QR code avec votre portefeuille Lightning.</p></div><button className="close-button" onClick={() => setInvoice(null)} aria-label="Fermer">×</button></div><div className="qr-wrap"><QRCodeSVG value={invoice.payment_request} size={188} level="M" includeMargin /></div><strong className="sats-amount">{formatFcfa(invoice.montant_sats)} <small>sats</small></strong><div className="invoice-copy"><code>{invoice.payment_request}</code><button onClick={() => { void navigator.clipboard.writeText(invoice.payment_request).then(() => setSuccess("Facture copiée.")).catch(() => setError("Copie impossible.")); }}>Copier</button></div><p className="qr-hint">Gardez cette page ouverte. Le statut se mettra à jour après confirmation du paiement.</p></article>}
                      <div className="security-callout"><span>◎</span><p><strong>Un suivi partagé.</strong><br />Les paiements sont vérifiés par le service Lightning avant que le statut ne change.</p></div>
                    </aside>
                  </div>
                </>
              )}
            </section>
          )}
          <footer className="page-footer"><span>Une tontine, en toute confiance.</span><span>Prototype Dakar Bitcoin Days <i /> Bitcoin Lightning</span></footer>
        </div>
      </main>
    </div>
  );
}

export default App;
