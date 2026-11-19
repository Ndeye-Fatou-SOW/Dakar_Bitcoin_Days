import { useEffect, useMemo, useState, type FormEvent } from "react";
import { QRCodeSVG } from "qrcode.react";
import { nip19 } from "nostr-tools";
import { verifyEvent, type Event as NostrEvent } from "nostr-tools/pure";

const API_BASE = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const SESSION_KEY = "tontine-lightning-session";

type Page = "home" | "create" | "join" | "login";
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
  identifiant_registre: string | null;
}

interface Session {
  tontineId: string;
  memberId: string;
  memberToken: string;
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
  jeton_membre: string;
  lien_invitation: string;
}

interface JoinResponse {
  tontine_id: string;
  membre_id: string;
  jeton_membre: string;
}

interface ReconnectResponse {
  tontine_id: string;
  membre_id: string;
  jeton_membre: string;
  jeton_organisateur: string | null;
  code_invitation: string;
}

interface RegistryInfo {
  actif: boolean;
  cle_publique?: string;
  relais?: string[];
  kind?: number;
}

type ProofType = "cotisation_payee" | "versement_fait" | "membre_en_defaut";

function isProofType(value: unknown): value is ProofType {
  return value === "cotisation_payee" || value === "versement_fait" || value === "membre_en_defaut";
}

interface ProofPayload {
  v: 1;
  application: "tontine-lightning";
  type: ProofType;
  tontine: string;
  numero: number;
  tour: number | null;
  date: number;
  membre?: string;
  beneficiaire?: string;
  montant_sats?: number;
  payment_hash?: string;
  preimage?: string;
  amende_fcfa?: number;
}

interface NostrProof extends ProofPayload {
  id: string;
  hashCoherent: boolean | null;
}

interface RelayResult {
  url: string;
  events: NostrEvent[];
  error?: string;
}

