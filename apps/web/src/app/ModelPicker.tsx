import { KeyboardEvent, ReactElement, useEffect, useMemo, useRef, useState } from "react";
import type { ModelOption } from "../lib/api";

/** Human-readable provider label used across the picker and settings. */
export function providerLabel(provider: string): string {
  switch (provider.toLowerCase()) {
    case "ollama":
      return "Ollama";
    case "deterministic":
      return "Local";
    case "openai":
      return "OpenAI";
    case "anthropic":
      return "Anthropic";
    case "unknown":
      return "Server";
    default:
      return provider.charAt(0).toUpperCase() + provider.slice(1);
  }
}

/** Compact context-window formatting (8192 → "8K", 32768 → "32K"). */
export function formatContextLength(length: number): string {
  if (!length || length <= 0) return "";
  if (length >= 1024 && length % 1024 === 0) return `${(length / 1024).toLocaleString()}K`;
  return length.toLocaleString();
}

type ModelPickerProps = {
  /** Full catalog of selectable models (availability flags respected). */
  models: ModelOption[];
  /** Currently active model id (per-conversation or the user default). */
  value: string;
  disabled?: boolean;
  onChange: (modelId: string) => void;
  /** Optional footer action, e.g. "Manage models in settings". */
  onManageModels?: () => void;
};

/**
 * Rich model/assistant selector for the chat header.
 *
 * Replaces the native <select> with a searchable, grouped popover that shows
 * each model's provider, context window and description, marks unavailable
 * models, and stays fully keyboard-accessible (listbox pattern with
 * aria-activedescendant).
 */
