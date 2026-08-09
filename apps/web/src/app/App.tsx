import { FormEvent, ReactElement, useCallback, useEffect, useState } from "react";
import { ApiError, authApi, chatApi, conversationApi, settingsApi, type Conversation, type Preferences, type User } from "../lib/api";
import { SettingsPage } from "./settings/SettingsPage";
import { applyPreferences, cachePreferences, readCachedPreferences } from "../lib/preferences";
import "../styles/app.css";

type Mode = "login" | "register";

type AuthScreenProps = {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onAuthenticated: (token: string, user: User) => void;
};

/** Short, quiet confirmation tone; created on demand so no audio runs unless enabled. */
function playChime(): void {
  try {
    const AudioCtor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtor) return;
    const context = new AudioCtor();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.05, context.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.25);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.26);
    oscillator.onended = () => void context.close();
  } catch {
    // Audio is a non-essential enhancement.
  }
}

function BrandMark(): ReactElement {
  return <span className="brand-mark" aria-hidden="true">J</span>;
}

function AuthScreen({ mode, onModeChange, onAuthenticated }: AuthScreenProps): ReactElement {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const registering = mode === "register";

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const session = registering
        ? await authApi.register({ email, password, display_name: name })
        : await authApi.login({ email, password });
      onAuthenticated(session.access_token, session.user);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to reach JaT. Try again shortly.");
    } finally {
      setLoading(false);
    }
  }

  return <main className="auth-page">
    <section className="auth-intro">
      <div className="brand"><BrandMark /><span>JaT</span></div>
      <div className="intro-copy"><p className="eyebrow">INDEPENDENT AI PLATFORM</p><h1>Make intelligence yours.</h1><p>JaT is being built as a secure, extensible home for conversations, knowledge, tools, and future models.</p></div>
      <div className="signal-grid" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /><i /><i /></div>
    </section>
    <section className="auth-panel">
      <div className="auth-card">
        <p className="eyebrow">WELCOME TO JAT</p><h2>{registering ? "Create your workspace" : "Welcome back"}</h2>
        <p className="muted">{registering ? "Start with a personal, secure workspace." : "Sign in to continue to your workspace."}</p>
        <form onSubmit={submit} className="auth-form">
          {registering && <label>Display name<input required minLength={1} maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="Ada Lovelace" autoComplete="name" /></label>}
          <label>Email<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" autoComplete="email" /></label>
          <label>Password<input required type="password" minLength={registering ? 12 : 1} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={registering ? "At least 12 characters" : "Your password"} autoComplete={registering ? "new-password" : "current-password"} /></label>
          {error && <p role="alert" className="form-error">{error}</p>}
          <button className="primary-button" disabled={loading}>{loading ? "Working…" : registering ? "Create workspace" : "Sign in"}<span>→</span></button>
        </form>
        <p className="switch-auth">{registering ? "Already have an account?" : "New to JaT?"} <button onClick={() => onModeChange(registering ? "login" : "register")}>{registering ? "Sign in" : "Create one"}</button></p>
      </div>
    </section>
  </main>;
}

type WorkspaceProps = {
  user: User;
  token: string;
  onLogout: () => void;
  preferences: Preferences;
  onPreferencesChange: (preferences: Preferences) => void;
  onProfileChange: (user: User) => void;
};

