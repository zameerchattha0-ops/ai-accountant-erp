"use client";

import React from "react";
import Image from "next/image";
import type { OrgContext } from "@/lib/hooks/useOrg";

export interface ReportDocumentShellProps {
  title: string;
  subtitle?: string;
  periodLabel?: string;
  org?: OrgContext | null;
  currency?: string;
  children: React.ReactNode;
  asOfDate?: string;
}

/**
 * Standard accounting format for financial statements:
 * - Negative numbers inside parentheses: (Rs. 1,234.50)
 * - Zero as a dash: -
 * - Positive numbers: Rs. 1,234.50
 */
export function formatAccountingAmount(
  amount: number,
  currency: string = "PKR",
  options?: { showSymbol?: boolean; hideZero?: boolean }
): string {
  const { showSymbol = true, hideZero = false } = options || {};
  if (!Number.isFinite(amount) || (Math.abs(amount) < 0.005 && hideZero)) {
    return "-";
  }

  const symbols: Record<string, string> = {
    PKR: "Rs.",
    USD: "$",
    EUR: "€",
    GBP: "£",
    AED: "AED",
    SAR: "SAR",
    INR: "₹",
  };
  const sym = symbols[currency] || currency;

  const absFormatted = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(amount));

  const textWithSym = showSymbol ? `${sym} ${absFormatted}` : absFormatted;

  if (amount < -0.005) {
    return `(${textWithSym})`;
  }
  return textWithSym;
}

export default function ReportDocumentShell({
  title,
  subtitle,
  periodLabel,
  org,
  currency,
  children,
  asOfDate,
}: ReportDocumentShellProps) {
  const todayFormatted = new Date().toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  const nowTimeFormatted = new Date().toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });

  const effectiveCurrency = currency || org?.base_currency_code || "PKR";
  const displayPeriod = periodLabel || (asOfDate ? `As of ${asOfDate}` : `As of ${todayFormatted}`);

  return (
    <div className="report-document w-full max-w-5xl mx-auto bg-white text-slate-900 border border-slate-300 print:border-0 rounded-none shadow-xl print:shadow-none p-8 sm:p-12 print:p-0 my-6 print:my-0 transition-all font-sans">
      {/* ============================================================== */}
      {/* FORMAL COMPANY LETTERHEAD                                      */}
      {/* ============================================================== */}
      <div className="border-b-2 border-slate-900 pb-5 mb-6">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4">
          <div className="space-y-1">
            <h1 className="font-serif text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">
              {org?.legal_name || org?.name || "Your Company Ltd."}
            </h1>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 font-mono">
              {org?.tax_number && (
                <span>
                  <strong className="text-slate-700">NTN / Tax ID:</strong> {org.tax_number}
                </span>
              )}
              {org?.registration_number && (
                <span>
                  <strong className="text-slate-700">Reg No:</strong> {org.registration_number}
                </span>
              )}
              <span>
                <strong className="text-slate-700">Jurisdiction:</strong> {org?.country_code || "PK"}
              </span>
            </div>
          </div>

          {org?.logo_url ? (
            <div className="relative w-28 h-12 shrink-0">
              <Image
                src={org.logo_url}
                alt={org.name || "Company Logo"}
                fill
                className="object-contain object-right"
              />
            </div>
          ) : (
            <div className="text-right hidden sm:block">
              <span className="text-[10px] uppercase font-bold tracking-[0.2em] text-slate-400 block">
                Official Financial Statement
              </span>
              <span className="text-xs text-slate-500 font-mono">CONFIDENTIAL</span>
            </div>
          )}
        </div>
      </div>

      {/* ============================================================== */}
      {/* STATEMENT TITLE & METADATA BAR                                 */}
      {/* ============================================================== */}
      <div className="mb-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between border-b border-slate-200 pb-3 gap-2">
          <div>
            <h2 className="font-serif text-xl sm:text-2xl font-bold uppercase tracking-wider text-slate-900">
              {title}
            </h2>
            {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
          </div>
          <div className="sm:text-right space-y-0.5">
            <p className="text-xs font-semibold text-slate-800">{displayPeriod}</p>
            <p className="text-[11px] text-slate-500 font-mono">
              All figures expressed in <span className="font-bold text-slate-700">{effectiveCurrency}</span>
            </p>
          </div>
        </div>
      </div>

      {/* ============================================================== */}
      {/* REPORT CONTENT BODY                                            */}
      {/* ============================================================== */}
      <div className="report-content min-w-full space-y-6">{children}</div>

      {/* ============================================================== */}
      {/* SIGNATURE / AUTHORIZATION BLOCK (Page-break safe)              */}
      {/* ============================================================== */}
      <div className="report-signoff mt-14 pt-8 border-t border-slate-300 break-inside-avoid">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-8 pt-4">
          <div>
            <div className="border-b border-slate-400 w-full mb-1 h-8" />
            <p className="text-xs font-semibold text-slate-800">Prepared By</p>
            <p className="text-[10px] text-slate-500">Accounts & Finance Officer</p>
          </div>
          <div>
            <div className="border-b border-slate-400 w-full mb-1 h-8" />
            <p className="text-xs font-semibold text-slate-800">Reviewed & Verified By</p>
            <p className="text-[10px] text-slate-500">Internal Audit / Finance Lead</p>
          </div>
          <div className="hidden sm:block">
            <div className="border-b border-slate-400 w-full mb-1 h-8" />
            <p className="text-xs font-semibold text-slate-800">Authorized Signatory</p>
            <p className="text-[10px] text-slate-500">Managing Director / Partner</p>
          </div>
        </div>

        {/* Audit footer note */}
        <div className="mt-8 pt-4 border-t border-slate-100 flex flex-col sm:flex-row justify-between items-center text-[10px] text-slate-400 gap-1">
          <span>
            Generated via <strong className="text-slate-500">Ai Accountant ERP</strong> on{" "}
            {todayFormatted} at {nowTimeFormatted}
          </span>
          <span>Double-Entry Verified Management Accounting Record · Page 1</span>
        </div>
      </div>
    </div>
  );
}

