import { ReactElement, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  integrationsApi,
  MIN_PASSWORD_LENGTH,
  settingsApi,
  type Accent,
  type Density,
  type FontScale,
  type ModelOption,
  type Preferences,
  type PreferencesPatch,
  type Profile,
  type ProviderCatalogItem,
  type SessionSummary,
  type Theme,
  type UsageStats,
  type User,
} from "../../lib/api";
import { Row, SegmentedControl, Section, Toggle } from "./fields";

type TabId = "general" | "appearance" | "chat" | "memory" | "integrations" | "account" | "data";

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: "general", label: "General", icon: "◎" },
  { id: "appearance", label: "Appearance", icon: "◐" },
  { id: "chat", label: "Chat", icon: "✦" },
  { id: "memory", label: "Memory", icon: "◈" },
  { id: "integrations", label: "Integrations", icon: "⧉" },
  { id: "account", label: "Account", icon: "⬡" },
  { id: "data", label: "Data controls", icon: "⛁" },
];

const ACCENTS: { value: Accent; label: string }[] = [
  { value: "evergreen", label: "Evergreen" },
  { value: "citrus", label: "Citrus" },
  { value: "ocean", label: "Ocean" },
  { value: "violet", label: "Violet" },
  { value: "ember", label: "Ember" },
];

