"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Upload, X } from "lucide-react";
import Image from "next/image";
import { createClient } from "@/lib/supabase/client";
import { useOrg, type OrgContext } from "@/lib/hooks/useOrg";
import PageHeader from "@/components/shared/PageHeader";
import StatusBadge from "@/components/shared/StatusBadge";
import { ErrorState, TableSkeleton } from "@/components/shared/States";
import { cn } from "@/lib/utils/cn";
import type { AccountingPeriod, FinancialYear, InvoiceTemplateId, OrganizationSettings } from "@/lib/types/entities";

const inputCls =
  "w-full px-3 py-2 rounded-xl bg-bg-primary border border-border-default text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ai-100 focus:border-ai-300 transition-colors";

const BUSINESS_TYPES = [
  "SOFTWARE_HOUSE", "IT_SERVICES", "SAAS_STARTUP", "DIGITAL_AGENCY",
  "TECHNOLOGY_CONSULTANT", "FREELANCER", "SMALL_TECH_STARTUP", "SERVICE_BUSINESS", "OTHER",
];

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const PREFIX_FIELDS: { key: keyof OrganizationSettings; label: string }[] = [
  { key: "invoice_prefix", label: "Invoice" },
  { key: "quotation_prefix", label: "Quotation" },
  { key: "bill_prefix", label: "Bill" },
  { key: "credit_note_prefix", label: "Credit Note" },
  { key: "journal_prefix", label: "Journal" },
  { key: "payment_prefix", label: "Payment" },
  { key: "receipt_prefix", label: "Receipt" },
  { key: "customer_prefix", label: "Customer" },
  { key: "supplier_prefix", label: "Supplier" },
  { key: "project_prefix", label: "Project" },
  { key: "expense_prefix", label: "Expense" },
  { key: "asset_prefix", label: "Asset" },
];

const TEMPLATES: { id: InvoiceTemplateId; label: string; description: string }[] = [
  { id: "modern", label: "Modern", description: "Gradient header, clean sans-serif, bold totals" },
  { id: "professional", label: "Professional", description: "Serif letterhead with ruled borders, formal layout" },
  { id: "minimal", label: "Minimal", description: "Monochrome hairlines, maximum whitespace, print-friendly" },
];

type MemberRow = {
  id: string;
  user_id: string;
  status: string;
  joined_at: string | null;
  role?: { code?: string; name?: string } | { code?: string; name?: string }[] | null;
};

type InviteRow = {
  id: string;
  email: string;
  role_code: string;
  status: string;
  created_at: string;
};

const EMPTY_PROFILE = {
  name: "", legal_name: "", tax_number: "", registration_number: "",
  business_type: "OTHER", base_currency_code: "PKR", country_code: "",
  timezone: "", fiscal_year_end_month: 6,
};

const profileFromOrg = (o: OrgContext) => ({
  name: o.name,
  legal_name: o.legal_name ?? "",
  tax_number: o.tax_number ?? "",
  registration_number: o.registration_number ?? "",
  business_type: o.business_type,
  base_currency_code: o.base_currency_code,
  country_code: o.country_code ?? "",
  timezone: o.timezone,
  fiscal_year_end_month: o.fiscal_year_end_month,
});

function SectionCard({
  title, description, children,
}: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="bg-bg-surface rounded-2xl border border-border-subtle p-5 sm:p-6 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
        {description && <p className="text-xs text-text-secondary mt-0.5">{description}</p>}
      </div>
      {children}
    </div>
  );
}

function SaveButton({
  saving, saved, label = "Save changes", onClick, disabled,
}: { saving: boolean; saved: boolean; label?: string; onClick: () => void; disabled?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <button
        onClick={onClick}
        disabled={saving || disabled}
        className="px-4 py-2 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {saving ? "Saving\u2026" : label}
      </button>
      {saved && (
        <span className="flex items-center gap-1 text-xs text-success-700">
          <Check className="w-3.5 h-3.5" /> Saved
        </span>
      )}
    </div>
  );
}

