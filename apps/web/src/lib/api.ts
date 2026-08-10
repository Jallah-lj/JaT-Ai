export type User = { id: string; email: string; display_name: string; kind: "person" | "guest" };
export type AuthSession = { access_token: string; token_type: "bearer"; user: User };

type ValidationIssue = { msg?: string; loc?: (string | number)[] };
type ApiProblem = { detail?: string | ValidationIssue[] | Record<string, unknown>; title?: string; code?: string };

/** FastAPI returns `detail` as a string for HTTPException, an array for validation errors. */
function problemMessage(problem: ApiProblem): string | undefined {
  const { detail } = problem;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const issue = detail[0];
    const field = issue.loc?.filter((part) => part !== "body").join(".");
    return field ? `${field}: ${issue.msg ?? "is invalid"}` : issue.msg;
  }
  if (detail && typeof detail === "object" && "detail" in detail) {
    const nested = (detail as { detail?: unknown }).detail;
    if (typeof nested === "string") return nested;
  }
  return problem.title;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Machine-readable code from the API problem envelope (e.g. "guest_limit_reached"). */
    readonly code?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    const problem = (await response.json().catch(() => ({}))) as ApiProblem;
    const code =
      typeof problem.code === "string"
        ? problem.code
        : problem.detail && typeof problem.detail === "object" && !Array.isArray(problem.detail)
          ? ((problem.detail as { code?: unknown }).code as string | undefined)
          : undefined;
    throw new ApiError(problemMessage(problem) ?? "Request failed", response.status, code);
  }
  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type Conversation = { id: string; title: string; model: string; created_at: string; updated_at: string };
export type ChatResult = { conversation_id: string; user_message_id: string; assistant_message_id: string; content: string; model: string };
export type StoredMessage = { id: string; role: string; status: "streaming" | "complete" | "cancelled" | "failed"; generation_id: string | null; content: string; created_at: string };

function authorized<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  return request<T>(path, { ...init, headers: { Authorization: `Bearer ${token}`, ...init.headers } });
}

export const conversationApi = {
  list: (token: string) => authorized<Conversation[]>("/conversations", token),
  create: (token: string, title = "New conversation", model?: string) =>
    authorized<Conversation>("/conversations", token, {
      method: "POST",
      body: JSON.stringify(model ? { title, model } : { title }),
    }),
  update: (token: string, conversationId: string, patch: { title?: string; model?: string }) =>
    authorized<Conversation>(`/conversations/${conversationId}`, token, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  remove: (token: string, conversationId: string) =>
    authorized<void>(`/conversations/${conversationId}`, token, { method: "DELETE" }),
  messages: (token: string, conversationId: string) =>
    authorized<StoredMessage[]>(`/conversations/${conversationId}/messages`, token),
};

export const chatApi = {
  send: (token: string, conversationId: string, content: string) =>
    authorized<ChatResult>("/chat", token, {
      method: "POST",
      body: JSON.stringify({ conversation_id: conversationId, content }),
    }),
  retry: (token: string, messageId: string) =>
    authorized<ChatResult>(`/chat/messages/${messageId}/retry`, token, { method: "POST" }),
  async stream(
    token: string,
    conversationId: string,
    content: string,
    onToken: (text: string) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const response = await fetch("/api/v1/chat/stream", {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ conversation_id: conversationId, content }),
    });
    if (!response.ok || !response.body) throw new ApiError("Unable to start response stream", response.status);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        if (frame.startsWith("event: token")) {
          const data = frame.split("\ndata: ")[1];
          if (data) onToken((JSON.parse(data) as { text: string }).text);
        }
      }
    }
  },
};

export type Theme = "light" | "dark" | "system";
export type Accent = "evergreen" | "citrus" | "ocean" | "violet" | "ember";
export type FontScale = "small" | "medium" | "large";
export type Density = "comfortable" | "compact";

export type Preferences = {
  theme: Theme;
  accent: Accent;
  font_scale: FontScale;
  density: Density;
  reduced_motion: boolean;
  default_model: string;
  stream_responses: boolean;
  send_on_enter: boolean;
  show_timestamps: boolean;
  temperature: number;
  max_tokens: number;
  system_prompt: string;
  memory_enabled: boolean;
  memories: string[];
  chat_history_enabled: boolean;
  analytics_enabled: boolean;
  sound_on_response: boolean;
  email_product_updates: boolean;
};

export type PreferencesPatch = Partial<Preferences>;
export type Profile = { id: string; email: string; display_name: string; created_at: string };
export type ModelOption = {
  id: string;
  label: string;
  description: string;
  provider: string;
  available: boolean;
  context_length: number;
};
export type SessionSummary = {
  id: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string;
  current: boolean;
};
export type UsageStats = {
  conversations: number;
  messages: number;
  input_tokens: number;
  output_tokens: number;
  first_activity_at: string | null;
  last_activity_at: string | null;
};
export type OperationResult = { ok: boolean; removed: number; detail: string };

export type IntegrationSummary = {
  id: string;
  provider: string;
  display_label: string | null;
  secret_hint: string;
  status: string;
  created_at: string;
  updated_at: string;
  last_verified_at: string | null;
};

