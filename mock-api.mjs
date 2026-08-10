/**
 * JaT demo mock API — lets the web UI be explored without Postgres/Redis/Ollama.
 *
 * Implements just enough of the API contract to walk the guest-trial journey:
 * anonymous status probe, guest session start, chat streaming, quota counting,
 * and account conversion. All state is in-memory and per-process.
 *
 * Run: node mock-api.mjs   (listens on 0.0.0.0:8000)
 */
import http from "node:http";
import { randomUUID } from "node:crypto";

const PORT = Number(process.env.PORT || 8000);
const GUEST_LIMIT = Number(process.env.GUEST_LIMIT || 10);
const GUEST_TTL_HOURS = 24;

const state = {
  guests: new Map(), // id -> { used, conversations, created_at }
  people: new Map(), // id -> { email, display_name, conversations }
};

const DEFAULT_PREFS = {
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

const MODELS = [
  { id: "jat-development", label: "JaT Development", description: "Fast, local preview model", provider: "ollama", available: true, context_length: 8192 },
  { id: "llama3.1:latest", label: "Llama 3.1", description: "General-purpose instruct model", provider: "ollama", available: true, context_length: 8192 },
  { id: "mistral:7b", label: "Mistral 7B", description: "Fast and lightweight", provider: "ollama", available: false, context_length: 4096 },
];

const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };

function json(res, status, body) {
  res.writeHead(status, JSON_HEADERS);
  res.end(JSON.stringify(body));
}

function guestUser(id) {
  return { id, email: `guest-${id.slice(0, 8)}@guest.jat.local`, display_name: "Guest", kind: "guest" };
}

function personUser(id, email, display_name) {
  return { id, email, display_name, kind: "person" };
}

function tokenFor(user) {
  const id = typeof user === "string" ? user : user.id;
  return `mock-token-${id}`;
}

function identity(req) {
  const auth = req.headers.authorization || "";
  const token = auth.replace(/^Bearer /, "");
  if (!token.startsWith("mock-token-")) return null;
  const id = token.slice("mock-token-".length);
  if (state.guests.has(id)) {
    const g = state.guests.get(id);
    return { user: guestUser(id), guest: g };
  }
  if (state.people.has(id)) return { user: personUser(id, ...state.people.get(id)), guest: null };
  return null;
}

function guestStatusBody(identityEntry) {
  if (identityEntry) {
    const { user, guest } = identityEntry;
    if (user.kind === "guest") {
      return {
        enabled: true,
        kind: "guest",
        message_limit: GUEST_LIMIT,
        messages_used: guest.used,
        conversation_limit: 5,
        conversations: guest.conversations.size,
        expires_at: new Date(guest.created_at + GUEST_TTL_HOURS * 3600_000).toISOString(),
      };
    }
    return { enabled: true, kind: "person", message_limit: GUEST_LIMIT, messages_used: 0, conversation_limit: 5, conversations: 0, expires_at: null };
  }
  return { enabled: true, kind: "anonymous", message_limit: GUEST_LIMIT, messages_used: 0, conversation_limit: 5, conversations: 0, expires_at: null };
}

function readBody(req) {
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
    });
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        resolve({});
      }
    });
  });
}

