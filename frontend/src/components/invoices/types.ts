import type { Invoice, InvoiceItem, Customer } from "@/lib/types/entities";
import type { OrgContext } from "@/lib/hooks/useOrg";

export interface InvoiceTemplateProps {
  invoice: Invoice;
  items: InvoiceItem[];
  customer: Pick<Customer, "name" | "email" | "phone" | "tax_number" | "customer_code"> | null;
  org: Pick<OrgContext, "name" | "legal_name" | "tax_number" | "base_currency_code"> | null;
  formatAmount: (n: number) => string;
}

export const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "-";
