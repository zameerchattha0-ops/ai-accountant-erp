import { describe, expect, it } from "vitest";

import {
  SESSION_STATUSES,
  STATUS_FILTERS,
  filterSessions,
  formatDuration,
  formatWhen,
  humanise,
  isActiveSession,
  isWriteTool,
  resultState,
  sessionDurationSeconds,
  sessionHeadline,
  toolLabel,
  trailCounts,
  visibleSessions,
} from "@/lib/ai-activity/logic";
import type { SessionSummary, ToolCallRecord } from "@/lib/types/api";

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "s1",
    user_request: "Create an invoice for Zameer Labs",
    status: "COMPLETED",
    current_phase: "COMPLETED",
    started_at: "2026-10-01T10:00:00Z",
    completed_at: "2026-10-01T10:00:12Z",
    created_at: "2026-10-01T10:00:00Z",
    ...overrides,
  };
}

describe("sessionHeadline", () => {
  it("shows the sentence the user typed", () => {
    expect(sessionHeadline(session())).toBe("Create an invoice for Zameer Labs");
  });

  it("trims surrounding whitespace", () => {
    expect(sessionHeadline(session({ user_request: "  booked it  " }))).toBe(
      "booked it"
    );
  });

  it("never renders an empty, unidentifiable card", () => {
    expect(sessionHeadline(session({ user_request: "" }))).toBe(
      "Untitled request"
    );
    expect(sessionHeadline(session({ user_request: "   " }))).toBe(
      "Untitled request"
    );
  });
});

describe("isActiveSession", () => {
  it("treats a run parked on the user as ACTIVE (it cannot finish alone)", () => {
    expect(isActiveSession("WAITING_FOR_USER")).toBe(true);
    expect(isActiveSession("PENDING")).toBe(true);
    expect(isActiveSession("PLANNING")).toBe(true);
    expect(isActiveSession("EXECUTING")).toBe(true);
  });

  it("treats terminal statuses as finished", () => {
    expect(isActiveSession("COMPLETED")).toBe(false);
    expect(isActiveSession("FAILED")).toBe(false);
    expect(isActiveSession("CANCELLED")).toBe(false);
  });

  it("is case-insensitive and safe on a missing value", () => {
    expect(isActiveSession("executing")).toBe(true);
    expect(isActiveSession("")).toBe(false);
  });
});

describe("humanise", () => {
  it("turns an enum code into a phrase", () => {
    expect(humanise("WAITING_FOR_USER")).toBe("waiting for user");
    expect(humanise("")).toBe("");
  });
});

describe("sessionDurationSeconds / formatDuration", () => {
  it("measures started -> completed", () => {
    expect(sessionDurationSeconds(session())).toBe(12);
  });

  it("is null while the run has not completed", () => {
    expect(sessionDurationSeconds(session({ completed_at: null }))).toBeNull();
  });

  it("falls back to created_at when started_at is missing", () => {
    expect(
      sessionDurationSeconds(
        session({ started_at: null, created_at: "2026-10-01T10:00:00Z" })
      )
    ).toBe(12);
  });

  it("refuses an inverted or unparseable span rather than a negative time", () => {
    expect(
      sessionDurationSeconds(
        session({
          started_at: "2026-10-01T10:05:00Z",
          completed_at: "2026-10-01T10:00:00Z",
        })
      )
    ).toBeNull();
    expect(
      sessionDurationSeconds(session({ completed_at: "not-a-date" }))
    ).toBeNull();
  });

  it("formats seconds, minutes and hours", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(0)).toBe("<1s");
    expect(formatDuration(12)).toBe("12s");
    expect(formatDuration(125)).toBe("2m 05s");
    expect(formatDuration(3780)).toBe("1h 03m");
  });
});

describe("formatWhen", () => {
  it("renders a valid stamp and a dash for anything unreadable", () => {
    // Timezone would make an exact-string assertion flaky, so assert shape.
    expect(formatWhen("2026-10-01T10:00:00Z")).not.toBe("—");
    expect(formatWhen("2026-10-01T10:00:00Z").length).toBeGreaterThan(6);
    expect(formatWhen(null)).toBe("—");
    expect(formatWhen(undefined)).toBe("—");
    expect(formatWhen("not-a-date")).toBe("—");
  });
});

describe("filterSessions", () => {
  const rows = [
    session({ id: "s1", user_request: "Create an invoice", status: "COMPLETED" }),
    session({ id: "s2", user_request: "Reconcile the bank account", status: "FAILED" }),
    session({ id: "s3", user_request: "Post a journal entry", status: "WAITING_FOR_USER" }),
  ];

  it("narrows by status but keeps everything on ALL", () => {
    expect(filterSessions(rows, "", "ALL")).toHaveLength(3);
    expect(filterSessions(rows, "", "FAILED").map((r) => r.id)).toEqual(["s2"]);
    expect(filterSessions(rows, "", "CANCELLED")).toEqual([]);
  });

  it("matches what the user typed, case-insensitively", () => {
    expect(filterSessions(rows, "bank", "ALL").map((r) => r.id)).toEqual(["s2"]);
    expect(filterSessions(rows, "INVOICE", "ALL").map((r) => r.id)).toEqual(["s1"]);
  });

  it("combines search with status", () => {
    expect(filterSessions(rows, "journal", "FAILED")).toEqual([]);
    expect(
      filterSessions(rows, "journal", "WAITING_FOR_USER").map((r) => r.id)
    ).toEqual(["s3"]);
  });

  it("is safe on a null request", () => {
    const blank = session({ id: "s9", user_request: "" });
    expect(filterSessions([blank], "", "ALL")).toHaveLength(1);
    expect(filterSessions([blank], "anything", "ALL")).toEqual([]);
  });
});

