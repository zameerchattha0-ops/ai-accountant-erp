/**
 * Entity types mirroring the live Supabase public schema.
 * Column names match information_schema exactly (verified 2026-08-29).
 */

export interface Customer {
  id: string;
  organization_id: string;
  customer_code: string | null;
  name: string;
  legal_name: string | null;
  tax_number: string | null;
  email: string | null;
  phone: string | null;
  website: string | null;
  credit_limit: number | null;
  payment_terms_days: number | null;
  currency_code: string | null;
  receivable_account_id: string | null;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface Supplier {
  id: string;
  organization_id: string;
  supplier_code: string | null;
  name: string;
  legal_name: string | null;
  tax_number: string | null;
  email: string | null;
  phone: string | null;
  website: string | null;
  credit_limit: number | null;
  payment_terms_days: number | null;
  currency_code: string | null;
  payable_account_id: string | null;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// Verified against live pg_enum 2026-08-29:
// invoice_status  = DRAFT | ISSUED | PARTIALLY_PAID | PAID | OVERDUE | VOIDED | CREDITED
// bill_status     = DRAFT | OPEN | PARTIALLY_PAID | PAID | OVERDUE | VOIDED
// quotation_status = DRAFT | SENT | ACCEPTED | REJECTED | EXPIRED | CONVERTED
export type DocumentStatus =
  | "DRAFT" | "ISSUED" | "PARTIALLY_PAID" | "PAID" | "OVERDUE" | "VOIDED" | "CREDITED";

export type BillStatus =
  | "DRAFT" | "OPEN" | "PARTIALLY_PAID" | "PAID" | "OVERDUE" | "VOIDED";

export type QuotationStatus =
  | "DRAFT" | "SENT" | "ACCEPTED" | "REJECTED" | "EXPIRED" | "CONVERTED";

export type JournalStatus = "DRAFT" | "VALIDATED" | "POSTED" | "REVERSED" | "VOIDED";

export type AccountType = "ASSET" | "LIABILITY" | "EQUITY" | "REVENUE" | "EXPENSE";

export interface InvoiceItem {
  id: string;
  organization_id: string;
  invoice_id: string;
  line_number: number;
  description: string;
  product_id: string | null;
  service_id: string | null;
  project_id: string | null;
  quantity: number;
  unit_price: number;
  discount_amount: number;
  tax_rate_id: string | null;
  tax_amount: number;
  line_total: number;
  revenue_account_id: string | null;
}

export interface Invoice {
  id: string;
  organization_id: string;
  invoice_number: string;
  customer_id: string;
  project_id: string | null;
  quotation_id: string | null;
  status: DocumentStatus;
  invoice_date: string;
  due_date: string | null;
  payment_terms_days: number | null;
  currency_code: string;
  subtotal: number;
  discount_total: number;
  tax_total: number;
  total: number;
  amount_paid: number;
  notes: string | null;
  terms: string | null;
  journal_entry_id: string | null;
  sent_at: string | null;
  paid_at: string | null;
  voided_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PurchaseBillItem {
  id: string;
  organization_id: string;
  bill_id: string;
  line_number: number;
  description: string;
  product_id: string | null;
  expense_account_id: string | null;
  project_id: string | null;
  fixed_asset_id: string | null;
  quantity: number;
  unit_price: number;
  discount_amount: number;
  tax_rate_id: string | null;
  tax_amount: number;
  line_total: number;
}

export interface PurchaseBill {
  id: string;
  organization_id: string;
  bill_number: string;
  supplier_id: string;
  status: BillStatus;
  bill_date: string;
  due_date: string | null;
  payment_terms_days: number | null;
  supplier_invoice_ref: string | null;
  currency_code: string;
  subtotal: number;
  discount_total: number;
  tax_total: number;
  total: number;
  amount_paid: number;
  notes: string | null;
  journal_entry_id: string | null;
  paid_at: string | null;
  voided_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface QuotationItem {
  id: string;
  organization_id: string;
  quotation_id: string;
  line_number: number;
  description: string;
  product_id: string | null;
  service_id: string | null;
  project_id: string | null;
  quantity: number;
  unit_price: number;
  discount_amount: number;
  tax_rate_id: string | null;
  tax_amount: number;
  line_total: number;
  notes: string | null;
}

export interface Quotation {
  id: string;
  organization_id: string;
  quotation_number: string;
  revision: number;
  customer_id: string;
  project_id: string | null;
  status: QuotationStatus;
  quotation_date: string;
  valid_until: string | null;
  currency_code: string;
  subtotal: number;
  discount_total: number;
  tax_total: number;
  total: number;
  notes: string | null;
  terms: string | null;
  created_at: string;
  updated_at: string;
}

export interface Account {
  id: string;
  organization_id: string;
  code: string;
  name: string;
  account_type: AccountType;
  parent_account_id: string | null;
  normal_balance: "DEBIT" | "CREDIT";
  is_system: boolean;
  is_control_account: boolean;
  is_active: boolean;
  description: string | null;
}

export interface JournalLine {
  id: string;
  organization_id: string;
  entry_id: string;
  line_number: number;
  account_id: string;
  description: string | null;
  debit: number;
  credit: number;
  customer_id: string | null;
  supplier_id: string | null;
  project_id: string | null;
}

export interface JournalEntry {
  id: string;
  organization_id: string;
  journal_number: string;
  transaction_date: string;
  accounting_period_id: string | null;
  description: string;
  reference: string | null;
  status: JournalStatus;
  source_type: string | null;
  source_id: string | null;
  currency_code: string;
  total_debit: number;
  total_credit: number;
  posted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrganizationSettings {
  id: string;
  organization_id: string;
  invoice_prefix: string;
  quotation_prefix: string;
  bill_prefix: string;
  credit_note_prefix: string;
  journal_prefix: string;
  payment_prefix: string;
  receipt_prefix: string;
  customer_prefix: string;
  supplier_prefix: string;
  project_prefix: string;
  expense_prefix: string;
  asset_prefix: string;
  return_prefix: string;
  default_payment_terms_days: number;
  settings: Record<string, unknown> | null;
}

export interface FinancialYear {
  id: string;
  organization_id: string;
  name: string;
  start_date: string;
  end_date: string;
  status: "OPEN" | "CLOSED";
  is_current: boolean;
}

export interface AccountingPeriod {
  id: string;
  organization_id: string;
  financial_year_id: string;
  period_number: number;
  name: string;
  start_date: string;
  end_date: string;
  status: "OPEN" | "CLOSED" | "LOCKED";
}

export type InvoiceTemplateId = "modern" | "professional" | "minimal";

/* ---- Reporting views ---- */

export interface GeneralLedgerRow {
  journal_entry_id: string;
  journal_number: string;
  journal_line_id: string;
  transaction_date: string;
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: AccountType;
  line_description: string | null;
  entry_description: string;
  debit: number;
  credit: number;
  entry_status: string;
}

export interface TrialBalanceRow {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: AccountType;
  normal_balance: "DEBIT" | "CREDIT";
  total_debit: number;
  total_credit: number;
  balance: number;
}

export interface StatementRow {
  account_type: AccountType;
  account_code: string;
  account_name: string;
  net_amount: number;
}

export interface AgingRow {
  organization_id: string;
  customer_id?: string;
  customer_name?: string;
  supplier_id?: string;
  supplier_name?: string;
  total_outstanding: number;
  bucket_current: number;
  bucket_1_30: number;
  bucket_31_60: number;
  bucket_61_90: number;
  bucket_90_plus: number;
}

export interface ProjectProfitabilityRow {
  organization_id: string;
  project_id: string;
  project_code: string;
  project_name: string;
  status: string;
  budget: number | null;
  project_revenue: number;
  project_costs: number;
  gross_profit: number;
  margin_percent: number | null;
}

/* ---- Banking ---- */

export type PaymentDirection = "INFLOW" | "OUTFLOW";

export type PaymentMethod = "CASH" | "BANK_TRANSFER" | "CHEQUE" | "CARD" | "ONLINE" | "OTHER";

export type PaymentStatus = "PENDING" | "COMPLETED" | "CANCELLED" | "REVERSED";

export type BankTxnStatus = "UNRECONCILED" | "MATCHED" | "RECONCILED";

export type CashFlowCategory = "OPERATING" | "INVESTING" | "FINANCING";

export interface BankAccount {
  id: string;
  organization_id: string;
  account_name: string;
  bank_name: string;
  account_number_masked: string | null;
  iban: string | null;
  branch_code: string | null;
  currency_code: string | null;
  gl_account_id: string;
  current_balance: number;
  last_reconciled_at: string | null;
  is_active: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface BankTransaction {
  id: string;
  organization_id: string;
  bank_account_id: string;
  transaction_date: string;
  value_date: string | null;
  direction: PaymentDirection;
  amount: number;
  description: string | null;
  reference: string | null;
  counterparty: string | null;
  status: BankTxnStatus;
  journal_entry_id: string | null;
  reconciliation_id: string | null;
  is_transfer: boolean;
  created_at: string;
  updated_at: string;
}

export interface Payment {
  id: string;
  organization_id: string;
  payment_number: string;
  payment_date: string;
  direction: PaymentDirection;
  payment_method: PaymentMethod;
  bank_account_id: string | null;
  cash_account_id: string | null;
  supplier_id: string | null;
  expense_id: string | null;
  amount: number;
  currency_code: string | null;
  reference: string | null;
  notes: string | null;
  status: PaymentStatus;
  journal_entry_id: string | null;
  is_transfer: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface Receipt {
  id: string;
  organization_id: string;
  receipt_number: string;
  receipt_date: string;
  payment_method: PaymentMethod;
  bank_account_id: string | null;
  cash_account_id: string | null;
  customer_id: string | null;
  amount: number;
  currency_code: string | null;
  reference: string | null;
  notes: string | null;
  status: PaymentStatus;
  journal_entry_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaymentAllocation {
  id: string;
  organization_id: string;
  payment_id: string;
  bill_id: string | null;
  expense_id: string | null;
  amount_allocated: number;
  created_at: string;
}

export interface ReceiptAllocation {
  id: string;
  organization_id: string;
  receipt_id: string;
  invoice_id: string | null;
  credit_note_id: string | null;
  amount_allocated: number;
  created_at: string;
}

export interface CashFlowRow {
  organization_id: string;
  transaction_date: string;
  journal_entry_id: string;
  journal_number: string;
  source_type: string | null;
  cash_flow_category: CashFlowCategory;
  cash_account_id: string;
  cash_account_code: string;
  cash_account_name: string;
  contra_account_id: string;
  contra_account_code: string;
  contra_account_name: string;
  contra_account_type: AccountType;
  debit: number;
  credit: number;
  net_amount: number;
  entry_description: string;
  contra_description: string | null;
}