function makeConversation(id, title, model) {
  return {
    id,
    title,
    model: model || "jat-development",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

const TICK = "▏▎▍▌▋▊▉█";

function sampleReply(text) {
  const subject = (text || "this").replace(/\s+/g, " ").slice(0, 60);
  return [
    `Great question about “${subject}”. `,
    `Here's what I'd suggest: start from first principles, keep the scope small, and validate early. `,
    `For JaT specifically, the architecture separates identity, conversations, and model providers, so you can swap models without touching chat history. `,
    `Try asking a follow-up, or attach a file — and remember this is a free trial demo, so feel free to explore.`,
  ].join("");
}

async function handler(req, res) {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  const path = url.pathname;
  const method = req.method;
  const ident = identity(req);

  // ---- auth ----
  if (path === "/api/v1/auth/guest/status" && method === "GET") {
    return json(res, 200, guestStatusBody(ident));
  }
  if (path === "/api/v1/auth/guest" && method === "POST") {
    if (!ident) {
      const id = randomUUID();
      state.guests.set(id, { used: 0, conversations: new Map(), created_at: Date.now() });
      return json(res, 200, { access_token: tokenFor(id), token_type: "bearer", user: guestUser(id) });
    }
    return json(res, 200, { access_token: tokenFor(ident.user.id), token_type: "bearer", user: ident.user });
  }
  if (path === "/api/v1/auth/register" && method === "POST") {
    const body = await readBody(req);
    const id = randomUUID();
    const email = String(body.email || "you@example.com").toLowerCase();
    state.people.set(id, [email, String(body.display_name || "New member")]);
    if (body.guest_token) {
      const guestId = body.guest_token.replace(/^mock-token-/, "");
      const guest = state.guests.get(guestId);
      if (guest) {
        state.people.get(id).push(guest.conversations); // carry chats over
        state.guests.delete(guestId);
      }
    }
    return json(res, 201, { access_token: tokenFor(id), token_type: "bearer", user: personUser(id, email, String(body.display_name || "New member")) });
  }
  if (path === "/api/v1/auth/login" && method === "POST") {
    const body = await readBody(req);
    const id = randomUUID();
    const email = String(body.email || "you@example.com").toLowerCase();
    state.people.set(id, [email, "Ada Lovelace"]);
    return json(res, 200, { access_token: tokenFor(id), token_type: "bearer", user: personUser(id, email, "Ada Lovelace") });
  }
  if (path === "/api/v1/auth/refresh" && method === "POST") {
    return json(res, 401, { detail: "Refresh credential required" });
  }
  if (path === "/api/v1/auth/logout" && method === "POST") {
    res.writeHead(204); return res.end();
  }

  // ---- conversations ----
  if (path === "/api/v1/conversations" && method === "GET") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    const list = ident.guest ? [...ident.guest.conversations.values()] : [];
    return json(res, 200, list);
  }
  if (path === "/api/v1/conversations" && method === "POST") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    const body = await readBody(req);
    if (ident.guest && ident.guest.used >= GUEST_LIMIT) {
      return json(res, 403, { code: "guest_limit_reached", detail: "You've used all 10 free messages. Create an account to keep chatting." });
    }
    const conversation = makeConversation(randomUUID(), String(body.title || "New conversation"), body.model);
    ident.guest?.conversations.set(conversation.id, conversation);
    return json(res, 201, conversation);
  }
  let match = path.match(/^\/api\/v1\/conversations\/([^/]+)$/);
  if (match && method === "GET") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    const conversation = ident.guest?.conversations.get(match[1]);
    return conversation ? json(res, 200, conversation) : json(res, 404, { detail: "Conversation not found" });
  }
  match = path.match(/^\/api\/v1\/conversations\/([^/]+)\/messages$/);
  if (match && method === "GET") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    return json(res, 200, []);
  }

  // ---- chat ----
  if (path === "/api/v1/chat" && method === "POST") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    if (ident.guest && ident.guest.used >= GUEST_LIMIT) {
      return json(res, 403, { code: "guest_limit_reached", detail: "You've used all 10 free messages. Create an account to keep chatting." });
    }
    ident.guest && ident.guest.used++;
    const body = await readBody(req);
    return json(res, 200, {
      conversation_id: body.conversation_id,
      user_message_id: randomUUID(),
      assistant_message_id: randomUUID(),
      content: sampleReply(body.content),
      model: "jat-development",
      citations: [],
    });
  }
  if (path === "/api/v1/chat/stream" && method === "POST") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    if (ident.guest && ident.guest.used >= GUEST_LIMIT) {
      return json(res, 403, { code: "guest_limit_reached", detail: "You've used all 10 free messages. Create an account to keep chatting." });
    }
    ident.guest && ident.guest.used++;
    const body = await readBody(req);
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    const reply = sampleReply(body.content);
    let i = 0;
    const timer = setInterval(() => {
      if (i >= reply.length) {
        clearInterval(timer);
        res.write(`event: complete\ndata: {"message_id":"${randomUUID()}","generation_id":"${randomUUID()}"}\n\n`);
        res.end();
        return;
      }
      const chunk = reply.slice(i, i + 3);
      i += 3;
      res.write(`event: token\ndata: ${JSON.stringify({ text: chunk, index: i })}\n\n`);
    }, 28);
    req.on("close", () => clearInterval(timer));
    return undefined;
  }
  if (path.startsWith("/api/v1/chat/messages/") && method === "POST") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    ident.guest && ident.guest.used++;
    return json(res, 200, {
      conversation_id: randomUUID(),
      user_message_id: randomUUID(),
      assistant_message_id: randomUUID(),
      content: sampleReply("retry"),
      model: "jat-development",
      citations: [],
    });
  }

  // ---- settings ----
  if (path === "/api/v1/settings" && method === "GET") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    return json(res, 200, DEFAULT_PREFS);
  }
  if (path === "/api/v1/settings/models" && method === "GET") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    return json(res, 200, MODELS);
  }
  if (path === "/api/v1/settings/profile" && method === "GET") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    if (ident.user.kind === "guest") {
      return json(res, 403, { detail: "Guest accounts cannot change account settings. Create an account to unlock them." });
    }
    return json(res, 200, { id: ident.user.id, email: ident.user.email, display_name: ident.user.display_name, created_at: new Date().toISOString() });
  }
  if (path === "/api/v1/settings/usage" && method === "GET") {
    if (!ident) return json(res, 401, { detail: "Authentication required" });
    return json(res, 200, {
      conversations: ident.guest ? ident.guest.conversations.size : 0,
      messages: ident.guest ? ident.guest.used : 0,
      input_tokens: 0, output_tokens: 0, first_activity_at: null, last_activity_at: null,
    });
  }
  if (path === "/api/v1/health/live") return json(res, 200, { status: "ok" });
  if (path === "/api/v1/health/ready") return json(res, 200, { status: "ready" });

  return json(res, 404, { detail: `No mock route for ${method} ${path}` });
}

const server = http.createServer(handler);
server.listen(PORT, "0.0.0.0", () => {
  console.log(`[mock-api] JaT demo API listening on http://0.0.0.0:${PORT}`);
  console.log(`[mock-api] guest limit = ${GUEST_LIMIT} messages, ttl = ${GUEST_TTL_HOURS}h`);
});
