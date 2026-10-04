import { describe, expect, it } from "vitest";

import {
  BILLING_TYPES,
  EMPTY_PROJECT_FORM,
  PROJECT_STATUSES,
  STATUS_FILTERS,
  filterProjects,
  formatMargin,
  hasPostings,
  humanise,
  messageOf,
  pnlState,
  projectFormBlocker,
  projectFormFrom,
  projectPayload,
  visibleProjects,
  type ProjectFormValues,
} from "@/lib/projects/logic";
import type { Project } from "@/lib/types/entities";

/** A minimal project row — only the fields a case reads vary. */
function project(overrides: Partial<Project> = {}): Project {
  return {
    id: "p1",
    organization_id: "org-1",
    project_code: "MOB-001",
    name: "Mobile App",
    description: "Android rebuild",
    customer_id: null,
    status: "ACTIVE",
    billing_type: "FIXED_PRICE",
    start_date: "2026-01-01",
    end_date: "2026-06-30",
    budget: 2_000_000,
    currency_code: "PKR",
    is_active: true,
    ...overrides,
  };
}

/** A form seeded with a usable name, then patched per case. */
function form(overrides: Partial<ProjectFormValues> = {}): ProjectFormValues {
  return { ...EMPTY_PROJECT_FORM, name: "Mobile App", ...overrides };
}

describe("messageOf", () => {
  it("surfaces the API's detail verbatim", () => {
    const err = new Error(JSON.stringify({ detail: "Project not found." }));
    expect(messageOf(err)).toBe("Project not found.");
  });

  it("passes plain-text errors through untouched", () => {
    expect(messageOf(new Error("network down"))).toBe("network down");
    expect(messageOf("boom")).toBe("boom");
  });
});

describe("filterProjects", () => {
  const rows = [
    { name: "Mobile App", project_code: "MOB-001", status: "ACTIVE",
      customer_name: "Zameer Labs" },
    { name: "Website", project_code: "WEB-001", status: "PLANNING",
      customer_name: null },
    { name: "Mobile Backend", project_code: "MOB-002", status: "ON_HOLD",
      customer_name: "Zameer Labs" },
  ];

  it("narrows by status but keeps everything on ALL", () => {
    expect(filterProjects(rows, "", "ALL")).toHaveLength(3);
    expect(filterProjects(rows, "", "ON_HOLD").map((r) => r.project_code)).toEqual([
      "MOB-002",
    ]);
    expect(filterProjects(rows, "", "ACTIVE")).toHaveLength(1);
  });

  it("matches name, project code or customer, case-insensitively", () => {
    expect(filterProjects(rows, "website", "ALL").map((r) => r.project_code))
      .toEqual(["WEB-001"]);
    expect(filterProjects(rows, "web-001", "ALL").map((r) => r.name))
      .toEqual(["Website"]);
    expect(filterProjects(rows, "zameer", "ALL").map((r) => r.project_code))
      .toEqual(["MOB-001", "MOB-002"]);
  });

  it("combines search with status", () => {
    expect(filterProjects(rows, "mobile", "ACTIVE").map((r) => r.name))
      .toEqual(["Mobile App"]);
    expect(filterProjects(rows, "mobile", "COMPLETED")).toEqual([]);
  });
});

describe("visibleProjects", () => {
  const rows = [
    { name: "Mobile App", project_code: "MOB-001", status: "ACTIVE",
      customer_name: null },
    { name: "Website", project_code: "WEB-001", status: "PLANNING",
      customer_name: null },
  ];
  const serverMatch = {
    name: "Far Away Project",
    project_code: "FAR-009",
    status: "ACTIVE",
    customer_name: null,
  };

  it("filters the loaded register in the browser when it is complete", () => {
    // serverMatches is deliberately ignored — the loaded set IS the register.
    expect(
      visibleProjects(rows, "web", "ALL", [serverMatch], false).map((r) => r.name)
    ).toEqual(["Website"]);
    expect(visibleProjects(rows, "", "PLANNING", null, false).map((r) => r.name))
      .toEqual(["Website"]);
  });

  it("uses the server's matches when the register is truncated", () => {
    expect(
      visibleProjects(rows, "far", "ALL", [serverMatch], true).map((r) => r.name)
    ).toEqual(["Far Away Project"]);
  });

  it("falls back to the loaded page while the server search is in flight", () => {
    expect(visibleProjects(rows, "far", "ALL", null, true)).toEqual(rows);
  });
});

describe("humanise", () => {
  it("turns an enum code into a scattered phrase", () => {
    expect(humanise("ON_HOLD")).toBe("on hold");
    expect(humanise("")).toBe("");
  });
});

