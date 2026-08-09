import { describe, expect, it } from "vitest";
import { titleFromMessage } from "../src/app/App";
import { MIN_PASSWORD_LENGTH } from "../src/lib/api";

describe("JaT web foundation", () => {
  it("has a passing test harness", () => {
    expect("JaT").toBe("JaT");
  });

  it("derives chat titles from the first user message", () => {
    expect(titleFromMessage("  Hello   world  ")).toBe("Hello world");
    expect(titleFromMessage("")).toBe("New conversation");
    const long = "a".repeat(80);
    expect(titleFromMessage(long).endsWith("…")).toBe(true);
    expect(titleFromMessage(long).length).toBeLessThanOrEqual(60);
  });

  it("exposes the reduced password minimum", () => {
    expect(MIN_PASSWORD_LENGTH).toBe(8);
  });
});