export function ModelPicker({
  models,
  value,
  disabled = false,
  onChange,
  onManageModels,
}: ModelPickerProps): ReactElement {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const selected =
    models.find((model) => model.id === value) ?? {
      id: value,
      label: value === "jat-development" ? "JaT development" : value,
      description: "",
      provider: "unknown",
      available: true,
      context_length: 0,
    };

  // Filter first, then group by provider so typing narrows the whole list.
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return models;
    return models.filter(
      (model) =>
        model.label.toLowerCase().includes(needle) ||
        model.id.toLowerCase().includes(needle) ||
        model.provider.toLowerCase().includes(needle) ||
        model.description.toLowerCase().includes(needle),
    );
  }, [models, query]);

  const groups = useMemo(() => {
    const byProvider = new Map<string, ModelOption[]>();
    for (const model of filtered) {
      const bucket = byProvider.get(model.provider) ?? [];
      bucket.push(model);
      byProvider.set(model.provider, bucket);
    }
    return [...byProvider.entries()]
      .map(([provider, items]) => ({
        provider,
        items: [...items].sort(
          (a, b) =>
            Number(b.available) - Number(a.available) ||
            a.label.localeCompare(b.label),
        ),
      }))
      .sort((a, b) => a.provider.localeCompare(b.provider));
  }, [filtered]);

  // Keyboard navigation walks only the selectable (available) options, in
  // display order; unavailable rows stay visible but are skipped.
  const selectableIds = useMemo(
    () => groups.flatMap((group) => group.items).filter((m) => m.available).map((m) => m.id),
    [groups],
  );
  const highlightIndex = highlightId ? selectableIds.indexOf(highlightId) : -1;
  const activeId =
    highlightIndex >= 0 ? highlightId : (selectableIds[0] ?? null);
  const optionId = (modelId: string): string => `model-option-${modelId.replace(/\W+/g, "-")}`;

  function openPicker(): void {
    setQuery("");
    const initial =
      models.find((model) => model.id === value && model.available)?.id ?? null;
    setHighlightId(initial);
    setOpen(true);
  }

  function closePicker(refocus = false): void {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  }

  function choose(modelId: string): void {
    if (modelId !== value) onChange(modelId);
    closePicker();
  }

  useEffect(() => {
    if (!open) return;
    window.setTimeout(() => searchRef.current?.focus(), 0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent | TouchEvent): void {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
    };
  }, [open]);

  // Keep the highlighted option in view as the highlight moves.
  useEffect(() => {
    if (!open || !activeId || !listRef.current) return;
    const options = listRef.current.querySelectorAll<HTMLElement>("[role='option']");
    for (const element of options) {
      if (element.dataset.optionId === activeId) {
        element.scrollIntoView?.({ block: "nearest" });
        break;
      }
    }
  }, [open, activeId, groups]);

  function onSearchKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (!selectableIds.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const current = selectableIds.indexOf(activeId ?? "");
      const delta = event.key === "ArrowDown" ? 1 : -1;
      const next = (current + delta + selectableIds.length) % selectableIds.length;
      setHighlightId(selectableIds[next]);
    } else if (event.key === "Home") {
      event.preventDefault();
      setHighlightId(selectableIds[0]);
    } else if (event.key === "End") {
      event.preventDefault();
      setHighlightId(selectableIds[selectableIds.length - 1]);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (activeId) choose(activeId);
    } else if (event.key === "Escape") {
      event.preventDefault();
      closePicker(true);
    }
  }

  return (
    <div
      className="model-picker"
      ref={rootRef}
      onBlur={(event) => {
        // Tab out of the popover closes it (clicks outside are handled by the
        // document listener; focus leaving via keyboard is caught here).
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        className="model-pill"
        disabled={disabled}
        onClick={() => (open ? closePicker(true) : openPicker())}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls="model-picker-listbox"
        title="Switch the model for this chat"
      >
        <span className="model-pill-label">{selected.label}</span>
        <span className="model-pill-provider">{providerLabel(selected.provider)}</span>
        <span className="model-pill-caret" aria-hidden="true">
          ▾
        </span>
      </button>

      {open && (
        <div
          className="model-menu"
          id="model-picker-listbox"
          role="listbox"
          aria-label="Conversation model"
          ref={listRef}
        >
          <div className="model-menu-search">
            <span aria-hidden="true">⌕</span>
            <input
              ref={searchRef}
              type="search"
              role="combobox"
              aria-expanded="true"
              aria-controls="model-picker-listbox"
              aria-autocomplete="list"
              aria-activedescendant={activeId ? optionId(activeId) : undefined}
              aria-label="Filter models"
              placeholder="Filter models…"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setHighlightId(null);
              }}
              onKeyDown={onSearchKeyDown}
            />
            {query && (
              <button
                type="button"
                className="model-menu-clear"
                aria-label="Clear model filter"
                onClick={() => setQuery("")}
              >
                ×
              </button>
            )}
          </div>

          <div className="model-menu-scroll">
            {groups.length === 0 && (
              <p className="model-menu-empty">No models match “{query}”.</p>
            )}
            {groups.map((group) => (
              <div key={group.provider} className="model-group">
                <p className="model-group-label">{providerLabel(group.provider)}</p>
                {group.items.map((model) => {
                  const id = optionId(model.id);
                  const isActive = activeId === model.id;
                  return (
                    <button
                      key={model.id}
                      type="button"
                      role="option"
                      id={id}
                      data-option-id={model.id}
                      aria-selected={model.id === value}
                      aria-disabled={!model.available}
                      disabled={!model.available}
                      className={`model-option ${model.id === value ? "selected" : ""} ${
                        isActive ? "highlighted" : ""
                      }`}
                      onClick={() => choose(model.id)}
                      onMouseEnter={() => setHighlightId(model.id)}
                    >
                      <span className="model-option-check" aria-hidden="true">
                        {model.id === value ? "✓" : ""}
                      </span>
                      <span className="model-option-main">
                        <strong>{model.label}</strong>
                        <small>{model.description || model.id}</small>
                      </span>
                      <span className="model-option-meta">
                        {model.context_length > 0 && (
                          <em>{formatContextLength(model.context_length)} ctx</em>
                        )}
                        {!model.available && <em className="unavailable">Unavailable</em>}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>

          {onManageModels && (
            <button
              type="button"
              className="model-menu-footer"
              onClick={() => {
                setOpen(false);
                onManageModels();
              }}
            >
              <span aria-hidden="true">⚙</span> Manage models in settings
            </button>
          )}
        </div>
      )}
    </div>
  );
}
