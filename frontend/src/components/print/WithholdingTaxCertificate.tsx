"use client";

import React, { useState } from "react";
import { Printer, X, ShieldCheck } from "lucide-react";
import { formatCurrency } from "@/lib/utils/currency";

export interface WithholdingTaxCertificateProps {
  certificateNumber?: string;
  issueDate?: string;
  paymentDate: string;
  paymentNumber: string;
  cprNumber?: string;
  // Withholding Agent (Buyer / Organization)
  agentName: string;
  agentNtn?: string | null;
  agentStrn?: string | null;
  agentAddress?: string | null;
  // Payee / Vendor
  payeeName: string;
  payeeNtn?: string | null;
  payeeStrn?: string | null;
  payeeAddress?: string | null;
  payeeStatus?: string | null;
  // Tax specifics
  sectionRef?: string;
  natureOfPayment?: string;
  grossAmount: number;
  taxRatePercent?: number;
  taxDeductedAmount?: number;
  currencyCode?: string;
  onClose?: () => void;
}

export default function WithholdingTaxCertificate({
  certificateNumber,
  issueDate = new Date().toISOString().slice(0, 10),
  paymentDate,
  paymentNumber,
  cprNumber: initialCpr,
  agentName,
  agentNtn,
  agentStrn,
  agentAddress,
  payeeName,
  payeeNtn,
  payeeStrn,
  payeeAddress,
  payeeStatus = "Active ATL Taxpayer",
  sectionRef = "Section 153(1)(a) - Purchase of Goods",
  natureOfPayment = "Supply of taxable goods",
  grossAmount,
  taxRatePercent = 5.0,
  taxDeductedAmount,
  currencyCode = "PKR",
  onClose,
}: WithholdingTaxCertificateProps) {
  const [rate, setRate] = useState<number>(taxRatePercent);
  const [cprNumber, setCprNumber] = useState<string>(() => {
    if (initialCpr) return initialCpr;
    const digits = (paymentNumber || "").replace(/[^0-9]/g, "").padStart(9, "0");
    return `CPR-${digits || "100000001"}`;
  });
  const [section, setSection] = useState<string>(sectionRef);
  const [nature, setNature] = useState<string>(natureOfPayment);

  // Computed tax values
  const calculatedTax = taxDeductedAmount !== undefined ? taxDeductedAmount : Math.round((grossAmount * (rate / 100)) * 100) / 100;
  const netPaid = Math.max(0, grossAmount - calculatedTax);
  const certNo = certificateNumber || `WHTC-${paymentDate.replace(/-/g, "")}-${paymentNumber}`;

  const handlePrint = () => {
    window.print();
  };

  const handleSectionChange = (val: string) => {
    setSection(val);
    if (val.includes("153(1)(a)")) {
      setNature("Purchase of Goods");
      setRate(5.0);
    } else if (val.includes("153(1)(b) - IT")) {
      setNature("IT and IT-enabled Services");
      setRate(4.0);
    } else if (val.includes("153(1)(b) - Specified")) {
      setNature("Specified Services");
      setRate(7.0);
    } else if (val.includes("153(1)(b) - Other")) {
      setNature("Other Services (Section 153)");
      setRate(14.0);
    } else if (val.includes("153(1)(c)")) {
      setNature("Execution of Contracts");
      setRate(7.5);
    } else if (val.includes("Wh-ST")) {
      setNature("Provincial Sales Tax Withholding");
      setRate(16.0);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 print:p-0 print:bg-white print:static">
      <div className="bg-bg-surface w-full max-w-4xl rounded-2xl border border-border-default shadow-2xl overflow-hidden print:border-none print:shadow-none print:max-w-none">
        {/* Modal Action Header (Hidden in Print) */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-subtle bg-bg-muted/40 print:hidden">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-ai-600" />
            <h3 className="text-sm font-semibold text-text-primary">
              Section 164 / Rule 42 Withholding Tax Certificate
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handlePrint}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-xs font-medium transition-colors shadow-2xs"
            >
              <Printer className="w-4 h-4" />
              Print Certificate
            </button>
            {onClose && (
              <button
                onClick={onClose}
                className="p-2 rounded-xl text-text-muted hover:text-text-primary hover:bg-bg-muted transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            )}
          </div>
        </div>

        {/* Customization Controls (Hidden in Print) */}
        <div className="px-6 py-3 border-b border-border-subtle bg-bg-surface grid grid-cols-1 sm:grid-cols-3 gap-3 print:hidden">
          <div>
            <label className="text-[11px] font-medium text-text-secondary">Statutory Section</label>
            <select
              value={section}
              onChange={(e) => handleSectionChange(e.target.value)}
              className="w-full mt-1 px-2.5 py-1.5 rounded-lg border border-border-default bg-bg-primary text-xs text-text-primary"
            >
              <option value="Section 153(1)(a) - Purchase of Goods (5%)">Section 153(1)(a) - Purchase of Goods (5%)</option>
              <option value="Section 153(1)(b) - IT Services (4%)">Section 153(1)(b) - IT Services (4%)</option>
              <option value="Section 153(1)(b) - Specified Services (7%)">Section 153(1)(b) - Specified Services (7%)</option>
              <option value="Section 153(1)(b) - Other Services (14%)">Section 153(1)(b) - Other Services (14%)</option>
              <option value="Section 153(1)(c) - Contracts (7.5%)">Section 153(1)(c) - Contracts (7.5%)</option>
              <option value="Provincial Wh-ST (16% / 15%)">Provincial Wh-ST on Services</option>
            </select>
          </div>
          <div>
            <label className="text-[11px] font-medium text-text-secondary">Deduction Rate (%)</label>
            <input
              type="number"
              step="0.1"
              value={rate}
              onChange={(e) => setRate(Number(e.target.value))}
              className="w-full mt-1 px-2.5 py-1.5 rounded-lg border border-border-default bg-bg-primary text-xs text-text-primary font-mono"
            />
          </div>
          <div>
            <label className="text-[11px] font-medium text-text-secondary">FBR CPR / Treasury Number</label>
            <input
              type="text"
              value={cprNumber}
              onChange={(e) => setCprNumber(e.target.value)}
              placeholder="e.g. CPR-123456789"
              className="w-full mt-1 px-2.5 py-1.5 rounded-lg border border-border-default bg-bg-primary text-xs text-text-primary font-mono"
            />
          </div>
        </div>

        {/* Printable Official Document Body */}
        <div className="p-8 bg-white text-slate-900 font-serif print:p-0 print:m-0">
          <div className="border-2 border-slate-900 p-6 space-y-6">
            {/* Header */}
            <div className="text-center space-y-1 border-b border-slate-800 pb-4">
              <h1 className="text-lg font-bold uppercase tracking-wider">Government of Pakistan</h1>
              <h2 className="text-base font-semibold uppercase">Federal Board of Revenue / Revenue Division</h2>
              <h3 className="text-sm font-bold tracking-wide mt-2 underline">
                CERTIFICATE OF COLLECTION OR DEDUCTION OF TAX
              </h3>
              <p className="text-xs italic font-sans text-slate-600">
                [Prescribed under Section 164 of the Income Tax Ordinance, 2001 & Rule 42 of Income Tax Rules, 2002]
              </p>
            </div>

            {/* Certificate Meta */}
            <div className="grid grid-cols-2 text-xs font-sans gap-4 border-b border-slate-300 pb-3">
              <div>
                <span className="font-bold text-slate-700">Certificate No:</span>{" "}
                <span className="font-mono font-semibold">{certNo}</span>
              </div>
              <div className="text-right">
                <span className="font-bold text-slate-700">Date of Issue:</span>{" "}
                <span className="font-mono">{issueDate}</span>
              </div>
            </div>

            {/* Parties: Withholding Agent & Payee */}
            <div className="grid grid-cols-2 gap-6 text-xs font-sans">
              {/* Agent */}
              <div className="p-3 border border-slate-300 rounded bg-slate-50/50 space-y-1">
                <span className="font-bold uppercase tracking-wide text-[10px] text-slate-600">
                  Withholding Agent (Person Deducting Tax)
                </span>
                <p className="font-bold text-sm text-slate-900">{agentName}</p>
                <div className="space-y-0.5 text-slate-700">
                  <p><span className="font-semibold">NTN:</span> <span className="font-mono">{agentNtn || "—"}</span></p>
                  <p><span className="font-semibold">STRN:</span> <span className="font-mono">{agentStrn || "—"}</span></p>
                  {agentAddress && <p><span className="font-semibold">Address:</span> {agentAddress}</p>}
                </div>
              </div>

              {/* Payee */}
              <div className="p-3 border border-slate-300 rounded bg-slate-50/50 space-y-1">
                <span className="font-bold uppercase tracking-wide text-[10px] text-slate-600">
                  Taxpayer / Payee (Person from Whom Tax Deducted)
                </span>
                <p className="font-bold text-sm text-slate-900">{payeeName}</p>
                <div className="space-y-0.5 text-slate-700">
                  <p><span className="font-semibold">NTN:</span> <span className="font-mono">{payeeNtn || "—"}</span></p>
                  <p><span className="font-semibold">STRN:</span> <span className="font-mono">{payeeStrn || "—"}</span></p>
                  {payeeAddress && <p><span className="font-semibold">Address:</span> {payeeAddress}</p>}
                  <p><span className="font-semibold">Taxpayer Status:</span> {payeeStatus}</p>
                </div>
              </div>
            </div>

            {/* Payment & Tax Deduction Breakdown Table */}
            <div className="space-y-2">
              <span className="text-xs font-bold font-sans uppercase tracking-wider text-slate-800">
                Payment & Tax Deduction Particulars
              </span>
              <table className="w-full text-xs font-sans border-collapse border border-slate-400">
                <thead>
                  <tr className="bg-slate-100 text-slate-800 text-left">
                    <th className="border border-slate-400 px-3 py-2 font-bold">Payment Ref</th>
                    <th className="border border-slate-400 px-3 py-2 font-bold">Date of Payment</th>
                    <th className="border border-slate-400 px-3 py-2 font-bold">Nature of Supply / Section</th>
                    <th className="border border-slate-400 px-3 py-2 text-right font-bold">Gross Amount</th>
                    <th className="border border-slate-400 px-3 py-2 text-right font-bold">Rate</th>
                    <th className="border border-slate-400 px-3 py-2 text-right font-bold">Tax Deducted</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="border border-slate-400 px-3 py-2 font-mono">{paymentNumber}</td>
                    <td className="border border-slate-400 px-3 py-2 font-mono">{paymentDate}</td>
                    <td className="border border-slate-400 px-3 py-2">
                      <div className="font-semibold">{section}</div>
                      <div className="text-[10px] text-slate-600">{nature}</div>
                    </td>
                    <td className="border border-slate-400 px-3 py-2 text-right font-mono font-medium">
                      {formatCurrency(grossAmount, currencyCode)}
                    </td>
                    <td className="border border-slate-400 px-3 py-2 text-right font-mono font-semibold">
                      {rate.toFixed(1)}%
                    </td>
                    <td className="border border-slate-400 px-3 py-2 text-right font-mono font-bold text-slate-900">
                      {formatCurrency(calculatedTax, currencyCode)}
                    </td>
                  </tr>
                  <tr className="bg-slate-50 font-bold">
                    <td colSpan={3} className="border border-slate-400 px-3 py-2 text-right uppercase">
                      Total Tax Deducted & Deposited into Treasury:
                    </td>
                    <td colSpan={3} className="border border-slate-400 px-3 py-2 text-right font-mono text-sm">
                      {formatCurrency(calculatedTax, currencyCode)}
                    </td>
                  </tr>
                  <tr className="bg-white">
                    <td colSpan={3} className="border border-slate-400 px-3 py-2 text-right text-slate-600">
                      Net Amount Disbursed to Payee:
                    </td>
                    <td colSpan={3} className="border border-slate-400 px-3 py-2 text-right font-mono text-slate-700">
                      {formatCurrency(netPaid, currencyCode)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Treasury Deposit Particulars */}
            <div className="p-3 border border-slate-300 rounded text-xs font-sans bg-slate-50 space-y-1">
              <span className="font-bold text-slate-800 uppercase tracking-wide text-[10px]">
                FBR / National Bank of Pakistan (NBP) Deposit Verification
              </span>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="font-semibold text-slate-700">Computerized Payment Receipt (CPR) No:</span>{" "}
                  <span className="font-mono font-bold">{cprNumber}</span>
                </div>
                <div>
                  <span className="font-semibold text-slate-700">Payment Status:</span>{" "}
                  <span className="font-semibold text-emerald-700">Deposited in Federal Treasury</span>
                </div>
              </div>
            </div>

            {/* Statutory Certification Statement */}
            <div className="pt-2 text-xs font-sans text-slate-700 leading-relaxed border-t border-slate-300 space-y-2">
              <p>
                <strong>Statutory Declaration:</strong> Certified that the sum of{" "}
                <strong>{formatCurrency(calculatedTax, currencyCode)}</strong> has been deducted at source under the
                provisions of the Income Tax Ordinance, 2001 and deposited to the credit of the Federal Board of Revenue /
                Government of Pakistan treasury via Computerized Payment Receipt (CPR) referenced above.
              </p>
            </div>

            {/* Signatures */}
            <div className="grid grid-cols-2 pt-8 text-xs font-sans">
              <div className="space-y-8">
                <div className="border-b border-slate-400 w-48" />
                <p className="font-semibold text-slate-700">Official Stamp / Seal</p>
              </div>
              <div className="space-y-8 text-right">
                <div className="border-b border-slate-400 w-48 ml-auto" />
                <p className="font-semibold text-slate-700">Signature of Withholding Agent / Officer</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