function Workspace({ user, token, onLogout, preferences, onPreferencesChange, onProfileChange }: WorkspaceProps): ReactElement {
  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<{ id?: string; role: "user" | "assistant"; content: string; status?: string }[]>([]);
  const [sending, setSending] = useState(false);
  const [streamController, setStreamController] = useState<AbortController | null>(null);

  useEffect(() => { void conversationApi.list(token).then((items) => { setConversations(items); setActive(items[0] ?? null); }).catch(() => undefined); }, [token]);
  useEffect(() => { if (!active) return; void conversationApi.messages(token, active.id).then((items) => setMessages(items.filter((item) => item.role === "user" || item.role === "assistant").map((item) => ({ id: item.id, role: item.role as "user" | "assistant", content: item.content, status: item.status })))).catch(() => undefined); }, [active, token]);
  async function newConversation(): Promise<void> { const item = await conversationApi.create(token); setConversations((items) => [item, ...items]); setActive(item); setMessages([]); }
  async function send(): Promise<void> {
    if (!draft.trim() || sending) return;
    const content = draft.trim(); setDraft(""); setSending(true); setMessages((items) => [...items, { role: "user", content }]);
    const controller = new AbortController(); setStreamController(controller);
    try {
      const target = active ?? await conversationApi.create(token);
      if (!active) { setActive(target); setConversations((items) => [target, ...items]); }
      if (preferences.stream_responses) {
        setMessages((items) => [...items, { role: "assistant", content: "" }]);
        await chatApi.stream(token, target.id, content, (chunk) => setMessages((items) => items.map((message, index) => index === items.length - 1 && message.role === "assistant" ? { ...message, content: message.content + chunk } : message)), controller.signal);
      } else {
        const result = await chatApi.send(token, target.id, content);
        setMessages((items) => [...items, { id: result.assistant_message_id, role: "assistant", content: result.content, status: "complete" }]);
      }
      if (preferences.sound_on_response) playChime();
    }
    catch (error) { if (!(error instanceof DOMException && error.name === "AbortError")) setMessages((items) => [...items, { role: "assistant", content: "JaT could not complete that request. Please try again." }]); }
    finally { setSending(false); setStreamController(null); }
  }
  async function retry(messageId: string): Promise<void> { setSending(true); try { const result = await chatApi.retry(token, messageId); setMessages((items) => [...items, { id: result.assistant_message_id, role: "assistant", content: result.content, status: "complete" }]); } finally { setSending(false); } }
  return <main className="workspace">
    <aside className={`sidebar ${navOpen ? "open" : ""}`}><div className="brand"><BrandMark /><span>JaT</span></div><button className="new-chat" onClick={() => { setNavOpen(false); void newConversation(); }}>+ <span>New conversation</span><kbd>⌘ K</kbd></button><nav><p>RECENT</p>{conversations.map((conversation) => <button key={conversation.id} onClick={() => { setActive(conversation); setMessages([]); setNavOpen(false); }} className={`nav-chat ${active?.id === conversation.id ? "active" : ""}`}>{conversation.title}</button>)}</nav><div className="sidebar-bottom"><button>⌘ Search</button><button>◌ Knowledge bases</button><button>⌁ Models <em>Phase 2</em></button></div></aside>
    <section className="chat-stage"><header className="chat-header"><button className="nav-toggle" aria-label="Open navigation" aria-expanded={navOpen} onClick={() => setNavOpen(true)}>☰</button><div><p className="eyebrow">JAT ASSISTANT</p><h2>{active?.title ?? "New conversation"}</h2></div><button className="model-pill">{active?.model ?? "JaT development"} <span>⌄</span></button></header>
      <div className={messages.length ? "message-list" : "empty-chat"}>{messages.length ? messages.map((message, index) => <article key={index} className={`message ${message.role}`}><span>{message.role === "user" ? user.display_name.slice(0, 1) : "J"}</span><div><p>{message.content}</p>{message.role === "assistant" && message.status && message.status !== "complete" && <small className="message-status">{message.status === "cancelled" ? "Generation stopped" : message.status === "failed" ? "Generation failed" : "Generating…"}</small>}{message.role === "assistant" && message.id && (message.status === "cancelled" || message.status === "failed") && <button className="retry-button" disabled={sending} onClick={() => void retry(message.id!)}>Retry response</button>}</div></article>) : <><div className="orbit"><span>✦</span></div><p className="eyebrow">THE JAT FOUNDATION</p><h1>How can I help?</h1><p>Ask a question to exercise JaT’s provider-neutral chat pipeline.</p><div className="suggestions"><button onClick={() => setDraft("Explain the JaT architecture.")}>Explore the architecture <span>↗</span></button><button onClick={() => setDraft("Review the security controls.")}>Review security controls <span>↗</span></button></div></>}</div>
      <div className="composer"><input value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
        const modifierSend = event.key === "Enter" && (event.metaKey || event.ctrlKey);
        const plainSend = preferences.send_on_enter && event.key === "Enter" && !event.shiftKey && !event.metaKey && !event.ctrlKey;
        if (modifierSend || plainSend) { event.preventDefault(); void send(); }
      }} placeholder="Ask JaT anything…" disabled={sending} /><button onClick={() => sending ? streamController?.abort() : void send()} disabled={!sending && !draft.trim()} aria-label={sending ? "Stop generating" : "Send message"}>{sending ? "■" : "↑"}</button></div>
    </section>
    <aside className="profile-rail"><button className="avatar" onClick={() => setMenuOpen(!menuOpen)} aria-label="Open profile menu">{user.display_name.slice(0, 1).toUpperCase()}</button>{menuOpen && <div className="profile-menu"><strong>{user.display_name}</strong><small>{user.email}</small><hr /><button onClick={() => { setSettingsOpen(true); setMenuOpen(false); }}>Settings</button><button onClick={onLogout}>Sign out</button></div>}</aside>
    {navOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setNavOpen(false)} />}
    {settingsOpen && <SettingsPage token={token} user={user} preferences={preferences} onPreferencesChange={onPreferencesChange} onProfileChange={onProfileChange} onClose={() => setSettingsOpen(false)} onSignedOut={onLogout} />}
  </main>;
}

export function App(): ReactElement {
  const [mode, setMode] = useState<Mode>("login");
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [preferences, setPreferences] = useState<Preferences>(readCachedPreferences);

  const updatePreferences = useCallback((next: Preferences) => {
    setPreferences(next);
    cachePreferences(next);
    applyPreferences(next);
  }, []);

  // Appearance must survive reloads and follow the OS when "system" is selected.
  useEffect(() => applyPreferences(preferences), [preferences]);
  useEffect(() => {
    if (typeof matchMedia === "undefined") return;
    const query = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyPreferences(preferences);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [preferences]);

  useEffect(() => { void authApi.refresh().then((session) => { setToken(session.access_token); setUser(session.user); }).catch(() => undefined); }, []);

  // Server preferences are authoritative once a session exists.
  useEffect(() => {
    if (!token) return;
    void settingsApi.get(token).then(updatePreferences).catch(() => undefined);
  }, [token, updatePreferences]);

  function signOut(): void {
    void authApi.logout().finally(() => { setToken(null); setUser(null); });
  }

  if (!token || !user) return <AuthScreen mode={mode} onModeChange={setMode} onAuthenticated={(nextToken, nextUser) => { setToken(nextToken); setUser(nextUser); }} />;
  return <Workspace user={user} token={token} onLogout={signOut} preferences={preferences} onPreferencesChange={updatePreferences} onProfileChange={setUser} />;
}