describe("projectFormFrom", () => {
  it("loads a row, trimming dates to YYYY-MM-DD and stringifying the budget", () => {
    const loaded = projectFormFrom(
      project({ start_date: "2026-01-01T00:00:00Z", budget: 1234.5 })
    );
    expect(loaded.start_date).toBe("2026-01-01");
    expect(loaded.budget).toBe("1234.5");
    expect(loaded.name).toBe("Mobile App");
  });

  it("renders a null budget / customer as a blank field, never 'null'", () => {
    const loaded = projectFormFrom(project({ budget: null, customer_id: null }));
    expect(loaded.budget).toBe("");
    expect(loaded.customer_id).toBe("");
  });
});

describe("constants", () => {
  it("exposes ALL first, then every project status", () => {
    expect(STATUS_FILTERS[0]).toBe("ALL");
    for (const status of PROJECT_STATUSES) {
      expect(STATUS_FILTERS).toContain(status);
    }
  });

  it("lists the billing-type enum", () => {
    expect([...BILLING_TYPES]).toEqual([
      "FIXED_PRICE",
      "TIME_AND_MATERIALS",
      "RETAINER",
    ]);
  });
});

describe("projectFormBlocker", () => {
  it("accepts a well-formed submission", () => {
    expect(
      projectFormBlocker(
        form({
          budget: "2000000",
          start_date: "2026-01-01",
          end_date: "2026-06-30",
          status: "ACTIVE",
          billing_type: "RETAINER",
        })
      )
    ).toBeNull();
  });

  it("demands a name of at least two characters", () => {
    expect(projectFormBlocker(form({ name: " " }))).toMatch(
      /at least 2 characters/
    );
    expect(projectFormBlocker(form({ name: "x" }))).toMatch(
      /at least 2 characters/
    );
  });

  it("treats a blank budget as 'no budget' (allowed)", () => {
    expect(projectFormBlocker(form({ budget: "" }))).toBeNull();
  });

  it("refuses a non-numeric or negative budget", () => {
    expect(projectFormBlocker(form({ budget: "abc" }))).toBe(
      "Project budget must be a number."
    );
    expect(projectFormBlocker(form({ budget: "-5" }))).toBe(
      "Project budget cannot be negative."
    );
  });

  it("refuses an end date before the start date", () => {
    expect(
      projectFormBlocker(
        form({ start_date: "2026-06-30", end_date: "2026-01-01" })
      )
    ).toBe("The end date cannot be before the start date.");
  });

  it("refuses a malformed date", () => {
    expect(projectFormBlocker(form({ start_date: "01/01/2026" }))).toMatch(
      /YYYY-MM-DD/
    );
  });

  it("refuses an unknown status or billing type with a readable sentence", () => {
    expect(projectFormBlocker(form({ status: "DONE" }))).toMatch(
      /Unknown project status/
    );
    expect(projectFormBlocker(form({ billing_type: "HOURLY" }))).toMatch(
      /Unknown billing type/
    );
  });

  it("accepts every declared status", () => {
    for (const status of PROJECT_STATUSES) {
      expect(projectFormBlocker(form({ status }))).toBeNull();
    }
  });
});

describe("projectPayload", () => {
  it("trims strings and turns blanks into nulls", () => {
    const payload = projectPayload(
      form({ name: "  Mobile App ", description: "  ", customer_id: "" })
    );
    expect(payload.name).toBe("Mobile App");
    expect(payload.description).toBeNull();
    expect(payload.customer_id).toBeNull();
  });

  it("keeps a blank budget as null (never 0)", () => {
    expect(projectPayload(form({ budget: "" })).budget).toBeNull();
    expect(projectPayload(form({ budget: "1500" })).budget).toBe(1500);
  });
});

describe("hasPostings", () => {
  it("is false only when nothing is posted", () => {
    expect(hasPostings({ revenue: 0, costs: 0 })).toBe(false);
    expect(hasPostings({ revenue: 500, costs: 0 })).toBe(true);
    expect(hasPostings({ revenue: 0, costs: 300 })).toBe(true);
  });
});

describe("pnlState", () => {
  it("is 'posted' only with real numbers and a known lookup", () => {
    expect(pnlState({ revenue: 500, costs: 300 }, true)).toBe("posted");
    expect(pnlState({ revenue: 0, costs: 300 }, true)).toBe("posted");
  });

  it("is 'none' when the lookup worked but nothing is posted", () => {
    expect(pnlState({ revenue: 0, costs: 0 }, true)).toBe("none");
  });

  it("is 'unknown' when the lookup failed — never mistaken for zero", () => {
    expect(pnlState({ revenue: 0, costs: 0 }, false)).toBe("unknown");
    // even stale-looking numbers are UNKNOWN once the lookup has failed
    expect(pnlState({ revenue: 500, costs: 300 }, false)).toBe("unknown");
  });
});

describe("formatMargin", () => {
  it("renders one decimal place", () => {
    expect(formatMargin(40)).toBe("40.0%");
    expect(formatMargin(12.34)).toBe("12.3%");
  });

  it("shows a dash when there is no margin to divide by", () => {
    expect(formatMargin(null)).toBe("—");
    expect(formatMargin(undefined)).toBe("—");
  });
});