interface NostrView {
  status: "idle" | "loading" | "inactive" | "ready" | "error";
  proofs: NostrProof[];
  relaysOk: number;
  relaysTotal: number;
  rejected: number;
  publicKey?: string;
  message?: string;
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
      typeof candidate.memberToken !== "string" ||
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

async function api<T>(path: string, init: RequestInit = {}, memberToken?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(memberToken ? { "X-Jeton": memberToken } : {}),
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

function parseNostrEvent(value: unknown): NostrEvent | null {
  if (typeof value !== "object" || value === null) return null;
  const event = value as Partial<NostrEvent>;
  if (
    typeof event.id !== "string" ||
    typeof event.pubkey !== "string" ||
    typeof event.sig !== "string" ||
    typeof event.content !== "string" ||
    !Number.isSafeInteger(event.kind) ||
    !Number.isSafeInteger(event.created_at) ||
    !Array.isArray(event.tags) ||
    !event.tags.every((tag) => Array.isArray(tag) && tag.every((part) => typeof part === "string"))
  ) return null;
  return event as NostrEvent;
}

function parseProofPayload(content: string, registryId: string): ProofPayload | null {
  let value: unknown;
  try {
    value = JSON.parse(content);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const data = value as Record<string, unknown>;
  if (
    data.v !== 1 ||
    data.application !== "tontine-lightning" ||
    data.tontine !== registryId ||
    !isProofType(data.type) ||
    typeof data.numero !== "number" ||
    !Number.isSafeInteger(data.numero) ||
    !(data.tour === null || (typeof data.tour === "number" && Number.isSafeInteger(data.tour))) ||
    typeof data.date !== "number" ||
    !Number.isSafeInteger(data.date)
  ) return null;

  const base = {
    v: 1 as const,
    application: "tontine-lightning" as const,
    type: data.type,
    tontine: data.tontine,
    numero: data.numero,
    tour: data.tour,
    date: data.date,
  };
  const anonymizedId = /^[\da-f]{16}$/i;
  if (data.type === "cotisation_payee") {
    if (
      typeof data.membre !== "string" ||
      !anonymizedId.test(data.membre) ||
      typeof data.montant_sats !== "number" ||
      !Number.isSafeInteger(data.montant_sats) ||
      data.montant_sats <= 0 ||
      typeof data.payment_hash !== "string" ||
      !/^[\da-f]{64}$/i.test(data.payment_hash) ||
      typeof data.preimage !== "string" ||
      !/^[\da-f]{64}$/i.test(data.preimage)
    ) return null;
    return {
      ...base,
      type: data.type,
      membre: data.membre,
      montant_sats: data.montant_sats,
      payment_hash: data.payment_hash,
      preimage: data.preimage,
    };
  }
  if (data.type === "versement_fait") {
    if (
      typeof data.beneficiaire !== "string" ||
      !anonymizedId.test(data.beneficiaire) ||
      typeof data.montant_sats !== "number" ||
      !Number.isSafeInteger(data.montant_sats) ||
      data.montant_sats <= 0 ||
      typeof data.payment_hash !== "string" ||
      !/^[\da-f]{64}$/i.test(data.payment_hash) ||
      typeof data.preimage !== "string" ||
      !/^[\da-f]{64}$/i.test(data.preimage)
    ) return null;
    return {
      ...base,
      type: data.type,
      beneficiaire: data.beneficiaire,
      montant_sats: data.montant_sats,
      payment_hash: data.payment_hash,
      preimage: data.preimage,
    };
  }
  if (
    typeof data.membre !== "string" ||
    !anonymizedId.test(data.membre) ||
    typeof data.amende_fcfa !== "number" ||
    !Number.isSafeInteger(data.amende_fcfa) ||
    data.amende_fcfa < 0
  ) return null;
  return { ...base, type: data.type, membre: data.membre, amende_fcfa: data.amende_fcfa };
}

async function hashMatchesPreimage(preimage: string, expectedHash: string): Promise<boolean> {
  if (!globalThis.crypto?.subtle) return false;
  const bytes = new Uint8Array(preimage.match(/../g)!.map((part) => Number.parseInt(part, 16)));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  const actualHash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  return actualHash === expectedHash.toLowerCase();
}

function queryNostrRelay(url: string, kind: number, tag: string): Promise<RelayResult> {
  return new Promise((resolve) => {
    const subscriptionId = `tontine-${Math.random().toString(36).slice(2)}`;
    const events: NostrEvent[] = [];
    let socket: WebSocket | null = null;
    let finished = false;
    const finish = (error?: string) => {
      if (finished) return;
      finished = true;
      window.clearTimeout(timeout);
      if (socket && socket.readyState !== WebSocket.CLOSED) {
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(["CLOSE", subscriptionId]));
        socket.close();
      }
      resolve({ url, events, ...(error ? { error } : {}) });
    };
    const timeout = window.setTimeout(() => finish("Délai de réponse dépassé"), 8000);
    try {
      socket = new WebSocket(url);
      socket.onopen = () => {
        if (finished) {
          socket?.close();
          return;
        }
        socket?.send(JSON.stringify([
          "REQ",
          subscriptionId,
          { kinds: [kind], "#t": [tag], limit: 100 },
        ]));
      };
      socket.onmessage = (message) => {
        if (typeof message.data !== "string") return;
        let response: unknown;
        try {
          response = JSON.parse(message.data);
        } catch {
          return;
        }
        if (!Array.isArray(response)) return;
        if (response[0] === "EVENT" && response[1] === subscriptionId) {
          const event = parseNostrEvent(response[2]);
          if (event) events.push(event);
        } else if (response[0] === "EOSE" && response[1] === subscriptionId) {
          finish();
        } else if (response[0] === "CLOSED" && response[1] === subscriptionId) {
          finish(typeof response[2] === "string" ? response[2] : "Le relais a fermé la requête.");
        }
      };
      socket.onerror = () => finish("Connexion au relais impossible");
      socket.onclose = () => finish("Connexion fermée avant la fin de la recherche");
    } catch {
      finish("URL de relais ou connexion invalide");
    }
  });
}

async function verifyNostrProof(
  event: NostrEvent,
  expectedPublicKey: string,
  registryId: string,
  expectedKind: number,
  tag: string,
): Promise<NostrProof | null> {
  let signatureValid = false;
  try {
    signatureValid =
      event.kind === expectedKind &&
      event.tags.some(([name, value]) => name === "t" && value === tag) &&
      verifyEvent(event) &&
      nip19.npubEncode(event.pubkey) === expectedPublicKey;
  } catch {
    signatureValid = false;
  }
  if (!signatureValid) return null;
  const payload = parseProofPayload(event.content, registryId);
  if (!payload) return null;
  const isPayment = payload.type === "cotisation_payee" || payload.type === "versement_fait";
  const hashCoherent = isPayment
    ? await hashMatchesPreimage(payload.preimage!, payload.payment_hash!)
    : null;
  return { ...payload, id: event.id, hashCoherent };
}

function formatFcfa(amount: number): string {
  return new Intl.NumberFormat("fr-FR").format(amount);
}

function formatSats(amount: number): string {
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
  const [nostr, setNostr] = useState<NostrView>({
    status: "idle",
    proofs: [],
    relaysOk: 0,
    relaysTotal: 0,
    rejected: 0,
  });
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
  const completedTours = tontine?.tours.filter((tour) => tour.versement_statut === "fait") ?? [];
  const isOrganizer = Boolean(session?.organizerToken);

  useEffect(() => {
    if (!session) {
      setTontine(null);
      return;
    }
    let active = true;
    const refresh = async () => {
      try {
        const fresh = await api<Tontine>(
          `/tontines/${encodeURIComponent(session.tontineId)}`,
          {},
          session.memberToken,
        );
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
    setNostr({ status: "idle", proofs: [], relaysOk: 0, relaysTotal: 0, rejected: 0 });
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
        memberToken: result.jeton_membre,
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
    // Accepte le code seul ou le lien d'invitation complet (…/rejoindre/<code>).
    const brut = String(form.get("code") ?? inviteCode).trim();
    const code = brut.match(/rejoindre\/([^/?#\s]+)/)?.[1] ?? brut;
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
      persistSession({
        tontineId: result.tontine_id,
        memberId: result.membre_id,
        memberToken: result.jeton_membre,
        invitationCode: code,
      });
      setInviteCode(code);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impossible de rejoindre cette tontine.");
    } finally {
      setLoading(false);
    }
  }

  async function handleReconnect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setLoading(true);
    setError("");
    try {
      const result = await api<ReconnectResponse>("/reconnexion", {
        method: "POST",
        body: JSON.stringify({ jeton_acces: String(form.get("jeton_acces") ?? "").trim() }),
      });
      persistSession({
        tontineId: result.tontine_id,
        memberId: result.membre_id,
        memberToken: result.jeton_membre,
        ...(result.jeton_organisateur ? { organizerToken: result.jeton_organisateur } : {}),
        invitationCode: result.code_invitation,
      });
      setSuccess("Vous êtes reconnecté à votre tontine.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impossible de retrouver votre tontine.");
    } finally {
      setLoading(false);
    }
  }

  function leaveSession() {
    if (!window.confirm("Avez-vous enregistré votre code d’accès personnel ? Il sera nécessaire pour vous reconnecter sur cet appareil après la déconnexion.")) {
      return;
    }
    window.localStorage.removeItem(SESSION_KEY);
    setSession(null);
    setTontine(null);
    setInvoice(null);
    setPage("home");
    setError("");
    setSuccess("");
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
        session.memberToken,
      );
      setInvoice(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impossible de créer la facture Lightning.");
    } finally {
      setLoading(false);
    }
  }

  async function loadNostrRegistry() {
    if (!tontine) return;
    setNostr({ status: "loading", proofs: [], relaysOk: 0, relaysTotal: 0, rejected: 0 });
    try {
      const info = await api<RegistryInfo>("/registre");
      if (!info.actif) {
        setNostr({
          status: "inactive",
          proofs: [],
          relaysOk: 0,
          relaysTotal: 0,
          rejected: 0,
          message: "Le registre Nostr n’est pas activé sur ce backend.",
        });
        return;
      }
      const publicKey = info.cle_publique;
      const relays = info.relais;
      const kind = info.kind;
      const registryId = tontine.identifiant_registre;
      if (!publicKey || !relays || !kind || !registryId) {
        throw new Error("La configuration ou l’identifiant public du registre est incomplet.");
      }

      const groupTag = `tl-${registryId}`;
      const results = await Promise.all(relays.map((relay) => queryNostrRelay(relay, kind, groupTag)));
      const proofsById = new Map<string, NostrProof>();
      let rejected = 0;
      for (const result of results) {
        for (const event of result.events) {
          try {
            const proof = await verifyNostrProof(event, publicKey, registryId, kind, groupTag);
            if (proof) proofsById.set(proof.id, proof);
            else rejected += 1;
          } catch {
            rejected += 1;
          }
        }
      }
      const proofs = [...proofsById.values()].sort(
        (left, right) => left.numero - right.numero || left.date - right.date,
      );
      const relaysOk = results.filter((result) => !result.error).length;
      setNostr({
        status: "ready",
        proofs,
        relaysOk,
        relaysTotal: results.length,
        rejected,
        publicKey,
        message: relaysOk === 0
          ? "Aucun relais n’a répondu. Vérifiez la connexion puis réessayez."
          : undefined,
      });
    } catch (reason) {
      setNostr({
        status: "error",
        proofs: [],
        relaysOk: 0,
        relaysTotal: 0,
        rejected: 0,
        message: reason instanceof Error ? reason.message : "Impossible de consulter le registre Nostr.",
      });
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

  async function copyAccessCode() {
    if (!session) return;
    try {
      await navigator.clipboard.writeText(session.memberToken);
      setSuccess("Code d’accès copié. Gardez-le secret pour pouvoir vous reconnecter.");
    } catch {
      setError("Copie impossible dans ce navigateur. Sélectionnez et copiez le code affiché.");
    }
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
          <button className={`nav-item ${page === "login" ? "active" : ""}`} onClick={() => setPage("login")}>
            <span className="nav-icon">↪</span> Me reconnecter
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
          <div className="breadcrumb">Dakar Bitcoin Days <span>/</span> <strong>{page === "create" ? "Nouvelle tontine" : page === "join" ? "Rejoindre un groupe" : page === "login" ? "Reconnexion" : "Espace tontine"}</strong></div>
          <div className="topbar-right">
            <span className="secure-tag"><span>●</span> Paiement Lightning</span>
            {session && <button className="avatar" title="Retour à ma tontine" onClick={() => setPage("home")}>{currentMember?.nom?.slice(0, 1).toUpperCase() ?? "M"}</button>}
            {session && <button className="session-exit" onClick={leaveSession}>Quitter</button>}
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

          {page === "login" && (
            <section className="form-page">
              <div className="eyebrow"><span className="eyebrow-dot" /> RETOUR AU GROUPE</div>
              <h1>Se reconnecter à sa <em>tontine.</em></h1>
              <p className="page-intro">Saisissez le code d’accès personnel enregistré lors de votre inscription. Il donne accès à votre tontine : ne le partagez avec personne.</p>
              <form className="form-card join-card" onSubmit={handleReconnect}>
                <div className="form-section-title"><span>01</span><div><strong>Votre code d’accès</strong><small>Il est différent du lien d’invitation</small></div></div>
                <label>Code d’accès personnel<input name="jeton_acces" autoComplete="off" placeholder="Collez votre code personnel" required /></label>
                <div className="form-footnote"><span>i</span> Votre session reste enregistrée sur cet appareil jusqu’à votre déconnexion.</div>
                <button className="button button-primary button-wide" type="submit" disabled={loading}>{loading ? "Reconnexion…" : "Retrouver ma tontine"} <span>→</span></button>
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
                  <button className="button button-secondary" onClick={() => setPage("login")}>Je suis déjà membre</button>
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
                  <details className="panel access-panel">
                    <summary>Mon accès personnel <span>Enregistrez ce code pour pouvoir vous reconnecter</span></summary>
                    <p>Ce code est secret et permet d’ouvrir votre tontine depuis un autre appareil. Il est sauvegardé automatiquement sur cet appareil.</p>
                    <div className="access-code-row"><code>{session.memberToken}</code><button className="button button-secondary" onClick={() => void copyAccessCode()}>Copier mon code</button></div>
                  </details>
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
                      {completedTours.length > 0 && (
                        <article className="panel completed-tours-panel">
                          <div className="panel-heading">
                            <div><h2>Tours terminés</h2><p>Les versements confirmés aux bénéficiaires.</p></div>
                            <span className="member-count">{completedTours.length} versement(s)</span>
                          </div>
                          <div className="completed-tour-list">
                            {completedTours.map((tour) => {
                              const paidMember = tontine.membres.find((member) => member.id === tour.beneficiaire_id);
                              const proof = nostr.proofs.find(
                                (item) => item.type === "versement_fait" && item.tour === tour.numero,
                              );
                              const proofStatus = proof
                                ? proof.hashCoherent
                                  ? "Preuve Nostr vérifiée : signature et empreinte cohérentes."
                                  : "Preuve Nostr trouvée, mais l’empreinte ne correspond pas."
                                : nostr.status === "ready"
                                  ? "Aucune preuve Nostr trouvée pour ce tour."
                                  : nostr.status === "inactive"
                                    ? "Le registre Nostr n’est pas activé."
                                    : nostr.status === "error"
                                      ? "Vérification Nostr indisponible."
                                      : nostr.status === "loading"
                                        ? "Recherche de la preuve Nostr…"
                                        : "Preuve publique à vérifier dans le registre Nostr.";
                              return (
                                <div className="completed-tour" key={tour.numero}>
                                  <div className="completed-tour-heading">
                                    <span className="tour-number">TOUR {String(tour.numero).padStart(2, "0")}</span>
                                    <span className="payout-confirmed"><i /> Versement confirmé</span>
                                  </div>
                                  <div className="completed-tour-summary">
                                    <div><small>BÉNÉFICIAIRE</small><strong>{paidMember?.nom ?? "Membre inconnu"}</strong></div>
                                    <div className="received-amount"><small>MONTANT REÇU</small><strong>{tour.versement_sats === null ? "—" : `${formatSats(tour.versement_sats)} sats`}</strong></div>
                                  </div>
                                  <div className={`payout-proof ${proof?.hashCoherent === false ? "payout-proof-invalid" : ""}`}>
                                    <span className="proof-icon">{proof?.hashCoherent === false ? "!" : "✓"}</span>
                                    <div><strong>Preuve du versement</strong><small>{proofStatus}</small>
                                      {proof && <code className="payout-proof-id">Événement Nostr · {proof.id}</code>}
                                    </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                          {nostr.status !== "inactive" && (
                            <button
                              className="button button-secondary button-wide completed-proof-button"
                              disabled={nostr.status === "loading"}
                              onClick={() => void loadNostrRegistry()}
                            >
                              {nostr.status === "loading" ? "Recherche de la preuve…" : nostr.status === "ready" ? "Actualiser les preuves Nostr" : "Vérifier les preuves Nostr"}
                            </button>
                          )}
                          <p className="completed-proof-note">Le statut confirme le versement par Lightning. La preuve Nostr authentifie l’événement publié et vérifie la cohérence de son empreinte ; elle ne remplace pas la confirmation du paiement par Lightning.</p>
                        </article>
                      )}
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
                      {invoice && <article className="panel qr-panel"><div className="panel-heading"><div><h2>Votre facture</h2><p>Scannez ce QR code avec votre portefeuille Lightning.</p></div><button className="close-button" onClick={() => setInvoice(null)} aria-label="Fermer">×</button></div><div className="qr-wrap"><QRCodeSVG value={invoice.payment_request} size={240} level="M" includeMargin fgColor="#111111" bgColor="#ffffff" title="QR code de la facture Lightning" /></div><strong className="sats-amount">{formatFcfa(invoice.montant_sats)} <small>sats</small></strong><div className="invoice-copy"><code>{invoice.payment_request}</code><button onClick={() => { void navigator.clipboard.writeText(invoice.payment_request).then(() => setSuccess("Facture copiée.")).catch(() => setError("Copie impossible.")); }}>Copier</button></div><p className="qr-hint">Gardez cette page ouverte. Le statut se mettra à jour après confirmation du paiement.</p></article>}
                      <div className="security-callout"><span>◎</span><p><strong>Un suivi partagé.</strong><br />Les paiements sont vérifiés par le service Lightning avant que le statut ne change.</p></div>
                      <article className="panel nostr-panel">
                        <div className="panel-heading">
                          <div><h2>Registre public Nostr</h2><p>Consultez les événements publiés pour ce groupe.</p></div>
                          <span className="nostr-mark">N</span>
                        </div>
                        <button
                          className="button button-secondary button-wide"
                          disabled={nostr.status === "loading"}
                          onClick={() => void loadNostrRegistry()}
                        >
                          {nostr.status === "loading" ? "Recherche sur les relais…" : "Consulter les preuves"}
                        </button>
                        {nostr.status === "inactive" && <p className="nostr-message">{nostr.message}</p>}
                        {nostr.status === "error" && <p className="nostr-message nostr-error">{nostr.message}</p>}
                        {nostr.status === "ready" && (
                          <>
                            <p className="nostr-message">
                              {nostr.proofs.length} événement(s) trouvés · {nostr.relaysOk}/{nostr.relaysTotal} relais répondent.
                              {nostr.publicKey && <><br />Clé du service : <code>{nostr.publicKey.slice(0, 15)}…{nostr.publicKey.slice(-8)}</code></>}
                            </p>
                            {nostr.message && <p className="nostr-message nostr-error">{nostr.message}</p>}
                            {nostr.rejected > 0 && <p className="nostr-warning">{nostr.rejected} événement(s) rejeté(s) : signature, format ou groupe non valide.</p>}
                            <div className="proof-list">
                              {nostr.proofs.map((proof) => (
                                <div className="proof-row" key={proof.id}>
                                  <span className={`proof-icon ${proof.hashCoherent === false ? "proof-invalid" : ""}`}>
                                    {proof.hashCoherent === false ? "!" : "✓"}
                                  </span>
                                  <div className="proof-details">
                                    <strong>
                                      {proof.type === "cotisation_payee" ? "Cotisation" : proof.type === "versement_fait" ? "Versement" : "Retard"}
                                      {proof.tour === null ? "" : ` · Tour ${proof.tour}`}
                                    </strong>
                                    <small>
                                      {new Date(proof.date * 1000).toLocaleString("fr-FR")}
                                      {proof.montant_sats !== undefined ? ` · ${formatSats(proof.montant_sats)} sats` : ` · Amende ${formatFcfa(proof.amende_fcfa ?? 0)} FCFA`}
                                    </small>
                                    <span className={proof.hashCoherent === false ? "proof-check failed" : "proof-check"}>
                                      {proof.hashCoherent === null ? "Signature du service valide" : proof.hashCoherent ? "Signature et hash cohérents" : "Hash et préimage incohérents"}
                                    </span>
                                  </div>
                                  <code className="proof-id">{proof.id.slice(0, 10)}…</code>
                                </div>
                              ))}
                            </div>
                          </>
                        )}
                        <p className="nostr-disclaimer">
                          La signature authentifie l’événement comme publié par le service. Le hash et la préimage sont comparés,
                          mais une preuve Nostr ne démontre pas à elle seule qu’un paiement Lightning a été reçu. Les événements et préimages publiés sont publics.
                        </p>
                      </article>
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