export type ProviderCatalogItem = {
  id: string;
  name: string;
  description: string;
  auth_type: string;
  scopes_hint: string;
  docs_url: string;
  icon: string;
  connected: boolean;
  connection: IntegrationSummary | null;
};

export type IntegrationActionResult = {
  ok: boolean;
  detail: string;
  connection: IntegrationSummary | null;
};

export const DEFAULT_PREFERENCES: Preferences = {
  theme: "system",
  accent: "evergreen",
  font_scale: "medium",
  density: "comfortable",
  reduced_motion: false,
  default_model: "jat-development",
  stream_responses: true,
  send_on_enter: true,
  show_timestamps: false,
  temperature: 0.2,
  max_tokens: 1024,
  system_prompt: "",
  memory_enabled: true,
  memories: [],
  chat_history_enabled: true,
  analytics_enabled: false,
  sound_on_response: false,
  email_product_updates: false,
};

/** Minimum password length accepted by the API for register and password change. */
export const MIN_PASSWORD_LENGTH = 8;

export const settingsApi = {
  get: (token: string) => authorized<Preferences>("/settings", token),
  update: (token: string, patch: PreferencesPatch) =>
    authorized<Preferences>("/settings", token, { method: "PATCH", body: JSON.stringify(patch) }),
  reset: (token: string) => authorized<Preferences>("/settings/reset", token, { method: "POST" }),

  addMemory: (token: string, text: string) =>
    authorized<Preferences>("/settings/memories", token, { method: "POST", body: JSON.stringify({ text }) }),
  deleteMemory: (token: string, index: number) =>
    authorized<Preferences>(`/settings/memories/${index}`, token, { method: "DELETE" }),
  clearMemories: (token: string) =>
    authorized<Preferences>("/settings/memories", token, { method: "DELETE" }),

  profile: (token: string) => authorized<Profile>("/settings/profile", token),
  updateProfile: (token: string, patch: { display_name?: string; email?: string }) =>
    authorized<Profile>("/settings/profile", token, { method: "PATCH", body: JSON.stringify(patch) }),
  changePassword: (token: string, current_password: string, new_password: string) =>
    authorized<OperationResult>("/settings/password", token, {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),

  models: (token: string) => authorized<ModelOption[]>("/settings/models", token),
  sessions: (token: string) => authorized<SessionSummary[]>("/settings/sessions", token),
  revokeSession: (token: string, id: string) =>
    authorized<OperationResult>(`/settings/sessions/${id}`, token, { method: "DELETE" }),
  revokeOtherSessions: (token: string) =>
    authorized<OperationResult>("/settings/sessions/revoke-others", token, { method: "POST" }),

  usage: (token: string) => authorized<UsageStats>("/settings/usage", token),
  exportData: (token: string) => authorized<Record<string, unknown>>("/settings/export", token),
  deleteConversations: (token: string) =>
    authorized<OperationResult>("/settings/conversations", token, { method: "DELETE" }),
  deleteAccount: (token: string, password: string, confirmation: string) =>
    request<void>("/settings/delete-account", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ password, confirmation }),
    }),
};

export const integrationsApi = {
  catalog: (token: string) => authorized<ProviderCatalogItem[]>("/integrations/catalog", token),
  list: (token: string) => authorized<IntegrationSummary[]>("/integrations", token),
  connect: (
    token: string,
    payload: { provider: string; access_token: string; display_label?: string; account_url?: string },
  ) =>
    authorized<IntegrationActionResult>("/integrations", token, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  verify: (token: string, provider: string) =>
    authorized<IntegrationActionResult>(`/integrations/${provider}/verify`, token, { method: "POST" }),
  disconnect: (token: string, provider: string) =>
    authorized<IntegrationActionResult>(`/integrations/${provider}`, token, { method: "DELETE" }),
};

/** Trial-budget snapshot surfaced by the guest banner and sign-up prompts. */
export type GuestStatus = {
  enabled: boolean;
  kind: "anonymous" | "guest" | "person";
  message_limit: number;
  messages_used: number;
  conversation_limit: number;
  conversations: number;
  expires_at: string | null;
};

export const authApi = {
  register: (payload: {
    email: string;
    password: string;
    display_name: string;
    /** Access token of the guest session whose chats should carry over. */
    guest_token?: string;
  }) =>
    request<AuthSession>("/auth/register", { method: "POST", body: JSON.stringify(payload) }),
  login: (payload: { email: string; password: string }) =>
    request<AuthSession>("/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  refresh: () => request<AuthSession>("/auth/refresh", { method: "POST" }),
  me: (token: string) =>
    request<User>("/auth/me", { headers: { Authorization: `Bearer ${token}` } }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  /** Start an anonymous trial session — no email, no password. */
  guest: () => request<AuthSession>("/auth/guest", { method: "POST" }),
  guestStatus: (token?: string) =>
    request<GuestStatus>(
      "/auth/guest/status",
      token ? { headers: { Authorization: `Bearer ${token}` } } : undefined,
    ),
};
