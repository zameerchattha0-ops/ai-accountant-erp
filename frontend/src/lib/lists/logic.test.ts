import { describe, expect, it } from "vitest";
import {
  createRecentList,
  createSequencer,
  documentOrFilter,
  ilikeAny,
  isAbortError,
  isValidUuid,
  pageRange,
  rangeLabel,
  sanitizeSearch,
} from "./logic";

describe("sanitizeSearch", () => {
  it("strips PostgREST or() grammar characters", () => {
    expect(sanitizeSearch("INV (2024), draft")).toBe("INV 2024 draft");
    expect(sanitizeSearch("O'Brien")).toBe("O Brien");
  });

  it("escapes ILIKE wildcards so they match literally", () => {
    expect(sanitizeSearch("50%")).toBe("50\\%");
    expect(sanitizeSearch("a_b")).toBe("a\\_b");
    expect(sanitizeSearch("c:\\path")).toBe("c:\\\\path");
  });

  it("collapses whitespace and trims", () => {
    expect(sanitizeSearch("  Acme   Engineering  ")).toBe("Acme Engineering");
  });

  it("returns empty string for empty / strip-only input", () => {
    expect(sanitizeSearch("")).toBe("");
    expect(sanitizeSearch(" ( , ) ")).toBe("");
  });
});

describe("ilikeAny", () => {
  it("builds an or() expression across the given columns", () => {
    expect(ilikeAny(["name", "email"], "acme")).toBe(
      "name.ilike.%acme%,email.ilike.%acme%"
    );
  });

  it("sanitises the query inside the expression", () => {
    expect(ilikeAny(["name"], "a,b")).toBe("name.ilike.%a b%");
    expect(ilikeAny(["name"], "50%")).toBe("name.ilike.%50\\%%");
  });

  it("returns empty string when nothing searchable remains", () => {
    expect(ilikeAny(["name"], " ( ) ")).toBe("");
    expect(ilikeAny(["name"], "")).toBe("");
  });
});

describe("documentOrFilter", () => {
  const UUID_A = "11111111-1111-4111-8111-111111111111";
  const UUID_B = "22222222-2222-4222-8222-222222222222";

  it("joins root-column matches with party id membership", () => {
    const expr = documentOrFilter(
      ["invoice_number"],
      "customer_id",
      "INV-1",
      [UUID_A, UUID_B]
    );
    expect(expr).toBe(
      `invoice_number.ilike.%INV-1%,customer_id.in.(${UUID_A},${UUID_B})`
    );
  });

  it("works with only party ids (no root match)", () => {
    expect(documentOrFilter([], "customer_id", "", [UUID_A])).toBe(
      `customer_id.in.(${UUID_A})`
    );
  });

  it("works with only a root search (no party matches)", () => {
    expect(documentOrFilter(["bill_number"], "supplier_id", "BILL", [])).toBe(
      "bill_number.ilike.%BILL%"
    );
  });

  it("drops non-uuid ids so raw syntax can never enter the filter", () => {
    expect(
      documentOrFilter([], "customer_id", "", [UUID_A, "x)or(name.ilike.*"])
    ).toBe(`customer_id.in.(${UUID_A})`);
    expect(documentOrFilter([], "customer_id", "", ["not-a-uuid"])).toBe("");
  });

  it("returns empty string when there is nothing to match", () => {
    expect(documentOrFilter(["invoice_number"], "customer_id", " ( ) ", [])).toBe(
      ""
    );
  });
});

describe("isValidUuid", () => {
  it("accepts canonical uuids and rejects everything else", () => {
    expect(isValidUuid("11111111-1111-4111-8111-111111111111")).toBe(true);
    expect(isValidUuid("11111111111141118111111111111111")).toBe(false);
    expect(isValidUuid("")).toBe(false);
    expect(isValidUuid("11111111-1111-4111-8111-111111111111'")).toBe(false);
  });
});

describe("pageRange / rangeLabel", () => {
  it("computes the window for a middle page", () => {
    const r = pageRange(1, 25, 342);
    expect(r).toMatchObject({
      total: 342,
      from: 26,
      to: 50,
      totalPages: 14,
      hasPrev: true,
      hasNext: true,
    });
    expect(rangeLabel(r)).toBe("26–50 of 342");
  });

  it("clamps the last partial page", () => {
    const r = pageRange(13, 25, 342);
    expect(r.from).toBe(326);
    expect(r.to).toBe(342);
    expect(r.hasNext).toBe(false);
    expect(r.hasPrev).toBe(true);
  });

  it("handles an empty list", () => {
    const r = pageRange(0, 25, 0);
    expect(r).toMatchObject({
      total: 0,
      from: 0,
      to: 0,
      totalPages: 1,
      hasPrev: false,
      hasNext: false,
    });
    expect(rangeLabel(r)).toBe("0 of 0");
  });

  it("clamps an out-of-range page back into the grid", () => {
    const r = pageRange(99, 25, 30);
    expect(r.from).toBe(26);
    expect(r.to).toBe(30);
    expect(r.hasPrev).toBe(true);
    expect(r.hasNext).toBe(false);
  });

  it("coerces a zero page size to 1 instead of dividing by zero", () => {
    const r = pageRange(0, 0, 10);
    expect(r.totalPages).toBe(10);
    expect(r.to).toBe(1);
  });
});

describe("isAbortError", () => {
  it("recognises DOMException-style aborts", () => {
    expect(isAbortError({ name: "AbortError" })).toBe(true);
    expect(isAbortError({ code: "ABORT_ERR" })).toBe(true);
  });

  it("does not swallow real errors", () => {
    expect(isAbortError(new Error("column customers.x does not exist"))).toBe(false);
    expect(isAbortError({ status: 401, message: "jwt expired" })).toBe(false);
    expect(isAbortError(null)).toBe(false);
    expect(isAbortError("AbortError")).toBe(false);
  });
});

describe("createSequencer", () => {
  it("only the newest issued sequence is current", () => {
    const seq = createSequencer();
    const a = seq.next();
    expect(seq.isCurrent(a)).toBe(true);
    const b = seq.next();
    expect(seq.isCurrent(a)).toBe(false);
    expect(seq.isCurrent(b)).toBe(true);
    expect(seq.current()).toBe(b);
  });
});

describe("createRecentList", () => {
  it("keeps most-recent-first, deduped, within capacity", () => {
    const recent = createRecentList(3);
    recent.push("a");
    recent.push("b");
    recent.push("a");
    expect(recent.list()).toEqual(["a", "b"]);
    recent.push("c");
    recent.push("d");
    expect(recent.list()).toEqual(["d", "c", "a"]);
  });

  it("supports remove/clear and ignores empty ids", () => {
    const recent = createRecentList(2);
    recent.push("");
    recent.push("a");
    recent.push("b");
    recent.remove("b");
    expect(recent.list()).toEqual(["a"]);
    recent.clear();
    expect(recent.list()).toEqual([]);
  });
});