describe("constants", () => {
  it("exposes ALL first, then every session status", () => {
    expect(STATUS_FILTERS[0]).toBe("ALL");
    for (const status of SESSION_STATUSES) {
      expect(STATUS_FILTERS).toContain(status);
    }
  });

  it("never offers a cancelled filter — cancelled runs are not activity", () => {
    // Production request 2026-10-08: the API drops cancelled rows at read
    // time, so a "cancelled (0)" chip would be a permanently dead option.
    expect(STATUS_FILTERS).not.toContain("CANCELLED");
    expect(SESSION_STATUSES).not.toContain("CANCELLED");
  });
});

describe("visibleSessions", () => {
  const rows = [
    session({ id: "s1", user_request: "Create an invoice", status: "COMPLETED" }),
    session({ id: "s2", user_request: "Reconcile the bank account", status: "FAILED" }),
  ];
  const serverMatch = session({ id: "s9", user_request: "Far away request" });

  it("filters the loaded feed in the browser when it is complete", () => {
    expect(
      visibleSessions(rows, "bank", "ALL", [serverMatch], false).map((r) => r.id)
    ).toEqual(["s2"]);
  });

  it("uses the server's matches when the feed is truncated", () => {
    expect(
      visibleSessions(rows, "far", "ALL", [serverMatch], true).map((r) => r.id)
    ).toEqual(["s9"]);
  });

  it("falls back to the loaded page while the server search is in flight", () => {
    expect(visibleSessions(rows, "far", "ALL", null, true)).toEqual(rows);
  });
});

function call(overrides: Partial<ToolCallRecord> = {}): ToolCallRecord {
  return {
    call_order: 1,
    tool_id: "11111111-2222-3333-4444-555555555555",
    tool_name: "create_invoice",
    tool_read_only: false,
    tool_risk_level: "HIGH",
    status: "SUCCESS",
    ...overrides,
  };
}

describe("toolLabel / isWriteTool", () => {
  it("shows the catalog name when it resolved", () => {
    expect(toolLabel(call())).toBe("create_invoice");
  });

  it("falls back to a readable id fragment, never an empty cell", () => {
    expect(toolLabel(call({ tool_name: null }))).toBe("Tool 11111111");
    expect(
      toolLabel(call({ tool_name: null, tool_id: "abc" }))
    ).toBe("Tool abc");
    // An unresolvable id (defensive — the column itself is NOT NULL) still
    // yields a readable label rather than an empty cell.
    expect(toolLabel(call({ tool_name: null, tool_id: "" }))).toBe(
      "Unknown tool"
    );
  });

  it("marks a call as a WRITE only when read_only is known-false", () => {
    expect(isWriteTool(call({ tool_read_only: false }))).toBe(true);
    expect(isWriteTool(call({ tool_read_only: true }))).toBe(false);
    // An unresolved catalog row is NOT claimed to be a write.
    expect(isWriteTool(call({ tool_read_only: null }))).toBe(false);
  });
});

describe("trailCounts", () => {
  it("separates writes, reads and unresolved calls", () => {
    const counts = trailCounts({
      steps: [{ step_order: 1, step_type: "REASON", status: "COMPLETED" }],
      tool_calls: [
        call({ call_order: 1, tool_read_only: false }),
        call({ call_order: 2, tool_read_only: true, tool_name: "list_ledgers" }),
        call({ call_order: 3, tool_read_only: null, tool_name: null }),
      ],
      clarifications: [
        { question: "Which currency?", status: "WAITING_FOR_USER" },
      ],
      confirmations: [
        {
          action_type: "POST_JOURNAL",
          risk_level: "HIGH",
          confirmation_required: true,
          user_confirmed: true,
        },
      ],
    });
    expect(counts).toEqual({
      steps: 1,
      toolCalls: 3,
      clarifications: 1,
      confirmations: 1,
      writes: 1,
      reads: 1,
      unknown: 1,
    });
  });

  it("tolerates a missing (null) trail", () => {
    expect(trailCounts({})).toEqual({
      steps: 0,
      toolCalls: 0,
      clarifications: 0,
      confirmations: 0,
      writes: 0,
      reads: 0,
      unknown: 0,
    });
  });
});

describe("resultState", () => {
  it("is 'recorded' when a result row exists", () => {
    expect(resultState(session(), { status: "COMPLETED" })).toBe("recorded");
  });

  it("is 'pending' while the run is still open (no result expected yet)", () => {
    expect(
      resultState(session({ status: "WAITING_FOR_USER" }), null)
    ).toBe("pending");
    expect(resultState(session({ status: "EXECUTING" }), null)).toBe("pending");
  });

  it("is 'missing' when a TERMINAL run wrote no result — never a silent blank", () => {
    expect(resultState(session({ status: "COMPLETED" }), null)).toBe("missing");
    expect(resultState(session({ status: "FAILED" }), undefined)).toBe("missing");
  });
});

