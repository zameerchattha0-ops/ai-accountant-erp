"use client";

import React, { useState } from "react";
import {
  FileText,
  CreditCard,
  Building2,
  Calendar,
  Layers,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Sliders,
  CheckCircle2,
  Percent,
  Play,
  Edit3,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import type {
  LivingDraft,
  AccountOption,
  ActionButton as ActionButtonType,
} from "@/lib/types/api";

interface LivingDraftCardProps {
  draft: LivingDraft;
  className?: string;
  defaultExpanded?: boolean;
  onAction?: (actionType: string, payload: Record<string, unknown>) => void;
  disabled?: boolean;
}

export default function LivingDraftCard({
  draft,
  className,
  defaultExpanded = true,
  onAction,
  disabled = false,
}: LivingDraftCardProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  // Extract interactive controls if attached
  const artifact = draft?.interactive_artifact;
  const pillCtrl = artifact?.controls?.find((c) => c.control_type === "account_pill_selector");
  const sliderCtrl = artifact?.controls?.find((c) => c.control_type === "depreciation_slider");
  const toggleCtrl = artifact?.controls?.find((c) => c.control_type === "wht_toggle");
  const btnCtrl = artifact?.controls?.find((c) => c.control_type === "action_button_group");

  // Local state for interactive controls
  const [selectedAccount, setSelectedAccount] = useState<string>(() => {
    const sel = pillCtrl?.account_pills?.find((p) => p.is_selected);
    return sel?.account_name || draft?.voucher_preview?.[0]?.account_name || "";
  });

  const [sliderValue, setSliderValue] = useState<number>(() => {
    return (
      sliderCtrl?.slider?.current_value ||
      draft?.depreciation_schedule?.useful_life_years ||
      3
    );
  });

  const [whtEnabled, setWhtEnabled] = useState<boolean>(() => {
    return toggleCtrl?.toggle?.is_enabled ?? false;
  });

  if (!draft) return null;

  const statusColors: Record<string, string> = {
    drafting: "bg-amber-50 text-amber-700 border-amber-200",
    awaiting_input: "bg-blue-50 text-blue-700 border-blue-200",
    ready_for_confirmation: "bg-emerald-50 text-emerald-700 border-emerald-200",
    posted: "bg-purple-50 text-purple-700 border-purple-200",
  };

  const statusLabel: Record<string, string> = {
    drafting: "DRAFTING",
    awaiting_input: "AWAITING DETAILS",
    ready_for_confirmation: "READY TO POST",
    posted: "POSTED TO LEDGER",
  };

  const formattedAmount =
    typeof draft.total_amount === "number"
      ? `PKR ${draft.total_amount.toLocaleString("en-PK", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}`
      : "Pending Amount";

  const channelLabel = draft.payment_channel
    ? draft.payment_channel.replace("_", " ").toUpperCase() +
      (draft.bank_name ? ` (${draft.bank_name})` : "")
    : "Pending Channel";

  // Reactive calculation for depreciation slider
  const totalCost = draft.total_amount || 0;
  const currentAnnual = totalCost > 0 ? totalCost / sliderValue : 0;
  const currentMonthly = currentAnnual / 12;

  // Handlers for bidirectional synchronization
  const handleSelectAccount = (pill: AccountOption) => {
    if (disabled) return;
    setSelectedAccount(pill.account_name);
    onAction?.("select_account", {
      account_code: pill.account_code,
      account_name: pill.account_name,
    });
  };

  const handleSliderChange = (newVal: number) => {
    if (disabled) return;
    setSliderValue(newVal);
    onAction?.("adjust_slider", { slider_value: newVal });
  };

  const handleToggleWht = (checked: boolean) => {
    if (disabled) return;
    setWhtEnabled(checked);
    onAction?.("toggle_wht", {
      is_enabled: checked,
      rate_percent: toggleCtrl?.toggle?.rate_percent || 5.0,
    });
  };

  const handleButtonClick = (btn: ActionButtonType) => {
    if (disabled) return;
    if (btn.requires_confirmation && btn.confirmation_message) {
      if (!window.confirm(btn.confirmation_message)) return;
    }
    onAction?.("trigger_button", { action_id: btn.action_id });
  };

  return (
    <div
      className={cn(
        "rounded-2xl border border-border-default bg-bg-surface/90 shadow-sm overflow-hidden transition-all duration-200",
        className
      )}
    >
      {/* Card Header */}
      <div
        className="flex items-center justify-between px-4 py-3 bg-bg-muted/50 cursor-pointer select-none border-b border-border-subtle"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="p-1.5 rounded-lg bg-ai-50 border border-ai-200 text-ai-600 shrink-0">
            <FileText className="w-4 h-4" />
          </div>
          <div className="truncate">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-text-primary truncate">
                {draft.document_type || "Provisional Voucher"}
              </span>
              <span
                className={cn(
                  "px-2 py-0.5 rounded-full text-[10px] font-mono font-medium border uppercase tracking-wider",
                  statusColors[draft.status] || "bg-bg-muted text-text-muted border-border-default"
                )}
              >
                {statusLabel[draft.status] || draft.status.toUpperCase()}
              </span>
            </div>
            <p className="text-[11px] text-text-secondary truncate mt-0.5">
              {draft.counterparty?.name ? `${draft.counterparty.name} • ` : ""}
              {formattedAmount}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-mono font-semibold text-text-primary hidden sm:inline">
            {formattedAmount}
          </span>
          <button
            type="button"
            className="p-1 rounded-md text-text-muted hover:text-text-primary hover:bg-bg-muted transition-colors"
          >
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Card Body */}
      {isExpanded && (
        <div className="p-4 space-y-4 text-xs text-text-secondary">
          {/* Metadata Highlights Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
            <div className="p-2.5 rounded-xl bg-bg-muted/40 border border-border-subtle">
              <div className="flex items-center gap-1.5 text-text-muted text-[11px]">
                <CreditCard className="w-3.5 h-3.5" />
                <span>Settlement</span>
              </div>
              <p className="font-medium text-text-primary mt-1 truncate">{channelLabel}</p>
            </div>

            <div className="p-2.5 rounded-xl bg-bg-muted/40 border border-border-subtle">
              <div className="flex items-center gap-1.5 text-text-muted text-[11px]">
                <Building2 className="w-3.5 h-3.5" />
                <span>Counterparty</span>
              </div>
              <p className="font-medium text-text-primary mt-1 truncate">
                {draft.counterparty?.name || "Pending Party"}
              </p>
            </div>

            <div className="p-2.5 rounded-xl bg-bg-muted/40 border border-border-subtle col-span-2 sm:col-span-1">
              <div className="flex items-center gap-1.5 text-text-muted text-[11px]">
                <Calendar className="w-3.5 h-3.5" />
                <span>Date</span>
              </div>
              <p className="font-medium text-text-primary mt-1 truncate">
                {draft.transaction_date || "Pending (Today)"}
              </p>
            </div>
          </div>

          {/* 1. INTERACTIVE CONTROL: Tappable Account Pills */}
          {pillCtrl?.account_pills && pillCtrl.account_pills.length > 0 && (
            <div className="space-y-1.5 p-3 rounded-xl bg-bg-muted/30 border border-border-subtle">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-text-primary text-[11px] flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-ai-600" />
                  Account Classification
                </span>
                <span className="text-[10px] text-text-muted">Tap to reclassify</span>
              </div>
              <div className="flex items-center gap-1.5 flex-wrap pt-1">
                {pillCtrl.account_pills.map((pill) => {
                  const isSelected = selectedAccount.includes(pill.account_code);
                  return (
                    <button
                      key={pill.account_code}
                      type="button"
                      disabled={disabled}
                      onClick={() => handleSelectAccount(pill)}
                      className={cn(
                        "px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all border flex items-center gap-1.5",
                        isSelected
                          ? "bg-ai-600 text-white border-ai-600 shadow-2xs"
                          : "bg-bg-surface hover:bg-bg-muted border-border-default text-text-secondary hover:text-text-primary"
                      )}
                    >
                      <span>{pill.account_name}</span>
                      {isSelected && <CheckCircle2 className="w-3 h-3 text-white" />}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* 2. INTERACTIVE CONTROL: Useful Life Depreciation Slider */}
          {sliderCtrl?.slider && (
            <div className="p-3.5 rounded-xl bg-purple-50/50 border border-purple-200 text-purple-900 space-y-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="font-semibold flex items-center gap-1.5">
                  <Sliders className="w-3.5 h-3.5 text-purple-600" />
                  IAS 16 Useful Life Slider
                </span>
                <span className="font-mono font-semibold bg-purple-100 px-2 py-0.5 rounded-md text-purple-800">
                  {sliderValue} Years Straight-Line
                </span>
              </div>

              <div className="pt-1">
                <input
                  type="range"
                  min={sliderCtrl.slider.min_value || 1}
                  max={sliderCtrl.slider.max_value || 10}
                  step={sliderCtrl.slider.step || 1}
                  value={sliderValue}
                  disabled={disabled}
                  onChange={(e) => handleSliderChange(parseInt(e.target.value, 10))}
                  className="w-full accent-purple-600 cursor-pointer"
                />
                <div className="flex justify-between text-[10px] text-purple-600 font-mono mt-0.5 px-0.5">
                  <span>1 yr</span>
                  <span>3 yrs (IT)</span>
                  <span>5 yrs (Furn)</span>
                  <span>10 yrs</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 pt-1 font-mono text-[11px] border-t border-purple-200/60">
                <div>
                  <span className="text-[10px] text-purple-700 block font-sans">Annual Depreciation</span>
                  <span className="font-semibold">PKR {currentAnnual.toLocaleString("en-PK", { maximumFractionDigits: 0 })}</span>
                </div>
                <div>
                  <span className="text-[10px] text-purple-700 block font-sans">Monthly Charge</span>
                  <span className="font-semibold">PKR {currentMonthly.toLocaleString("en-PK", { maximumFractionDigits: 0 })}/mo</span>
                </div>
              </div>
            </div>
          )}

          {/* 3. INTERACTIVE CONTROL: Section 153 WHT Toggle Switch */}
          {toggleCtrl?.toggle && (
            <div className="flex items-center justify-between p-3 rounded-xl bg-emerald-50/50 border border-emerald-200 text-emerald-950">
              <div className="space-y-0.5 pr-2">
                <div className="flex items-center gap-1.5 font-semibold text-[11px]">
                  <Percent className="w-3.5 h-3.5 text-emerald-600" />
                  <span>Section 153 Withholding Tax ({toggleCtrl.toggle.rate_percent}%)</span>
                </div>
                <p className="text-[10px] text-emerald-700">
                  {whtEnabled
                    ? `Withholding PKR ${(totalCost * (toggleCtrl.toggle.rate_percent / 100)).toLocaleString("en-PK")} (Net: PKR ${(totalCost * (1 - toggleCtrl.toggle.rate_percent / 100)).toLocaleString("en-PK")})`
                    : "Toggle to apply statutory tax deduction upon vendor settlement"}
                </p>
              </div>

              <label className="relative inline-flex items-center cursor-pointer shrink-0">
                <input
                  type="checkbox"
                  checked={whtEnabled}
                  disabled={disabled}
                  onChange={(e) => handleToggleWht(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-emerald-600"></div>
              </label>
            </div>
          )}

          {/* Provisional Voucher Journal Preview Table */}
          {draft.voucher_preview && draft.voucher_preview.length > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5 font-semibold text-text-primary text-[11px]">
                <Layers className="w-3.5 h-3.5 text-ai-600" />
                <span>Provisional Journal Entries</span>
              </div>
              <div className="rounded-xl border border-border-default overflow-hidden bg-bg-surface">
                <table className="w-full text-left text-[11px] divide-y divide-border-subtle">
                  <thead className="bg-bg-muted/60 text-text-muted font-medium">
                    <tr>
                      <th className="py-1.5 px-3">Account Head</th>
                      <th className="py-1.5 px-3 text-right">Debit (PKR)</th>
                      <th className="py-1.5 px-3 text-right">Credit (PKR)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-subtle font-mono">
                    {draft.voucher_preview.map((line, idx) => (
                      <tr key={idx} className="hover:bg-bg-muted/20">
                        <td className="py-1.5 px-3 font-sans text-text-primary">
                          <div>{line.account_name}</div>
                          {line.description && (
                            <div className="text-[10px] text-text-muted truncate max-w-xs">
                              {line.description}
                            </div>
                          )}
                        </td>
                        <td className="py-1.5 px-3 text-right text-text-primary">
                          {line.debit > 0
                            ? line.debit.toLocaleString("en-PK", {
                                minimumFractionDigits: 2,
                              })
                            : "-"}
                        </td>
                        <td className="py-1.5 px-3 text-right text-text-primary">
                          {line.credit > 0
                            ? line.credit.toLocaleString("en-PK", {
                                minimumFractionDigits: 2,
                              })
                            : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Statutory Compliance Notes */}
          {draft.compliance_notes && draft.compliance_notes.length > 0 && (
            <div className="space-y-1">
              {draft.compliance_notes.map((note, idx) => (
                <div
                  key={idx}
                  className={cn(
                    "p-2 rounded-lg text-[11px] leading-relaxed flex items-start gap-1.5",
                    note.includes("⚠️")
                      ? "bg-amber-50 text-amber-800 border border-amber-200"
                      : "bg-emerald-50 text-emerald-800 border border-emerald-200"
                  )}
                >
                  <ShieldCheck className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>{note}</span>
                </div>
              ))}
            </div>
          )}

          {/* 4. INTERACTIVE CONTROL: Action Buttons */}
          {btnCtrl?.buttons && btnCtrl.buttons.length > 0 && (
            <div className="pt-2 flex items-center justify-end gap-2 border-t border-border-subtle">
              {btnCtrl.buttons.map((btn) => (
                <button
                  key={btn.action_id}
                  type="button"
                  disabled={disabled || !btn.enabled}
                  onClick={() => handleButtonClick(btn)}
                  className={cn(
                    "px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5 shadow-2xs",
                    btn.variant === "primary"
                      ? "bg-ai-600 hover:bg-ai-700 text-white"
                      : btn.variant === "secondary"
                      ? "bg-bg-muted hover:bg-border-default text-text-primary"
                      : "bg-bg-surface border border-border-default hover:bg-bg-muted text-text-secondary"
                  )}
                >
                  {btn.action_id === "post_to_ledger" && <CheckCircle2 className="w-3.5 h-3.5" />}
                  {btn.action_id === "modify_terms" && <Edit3 className="w-3.5 h-3.5" />}
                  {btn.action_id === "run_scenario" && <Play className="w-3.5 h-3.5" />}
                  <span>{btn.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
