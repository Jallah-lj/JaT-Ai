import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SettingsPage } from "../src/app/settings/SettingsPage";
import { DEFAULT_PREFERENCES, type Preferences, type User } from "../src/lib/api";
import { applyPreferences, readCachedPreferences, cachePreferences } from "../src/lib/preferences";

const user: User = { id: "u1", email: "ada@example.com", display_name: "Ada Lovelace", kind: "person" };

function mockJson(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
  } as unknown as Response;
}

/** Renders the settings page with controllable preference state. */
function renderSettings(overrides: Partial<Preferences> = {}) {
  const state = { current: { ...DEFAULT_PREFERENCES, ...overrides } };
  const onPreferencesChange = vi.fn((next: Preferences) => {
    state.current = next;
  });
  const onClose = vi.fn();
  const onProfileChange = vi.fn();
  const onSignedOut = vi.fn();

  const view = render(
    <SettingsPage
      token="test-token"
      user={user}
      preferences={state.current}
      onPreferencesChange={onPreferencesChange}
      onProfileChange={onProfileChange}
      onClose={onClose}
      onSignedOut={onSignedOut}
    />,
  );
  const rerender = () =>
    view.rerender(
      <SettingsPage
        token="test-token"
        user={user}
        preferences={state.current}
        onPreferencesChange={onPreferencesChange}
        onProfileChange={onProfileChange}
        onClose={onClose}
        onSignedOut={onSignedOut}
      />,
    );
  return { state, onPreferencesChange, onClose, onProfileChange, onSignedOut, rerender };
}

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (url.includes("/settings/models")) {
      return mockJson([
        {
          id: "jat-development",
          label: "JaT development",
          description: "Deterministic development provider.",
          provider: "deterministic",
          available: true,
          context_length: 8192,
        },
        {
          id: "ollama",
          label: "Local Ollama",
          description: "Set JAT_MODEL_ENDPOINT to enable.",
          provider: "ollama",
          available: false,
          context_length: 8192,
        },
      ]);
    }
    if (url.includes("/settings/sessions")) return mockJson([]);
    if (url.includes("/integrations/catalog")) {
      return mockJson([
        {
          id: "github",
          name: "GitHub",
          description: "Connect repositories.",
          auth_type: "token",
          scopes_hint: "repo",
          docs_url: "https://github.com/settings/tokens",
          icon: "github",
          connected: false,
          connection: null,
        },
      ]);
    }
    if (url.includes("/settings/usage")) {
      return mockJson({
        conversations: 3,
        messages: 12,
        input_tokens: 100,
        output_tokens: 250,
        first_activity_at: null,
        last_activity_at: null,
      });
    }
    if (url.includes("/settings/memories") && method === "POST") {
      const body = JSON.parse(String(init?.body)) as { text: string };
      return mockJson({ ...DEFAULT_PREFERENCES, memories: [body.text] });
    }
    if (url.endsWith("/settings") && method === "PATCH") {
      const patch = JSON.parse(String(init?.body)) as Partial<Preferences>;
      return mockJson({ ...DEFAULT_PREFERENCES, ...patch });
    }
    return mockJson({});
  });
});

