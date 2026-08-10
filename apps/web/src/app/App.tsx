import {
  ChangeEvent,
  FormEvent,
  KeyboardEvent,
  ReactElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ApiError,
  authApi,
  chatApi,
  conversationApi,
  MIN_PASSWORD_LENGTH,
  settingsApi,
  type Conversation,
  type ModelOption,
  type Preferences,
  type User,
} from "../lib/api";
import { SettingsPage } from "./settings/SettingsPage";
import { applyPreferences, cachePreferences, readCachedPreferences } from "../lib/preferences";
import logoUrl from "../assets/logo.svg";
import "../styles/app.css";

type Mode = "login" | "register";

type AuthScreenProps = {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onAuthenticated: (token: string, user: User) => void;
};

type ChatMessage = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  status?: string;
  attachments?: AttachedFile[];
};

type AttachedFile = {
  id: string;
  name: string;
  size: number;
  type: string;
  textPreview?: string;
};

/** Short, quiet confirmation tone; created on demand so no audio runs unless enabled. */
function playChime(): void {
  try {
    const AudioCtor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
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

function BrandMark({ size = 28 }: { size?: number }): ReactElement {
  return (
    <img
      className="brand-logo"
      src={logoUrl}
      alt=""
      width={size}
      height={size}
      draggable={false}
    />
  );
}

function Brand({ compact = false }: { compact?: boolean }): ReactElement {
  return (
    <div className={`brand ${compact ? "compact" : ""}`}>
      <BrandMark size={compact ? 24 : 28} />
      <span>JaT</span>
    </div>
  );
}

/** Build a short title from the first user message when the server has not titled yet. */
export function titleFromMessage(content: string, maxLength = 60): string {
  const cleaned = content.trim().replace(/\s+/g, " ");
  if (!cleaned) return "New conversation";
  if (cleaned.length <= maxLength) return cleaned;
  const cut = cleaned.slice(0, maxLength - 1).replace(/\s+\S*$/, "");
  return `${cut || cleaned.slice(0, maxLength - 1)}…`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function readFileAsAttachment(file: File): Promise<AttachedFile> {
  const id = `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`;
  const isText =
    file.type.startsWith("text/") ||
    /\.(md|txt|csv|json|ts|tsx|js|jsx|py|rs|go|java|c|cpp|h|yml|yaml|toml|xml|html|css|sql)$/i.test(
      file.name,
    );
  let textPreview: string | undefined;
  if (isText && file.size <= 200_000) {
    try {
      const raw = await file.text();
      textPreview = raw.slice(0, 12_000);
    } catch {
      textPreview = undefined;
    }
  }
  return { id, name: file.name, size: file.size, type: file.type || "application/octet-stream", textPreview };
}

function composeMessageWithFiles(text: string, files: AttachedFile[]): string {
  if (!files.length) return text;
  const blocks = files.map((file) => {
    if (file.textPreview) {
      return `Attached file: ${file.name}\n\`\`\`\n${file.textPreview}\n\`\`\``;
    }
    return `Attached file: ${file.name} (${formatBytes(file.size)}, ${file.type})`;
  });
  return [text.trim(), ...blocks].filter(Boolean).join("\n\n");
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

  return (
    <main className="auth-page">
      <section className="auth-intro">
        <Brand />
        <div className="intro-copy">
          <p className="eyebrow">INDEPENDENT AI PLATFORM</p>
          <h1>Make intelligence yours.</h1>
          <p>
            JaT is being built as a secure, extensible home for conversations, knowledge, tools, and
            future models.
          </p>
        </div>
        <div className="signal-grid" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <div className="auth-card-brand">
            <BrandMark size={36} />
          </div>
          <p className="eyebrow">WELCOME TO JAT</p>
          <h2>{registering ? "Create your workspace" : "Welcome back"}</h2>
          <p className="muted">
            {registering ? "Start with a personal, secure workspace." : "Sign in to continue to your workspace."}
          </p>
          <form onSubmit={submit} className="auth-form">
            {registering && (
              <label>
                Display name
                <input
                  required
                  minLength={1}
                  maxLength={120}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Ada Lovelace"
                  autoComplete="name"
                />
              </label>
            )}
            <label>
              Email
              <input
                required
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
              />
            </label>
            <label>
              Password
              <input
                required
                type="password"
                minLength={registering ? MIN_PASSWORD_LENGTH : 1}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={
                  registering ? `At least ${MIN_PASSWORD_LENGTH} characters` : "Your password"
                }
                autoComplete={registering ? "new-password" : "current-password"}
              />
            </label>
            {error && (
              <p role="alert" className="form-error">
                {error}
              </p>
            )}
            <button className="primary-button" disabled={loading} type="submit">
              {loading ? "Working…" : registering ? "Create workspace" : "Sign in"}
              <span>→</span>
            </button>
          </form>
          <p className="switch-auth">
            {registering ? "Already have an account?" : "New to JaT?"}{" "}
            <button type="button" onClick={() => onModeChange(registering ? "login" : "register")}>
              {registering ? "Sign in" : "Create one"}
            </button>
          </p>
        </div>
      </section>
    </main>
  );
}

type WorkspaceProps = {
  user: User;
  token: string;
  onLogout: () => void;
  preferences: Preferences;
  onPreferencesChange: (preferences: Preferences) => void;
  onProfileChange: (user: User) => void;
};

function Workspace({
  user,
  token,
  onLogout,
  preferences,
  onPreferencesChange,
  onProfileChange,
}: WorkspaceProps): ReactElement {
  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<string | undefined>(undefined);
  const [navOpen, setNavOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [streamController, setStreamController] = useState<AbortController | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [menuFlipUp, setMenuFlipUp] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [attachments, setAttachments] = useState<AttachedFile[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [composerError, setComposerError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);

  const refreshConversations = useCallback(async (): Promise<Conversation[]> => {
    const items = await conversationApi.list(token);
    setConversations(items);
    return items;
  }, [token]);

  useEffect(() => {
    void refreshConversations()
      .then((items) => setActive((current) => current ?? items[0] ?? null))
      .catch(() => undefined);
  }, [refreshConversations]);

  useEffect(() => {
    settingsApi
      .models(token)
      .then(setModels)
      .catch(() => undefined);
  }, [token]);

  useEffect(() => {
    if (!active) {
      setMessages([]);
      return;
    }
    void conversationApi
      .messages(token, active.id)
      .then((items) =>
        setMessages(
          items
            .filter((item) => item.role === "user" || item.role === "assistant")
            .map((item) => ({
              id: item.id,
              role: item.role as "user" | "assistant",
              content: item.content,
              status: item.status,
            })),
        ),
      )
      .catch(() => undefined);
  }, [active, token]);

  useEffect(() => {
    // Scroll only the message list, never the surrounding page, so the header,
    // sidebar, and composer stay pinned while the conversation moves.
    const list = messageListRef.current;
    if (!list) return;
    list.scrollTo({ top: list.scrollHeight, behavior: preferences.reduced_motion ? "auto" : "smooth" });
  }, [messages, preferences.reduced_motion]);

  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
        setNavOpen(true);
        window.setTimeout(() => searchInputRef.current?.focus(), 0);
      }
      if (meta && event.key.toLowerCase() === "n" && !event.shiftKey) {
        event.preventDefault();
        void newConversation();
      }
      if (event.key === "Escape") {
        setMenuFor(null);
        setSearchOpen(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [token]);

  const filteredConversations = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return conversations;
    return conversations.filter((conversation) => conversation.title.toLowerCase().includes(query));
  }, [conversations, searchQuery]);

  const activeModel = active?.model ?? preferences.default_model ?? "jat-development";
  const modelOptions = useMemo(() => {
    // Always let the current model render as selectable, even before the catalog loads
    // or if the conversation pins a model the server no longer advertises.
    if (!activeModel || models.some((option) => option.id === activeModel)) return models;
    return [
      {
        id: activeModel,
        label: activeModel,
        description: "",
        provider: "unknown",
        available: true,
        context_length: 0,
      },
      ...models,
    ];
  }, [activeModel, models]);

  async function newConversation(): Promise<void> {
    try {
      const item = await conversationApi.create(token, "New conversation", preferences.default_model);
      setConversations((items) => [item, ...items]);
      setActive(item);
      setMessages([]);
      setAttachments([]);
      setDraft("");
      setNavOpen(false);
      setSearchQuery("");
      setMenuFor(null);
      window.setTimeout(() => composerRef.current?.focus(), 0);
    } catch (caught) {
      setComposerError(caught instanceof ApiError ? caught.message : "Could not start a new chat.");
    }
  }

  async function deleteConversation(conversation: Conversation): Promise<void> {
    if (!confirm(`Delete “${conversation.title}”? This cannot be undone.`)) return;
    try {
      await conversationApi.remove(token, conversation.id);
      setConversations((items) => items.filter((item) => item.id !== conversation.id));
      if (active?.id === conversation.id) {
        const remaining = conversations.filter((item) => item.id !== conversation.id);
        setActive(remaining[0] ?? null);
        setMessages([]);
      }
      setMenuFor(null);
    } catch (caught) {
      setComposerError(caught instanceof ApiError ? caught.message : "Could not delete that chat.");
    }
  }

  async function saveRename(conversation: Conversation): Promise<void> {
    const title = renameDraft.trim();
    if (!title || title === conversation.title) {
      setRenamingId(null);
      return;
    }
    try {
      const updated = await conversationApi.update(token, conversation.id, { title });
      setConversations((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      if (active?.id === updated.id) setActive(updated);
    } catch (caught) {
      setComposerError(caught instanceof ApiError ? caught.message : "Could not rename that chat.");
    } finally {
      setRenamingId(null);
      setMenuFor(null);
    }
  }

  async function changeModel(model: string): Promise<void> {
    if (!active || !model || model === active.model) return;
    try {
      const updated = await conversationApi.update(token, active.id, { model });
      setActive(updated);
      setConversations((items) => items.map((item) => (item.id === updated.id ? updated : item)));
    } catch (caught) {
      setComposerError(caught instanceof ApiError ? caught.message : "Could not switch model.");
    }
  }

  async function handleFiles(fileList: FileList | null): Promise<void> {
    if (!fileList?.length) return;
    const next: AttachedFile[] = [];
    for (const file of Array.from(fileList).slice(0, 8)) {
      if (file.size > 5 * 1024 * 1024) {
        setComposerError(`“${file.name}” is larger than 5 MB.`);
        continue;
      }
      next.push(await readFileAsAttachment(file));
    }
    if (next.length) {
      setAttachments((current) => [...current, ...next].slice(0, 10));
      setComposerError("");
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function removeAttachment(id: string): void {
    setAttachments((current) => current.filter((file) => file.id !== id));
  }

  async function send(): Promise<void> {
    const text = draft.trim();
    if ((!text && attachments.length === 0) || sending) return;

    const content = composeMessageWithFiles(text, attachments);
    const pendingAttachments = attachments;
    const displayText = text || pendingAttachments.map((file) => file.name).join(", ");

    setDraft("");
    setAttachments([]);
    setComposerError("");
    setSending(true);
    setMessages((items) => [
      ...items,
      { role: "user", content: displayText, attachments: pendingAttachments },
    ]);

    const controller = new AbortController();
    setStreamController(controller);

    try {
      let target = active;
      if (!target) {
        target = await conversationApi.create(token, titleFromMessage(text || pendingAttachments[0]?.name || "New conversation"), preferences.default_model);
        setActive(target);
        setConversations((items) => [target!, ...items]);
      } else if (
        !messages.length &&
        (!target.title || target.title.toLowerCase() === "new conversation")
      ) {
        const titled = titleFromMessage(text || pendingAttachments[0]?.name || "New conversation");
        try {
          const updated = await conversationApi.update(token, target.id, { title: titled });
          target = updated;
          setActive(updated);
          setConversations((items) => items.map((item) => (item.id === updated.id ? updated : item)));
        } catch {
          // Server-side auto-title will still apply on chat.
        }
      }

      if (preferences.stream_responses) {
        setMessages((items) => [...items, { role: "assistant", content: "" }]);
        await chatApi.stream(
          token,
          target.id,
          content,
          (chunk) =>
            setMessages((items) =>
              items.map((message, index) =>
                index === items.length - 1 && message.role === "assistant"
                  ? { ...message, content: message.content + chunk }
                  : message,
              ),
            ),
          controller.signal,
        );
      } else {
        const result = await chatApi.send(token, target.id, content);
        setMessages((items) => [
          ...items,
          {
            id: result.assistant_message_id,
            role: "assistant",
            content: result.content,
            status: "complete",
          },
        ]);
      }

      // Refresh titles (server may have auto-titled) and bump order.
      void refreshConversations()
        .then((items) => {
          const fresh = items.find((item) => item.id === target!.id);
          if (fresh) setActive(fresh);
        })
        .catch(() => undefined);

      if (preferences.sound_on_response) playChime();
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessages((items) => [
          ...items,
          { role: "assistant", content: "JaT could not complete that request. Please try again." },
        ]);
      }
    } finally {
      setSending(false);
      setStreamController(null);
      const composer = composerRef.current;
      if (composer) {
        composer.style.height = "auto";
        composer.focus();
      }
    }
  }

  async function retry(messageId: string): Promise<void> {
    setSending(true);
    try {
      const result = await chatApi.retry(token, messageId);
      setMessages((items) => [
        ...items,
        {
          id: result.assistant_message_id,
          role: "assistant",
          content: result.content,
          status: "complete",
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    const modifierSend = event.key === "Enter" && (event.metaKey || event.ctrlKey);
    const plainSend =
      preferences.send_on_enter &&
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.metaKey &&
      !event.ctrlKey;
    if (modifierSend || plainSend) {
      event.preventDefault();
      void send();
    }
  }

  function openSettings(tab?: string): void {
    setSettingsTab(tab);
    setSettingsOpen(true);
    setMenuOpen(false);
    setNavOpen(false);
  }

  const canSend = !sending && (draft.trim().length > 0 || attachments.length > 0);
  const headerTitle = active?.title ?? "New conversation";

  return (
    <main className="workspace">
      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <Brand />
        <button
          type="button"
          className="new-chat"
          onClick={() => {
            void newConversation();
          }}
        >
          + <span>New chat</span>
          <kbd>⌘ N</kbd>
        </button>

        <div className={`sidebar-search ${searchOpen || searchQuery ? "active" : ""}`}>
          <span aria-hidden="true">⌕</span>
          <input
            ref={searchInputRef}
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            onFocus={() => setSearchOpen(true)}
            placeholder="Search chats…"
            aria-label="Search chats"
          />
          {searchQuery && (
            <button
              type="button"
              className="search-clear"
              aria-label="Clear search"
              onClick={() => {
                setSearchQuery("");
                searchInputRef.current?.focus();
              }}
            >
              ×
            </button>
          )}
        </div>

        <nav aria-label="Conversations">
          <p>RECENT</p>
          {filteredConversations.length === 0 ? (
            <p className="nav-empty">
              {searchQuery ? "No chats match your search." : "No conversations yet."}
            </p>
          ) : (
            filteredConversations.map((conversation) => (
              <div
                key={conversation.id}
                className={`nav-chat-row ${active?.id === conversation.id ? "active" : ""}`}
              >
                {renamingId === conversation.id ? (
                  <form
                    className="rename-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void saveRename(conversation);
                    }}
                  >
                    <input
                      autoFocus
                      value={renameDraft}
                      maxLength={200}
                      aria-label="Rename conversation"
                      onChange={(event) => setRenameDraft(event.target.value)}
                      onBlur={() => void saveRename(conversation)}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") {
                          event.preventDefault();
                          setRenamingId(null);
                        }
                      }}
                    />
                  </form>
                ) : (
                  <button
                    type="button"
                    className={`nav-chat ${active?.id === conversation.id ? "active" : ""}`}
                    onClick={() => {
                      setActive(conversation);
                      setMessages([]);
                      setNavOpen(false);
                      setMenuFor(null);
                    }}
                    title={conversation.title}
                  >
                    {conversation.title}
                  </button>
                )}
                <div className="nav-chat-actions">
                  <button
                    type="button"
                    className="nav-more"
                    aria-label={`Options for ${conversation.title}`}
                    aria-expanded={menuFor === conversation.id}
                    onClick={(event) => {
                      event.stopPropagation();
                      const isOpen = menuFor === conversation.id;
                      if (!isOpen) {
                        // The nav list scrolls; open the menu upward when it would
                        // otherwise be clipped below the visible nav area.
                        const navBox = event.currentTarget
                          .closest("nav")
                          ?.getBoundingClientRect();
                        const buttonBox = event.currentTarget.getBoundingClientRect();
                        const menuHeight = 96;
                        setMenuFlipUp(
                          Boolean(
                            navBox &&
                              buttonBox.bottom + menuHeight > navBox.bottom &&
                              buttonBox.top - menuHeight >= navBox.top,
                          ),
                        );
                      }
                      setMenuFor(isOpen ? null : conversation.id);
                    }}
                  >
                    ⋯
                  </button>
                  {menuFor === conversation.id && (
                    <div
                      className={`chat-context-menu ${menuFlipUp ? "flip-up" : ""}`}
                      role="menu"
                    >
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setRenamingId(conversation.id);
                          setRenameDraft(conversation.title);
                          setMenuFor(null);
                        }}
                      >
                        Rename
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        className="danger"
                        onClick={() => void deleteConversation(conversation)}
                      >
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
        </nav>

        <div className="sidebar-bottom">
          <button type="button" onClick={() => openSettings("integrations")}>
            ⧉ Integrations
          </button>
          <button type="button" onClick={() => openSettings("data")}>
            ◌ Knowledge bases
          </button>
          <button type="button" onClick={() => openSettings("chat")}>
            ⌁ Models <em>Phase 2</em>
          </button>
          <button type="button" onClick={() => openSettings()}>
            ⚙ Settings
          </button>
        </div>
      </aside>

      <section className="chat-stage">
        <header className="chat-header">
          <button
            type="button"
            className="nav-toggle"
            aria-label="Open navigation"
            aria-expanded={navOpen}
            onClick={() => setNavOpen(true)}
          >
            ☰
          </button>
          <div className="chat-header-title">
            <p className="eyebrow">JAT ASSISTANT</p>
            <h2 title={headerTitle}>{headerTitle}</h2>
          </div>
          <div className="chat-header-actions">
            {active && (
              <button
                type="button"
                className="header-icon-btn"
                aria-label="Delete conversation"
                title="Delete conversation"
                onClick={() => void deleteConversation(active)}
              >
                ⌫
              </button>
            )}
            <select
              className="model-pill"
              aria-label="Conversation model"
              title="Switch the model for this chat"
              value={activeModel}
              disabled={!active}
              onChange={(event) => void changeModel(event.target.value)}
            >
              {modelOptions.length === 0 ? (
                <option value={activeModel}>{active?.model ?? "JaT development"}</option>
              ) : (
                modelOptions.map((option) => (
                  <option key={option.id} value={option.id} disabled={!option.available}>
                    {option.label}
                    {option.available ? "" : " (unavailable)"}
                  </option>
                ))
              )}
            </select>
          </div>
        </header>

        <div ref={messageListRef} className={messages.length ? "message-list" : "empty-chat"}>
          {messages.length ? (
            <>
              {messages.map((message, index) => (
                <article key={message.id ?? index} className={`message ${message.role}`}>
                  <span>
                    {message.role === "user" ? (
                      user.display_name.slice(0, 1).toUpperCase()
                    ) : (
                      <img src={logoUrl} alt="" className="message-logo" />
                    )}
                  </span>
                  <div>
                    {message.attachments && message.attachments.length > 0 && (
                      <ul className="message-attachments">
                        {message.attachments.map((file) => (
                          <li key={file.id}>
                            <span aria-hidden="true">📎</span>
                            {file.name}
                            <em>{formatBytes(file.size)}</em>
                          </li>
                        ))}
                      </ul>
                    )}
                    <p>{message.content}</p>
                    {message.role === "assistant" &&
                      message.status &&
                      message.status !== "complete" && (
                        <small className="message-status">
                          {message.status === "cancelled"
                            ? "Generation stopped"
                            : message.status === "failed"
                              ? "Generation failed"
                              : "Generating…"}
                        </small>
                      )}
                    {message.role === "assistant" &&
                      message.id &&
                      (message.status === "cancelled" || message.status === "failed") && (
                        <button
                          type="button"
                          className="retry-button"
                          disabled={sending}
                          onClick={() => void retry(message.id!)}
                        >
                          Retry response
                        </button>
                      )}
                  </div>
                </article>
              ))}
            </>
          ) : (
            <>
              <div className="orbit">
                <img src={logoUrl} alt="" className="orbit-logo" />
              </div>
              <p className="eyebrow">THE JAT FOUNDATION</p>
              <h1>How can I help?</h1>
              <p>Ask a question, attach a file, or connect GitHub from Settings → Integrations.</p>
              <div className="suggestions">
                <button type="button" onClick={() => setDraft("Explain the JaT architecture.")}>
                  Explore the architecture <span>↗</span>
                </button>
                <button type="button" onClick={() => setDraft("Review the security controls.")}>
                  Review security controls <span>↗</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    openSettings("integrations");
                  }}
                >
                  Connect GitHub <span>↗</span>
                </button>
              </div>
            </>
          )}
        </div>

        <div className="composer-shell">
          {attachments.length > 0 && (
            <ul className="attachment-list" aria-label="Attached files">
              {attachments.map((file) => (
                <li key={file.id}>
                  <span aria-hidden="true">📎</span>
                  <span className="attachment-name">{file.name}</span>
                  <em>{formatBytes(file.size)}</em>
                  <button
                    type="button"
                    aria-label={`Remove ${file.name}`}
                    onClick={() => removeAttachment(file.id)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          {composerError && (
            <p className="composer-error" role="alert">
              {composerError}
            </p>
          )}
          <div className="composer">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                void handleFiles(event.target.files);
              }}
            />
            <button
              type="button"
              className="composer-attach"
              aria-label="Add files"
              title="Add files"
              disabled={sending}
              onClick={() => fileInputRef.current?.click()}
            >
              ＋
            </button>
            <textarea
              ref={composerRef}
              value={draft}
              rows={1}
              onChange={(event) => {
                setDraft(event.target.value);
                const el = event.target;
                el.style.height = "auto";
                el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
              }}
              onKeyDown={onComposerKeyDown}
              placeholder="Ask JaT anything…"
              disabled={sending}
              aria-label="Message"
            />
            <button
              type="button"
              className={`composer-send ${canSend || sending ? "ready" : ""}`}
              onClick={() => {
                if (sending) {
                  streamController?.abort();
                  return;
                }
                void send();
              }}
              disabled={!sending && !canSend}
              aria-label={sending ? "Stop generating" : "Send message"}
              title={sending ? "Stop" : "Send"}
            >
              {sending ? "■" : "↑"}
            </button>
          </div>
          <p className="composer-hint">
            {preferences.send_on_enter ? "Enter to send · Shift+Enter for newline" : "⌘/Ctrl+Enter to send"}
            {" · "}
            Attach files with ＋
          </p>
        </div>
      </section>

      <aside className="profile-rail">
        <button
          type="button"
          className="avatar"
          onClick={() => setMenuOpen(!menuOpen)}
          aria-label="Open profile menu"
          aria-expanded={menuOpen}
        >
          {user.display_name.slice(0, 1).toUpperCase()}
        </button>
        {menuOpen && (
          <div className="profile-menu">
            <strong>{user.display_name}</strong>
            <small>{user.email}</small>
            <hr />
            <button type="button" onClick={() => openSettings()}>
              Settings
            </button>
            <button type="button" onClick={() => openSettings("integrations")}>
              Integrations
            </button>
            <button type="button" onClick={() => void newConversation()}>
              New chat
            </button>
            <hr />
            <button type="button" onClick={onLogout}>
              Sign out
            </button>
          </div>
        )}
      </aside>

      {navOpen && (
        <button
          type="button"
          className="nav-scrim"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
        />
      )}
      {menuFor && (
        <button
          type="button"
          className="menu-scrim"
          aria-label="Close menu"
          onClick={() => setMenuFor(null)}
        />
      )}
      {settingsOpen && (
        <SettingsPage
          token={token}
          user={user}
          preferences={preferences}
          initialTab={settingsTab}
          onPreferencesChange={onPreferencesChange}
          onProfileChange={onProfileChange}
          onClose={() => {
            setSettingsOpen(false);
            setSettingsTab(undefined);
          }}
          onSignedOut={onLogout}
        />
      )}
    </main>
  );
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

  useEffect(() => {
    void authApi
      .refresh()
      .then((session) => {
        setToken(session.access_token);
        setUser(session.user);
      })
      .catch(() => undefined);
  }, []);

  // Server preferences are authoritative once a session exists.
  useEffect(() => {
    if (!token) return;
    void settingsApi.get(token).then(updatePreferences).catch(() => undefined);
  }, [token, updatePreferences]);

  function signOut(): void {
    void authApi.logout().finally(() => {
      setToken(null);
      setUser(null);
    });
  }

  if (!token || !user) {
    return (
      <AuthScreen
        mode={mode}
        onModeChange={setMode}
        onAuthenticated={(nextToken, nextUser) => {
          setToken(nextToken);
          setUser(nextUser);
        }}
      />
    );
  }
  return (
    <Workspace
      user={user}
      token={token}
      onLogout={signOut}
      preferences={preferences}
      onPreferencesChange={updatePreferences}
      onProfileChange={setUser}
    />
  );
}
