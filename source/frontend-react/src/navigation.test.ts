import { describe, expect, it } from "vitest";
import { loginLandingPath } from "./navigation";

describe("login landing navigation", () => {
  it("lands explicit password login on Overview / Day / Today", () => {
    expect(loginLandingPath("2026-10-05")).toBe("/?view=day&date=2026-10-05");
  });
});
