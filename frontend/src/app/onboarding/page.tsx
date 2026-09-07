"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils/cn";
import Image from "next/image";
import { Building2, Settings2, Coins, FileCheck, Check, Landmark, Upload, X } from "lucide-react";

const BUSINESS_TYPES = [
  { value: "SOFTWARE_HOUSE", label: "Software House" },
  { value: "IT_SERVICES", label: "IT Services" },
  { value: "CONSULTING", label: "Consulting" },
  { value: "E_COMMERCE", label: "E-Commerce" },
  { value: "MANUFACTURING", label: "Manufacturing" },
  { value: "TRADING", label: "Trading" },
  { value: "CONSTRUCTION", label: "Construction" },
  { value: "HEALTHCARE", label: "Healthcare" },
  { value: "EDUCATION", label: "Education" },
  { value: "OTHER", label: "Other" },
];

const CURRENCIES = ["PKR", "USD", "EUR", "GBP", "AED", "SAR", "INR"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const STEPS = [
  { label: "Business Identity", icon: Building2 },
  { label: "Details", icon: FileCheck },
  { label: "Financial Config", icon: Coins },
  { label: "Document Prefixes", icon: Settings2 },
  { label: "Review & Create", icon: Check },
];

interface FormState {
  name: string;
  business_type: string;
  legal_name: string;
  tax_number: string;
  registration_number: string;
  core_services: string;
  industry_details: string;
  base_currency_code: string;
  country_code: string;
  timezone: string;
  fiscal_year_end_month: number;
  fiscal_year_start_year: number;
  invoice_prefix: string;
  quotation_prefix: string;
  bill_prefix: string;
  journal_prefix: string;
}

const INITIAL: FormState = {
  name: "",
  business_type: "SOFTWARE_HOUSE",
  legal_name: "",
  tax_number: "",
  registration_number: "",
  core_services: "",
  industry_details: "",
  base_currency_code: "PKR",
  country_code: "PK",
  timezone: "Asia/Karachi",
  fiscal_year_end_month: 6,
  fiscal_year_start_year: new Date().getFullYear(),
  invoice_prefix: "INV",
  quotation_prefix: "QUT",
  bill_prefix: "BIL",
  journal_prefix: "JV",
};

/* ---- Small field primitives ---- */

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-text-secondary">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint && <span className="text-[11px] text-text-muted mt-1 block">{hint}</span>}
    </label>
  );
}

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormState>(INITIAL);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [logoPreview, setLogoPreview] = useState<string | null>(null);
  const logoInputRef = useRef<HTMLInputElement>(null);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const slugPreview = useMemo(
    () => form.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, ""),
    [form.name]
  );

  const canNext = () => {
    if (step === 0) return form.name.trim().length >= 2;
    return true;
  };

  const handleCreate = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const supabase = createClient();
      const { data, error: rpcError } = await supabase.rpc("create_organization", {
        p_name: form.name.trim(),
        p_business_type: form.business_type,
        p_base_currency_code: form.base_currency_code,
        p_country_code: form.country_code,
        p_timezone: form.timezone,
        p_fiscal_year_end_month: form.fiscal_year_end_month,
        p_legal_name: form.legal_name.trim() || null,
        p_tax_number: form.tax_number.trim() || null,
        p_registration_number: form.registration_number.trim() || null,
        p_core_services: form.core_services.trim() || null,
        p_industry_details: form.industry_details.trim() || null,
        p_fiscal_year_start_year: form.fiscal_year_start_year,
      });
      if (rpcError) throw rpcError;
      if (!data) throw new Error("Organization creation returned no id");

      // Persist prefix preferences on the created org's settings row.
      await supabase
        .from("organization_settings")
        .update({
          invoice_prefix: form.invoice_prefix.trim() || "INV",
          quotation_prefix: form.quotation_prefix.trim() || "QUT",
          bill_prefix: form.bill_prefix.trim() || "BIL",
          journal_prefix: form.journal_prefix.trim() || "JV",
        })
        .eq("organization_id", data as string);

      // Upload logo if selected
      if (logoFile) {
        try {
          const ext = logoFile.name.split(".").pop() || "png";
          const path = `${data}/${Date.now()}.${ext}`;
          const { error: uploadErr } = await supabase.storage.from("org-logos").upload(path, logoFile);
          if (!uploadErr) {
            const { data: urlData } = supabase.storage.from("org-logos").getPublicUrl(path);
            await supabase.from("organizations").update({ logo_url: urlData.publicUrl }).eq("id", data as string);
          }
        } catch {
          // Logo upload is optional, continue anyway
          console.warn("Optional logo upload failed");
        }
      }

      router.push("/");
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create organization");
      setSubmitting(false);
    }
  };

  const businessTypeLabel =
    BUSINESS_TYPES.find((t) => t.value === form.business_type)?.label ?? form.business_type;

  return (
    <div className="flex-1 flex flex-col items-center px-4 py-10">
      <div className="w-full max-w-2xl">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-brand-teal to-brand-navy flex items-center justify-center mx-auto mb-4 shadow-lg shadow-brand-teal/20">
            <Landmark className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-2xl font-semibold text-text-primary">Set up your organization</h1>
          <p className="text-sm text-text-secondary mt-1">
            This creates your chart of accounts, financial year and document
            numbering - everything needed to start bookkeeping.
          </p>
        </div>

        {/* Stepper */}
        <div className="flex items-center justify-between mb-8 px-2">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            const done = i < step;
            const active = i === step;
            return (
              <div key={s.label} className="flex items-center flex-1 last:flex-none">
                <div className="flex flex-col items-center gap-1.5">
                  <div
                    className={cn(
                      "w-9 h-9 rounded-full flex items-center justify-center border-2 transition-colors",
                      done && "bg-ai-500 border-ai-500 text-white",
                      active && "border-ai-500 text-ai-600 bg-bg-surface",
                      !done && !active && "border-border-default text-text-muted bg-bg-surface"
                    )}
                  >
                    {done ? <Check className="w-4 h-4" /> : <Icon className="w-4 h-4" />}
                  </div>
                  <span
                    className={cn(
                      "text-[10px] font-medium hidden sm:block",
                      active ? "text-text-primary" : "text-text-muted"
                    )}
                  >
                    {s.label}
                  </span>
                </div>
                {i < STEPS.length - 1 && (
                  <div
                    className={cn(
                      "flex-1 h-0.5 mx-2 -mt-5 rounded",
                      i < step ? "bg-ai-500" : "bg-border-default"
                    )}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Card */}
        <div className="clay bg-bg-surface rounded-2xl p-6 space-y-5">
          {step === 0 && (
            <>
              <Field label="Organization name *" hint={`Your workspace slug will be: ${slugPreview || "…"}`}>
                <input
                  className={inputCls}
                  value={form.name}
                  onChange={(e) => set("name", e.target.value)}
                  placeholder="e.g. Intelligent Soft Enterprise"
                  autoFocus
                />
              </Field>
              <Field label="Business type">
                <select
                  className={inputCls}
                  value={form.business_type}
                  onChange={(e) => set("business_type", e.target.value)}
                >
                  {BUSINESS_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </Field>
              <p className="text-xs text-text-muted">
                We&apos;ll seed your chart of accounts from the template matching
                this business type.
              </p>
              <div>
                <span className="text-xs font-medium text-text-secondary">Logo (optional)</span>
                <p className="text-[11px] text-text-muted mt-0.5 mb-2">
                  Upload your organization logo to display on reports and the dashboard.
                </p>
                {logoPreview ? (
                  <div className="relative inline-flex items-center gap-3 p-3 rounded-xl border border-border-subtle bg-white">
                    <Image src={logoPreview} alt="Logo preview" width={80} height={32} className="h-8 w-auto object-contain" />
                    <button
                      type="button"
                      onClick={() => { setLogoFile(null); setLogoPreview(null); }}
                      className="text-text-muted hover:text-error-500 transition-colors"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => logoInputRef.current?.click()}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-xl border-2 border-dashed border-border-default hover:border-ai-200 text-xs text-text-secondary hover:text-text-primary transition-colors"
                  >
                    <Upload className="w-4 h-4" />
                    Upload logo
                  </button>
                )}
                <input
                  ref={logoInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/svg+xml,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      setLogoFile(file);
                      setLogoPreview(URL.createObjectURL(file));
                    }
                  }}
                />
              </div>
            </>
          )}

          {step === 1 && (
            <>
              <Field label="Legal name" hint="Registered company name, if different">
                <input
                  className={inputCls}
                  value={form.legal_name}
                  onChange={(e) => set("legal_name", e.target.value)}
                  placeholder="e.g. Intelligent Soft (Private) Limited"
                />
              </Field>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Tax number (NTN)">
                  <input
                    className={inputCls}
                    value={form.tax_number}
                    onChange={(e) => set("tax_number", e.target.value)}
                  />
                </Field>
                <Field label="Registration number">
                  <input
                    className={inputCls}
                    value={form.registration_number}
                    onChange={(e) => set("registration_number", e.target.value)}
                  />
                </Field>
              </div>
              <Field label="Core services">
                <textarea
                  className={cn(inputCls, "min-h-20 resize-y")}
                  value={form.core_services}
                  onChange={(e) => set("core_services", e.target.value)}
                  placeholder="What does your business sell or provide?"
                />
              </Field>
              <Field label="Industry details">
                <input
                  className={inputCls}
                  value={form.industry_details}
                  onChange={(e) => set("industry_details", e.target.value)}
                  placeholder="Optional context for the AI agent"
                />
              </Field>
            </>
          )}

          {step === 2 && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Base currency">
                  <select
                    className={inputCls}
                    value={form.base_currency_code}
                    onChange={(e) => set("base_currency_code", e.target.value)}
                  >
                    {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </Field>
                <Field label="Country code">
                  <input
                    className={inputCls}
                    maxLength={2}
                    value={form.country_code}
                    onChange={(e) => set("country_code", e.target.value.toUpperCase())}
                  />
                </Field>
              </div>
              <Field label="Timezone">
                <select
                  className={inputCls}
                  value={form.timezone}
                  onChange={(e) => set("timezone", e.target.value)}
                >
                  {["Asia/Karachi", "Asia/Dubai", "Asia/Riyadh", "Europe/London", "America/New_York", "UTC"].map((tz) => (
                    <option key={tz} value={tz}>{tz}</option>
                  ))}
                </select>
              </Field>
              <Field
                label="Fiscal year ends in"
              >
                <select
                  className={inputCls}
                  value={form.fiscal_year_end_month}
                  onChange={(e) => set("fiscal_year_end_month", Number(e.target.value))}
                >
                  {MONTHS.map((m, i) => (
                    <option key={m} value={i + 1}>{m}</option>
                  ))}
                </select>
              </Field>
              <Field
                label="Starting from year"
                hint={`FY runs ${MONTHS[(form.fiscal_year_end_month % 12)]} ${form.fiscal_year_start_year} \u2013 ${MONTHS[form.fiscal_year_end_month - 1]} ${form.fiscal_year_start_year + 1}`}
              >
                <select
                  className={inputCls}
                  value={form.fiscal_year_start_year}
                  onChange={(e) => set("fiscal_year_start_year", Number(e.target.value))}
                >
                  {Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - 2 + i).map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </Field>
            </>
          )}

          {step === 3 && (
            <>
              <p className="text-xs text-text-muted">
                Prefixes are used to auto-number documents (INV-00001, QUT-00001…).
                Defaults are fine to keep.
              </p>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Invoice prefix">
                  <input className={inputCls} maxLength={8} value={form.invoice_prefix}
                    onChange={(e) => set("invoice_prefix", e.target.value.toUpperCase())} />
                </Field>
                <Field label="Quotation prefix">
                  <input className={inputCls} maxLength={8} value={form.quotation_prefix}
                    onChange={(e) => set("quotation_prefix", e.target.value.toUpperCase())} />
                </Field>
                <Field label="Purchase bill prefix">
                  <input className={inputCls} maxLength={8} value={form.bill_prefix}
                    onChange={(e) => set("bill_prefix", e.target.value.toUpperCase())} />
                </Field>
                <Field label="Journal prefix">
                  <input className={inputCls} maxLength={8} value={form.journal_prefix}
                    onChange={(e) => set("journal_prefix", e.target.value.toUpperCase())} />
                </Field>
              </div>
            </>
          )}

          {step === 4 && (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-text-primary">Review</h3>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2.5 text-sm">
                {[
                  ["Name", form.name],
                  ["Business type", businessTypeLabel],
                  ["Legal name", form.legal_name || "-"],
                  ["Tax number", form.tax_number || "-"],
                  ["Currency", form.base_currency_code],
                  ["Country", form.country_code],
                  ["Timezone", form.timezone],
                  ["Fiscal year", `${MONTHS[(form.fiscal_year_end_month % 12)]} ${form.fiscal_year_start_year} - ${MONTHS[form.fiscal_year_end_month - 1]} ${form.fiscal_year_start_year + 1}`],
                  ["Prefixes", `${form.invoice_prefix} · ${form.quotation_prefix} · ${form.bill_prefix} · ${form.journal_prefix}`],
                ].map(([label, value]) => (
                  <div key={label} className="flex flex-col">
                    <dt className="text-[11px] uppercase tracking-wide text-text-muted">{label}</dt>
                    <dd className="text-text-primary font-medium truncate">{value}</dd>
                  </div>
                ))}
              </dl>
              <div className="rounded-xl bg-ai-50 border border-ai-100 p-3 text-xs text-ai-700 leading-relaxed">
                Creating now will set you up as <strong>Owner</strong> and generate:
                your organization, a {MONTHS[(form.fiscal_year_end_month % 12)]}{" "}
                {form.fiscal_year_start_year}-{MONTHS[form.fiscal_year_end_month - 1]}{" "}
                {form.fiscal_year_start_year + 1} financial year with 12 monthly
                periods, default document numbering, and a chart of accounts from
                the {businessTypeLabel} template.
              </div>
              {error && (
                <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{error}</p>
              )}
            </div>
          )}

          {/* Nav */}
          <div className="flex items-center justify-between pt-2 border-t border-border-subtle">
            <button
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0 || submitting}
              className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Back
            </button>
            {step < STEPS.length - 1 ? (
              <button
                onClick={() => canNext() && setStep((s) => s + 1)}
                disabled={!canNext()}
                className="px-5 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Continue
              </button>
            ) : (
              <button
                onClick={handleCreate}
                disabled={submitting || form.name.trim().length < 2}
                className="px-5 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
              >
                {submitting && (
                  <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                )}
                {submitting ? "Creating…" : "Create organization"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