describe("settings page", () => {
  it("renders every section tab", () => {
    renderSettings();
    const nav = screen.getByRole("navigation", { name: /settings sections/i });
    for (const label of [
      "General",
      "Appearance",
      "Chat",
      "Memory",
      "Integrations",
      "Account",
      "Data controls",
    ]) {
      expect(within(nav).getByRole("button", { name: new RegExp(label, "i") })).toBeTruthy();
    }
  });

  it("persists a theme change through the API and reports success", async () => {
    const person = userEvent.setup();
    const { onPreferencesChange } = renderSettings();
    await person.click(screen.getByRole("button", { name: /Appearance/i }));
    await person.click(screen.getByRole("radio", { name: "Dark" }));

    await waitFor(() => {
      const call = vi.mocked(fetch).mock.calls.find(
        ([, init]) => (init?.method ?? "") === "PATCH",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ theme: "dark" });
    });
    expect(onPreferencesChange).toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Saved"));
  });

  it("sends only the changed field so other preferences are preserved", async () => {
    const person = userEvent.setup();
    renderSettings({ theme: "dark", accent: "ocean" });
    await person.click(screen.getByRole("button", { name: /Appearance/i }));
    await person.click(screen.getByRole("switch", { name: /reduce motion/i }));

    await waitFor(() => {
      const call = vi.mocked(fetch).mock.calls.find(
        ([, init]) => (init?.method ?? "") === "PATCH",
      );
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ reduced_motion: true });
    });
  });

  it("rolls back the optimistic update when the server rejects it", async () => {
    vi.mocked(fetch).mockImplementation(async () =>
      mockJson({ detail: "Invalid theme" }, 422),
    );
    const person = userEvent.setup();
    const { onPreferencesChange } = renderSettings();
    await person.click(screen.getByRole("button", { name: /Appearance/i }));
    await person.click(screen.getByRole("radio", { name: "Dark" }));

    await waitFor(() => {
      const status = screen.getByRole("status");
      expect(status.textContent).toBe("Invalid theme");
      expect(status.className).toContain("error");
    });
    // Last call restores the previous value.
    const last = onPreferencesChange.mock.calls.at(-1)?.[0] as Preferences;
    expect(last.theme).toBe("system");
  });

  it("marks unavailable models as disabled options", async () => {
    const person = userEvent.setup();
    renderSettings();
    await person.click(screen.getByRole("button", { name: /Chat/i }));
    const option = await screen.findByRole("option", { name: /Local Ollama \(unavailable\)/i });
    expect((option as HTMLOptionElement).disabled).toBe(true);
  });

  it("adds a memory and shows it in the list", async () => {
    const person = userEvent.setup();
    const { rerender } = renderSettings();
    await person.click(screen.getByRole("button", { name: /Memory/i }));
    await person.type(screen.getByLabelText(/new memory/i), "Prefers concise answers");
    await person.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => rerender());
    expect(screen.getByText("Prefers concise answers")).toBeTruthy();
  });

  it("blocks account deletion until the password and DELETE confirmation are supplied", async () => {
    const person = userEvent.setup();
    renderSettings();
    await person.click(screen.getByRole("button", { name: /Data controls/i }));
    await person.click(screen.getByRole("button", { name: "Delete account" }));

    const confirm = screen.getByRole("button", { name: /permanently delete/i });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);

    await person.type(screen.getByLabelText(/confirm your password/i), "hunter2hunter2");
    expect((confirm as HTMLButtonElement).disabled).toBe(true);

    await person.type(screen.getByLabelText(/type delete to confirm/i), "DELETE");
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
  });

  it("requires matching passwords of at least 8 characters", async () => {
    const person = userEvent.setup();
    renderSettings();
    await person.click(screen.getByRole("button", { name: /Account/i }));
    await person.type(screen.getByLabelText(/current password/i), "old-password");
    await person.type(screen.getByLabelText("New password"), "short");
    expect(document.querySelector(".field-error")?.textContent).toMatch(/at least 8 characters/i);
    expect(screen.getByLabelText("New password").getAttribute("aria-invalid")).toBe("true");

    await person.clear(screen.getByLabelText("New password"));
    await person.type(screen.getByLabelText("New password"), "long-enough");
    await person.type(screen.getByLabelText(/confirm new password/i), "different-password");
    expect(screen.getByText(/do not match/i)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /update password/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("closes on Escape and on backdrop click", async () => {
    const person = userEvent.setup();
    const { onClose } = renderSettings();
    await person.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    await person.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("exposes the dialog with an accessible name", () => {
    renderSettings();
    const dialog = screen.getByRole("dialog", { name: /settings/i });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
  });
});

describe("preference application", () => {
  it("writes theme, accent, density and font size onto the document root", () => {
    applyPreferences({
      ...DEFAULT_PREFERENCES,
      theme: "dark",
      accent: "violet",
      density: "compact",
      font_scale: "large",
    });
    const root = document.documentElement;
    expect(root.dataset.theme).toBe("dark");
    expect(root.dataset.accent).toBe("violet");
    expect(root.dataset.density).toBe("compact");
    expect(root.style.getPropertyValue("--font-size-base")).toBe("18px");
  });

  it("round-trips through the local cache and fills missing keys with defaults", () => {
    cachePreferences({ ...DEFAULT_PREFERENCES, accent: "ember" });
    expect(readCachedPreferences().accent).toBe("ember");
    localStorage.setItem("jat.preferences", JSON.stringify({ theme: "dark" }));
    const restored = readCachedPreferences();
    expect(restored.theme).toBe("dark");
    expect(restored.max_tokens).toBe(DEFAULT_PREFERENCES.max_tokens);
  });

  it("falls back to defaults when the cache is corrupt", () => {
    localStorage.setItem("jat.preferences", "{not json");
    expect(readCachedPreferences()).toEqual(DEFAULT_PREFERENCES);
  });
});