function errorMessage(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export type SettingsPageProps = {
  token: string;
  user: User;
  preferences: Preferences;
  initialTab?: string;
  onPreferencesChange: (preferences: Preferences) => void;
  onProfileChange: (user: User) => void;
  onClose: () => void;
  onSignedOut: () => void;
};

function resolveTab(value: string | undefined): TabId {
  const match = TABS.find((tab) => tab.id === value);
  return match?.id ?? "general";
}

export function SettingsPage({
  token,
  user,
  preferences,
  initialTab,
  onPreferencesChange,
  onProfileChange,
  onClose,
  onSignedOut,
}: SettingsPageProps): ReactElement {
  const [tab, setTab] = useState<TabId>(() => resolveTab(initialTab));
  const [status, setStatus] = useState<{ kind: "saved" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const statusTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const announce = useCallback((kind: "saved" | "error", text: string) => {
    setStatus({ kind, text });
    if (statusTimer.current) clearTimeout(statusTimer.current);
    statusTimer.current = setTimeout(() => setStatus(null), 4000);
  }, []);

  useEffect(() => () => {
    if (statusTimer.current) clearTimeout(statusTimer.current);
  }, []);

  /** Optimistically apply a change, then persist it; roll back if the server rejects. */
  const persist = useCallback(
    async (patch: PreferencesPatch, successText = "Saved") => {
      const previous = preferences;
      onPreferencesChange({ ...preferences, ...patch });
      try {
        const saved = await settingsApi.update(token, patch);
        onPreferencesChange(saved);
        announce("saved", successText);
      } catch (caught) {
        onPreferencesChange(previous);
        announce("error", errorMessage(caught, "Could not save that change"));
      }
    },
    [announce, onPreferencesChange, preferences, token],
  );

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  useEffect(() => {
    if (initialTab) setTab(resolveTab(initialTab));
  }, [initialTab]);

  return (
    <div
      className="settings-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Settings"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="settings-panel" ref={panelRef} tabIndex={-1}>
        <header className="settings-header">
          <div>
            <p className="eyebrow">PREFERENCES</p>
            <h2>Settings</h2>
          </div>
          <div className="settings-header-actions">
            <span
              role="status"
              aria-live="polite"
              className={`save-status ${status ? status.kind : ""}`}
            >
              {status?.text ?? ""}
            </span>
            <button className="close-settings" onClick={onClose} aria-label="Close settings">
              ×
            </button>
          </div>
        </header>

        <nav className="settings-nav" aria-label="Settings sections">
          {TABS.map((item) => (
            <button
              key={item.id}
              className={tab === item.id ? "selected" : ""}
              aria-current={tab === item.id ? "page" : undefined}
              onClick={() => setTab(item.id)}
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          {tab === "general" && (
            <GeneralTab
              token={token}
              user={user}
              preferences={preferences}
              persist={persist}
              onProfileChange={onProfileChange}
              announce={announce}
              busy={busy}
              setBusy={setBusy}
            />
          )}
          {tab === "appearance" && (
            <AppearanceTab preferences={preferences} persist={persist} />
          )}
          {tab === "chat" && <ChatTab token={token} preferences={preferences} persist={persist} />}
          {tab === "memory" && (
            <MemoryTab
              token={token}
              preferences={preferences}
              persist={persist}
              onPreferencesChange={onPreferencesChange}
              announce={announce}
            />
          )}
          {tab === "integrations" && (
            <IntegrationsTab token={token} announce={announce} />
          )}
          {tab === "account" && (
            <AccountTab token={token} announce={announce} onSignedOut={onSignedOut} />
          )}
          {tab === "data" && (
            <DataTab
              token={token}
              preferences={preferences}
              persist={persist}
              announce={announce}
              onSignedOut={onSignedOut}
            />
          )}
        </div>
      </section>
    </div>
  );
}

// ------------------------------------------------------------------ General

function GeneralTab({
  token,
  user,
  preferences,
  persist,
  onProfileChange,
  announce,
  busy,
  setBusy,
}: {
  token: string;
  user: User;
  preferences: Preferences;
  persist: (patch: PreferencesPatch, text?: string) => Promise<void>;
  onProfileChange: (user: User) => void;
  announce: (kind: "saved" | "error", text: string) => void;
  busy: boolean;
  setBusy: (value: boolean) => void;
}): ReactElement {
  const [displayName, setDisplayName] = useState(user.display_name);
  const [email, setEmail] = useState(user.email);

  useEffect(() => {
    setDisplayName(user.display_name);
    setEmail(user.email);
  }, [user.display_name, user.email]);

  const dirty = displayName.trim() !== user.display_name || email.trim() !== user.email;

  async function saveProfile(): Promise<void> {
    setBusy(true);
    try {
      const profile: Profile = await settingsApi.updateProfile(token, {
        display_name: displayName.trim(),
        email: email.trim(),
      });
      onProfileChange({
        id: profile.id,
        email: profile.email,
        display_name: profile.display_name,
        // Profile settings are person-only (guests are rejected upstream).
        kind: "person",
      });
      announce("saved", "Profile updated");
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not update your profile"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Section title="Profile" description="How JaT identifies you across the workspace.">
        <Row label="Display name" htmlFor="display-name" stacked>
          <input
            id="display-name"
            value={displayName}
            maxLength={120}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="Your name"
          />
        </Row>
        <Row label="Email address" htmlFor="email" hint="Used to sign in." stacked>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
          />
        </Row>
        <div className="row-actions">
          <button
            className="primary-action"
            disabled={!dirty || busy || !displayName.trim() || !email.trim()}
            onClick={() => void saveProfile()}
          >
            {busy ? "Saving…" : "Save profile"}
          </button>
          {dirty && (
            <button
              className="ghost-action"
              onClick={() => {
                setDisplayName(user.display_name);
                setEmail(user.email);
              }}
            >
              Discard
            </button>
          )}
        </div>
      </Section>

      <Section title="Notifications" description="Quiet by default; enable only what helps.">
        <Row label="Sound on response" hint="Play a soft chime when a reply finishes.">
          <Toggle
            label="Sound on response"
            checked={preferences.sound_on_response}
            onChange={(value) => void persist({ sound_on_response: value })}
          />
        </Row>
        <Row label="Product updates" hint="Occasional email about new JaT capabilities.">
          <Toggle
            label="Product updates"
            checked={preferences.email_product_updates}
            onChange={(value) => void persist({ email_product_updates: value })}
          />
        </Row>
      </Section>
    </>
  );
}

// ------------------------------------------------------------------ Appearance

function AppearanceTab({
  preferences,
  persist,
}: {
  preferences: Preferences;
  persist: (patch: PreferencesPatch, text?: string) => Promise<void>;
}): ReactElement {
  return (
    <>
      <Section title="Theme" description="Applies instantly across the whole workspace.">
        <Row label="Colour mode">
          <SegmentedControl<Theme>
            label="Colour mode"
            value={preferences.theme}
            onChange={(value) => void persist({ theme: value })}
            options={[
              { value: "light", label: "Light" },
              { value: "dark", label: "Dark" },
              { value: "system", label: "System" },
            ]}
          />
        </Row>
        <Row label="Accent colour" hint="Used for highlights, focus rings, and actions." stacked>
          <div className="accent-picker" role="radiogroup" aria-label="Accent colour">
            {ACCENTS.map((accent) => (
              <button
                key={accent.value}
                type="button"
                role="radio"
                aria-checked={preferences.accent === accent.value}
                aria-label={accent.label}
                title={accent.label}
                data-accent={accent.value}
                className={`accent-swatch ${preferences.accent === accent.value ? "selected" : ""}`}
                onClick={() => void persist({ accent: accent.value })}
              />
            ))}
          </div>
        </Row>
      </Section>

      <Section title="Layout" description="Tune reading comfort and information density.">
        <Row label="Text size">
          <SegmentedControl<FontScale>
            label="Text size"
            value={preferences.font_scale}
            onChange={(value) => void persist({ font_scale: value })}
            options={[
              { value: "small", label: "Small" },
              { value: "medium", label: "Medium" },
              { value: "large", label: "Large" },
            ]}
          />
        </Row>
        <Row label="Density">
          <SegmentedControl<Density>
            label="Density"
            value={preferences.density}
            onChange={(value) => void persist({ density: value })}
            options={[
              { value: "comfortable", label: "Comfortable" },
              { value: "compact", label: "Compact" },
            ]}
          />
        </Row>
        <Row label="Reduce motion" hint="Minimise animations and transitions.">
          <Toggle
            label="Reduce motion"
            checked={preferences.reduced_motion}
            onChange={(value) => void persist({ reduced_motion: value })}
          />
        </Row>
      </Section>
    </>
  );
}

// ------------------------------------------------------------------ Chat

function ChatTab({
  token,
  preferences,
  persist,
}: {
  token: string;
  preferences: Preferences;
  persist: (patch: PreferencesPatch, text?: string) => Promise<void>;
}): ReactElement {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [prompt, setPrompt] = useState(preferences.system_prompt);

  useEffect(() => {
    void settingsApi
      .models(token)
      .then(setModels)
      .catch(() => setModels([]));
  }, [token]);

  useEffect(() => setPrompt(preferences.system_prompt), [preferences.system_prompt]);

  const promptDirty = prompt !== preferences.system_prompt;

  return (
    <>
      <Section title="Model" description="Provider-neutral selection served by the API.">
        <Row label="Default model" htmlFor="model" stacked>
          <select
            id="model"
            value={preferences.default_model}
            onChange={(event) => void persist({ default_model: event.target.value })}
          >
            {models.length === 0 && <option value={preferences.default_model}>Loading…</option>}
            {models.map((model) => (
              <option key={model.id} value={model.id} disabled={!model.available}>
                {model.label}
                {model.available ? "" : " (unavailable)"}
              </option>
            ))}
          </select>
          {models.find((model) => model.id === preferences.default_model)?.description && (
            <p className="field-hint">
              {models.find((model) => model.id === preferences.default_model)?.description}
            </p>
          )}
        </Row>

        <Row
          label={`Temperature — ${preferences.temperature.toFixed(2)}`}
          hint="Lower is more focused, higher is more exploratory."
          htmlFor="temperature"
          stacked
        >
          <input
            id="temperature"
            type="range"
            min={0}
            max={2}
            step={0.05}
            value={preferences.temperature}
            onChange={(event) =>
              void persist({ temperature: Number(event.target.value) })
            }
          />
        </Row>

        <Row
          label={`Max response tokens — ${preferences.max_tokens}`}
          hint="Upper bound on the length of a single reply."
          htmlFor="max-tokens"
          stacked
        >
          <input
            id="max-tokens"
            type="range"
            min={64}
            max={16384}
            step={64}
            value={preferences.max_tokens}
            onChange={(event) => void persist({ max_tokens: Number(event.target.value) })}
          />
        </Row>
      </Section>

      <Section title="System prompt" description="Guidance prepended to every conversation.">
        <Row label="Custom instructions" htmlFor="system-prompt" stacked>
          <textarea
            id="system-prompt"
            rows={5}
            maxLength={4000}
            value={prompt}
            placeholder="e.g. Answer concisely and cite trade-offs."
            onChange={(event) => setPrompt(event.target.value)}
          />
          <p className="field-hint">{prompt.length} / 4000</p>
        </Row>
        <div className="row-actions">
          <button
            className="primary-action"
            disabled={!promptDirty}
            onClick={() => void persist({ system_prompt: prompt }, "Instructions saved")}
          >
            Save instructions
          </button>
          {promptDirty && (
            <button className="ghost-action" onClick={() => setPrompt(preferences.system_prompt)}>
              Discard
            </button>
          )}
        </div>
      </Section>

      <Section title="Behaviour">
        <Row label="Stream responses" hint="Show replies token by token as they generate.">
          <Toggle
            label="Stream responses"
            checked={preferences.stream_responses}
            onChange={(value) => void persist({ stream_responses: value })}
          />
        </Row>
        <Row label="Send with Enter" hint="Off means Enter adds a newline and ⌘/Ctrl+Enter sends.">
          <Toggle
            label="Send with Enter"
            checked={preferences.send_on_enter}
            onChange={(value) => void persist({ send_on_enter: value })}
          />
        </Row>
        <Row label="Show timestamps" hint="Display the time beside each message.">
          <Toggle
            label="Show timestamps"
            checked={preferences.show_timestamps}
            onChange={(value) => void persist({ show_timestamps: value })}
          />
        </Row>
      </Section>
    </>
  );
}

// ------------------------------------------------------------------ Memory

function MemoryTab({
  token,
  preferences,
  persist,
  onPreferencesChange,
  announce,
}: {
  token: string;
  preferences: Preferences;
  persist: (patch: PreferencesPatch, text?: string) => Promise<void>;
  onPreferencesChange: (preferences: Preferences) => void;
  announce: (kind: "saved" | "error", text: string) => void;
}): ReactElement {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  async function addMemory(): Promise<void> {
    const text = draft.trim();
    if (!text) return;
    setBusy(true);
    try {
      onPreferencesChange(await settingsApi.addMemory(token, text));
      setDraft("");
      announce("saved", "Memory added");
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not add that memory"));
    } finally {
      setBusy(false);
    }
  }

  async function removeMemory(index: number): Promise<void> {
    try {
      onPreferencesChange(await settingsApi.deleteMemory(token, index));
      announce("saved", "Memory removed");
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not remove that memory"));
    }
  }

  async function clearAll(): Promise<void> {
    if (!confirm("Forget every stored memory? This cannot be undone.")) return;
    try {
      onPreferencesChange(await settingsApi.clearMemories(token));
      announce("saved", "All memories cleared");
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not clear memories"));
    }
  }

  return (
    <>
      <Section
        title="Conversation memory"
        description="Facts JaT may reuse to personalise future answers."
      >
        <Row label="Enable memory" hint="Turn off to stop JaT referencing stored facts.">
          <Toggle
            label="Enable memory"
            checked={preferences.memory_enabled}
            onChange={(value) => void persist({ memory_enabled: value })}
          />
        </Row>
      </Section>

      <Section title="Stored memories" description={`${preferences.memories.length} of 50 saved.`}>
        <div className="memory-add">
          <input
            value={draft}
            maxLength={500}
            disabled={!preferences.memory_enabled}
            placeholder="e.g. Prefers TypeScript examples"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void addMemory();
              }
            }}
            aria-label="New memory"
          />
          <button
            className="primary-action"
            disabled={!draft.trim() || busy || !preferences.memory_enabled}
            onClick={() => void addMemory()}
          >
            Add
          </button>
        </div>

        {preferences.memories.length === 0 ? (
          <p className="empty-note">
            No memories yet. Anything you add here is available to future conversations.
          </p>
        ) : (
          <ul className="memory-list">
            {preferences.memories.map((memory, index) => (
              <li key={`${memory}-${index}`}>
                <span>{memory}</span>
                <button
                  className="icon-action"
                  aria-label={`Forget memory: ${memory}`}
                  onClick={() => void removeMemory(index)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}

        {preferences.memories.length > 0 && (
          <div className="row-actions">
            <button className="danger-action" onClick={() => void clearAll()}>
              Forget all memories
            </button>
          </div>
        )}
      </Section>
    </>
  );
}

// ------------------------------------------------------------------ Integrations

function IntegrationsTab({
  token,
  announce,
}: {
  token: string;
  announce: (kind: "saved" | "error", text: string) => void;
}): ReactElement {
  const [catalog, setCatalog] = useState<ProviderCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [tokenDraft, setTokenDraft] = useState("");
  const [labelDraft, setLabelDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    void integrationsApi
      .catalog(token)
      .then(setCatalog)
      .catch(() => setCatalog([]))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(load, [load]);

  async function connect(provider: string): Promise<void> {
    if (tokenDraft.trim().length < 8) {
      announce("error", "Paste an access token of at least 8 characters");
      return;
    }
    setBusy(true);
    try {
      const result = await integrationsApi.connect(token, {
        provider,
        access_token: tokenDraft.trim(),
        display_label: labelDraft.trim() || undefined,
      });
      setTokenDraft("");
      setLabelDraft("");
      setConnecting(null);
      load();
      announce("saved", result.detail || "Connected");
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not connect that integration"));
    } finally {
      setBusy(false);
    }
  }

  async function disconnect(provider: string, name: string): Promise<void> {
    if (!confirm(`Disconnect ${name}? JaT will stop using that account.`)) return;
    try {
      const result = await integrationsApi.disconnect(token, provider);
      load();
      announce("saved", result.detail || "Disconnected");
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not disconnect"));
    }
  }

  async function verify(provider: string): Promise<void> {
    try {
      const result = await integrationsApi.verify(token, provider);
      load();
      announce("saved", result.detail || "Verified");
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not verify that connection"));
    }
  }

  return (
    <>
      <Section
        title="Connected systems"
        description="Link GitHub and other tools so JaT can work across your stack. Tokens are stored hashed and never shown again."
      >
        {loading ? (
          <p className="empty-note">Loading integrations…</p>
        ) : (
          <ul className="integration-list">
            {catalog.map((item) => (
              <li key={item.id} className={item.connected ? "connected" : ""}>
                <div className="integration-head">
                  <div className="integration-icon" aria-hidden="true">
                    {item.icon === "github"
                      ? "⌥"
                      : item.icon === "gitlab"
                        ? "⑂"
                        : item.icon === "slack"
                          ? "#"
                          : item.icon === "notion"
                            ? "N"
                            : item.icon === "linear"
                              ? "L"
                              : "☁"}
                  </div>
                  <div>
                    <strong>
                      {item.name}
                      {item.connected && <span className="badge">Connected</span>}
                    </strong>
                    <p>{item.description}</p>
                    {item.connected && item.connection && (
                      <p className="field-hint">
                        Token ending ···{item.connection.secret_hint}
                        {item.connection.display_label
                          ? ` · ${item.connection.display_label}`
                          : ""}
                      </p>
                    )}
                  </div>
                </div>

                {connecting === item.id ? (
                  <div className="integration-connect-form">
                    <Row
                      label="Access token"
                      htmlFor={`token-${item.id}`}
                      hint={`Scopes: ${item.scopes_hint}`}
                      stacked
                    >
                      <input
                        id={`token-${item.id}`}
                        type="password"
                        autoComplete="off"
                        value={tokenDraft}
                        placeholder="Paste personal access token"
                        onChange={(event) => setTokenDraft(event.target.value)}
                      />
                    </Row>
                    <Row label="Label (optional)" htmlFor={`label-${item.id}`} stacked>
                      <input
                        id={`label-${item.id}`}
                        value={labelDraft}
                        placeholder="e.g. Work account"
                        onChange={(event) => setLabelDraft(event.target.value)}
                      />
                    </Row>
                    <div className="row-actions">
                      <button
                        className="primary-action"
                        disabled={busy || tokenDraft.trim().length < 8}
                        onClick={() => void connect(item.id)}
                      >
                        {busy ? "Connecting…" : item.connected ? "Update token" : "Connect"}
                      </button>
                      <button
                        className="ghost-action"
                        onClick={() => {
                          setConnecting(null);
                          setTokenDraft("");
                          setLabelDraft("");
                        }}
                      >
                        Cancel
                      </button>
                      <a
                        className="ghost-action link-action"
                        href={item.docs_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Get a token ↗
                      </a>
                    </div>
                  </div>
                ) : (
                  <div className="row-actions">
                    {item.connected ? (
                      <>
                        <button className="ghost-action" onClick={() => void verify(item.id)}>
                          Verify
                        </button>
                        <button
                          className="ghost-action"
                          onClick={() => {
                            setConnecting(item.id);
                            setTokenDraft("");
                            setLabelDraft(item.connection?.display_label ?? "");
                          }}
                        >
                          Update
                        </button>
                        <button
                          className="danger-action"
                          onClick={() => void disconnect(item.id, item.name)}
                        >
                          Disconnect
                        </button>
                      </>
                    ) : (
                      <button
                        className="primary-action"
                        onClick={() => {
                          setConnecting(item.id);
                          setTokenDraft("");
                          setLabelDraft("");
                        }}
                      >
                        Connect
                      </button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}

// ------------------------------------------------------------------ Account

function AccountTab({
  token,
  announce,
  onSignedOut,
}: {
  token: string;
  announce: (kind: "saved" | "error", text: string) => void;
  onSignedOut: () => void;
}): ReactElement {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [busy, setBusy] = useState(false);

  const loadSessions = useCallback(() => {
    void settingsApi
      .sessions(token)
      .then(setSessions)
      .catch(() => setSessions([]));
  }, [token]);

  useEffect(loadSessions, [loadSessions]);

  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword;
  const tooShort = newPassword.length > 0 && newPassword.length < MIN_PASSWORD_LENGTH;
  const canSubmit =
    currentPassword.length > 0 &&
    newPassword.length >= MIN_PASSWORD_LENGTH &&
    newPassword === confirmPassword;

  async function changePassword(): Promise<void> {
    setBusy(true);
    try {
      const result = await settingsApi.changePassword(token, currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      loadSessions();
      announce("saved", result.detail || "Password updated");
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not change your password"));
    } finally {
      setBusy(false);
    }
  }

  async function revokeOthers(): Promise<void> {
    try {
      const result = await settingsApi.revokeOtherSessions(token);
      loadSessions();
      announce("saved", `${result.removed} other session(s) signed out`);
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not sign out other sessions"));
    }
  }

  async function revokeOne(session: SessionSummary): Promise<void> {
    try {
      await settingsApi.revokeSession(token, session.id);
      if (session.current) {
        onSignedOut();
        return;
      }
      loadSessions();
      announce("saved", "Session signed out");
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not sign out that session"));
    }
  }

  return (
    <>
      <Section title="Password" description="Changing it signs out every other device.">
        <Row label="Current password" htmlFor="current-password" stacked>
          <input
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
        </Row>
        <Row
          label="New password"
          htmlFor="new-password"
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          stacked
        >
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            aria-invalid={tooShort}
          />
          {tooShort && (
            <p className="field-error">Use at least {MIN_PASSWORD_LENGTH} characters.</p>
          )}
        </Row>
        <Row label="Confirm new password" htmlFor="confirm-password" stacked>
          <input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            aria-invalid={mismatch}
          />
          {mismatch && <p className="field-error">Passwords do not match.</p>}
        </Row>
        <div className="row-actions">
          <button
            className="primary-action"
            disabled={!canSubmit || busy}
            onClick={() => void changePassword()}
          >
            {busy ? "Updating…" : "Update password"}
          </button>
        </div>
      </Section>

      <Section title="Active sessions" description="Devices with a valid refresh session.">
        {sessions.length === 0 ? (
          <p className="empty-note">No active sessions found.</p>
        ) : (
          <ul className="session-list">
            {sessions.map((session) => (
              <li key={session.id}>
                <div>
                  <strong>
                    {session.current ? "This device" : "Other device"}
                    {session.current && <span className="badge">Current</span>}
                  </strong>
                  <p>
                    Started {formatDate(session.created_at)} · Expires{" "}
                    {formatDate(session.expires_at)}
                  </p>
                </div>
                <button className="ghost-action" onClick={() => void revokeOne(session)}>
                  {session.current ? "Sign out" : "Revoke"}
                </button>
              </li>
            ))}
          </ul>
        )}
        {sessions.some((session) => !session.current) && (
          <div className="row-actions">
            <button className="danger-action" onClick={() => void revokeOthers()}>
              Sign out all other sessions
            </button>
          </div>
        )}
      </Section>
    </>
  );
}

// ------------------------------------------------------------------ Data controls

function DataTab({
  token,
  preferences,
  persist,
  announce,
  onSignedOut,
}: {
  token: string;
  preferences: Preferences;
  persist: (patch: PreferencesPatch, text?: string) => Promise<void>;
  announce: (kind: "saved" | "error", text: string) => void;
  onSignedOut: () => void;
}): ReactElement {
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showDelete, setShowDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  const loadUsage = useCallback(() => {
    void settingsApi
      .usage(token)
      .then(setUsage)
      .catch(() => setUsage(null));
  }, [token]);

  useEffect(loadUsage, [loadUsage]);

  const totalTokens = useMemo(
    () => (usage ? usage.input_tokens + usage.output_tokens : 0),
    [usage],
  );

  async function exportData(): Promise<void> {
    try {
      const payload = await settingsApi.exportData(token);
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `jat-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      announce("saved", "Export downloaded");
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not export your data"));
    }
  }

  async function deleteConversations(): Promise<void> {
    if (!confirm("Permanently delete every conversation? This cannot be undone.")) return;
    try {
      const result = await settingsApi.deleteConversations(token);
      loadUsage();
      announce("saved", `${result.removed} conversation(s) deleted`);
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not delete conversations"));
    }
  }

  async function deleteAccount(): Promise<void> {
    setBusy(true);
    try {
      await settingsApi.deleteAccount(token, password, confirmation);
      onSignedOut();
    } catch (caught) {
      announce("error", errorMessage(caught, "Could not delete your account"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Section title="Usage" description="Activity recorded for this workspace.">
        <div className="usage-grid">
          <div>
            <strong>{usage?.conversations ?? "—"}</strong>
            <span>Conversations</span>
          </div>
          <div>
            <strong>{usage?.messages ?? "—"}</strong>
            <span>Messages</span>
          </div>
          <div>
            <strong>{usage ? totalTokens.toLocaleString() : "—"}</strong>
            <span>Tokens</span>
          </div>
          <div>
            <strong className="stat-date">{formatDate(usage?.last_activity_at ?? null)}</strong>
            <span>Last activity</span>
          </div>
        </div>
      </Section>

      <Section title="Privacy" description="You control what JaT keeps and measures.">
        <Row label="Save chat history" hint="Turn off to stop retaining new conversations.">
          <Toggle
            label="Save chat history"
            checked={preferences.chat_history_enabled}
            onChange={(value) => void persist({ chat_history_enabled: value })}
          />
        </Row>
        <Row label="Product analytics" hint="Share anonymous usage data to improve JaT.">
          <Toggle
            label="Product analytics"
            checked={preferences.analytics_enabled}
            onChange={(value) => void persist({ analytics_enabled: value })}
          />
        </Row>
      </Section>

      <Section title="Your data" description="Export or remove the data JaT holds for you.">
        <Row label="Export data" hint="Download conversations and preferences as JSON.">
          <button className="ghost-action" onClick={() => void exportData()}>
            Export
          </button>
        </Row>
        <Row label="Delete conversations" hint="Removes every conversation and message.">
          <button className="danger-action" onClick={() => void deleteConversations()}>
            Delete all
          </button>
        </Row>
      </Section>

      <Section title="Danger zone" description="Irreversible actions.">
        <div className="danger-zone">
          <div>
            <strong>Delete account</strong>
            <p>Your account is deactivated and its conversations are permanently removed.</p>
          </div>
          {!showDelete ? (
            <button className="danger-action" onClick={() => setShowDelete(true)}>
              Delete account
            </button>
          ) : (
            <div className="delete-confirm">
              <label htmlFor="delete-password">Confirm your password</label>
              <input
                id="delete-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <label htmlFor="delete-confirmation">Type DELETE to confirm</label>
              <input
                id="delete-confirmation"
                value={confirmation}
                placeholder="DELETE"
                onChange={(event) => setConfirmation(event.target.value)}
              />
              <div className="row-actions">
                <button
                  className="danger-action"
                  disabled={!password || confirmation.trim().toUpperCase() !== "DELETE" || busy}
                  onClick={() => void deleteAccount()}
                >
                  {busy ? "Deleting…" : "Permanently delete"}
                </button>
                <button
                  className="ghost-action"
                  onClick={() => {
                    setShowDelete(false);
                    setPassword("");
                    setConfirmation("");
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </Section>
    </>
  );
}
