import { describe, expect, it } from "vitest";
import { professionalName } from "./displayName";

describe("professionalName", () => {
  it("capitalises lowercase words from natural-language input", () => {
    expect(professionalName("motorbike")).toBe("Motorbike");
    expect(professionalName("motorbikes")).toBe("Motorbikes");
    expect(professionalName("motorbikes for sale")).toBe("Motorbikes for Sale");
  });

  it("keeps connector words lowercase mid-name", () => {
    expect(professionalName("john and sons")).toBe("John and Sons");
    expect(professionalName("the office")).toBe("The Office");
  });

  it("never rewrites acronyms or deliberate mixed case", () => {
    expect(professionalName("ABC Autos")).toBe("ABC Autos");
    expect(professionalName("Zameer Labs PVT Ltd")).toBe("Zameer Labs PVT Ltd");
    expect(professionalName("iPhone")).toBe("iPhone");
    expect(professionalName("Al-Areesh Engineering")).toBe("Al-Areesh Engineering");
  });

  it("preserves punctuation and digits, collapsing whitespace", () => {
    expect(professionalName("al-areesh engineering")).toBe("Al-Areesh Engineering");
    expect(professionalName("don't panic")).toBe("Don't Panic");
    expect(professionalName("45000 laptops")).toBe("45000 Laptops");
    expect(professionalName("  acme   motors  ")).toBe("Acme Motors");
  });

  it("treats empty and nullish input as empty", () => {
    expect(professionalName("")).toBe("");
    expect(professionalName("   ")).toBe("");
    expect(professionalName(null)).toBe("");
    expect(professionalName(undefined)).toBe("");
  });
});
