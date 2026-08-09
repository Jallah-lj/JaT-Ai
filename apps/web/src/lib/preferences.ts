import { DEFAULT_PREFERENCES, type Preferences } from "./api";

const STORAGE_KEY = "jat.preferences";

/** Read the last known preferences so the first paint is not a flash of the wrong theme. */
export function readCachedPreferences(): Preferences {
  if (typeof localStorage === "undefined") return DEFAULT_PREFERENCES;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFERENCES;
    return { ...DEFAULT_PREFERENCES, ...(JSON.parse(raw) as Partial<Preferences>) };
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

export function cachePreferences(preferences: Preferences): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // Storage may be unavailable (private mode / quota); preferences still live server-side.
  }
}

export function prefersDarkScheme(): boolean {
  return (
    typeof matchMedia !== "undefined" && matchMedia("(prefers-color-scheme: dark)").matches
  );
}

export function resolveTheme(theme: Preferences["theme"]): "light" | "dark" {
  return theme === "system" ? (prefersDarkScheme() ? "dark" : "light") : theme;
}

const FONT_SCALE: Record<Preferences["font_scale"], string> = {
  small: "15px",
  medium: "16px",
  large: "18px",
};

/**
 * Apply appearance preferences to the document root so every surface — including
 * portals and the auth screen — reacts without prop drilling.
 */
export function applyPreferences(preferences: Preferences): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.theme = resolveTheme(preferences.theme);
  root.dataset.accent = preferences.accent;
  root.dataset.density = preferences.density;
  root.style.setProperty("--font-size-base", FONT_SCALE[preferences.font_scale]);
  root.dataset.reducedMotion = String(
    preferences.reduced_motion ||
      (typeof matchMedia !== "undefined" &&
        matchMedia("(prefers-reduced-motion: reduce)").matches),
  );
}