function LogoUploader({
  org,
  onUploaded,
  onError,
}: {
  org: OrgContext;
  onUploaded: () => void;
  onError: (msg: string) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const handleFile = async (file: File | null | undefined) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { onError("File must be under 2 MB"); return; }
    setUploading(true);
    try {
      const supabase = createClient();
      const ext = file.name.split(".").pop() || "png";
      const path = `${org.organization_id}/${Date.now()}.${ext}`;
      const { error: uploadErr } = await supabase.storage.from("org-logos").upload(path, file, { upsert: true });
      if (uploadErr) throw uploadErr;
      const { data: urlData } = supabase.storage.from("org-logos").getPublicUrl(path);
      await supabase.from("organizations").update({ logo_url: urlData.publicUrl }).eq("id", org.organization_id);
      onUploaded();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer.files?.[0]);
  };

  const removeLogo = async () => {
    setUploading(true);
    try {
      const supabase = createClient();
      if (org.logo_url) {
        const urlParts = org.logo_url.split("/org-logos/");
        if (urlParts[1]) await supabase.storage.from("org-logos").remove([urlParts[1]]);
      }
      await supabase.from("organizations").update({ logo_url: null }).eq("id", org.organization_id);
      onUploaded();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Failed to remove logo");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-3">
      {org.logo_url ? (
        <div className="flex items-center gap-4">
          <div className="relative group rounded-xl border border-border-subtle bg-white p-2">
            <Image src={org.logo_url} alt="Organization logo" width={120} height={48} className="h-12 w-auto object-contain" />
            <button
              onClick={removeLogo}
              disabled={uploading}
              className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-error-500 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
          <p className="text-xs text-text-muted">Hover the logo to remove it.</p>
        </div>
      ) : (
        <label
          onDrop={handleDrop}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          className={cn(
            "flex flex-col items-center justify-center gap-2 p-6 rounded-xl border-2 border-dashed cursor-pointer transition-colors",
            dragOver ? "border-ai-300 bg-ai-50/40" : "border-border-default hover:border-ai-200 hover:bg-bg-muted"
          )}
        >
          {uploading ? (
            <span className="w-5 h-5 border-2 border-ai-200 border-t-ai-500 rounded-full animate-spin" />
          ) : (
            <Upload className="w-5 h-5 text-text-muted" />
          )}
          <span className="text-xs text-text-secondary">{uploading ? "Uploading\u2026" : "Drop an image here or click to browse"}</span>
          <span className="text-[11px] text-text-muted">PNG, JPEG, SVG or WebP (max 2 MB)</span>
          <input
            type="file"
            accept="image/png,image/jpeg,image/svg+xml,image/webp"
            className="hidden"
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </label>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const { org, loading: orgLoading, refresh } = useOrg();

  /* ---- Profile (derived from org; draft holds edits) ---- */
  const [profileDraft, setProfileDraft] = useState<ReturnType<typeof profileFromOrg> | null>(null);
  const profile = profileDraft ?? (org ? profileFromOrg(org) : EMPTY_PROFILE);
  const setProfile = setProfileDraft;
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  /* ---- Logo upload ---- */
  const [logoError, setLogoError] = useState<string | null>(null);
  const [logoPreference, setLogoPreference] = useState<"logo" | "name">("name");

  const saveProfile = async () => {
    if (!org) return;
    setProfileSaving(true);
    setProfileSaved(false);
    setProfileError(null);
    const supabase = createClient();
    const { error: updError } = await supabase
      .from("organizations")
      .update({
        name: profile.name.trim(),
        legal_name: profile.legal_name.trim() || null,
        tax_number: profile.tax_number.trim() || null,
        registration_number: profile.registration_number.trim() || null,
        business_type: profile.business_type,
        base_currency_code: profile.base_currency_code,
        country_code: profile.country_code.trim().toUpperCase() || null,
        timezone: profile.timezone.trim() || "Asia/Karachi",
        fiscal_year_end_month: Number(profile.fiscal_year_end_month) || 6,
      })
      .eq("id", org.organization_id);
    setProfileSaving(false);
    if (updError) setProfileError(updError.message);
    else { setProfileSaved(true); setProfileDraft(null); refresh(); }
  };

  /* ---- Team ---- */
  const [members, setMembers] = useState<MemberRow[] | null>(null);
  const [membersError, setMembersError] = useState<string | null>(null);
  const [memberEmails, setMemberEmails] = useState<Record<string, string>>({});
  const [myUserId, setMyUserId] = useState<string | null>(null);
  const [invites, setInvites] = useState<InviteRow[]>([]);
  const [roleOptions, setRoleOptions] = useState<{ code: string; name: string }[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("ACCOUNTANT");
  const [inviteSaving, setInviteSaving] = useState(false);
  const [inviteMsg, setInviteMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const loadTeam = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const orgId = org.organization_id;

    // SELF-SERVE ACCEPT: if the signed-in user has a PENDING invite for
    // their email (owner inviting themselves, or a teammate who registered
    // before the invite), the database links the membership right now.
    supabase.rpc("accept_my_team_invite").then(({ data: joined }) => {
      if (typeof joined === "number" && joined > 0) {
        window.dispatchEvent(new CustomEvent("erp:data-changed"));
      }
    });

    const { data: userData } = await supabase.auth.getUser();
    setMyUserId(userData?.user?.id ?? null);

    const [membersRes, emailsRes, invitesRes, rolesRes] = await Promise.all([
      supabase
        .from("organization_members")
        .select("id, user_id, status, joined_at, role:organization_roles(code, name)")
        .eq("organization_id", orgId)
        .order("created_at"),
      supabase.rpc("list_team_members", { target_org: orgId }),
      supabase
        .from("team_invites")
        .select("id, email, role_code, status, created_at")
        .eq("organization_id", orgId)
        .order("created_at", { ascending: false }),
      supabase.from("organization_roles").select("code, name").order("rank"),
    ]);
    if (membersRes.error) setMembersError(membersRes.error.message);
    else setMembers((membersRes.data as MemberRow[]) ?? []);
    if (emailsRes.error) setMemberEmails({});
    else {
      const map: Record<string, string> = {};
      for (const r of (emailsRes.data as { user_id: string; email: string }[]) ?? []) {
        map[r.user_id] = r.email;
      }
      setMemberEmails(map);
    }
    if (invitesRes.error) setInvites([]);
    else setInvites((invitesRes.data as InviteRow[]) ?? []);
    if (rolesRes.error) setRoleOptions([]);
    else setRoleOptions((rolesRes.data as { code: string; name: string }[]) ?? []);
  }, [org]);

  useEffect(() => { loadTeam(); }, [loadTeam]);

  /* ---- Financial years + periods (continuous) ---- */
  const [years, setYears] = useState<FinancialYear[] | null>(null);
  const [periods, setPeriods] = useState<AccountingPeriod[]>([]);
  const [yearsError, setYearsError] = useState<string | null>(null);
  const [yearsBusy, setYearsBusy] = useState(false);
  const [yearMsg, setYearMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const loadYears = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const [yearsRes, periodsRes] = await Promise.all([
      supabase
        .from("financial_years")
        .select("*")
        .eq("organization_id", org.organization_id)
        .order("start_date"),
      supabase
        .from("accounting_periods")
        .select("*")
        .eq("organization_id", org.organization_id)
        .order("period_number"),
    ]);
    if (yearsRes.error) setYearsError(yearsRes.error.message);
    else setYears((yearsRes.data as FinancialYear[]) ?? []);
    if (!periodsRes.error) setPeriods((periodsRes.data as AccountingPeriod[]) ?? []);
  }, [org]);

  useEffect(() => { loadYears(); }, [loadYears]);

  // CONTINUOUS YEARS: creates the year AFTER the latest one (start =
  // previous end + 1 day) with 12 monthly OPEN periods.  Click again next
  // year - recording never has to stop.  If "today" falls inside the new
  // year it becomes the reporting year automatically.
  const addNextYear = async () => {
    if (!org) return;
    setYearsBusy(true);
    setYearMsg(null);
    const supabase = createClient();
    const { data, error } = await supabase.rpc("create_next_financial_year", {
      target_org: org.organization_id,
    });
    setYearsBusy(false);
    if (error) {
      setYearMsg({ ok: false, text: error.message });
      return;
    }
    const created = data as FinancialYear | null;
    setYearMsg({
      ok: true,
      text: created
        ? `${created.name} (${created.start_date} → ${created.end_date}) created with 12 open monthly periods.`
        : "Financial year created.",
    });
    loadYears();
  };

  const switchReportingYear = async (yearId: string, name: string) => {
    if (!org) return;
    setYearsBusy(true);
    setYearMsg(null);
    const supabase = createClient();
    const { error } = await supabase.rpc("set_reporting_year", {
      target_org: org.organization_id,
      year_id: yearId,
    });
    setYearsBusy(false);
    if (error) {
      setYearMsg({ ok: false, text: error.message });
      return;
    }
    setYearMsg({ ok: true, text: `Reports now cover ${name}.` });
    loadYears();
  };

  /* ---- Settings row: prefixes + jsonb ---- */
  const [settingsRow, setSettingsRow] = useState<OrganizationSettings | null>(null);
  const [prefixes, setPrefixes] = useState<Record<string, string>>({});
  const [paymentTerms, setPaymentTerms] = useState("30");
  const [prefixesSaving, setPrefixesSaving] = useState(false);
  const [prefixesSaved, setPrefixesSaved] = useState(false);
  const [prefixesError, setPrefixesError] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    if (!org) return;
    const supabase = createClient();
    const { data, error } = await supabase
      .from("organization_settings")
      .select("*")
      .eq("organization_id", org.organization_id)
      .limit(1);
    if (error) { setPrefixesError(error.message); return; }
    const row = (data as OrganizationSettings[])[0] ?? null;
    setSettingsRow(row);
    if (row) {
      const map: Record<string, string> = {};
      for (const f of PREFIX_FIELDS) map[f.key as string] = String(row[f.key] ?? "");
      setPrefixes(map);
      setPaymentTerms(String(row.default_payment_terms_days ?? 30));
    }
  }, [org]);

  useEffect(() => { loadSettings(); }, [loadSettings]);

  const savePrefixes = async () => {
    if (!org) return;
    setPrefixesSaving(true);
    setPrefixesSaved(false);
    setPrefixesError(null);
    const supabase = createClient();
    const { error: updError } = await supabase
      .from("organization_settings")
      .update({
        ...Object.fromEntries(
          PREFIX_FIELDS.map((f) => [f.key, prefixes[f.key as string]?.trim() || String(settingsRow?.[f.key] ?? "")])
        ),
        default_payment_terms_days: Number(paymentTerms) || 30,
      })
      .eq("organization_id", org.organization_id);
    setPrefixesSaving(false);
    if (updError) setPrefixesError(updError.message);
    else { setPrefixesSaved(true); loadSettings(); }
  };

  /* ---- Invoice template preference (derived from settings; override holds edits) ---- */
  const [templateOverride, setTemplateOverride] = useState<InvoiceTemplateId | null>(null);
  const preferredTemplate = (settingsRow?.settings as Record<string, unknown> | null)?.invoice_template;
  const template: InvoiceTemplateId =
    templateOverride ??
    (preferredTemplate && TEMPLATES.some((t) => t.id === preferredTemplate)
      ? (preferredTemplate as InvoiceTemplateId)
      : "modern");
  const [templateSaving, setTemplateSaving] = useState(false);
  const [templateSaved, setTemplateSaved] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);

  const saveTemplate = async (id: InvoiceTemplateId) => {
    if (!org || !settingsRow) return;
    setTemplateOverride(id);
    setTemplateSaving(true);
    setTemplateSaved(false);
    setTemplateError(null);
    const supabase = createClient();
    const merged = { ...(settingsRow.settings ?? {}), invoice_template: id };
    const { error: updError } = await supabase
      .from("organization_settings")
      .update({ settings: merged })
      .eq("organization_id", org.organization_id);
    setTemplateSaving(false);
    if (updError) setTemplateError(updError.message);
    else { setTemplateSaved(true); loadSettings(); }
  };

  const roleLabel = (m: MemberRow) => {
    const r = Array.isArray(m.role) ? m.role[0] : m.role;
    return r?.code ?? "-";
  };

  // Owner/Admin gate - mirrors the database RLS on team_invites.
  const canManage =
    members?.some(
      (m) =>
        m.user_id === myUserId &&
        ["OWNER", "ADMIN"].includes(roleLabel(m))
    ) ?? false;

  const sendInvite = async () => {
    if (!org) return;
    const email = inviteEmail.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      setInviteMsg({ ok: false, text: "Enter a valid email address." });
      return;
    }
    setInviteSaving(true);
    setInviteMsg(null);
    const supabase = createClient();
    // Upsert: re-inviting a revoked/accepted email re-opens the invite with
    // the newly chosen role (RLS: owner/admin only).
    const { error } = await supabase.from("team_invites").upsert(
      {
        organization_id: org.organization_id,
        email,
        role_code: inviteRole,
        status: "PENDING",
        invited_by: myUserId,
      },
      { onConflict: "organization_id,email" }
    );
    setInviteSaving(false);
    if (error) {
      setInviteMsg({
        ok: false,
        text:
          error.message.includes("row-level security") ||
          error.message.includes("permission")
            ? "Only the Owner or an Administrator can invite teammates."
            : error.message,
      });
      return;
    }
    setInviteMsg({
      ok: true,
      text: `Invite ready for ${email}. Share your app link - they're added automatically when they sign up with this email.`,
    });
    setInviteEmail("");
    loadTeam();
  };

  const revokeInvite = async (id: string) => {
    const supabase = createClient();
    await supabase.from("team_invites").update({ status: "REVOKED" }).eq("id", id);
    loadTeam();
  };

  const periodSummary = useMemo(() => {
    const map = new Map<string, AccountingPeriod[]>();
    for (const p of periods) {
      const list = map.get(p.financial_year_id) ?? [];
      list.push(p);
      map.set(p.financial_year_id, list);
    }
    return map;
  }, [periods]);

  if (orgLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-6">
        <TableSkeleton rows={12} cols={4} />
      </div>
    );
  }

  if (!org) {
    return (
      <div className="max-w-4xl mx-auto">
        <ErrorState message="No active organization found for this account." />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <PageHeader title="Settings" subtitle="Organization profile, team, books and documents" />

      {/* ---- Organization identity ---- */}
      <SectionCard title="Organization identity" description="Choose how your organization appears on reports, invoices and the dashboard">
        <div className="grid sm:grid-cols-2 gap-5">
          <div>
            <label className="text-xs font-medium text-text-secondary">Display name</label>
            <input className={`${inputCls} mt-1.5`} value={profile.name}
              onChange={(e) => setProfile({ ...profile, name: e.target.value })} />
            <p className="text-[11px] text-text-muted mt-1">Text shown when no logo is uploaded.</p>
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">Upload logo</label>
            <div className="mt-1.5">
              <LogoUploader
                org={org}
                onUploaded={() => { setLogoError(null); refresh(); }}
                onError={setLogoError}
              />
            </div>
          </div>
        </div>

        {org.logo_url && (
          <div className="pt-2">
            <span className="text-xs font-medium text-text-secondary">Display on reports</span>
            <div className="flex gap-4 mt-2">
              {(["logo", "name"] as const).map((pref) => (
                <label key={pref} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="logo-pref"
                    checked={logoPreference === pref}
                    onChange={() => setLogoPreference(pref)}
                    className="accent-ai-500"
                  />
                  <span className="text-sm text-text-primary">
                    {pref === "logo" ? "Use uploaded logo" : "Use display name"}
                  </span>
                </label>
              ))}
            </div>
          </div>
        )}

        {org.logo_url && (
          <div className="pt-2">
            <span className="text-xs font-medium text-text-secondary">Preview at report scale</span>
            <div className="mt-2 p-4 rounded-xl bg-white border border-border-subtle">
              <Image
                src={org.logo_url}
                alt="Logo preview"
                width={180}
                height={56}
                className="h-10 w-auto object-contain"
              />
            </div>
          </div>
        )}

        {logoError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{logoError}</p>}
      </SectionCard>

      {/* ---- Profile ---- */}
      <SectionCard title="Organization profile" description="Shown on invoices, reports and documents">
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-text-secondary">Display name *</label>
            <input className={`${inputCls} mt-1.5`} value={profile.name}
              onChange={(e) => setProfile({ ...profile, name: e.target.value })} />
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">Legal name</label>
            <input className={`${inputCls} mt-1.5`} value={profile.legal_name}
              onChange={(e) => setProfile({ ...profile, legal_name: e.target.value })} />
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">Tax / NTN number</label>
            <input className={`${inputCls} mt-1.5`} value={profile.tax_number}
              onChange={(e) => setProfile({ ...profile, tax_number: e.target.value })} />
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">Registration number</label>
            <input className={`${inputCls} mt-1.5`} value={profile.registration_number}
              onChange={(e) => setProfile({ ...profile, registration_number: e.target.value })} />
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">Business type</label>
            <select className={`${inputCls} mt-1.5`} value={profile.business_type}
              onChange={(e) => setProfile({ ...profile, business_type: e.target.value })}>
              {BUSINESS_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-text-secondary">Currency</label>
              <input className={`${inputCls} mt-1.5`} maxLength={3} value={profile.base_currency_code}
                onChange={(e) => setProfile({ ...profile, base_currency_code: e.target.value.toUpperCase() })} />
            </div>
            <div>
              <label className="text-xs font-medium text-text-secondary">Country</label>
              <input className={`${inputCls} mt-1.5`} maxLength={2} value={profile.country_code}
                onChange={(e) => setProfile({ ...profile, country_code: e.target.value.toUpperCase() })}
                placeholder="PK" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">Timezone</label>
            <input className={`${inputCls} mt-1.5`} value={profile.timezone}
              onChange={(e) => setProfile({ ...profile, timezone: e.target.value })} />
          </div>
          <div>
            <label className="text-xs font-medium text-text-secondary">Fiscal year ends</label>
            <select className={`${inputCls} mt-1.5`} value={profile.fiscal_year_end_month}
              onChange={(e) => setProfile({ ...profile, fiscal_year_end_month: Number(e.target.value) })}>
              {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
            <p className="text-[11px] text-text-muted mt-1">
              Applies to future financial years (existing years are unchanged).
            </p>
          </div>
        </div>
        {profileError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{profileError}</p>}
        <SaveButton saving={profileSaving} saved={profileSaved} onClick={saveProfile}
          disabled={!profile.name.trim()} />
      </SectionCard>

      {/* ---- Team ---- */}
      <SectionCard title="Team" description="People with access to this organization's books">
        {membersError ? (
          <p className="text-xs text-error-600">{membersError}</p>
        ) : !members ? (
          <p className="text-xs text-text-muted">Loading…</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-2 py-2 font-medium">Member</th>
                <th className="px-2 py-2 font-medium">Role</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium">Joined</th>
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className="border-b border-border-subtle/60 last:border-0">
                  <td className="px-2 py-2.5 text-text-primary text-xs">
                    <span className="block">{memberEmails[m.user_id] ?? `${m.user_id.slice(0, 8)}…`}</span>
                  </td>
                  <td className="px-2 py-2.5 text-text-secondary">{roleLabel(m)}</td>
                  <td className="px-2 py-2.5"><StatusBadge status={m.status} /></td>
                  <td className="px-2 py-2.5 text-text-secondary tabular-nums text-xs">
                    {m.joined_at ? new Date(m.joined_at).toLocaleDateString("en-GB") : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {/* ---- Self-serve invites (database allowlist - no admin API) ---- */}
        {canManage && (
          <div className="rounded-xl border border-border-subtle bg-bg-primary/50 p-3 space-y-2.5">
            <p className="text-xs font-semibold text-text-secondary">Invite a teammate</p>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                type="email"
                className={`${inputCls} flex-1`}
                placeholder="teammate@email.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && inviteEmail.trim()) sendInvite();
                }}
              />
              <select
                className={`${inputCls} sm:w-44`}
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
              >
                {roleOptions
                  .filter((r) => r.code !== "OWNER")
                  .map((r) => (
                    <option key={r.code} value={r.code}>{r.name}</option>
                  ))}
              </select>
              <button
                onClick={sendInvite}
                disabled={inviteSaving || !inviteEmail.trim()}
                className="btn-3d btn-shine px-4 py-2 rounded-xl bg-gradient-to-b from-ai-500 to-ai-600 text-white text-sm font-semibold disabled:opacity-40 transition-colors whitespace-nowrap"
              >
                {inviteSaving ? "Inviting…" : "Send invite"}
              </button>
            </div>
            {inviteMsg && (
              <p
                className={cn(
                  "text-xs rounded-xl px-3 py-2",
                  inviteMsg.ok
                    ? "text-success-700 bg-success-50"
                    : "text-error-600 bg-error-50"
                )}
              >
                {inviteMsg.text}
              </p>
            )}
            <p className="text-[11px] text-text-muted">
              No invitation email is sent automatically - share your app link.
              When someone signs up with this exact email they are{" "}
              <span className="font-medium text-text-secondary">added to this organization automatically</span>{" "}
              with the chosen role (a database allowlist - no admin API needed).
              Already registered? They are joined the moment they open the app.
            </p>
          </div>
        )}

        {canManage && invites.filter((i) => i.status === "PENDING").length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-semibold text-text-secondary">Pending invites</p>
            {invites
              .filter((i) => i.status === "PENDING")
              .map((inv) => (
                <div
                  key={inv.id}
                  className="flex items-center justify-between rounded-xl border border-border-subtle px-3 py-2"
                >
                  <div>
                    <p className="text-sm text-text-primary">{inv.email}</p>
                    <p className="text-[11px] text-text-muted">
                      {inv.role_code} · invited{" "}
                      {new Date(inv.created_at).toLocaleDateString("en-GB")}
                    </p>
                  </div>
                  <button
                    onClick={() => revokeInvite(inv.id)}
                    className="text-xs font-medium text-error-600 hover:text-error-700 transition-colors"
                  >
                    Revoke
                  </button>
                </div>
              ))}
          </div>
        )}

        <p className="text-[11px] text-text-muted">
          Teammates join by signing up with their invited email - the database
          links them to this organization with the invited role automatically.
        </p>
      </SectionCard>

      {/* ---- Financial years ---- */}
      <SectionCard title="Financial years & periods" description="Books are kept per financial year with monthly periods">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-text-secondary">
            Reporting year:{" "}
            <span className="font-semibold text-ai-700">
              {years?.find((y) => y.is_current)?.name ?? "-"}
            </span>{" "}
            <span className="text-text-muted">
              (all P&amp;L, trial balance and dashboard KPIs cover this year)
            </span>
          </p>
          <button
            onClick={addNextYear}
            disabled={yearsBusy}
            className="btn-3d btn-shine px-4 py-2 rounded-xl bg-gradient-to-b from-ai-500 to-ai-600 text-white text-sm font-semibold disabled:opacity-40 transition-colors whitespace-nowrap"
          >
            {yearsBusy ? "Working…" : "+ Add next financial year"}
          </button>
        </div>
        {yearMsg && (
          <p
            className={cn(
              "text-xs rounded-xl px-3 py-2",
              yearMsg.ok ? "text-success-700 bg-success-50" : "text-error-600 bg-error-50"
            )}
          >
            {yearMsg.text}
          </p>
        )}
        {yearsError ? (
          <p className="text-xs text-error-600">{yearsError}</p>
        ) : !years ? (
          <p className="text-xs text-text-muted">Loading…</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-muted border-b border-border-subtle">
                <th className="px-2 py-2 font-medium">Year</th>
                <th className="px-2 py-2 font-medium">Range</th>
                <th className="px-2 py-2 font-medium">Periods</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {years.map((y) => {
                const ps = periodSummary.get(y.id) ?? [];
                const open = ps.filter((p) => p.status === "OPEN").length;
                return (
                  <tr key={y.id} className="border-b border-border-subtle/60 last:border-0">
                    <td className="px-2 py-2.5 text-text-primary font-medium">
                      {y.name}
                      {y.is_current && (
                        <span className="ml-2 text-[11px] text-ai-700 bg-ai-50 border border-ai-100 px-2 py-0.5 rounded-full font-medium">
                          reporting year
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2.5 text-text-secondary tabular-nums text-xs">
                      {y.start_date} → {y.end_date}
                    </td>
                    <td className="px-2 py-2.5 text-text-secondary">
                      {ps.length} ({open} open)
                    </td>
                    <td className="px-2 py-2.5"><StatusBadge status={y.status} /></td>
                    <td className="px-2 py-2.5 text-right">
                      {!y.is_current && (
                        <button
                          onClick={() => switchReportingYear(y.id, y.name)}
                          disabled={yearsBusy}
                          className="text-xs font-medium text-ai-600 hover:text-ai-700 disabled:opacity-50 transition-colors"
                        >
                          Make reporting year
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="text-[11px] text-text-muted">
          “Add next financial year” creates the year following the latest one
          (starting the day after it ends) with 12 open monthly periods - click
          it again whenever you need the next one, recording never has to stop.
          Posting requires an open period; closed periods lock automatically.
        </p>
      </SectionCard>

      {/* ---- Document numbering ---- */}
      <SectionCard title="Document numbering" description="Prefixes used by the auto-numbering triggers (e.g. INV-000001)">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {PREFIX_FIELDS.map((f) => (
            <div key={f.key as string}>
              <label className="text-xs font-medium text-text-secondary">{f.label}</label>
              <input
                className={`${inputCls} mt-1`}
                value={prefixes[f.key as string] ?? ""}
                onChange={(e) => setPrefixes((p) => ({ ...p, [f.key as string]: e.target.value }))}
              />
            </div>
          ))}
        </div>
        <div className="max-w-48">
          <label className="text-xs font-medium text-text-secondary">Default payment terms (days)</label>
          <input type="number" min={0} className={`${inputCls} mt-1`} value={paymentTerms}
            onChange={(e) => setPaymentTerms(e.target.value)} />
        </div>
        {prefixesError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{prefixesError}</p>}
        <SaveButton saving={prefixesSaving} saved={prefixesSaved} onClick={savePrefixes} />
      </SectionCard>

      {/* ---- Invoice template ---- */}
      <SectionCard title="Invoice template" description="Default look for invoices and other customer documents">
        <div className="grid sm:grid-cols-3 gap-3">
          {TEMPLATES.map((t) => (
            <button
              key={t.id}
              onClick={() => saveTemplate(t.id)}
              disabled={templateSaving}
              className={cn(
                "text-left rounded-xl border p-4 transition-colors disabled:opacity-60",
                template === t.id
                  ? "border-ai-300 bg-ai-50/60 ring-2 ring-ai-100"
                  : "border-border-subtle hover:border-ai-200"
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-text-primary">{t.label}</span>
                {template === t.id && <Check className="w-4 h-4 text-ai-600" />}
              </div>
              <p className="text-xs text-text-secondary mt-1">{t.description}</p>
            </button>
          ))}
        </div>
        {templateError && <p className="text-xs text-error-600 bg-error-50 rounded-xl px-3 py-2">{templateError}</p>}
        {templateSaved && (
          <span className="flex items-center gap-1 text-xs text-success-700">
            <Check className="w-3.5 h-3.5" /> Saved - new invoices will use this template by default
          </span>
        )}
        <p className="text-[11px] text-text-muted">
          You can still switch templates per-invoice from the invoice screen.
        </p>
      </SectionCard>
    </div>
  );
}
