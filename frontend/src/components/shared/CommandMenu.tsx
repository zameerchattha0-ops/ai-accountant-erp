"use client";

/**
 * CommandMenu — Ctrl/Cmd+K page search (audit A2/A9).
 *
 * Replaces the TopBar's non-functional Search button with a real, keyboard-
 * first navigation palette: type a few letters, press Enter, arrive. Routes
 * come from the SAME `navItems` the Sidebar renders, so the palette can never
 * promise a page the app doesn't have.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { navItems } from "@/components/layout/Sidebar";

interface PaletteEntry {
  label: string;
  href: string;
  group: string;
}

function flattenNav(): PaletteEntry[] {
  const out: PaletteEntry[] = [];
  for (const item of navItems) {
    if (item.href) out.push({ label: item.label, href: item.href, group: "Pages" });
    for (const child of item.children ?? []) {
      out.push({ label: child.label, href: child.href, group: item.label });
    }
  }
  return out;
}

const ENTRIES = flattenNav();

export default function CommandMenu() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Global shortcut + the TopBar's search button (custom event, same
  // pattern as `erp:data-changed`).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("app:open-command-menu", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("app:open-command-menu", onOpen);
    };
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      const raf = requestAnimationFrame(() => inputRef.current?.focus());
      return () => cancelAnimationFrame(raf);
    }
  }, [open]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ENTRIES;
    return ENTRIES.filter(
      (e) =>
        e.label.toLowerCase().includes(q) || e.group.toLowerCase().includes(q)
    );
  }, [query]);

  useEffect(() => setActive(0), [query]);

  // Keep the highlighted row visible inside the list's own scroll window.
  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const go = (entry: PaletteEntry | undefined) => {
    if (!entry) return;
    setOpen(false);
    router.push(entry.href);
  };

  if (!open) return null;


  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center pt-[12vh] px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Search pages"
    >
      <div
        className="fixed inset-0 bg-black/40"
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />
      <div className="relative w-full max-w-lg bg-bg-surface rounded-2xl shadow-lg border border-border-subtle overflow-hidden">
        <div className="flex items-center gap-2 px-4 border-b border-border-subtle">
          <Search className="w-4 h-4 text-text-muted shrink-0" />
          <input
            ref={inputRef}
            className="w-full bg-transparent py-3.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none"
            placeholder="Jump to a page…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((i) => Math.min(i + 1, results.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((i) => Math.max(0, i - 1));
              } else if (e.key === "Enter") {
                e.preventDefault();
                go(results[active]);
              } else if (e.key === "Escape") {
                e.preventDefault();
                setOpen(false);
              }
            }}
            aria-label="Search pages"
            aria-controls="command-menu-list"
            aria-activedescendant={
              results[active] ? `command-menu-opt-${active}` : undefined
            }
            role="combobox"
            aria-expanded="true"
            aria-autocomplete="list"
            autoComplete="off"
          />
          <kbd className="hidden sm:inline-block px-1.5 py-0.5 rounded border border-border-subtle text-[10px] text-text-muted">
            Esc
          </kbd>
        </div>
        <div
          id="command-menu-list"
          role="listbox"
          ref={listRef}
          className="max-h-80 overflow-y-auto overscroll-contain py-1"
        >
          {results.length === 0 ? (
            <p className="px-4 py-6 text-sm text-text-muted text-center">
              No page matches “{query}”.
            </p>
          ) : (
            results.map((entry, i) => (
              <button
                key={entry.href}
                type="button"
                id={`command-menu-opt-${i}`}
                role="option"
                aria-selected={i === active}
                data-idx={i}
                onMouseEnter={() => setActive(i)}
                onClick={() => go(entry)}
                className={`w-full flex items-center justify-between gap-3 px-4 py-2.5 text-left text-sm transition-colors ${
                  i === active ? "bg-bg-muted" : "hover:bg-bg-muted/60"
                }`}
              >
                <span className="text-text-primary truncate">{entry.label}</span>
                <span className="text-[11px] text-text-muted shrink-0">
                  {entry.group}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
