export type User = { id: string; email: string; display_name: string };
export type AuthSession = { access_token: string; token_type: "bearer"; user: User };

type ApiProblem = { detail?: string; title?: string };

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
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
    throw new ApiError(problem.detail ?? problem.title ?? "Request failed", response.status);
  }
  return response.json() as Promise<T>;
}

export type Conversation = { id: string; title: string; model: string; created_at: string; updated_at: string };
export type ChatResult = { conversation_id: string; user_message_id: string; assistant_message_id: string; content: string; model: string };
export type StoredMessage = { id: string; role: string; status: "streaming" | "complete" | "cancelled" | "failed"; generation_id: string | null; content: string; created_at: string };

function authorized<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  return request<T>(path, { ...init, headers: { Authorization: `Bearer ${token}`, ...init.headers } });
}

export const conversationApi = {
  list: (token: string) => authorized<Conversation[]>("/conversations", token),
  create: (token: string, title = "New conversation") => authorized<Conversation>("/conversations", token, { method: "POST", body: JSON.stringify({ title }) }),
  messages: (token: string, conversationId: string) => authorized<StoredMessage[]>(`/conversations/${conversationId}/messages`, token),
};

export const chatApi = {
  send: (token: string, conversationId: string, content: string) => authorized<ChatResult>("/chat", token, { method: "POST", body: JSON.stringify({ conversation_id: conversationId, content }) }),
  retry: (token: string, messageId: string) => authorized<ChatResult>(`/chat/messages/${messageId}/retry`, token, { method: "POST" }),
  async stream(token: string, conversationId: string, content: string, onToken: (text: string) => void, signal: AbortSignal): Promise<void> {
    const response = await fetch("/api/v1/chat/stream", { method: "POST", signal, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ conversation_id: conversationId, content }) });
    if (!response.ok || !response.body) throw new ApiError("Unable to start response stream", response.status);
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    while (true) { const { done, value } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); const frames = buffer.split("\n\n"); buffer = frames.pop() ?? ""; for (const frame of frames) { if (frame.startsWith("event: token")) { const data = frame.split("\ndata: ")[1]; if (data) onToken((JSON.parse(data) as { text: string }).text); } } }
  },
};

export type Preferences = { theme: "light" | "dark" | "system"; stream_responses: boolean; default_model: string; memory_enabled: boolean; chat_history_enabled: boolean; analytics_enabled: boolean; reduced_motion: boolean };
export const settingsApi = { get: (token: string) => authorized<Preferences>("/settings", token), save: (token: string, preferences: Preferences) => authorized<Preferences>("/settings", token, { method: "PATCH", body: JSON.stringify(preferences) }) };

export const authApi = {
  register: (payload: { email: string; password: string; display_name: string }) =>
    request<AuthSession>("/auth/register", { method: "POST", body: JSON.stringify(payload) }),
  login: (payload: { email: string; password: string }) =>
    request<AuthSession>("/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  refresh: () => request<AuthSession>("/auth/refresh", { method: "POST" }),
  me: (token: string) =>
    request<User>("/auth/me", { headers: { Authorization: `Bearer ${token}` } }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
};
