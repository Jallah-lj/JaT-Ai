import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ModelPicker, formatContextLength, providerLabel } from "../src/app/ModelPicker";
import type { ModelOption } from "../src/lib/api";

const MODELS: ModelOption[] = [
  {
    id: "jat-development",
    label: "JaT development",
    description: "Deterministic development provider.",
    provider: "deterministic",
    available: true,
    context_length: 8192,
  },
  {
    id: "llama3.1:latest",
    label: "Llama 3.1",
    description: "General-purpose instruct model.",
    provider: "ollama",
    available: true,
    context_length: 8192,
  },
  {
    id: "mistral:7b",
    label: "Mistral 7B",
    description: "Fast and lightweight.",
    provider: "ollama",
    available: false,
    context_length: 4096,
  },
];

function renderPicker(props: Partial<Parameters<typeof ModelPicker>[0]> = {}) {
  const onChange = vi.fn();
  const onManageModels = vi.fn();
  const view = render(
    <ModelPicker
      models={MODELS}
      value="jat-development"
      onChange={onChange}
      onManageModels={onManageModels}
      {...props}
    />,
  );
  return { onChange, onManageModels, view };
}

describe("ModelPicker", () => {
  it("shows the active model and its provider on the trigger", () => {
    renderPicker();
    const trigger = screen.getByRole("button", { name: /JaT development/i });
    expect(within(trigger).getByText("Local")).toBeTruthy();
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(trigger.getAttribute("aria-haspopup")).toBe("listbox");
  });

  it("opens a grouped listbox with model details on click", async () => {
    const person = userEvent.setup();
    renderPicker();
    await person.click(screen.getByRole("button", { name: /JaT development/i }));

    const listbox = screen.getByRole("listbox", { name: /conversation model/i });
    expect(listbox).toBeTruthy();
    expect(within(listbox).getByText("Ollama")).toBeTruthy();
    expect(within(listbox).getByText("Local")).toBeTruthy();
    expect(within(listbox).getByText("General-purpose instruct model.")).toBeTruthy();
    // Context window is advertised for models that report one.
    const llama = within(listbox).getByRole("option", { name: /Llama 3.1/i });
    expect(within(llama).getByText("8K ctx")).toBeTruthy();
  });

  it("marks unavailable models as disabled options", async () => {
    const person = userEvent.setup();
    renderPicker();
    await person.click(screen.getByRole("button", { name: /JaT development/i }));

    const option = screen.getByRole("option", { name: /Mistral 7B/i });
    expect((option as HTMLButtonElement).disabled).toBe(true);
    expect(option.getAttribute("aria-disabled")).toBe("true");
    expect(within(option).getByText("Unavailable")).toBeTruthy();
  });

  it("selects a model and reports the change", async () => {
    const person = userEvent.setup();
    const { onChange } = renderPicker();
    await person.click(screen.getByRole("button", { name: /JaT development/i }));
    await person.click(screen.getByRole("option", { name: /Llama 3.1/i }));

    expect(onChange).toHaveBeenCalledWith("llama3.1:latest");
    // Popover closes after selection.
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("filters models while typing in the search box", async () => {
    const person = userEvent.setup();
    renderPicker();
    await person.click(screen.getByRole("button", { name: /JaT development/i }));

    await person.type(screen.getByRole("combobox", { name: /filter models/i }), "mistral");
    expect(screen.queryByRole("option", { name: /JaT development/i })).toBeNull();
    expect(screen.getByRole("option", { name: /Mistral 7B/i })).toBeTruthy();
  });

  it("supports keyboard navigation and Enter to choose", async () => {
    const person = userEvent.setup();
    const { onChange } = renderPicker();
    await person.click(screen.getByRole("button", { name: /JaT development/i }));

    await person.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("llama3.1:latest");
    await person.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("closes when clicking outside and offers the settings shortcut", async () => {
    const person = userEvent.setup();
    const { onManageModels } = renderPicker();
    await person.click(screen.getByRole("button", { name: /JaT development/i }));
    await person.click(screen.getByRole("button", { name: /manage models in settings/i }));
    expect(onManageModels).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("keeps a pinned model selectable even when absent from the catalog", () => {
    renderPicker({ value: "custom-archived-model", models: MODELS });
    expect(
      screen.getByRole("button", { name: /custom-archived-model/i }),
    ).toBeTruthy();
  });
});

describe("picker helpers", () => {
  it("formats provider names", () => {
    expect(providerLabel("ollama")).toBe("Ollama");
    expect(providerLabel("deterministic")).toBe("Local");
    expect(providerLabel("openai")).toBe("OpenAI");
    expect(providerLabel("unknown")).toBe("Server");
    expect(providerLabel("custom")).toBe("Custom");
  });

  it("formats context windows compactly", () => {
    expect(formatContextLength(8192)).toBe("8K");
    expect(formatContextLength(32768)).toBe("32K");
    expect(formatContextLength(4096)).toBe("4K");
    expect(formatContextLength(0)).toBe("");
    expect(formatContextLength(500)).toBe("500");
  });
});
