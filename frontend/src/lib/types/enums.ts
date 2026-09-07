// Enums matching backend Python models

export enum ExecutionStatus {
  RECEIVED = "RECEIVED",
  INTERPRETING = "INTERPRETING",
  PLANNING = "PLANNING",
  CONTEXT_LOADING = "CONTEXT_LOADING",
  AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION",
  VALIDATING = "VALIDATING",
  AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION",
  EXECUTING = "EXECUTING",
  VERIFYING = "VERIFYING",
  COMPLETED = "COMPLETED",
  FAILED = "FAILED",
  CANCELLED = "CANCELLED",
  REJECTED = "REJECTED",
}

export enum RiskLevel {
  LOW = "LOW",
  MEDIUM = "MEDIUM",
  HIGH = "HIGH",
  CRITICAL = "CRITICAL",
}

export enum JournalStatus {
  DRAFT = "DRAFT",
  VALIDATED = "VALIDATED",
  POSTED = "POSTED",
  REVERSED = "REVERSED",
  VOIDED = "VOIDED",
}

export enum InvoiceStatus {
  DRAFT = "DRAFT",
  CONFIRMED = "CONFIRMED",
  POSTED = "POSTED",
  PAID = "PAID",
  PARTIAL = "PARTIAL",
  VOIDED = "VOIDED",
  OVERDUE = "OVERDUE",
}

export enum BillStatus {
  DRAFT = "DRAFT",
  CONFIRMED = "CONFIRMED",
  POSTED = "POSTED",
  PAID = "PAID",
  PARTIAL = "PARTIAL",
  VOIDED = "VOIDED",
}

export enum QuotationStatus {
  DRAFT = "DRAFT",
  SENT = "SENT",
  ACCEPTED = "ACCEPTED",
  REJECTED = "REJECTED",
  EXPIRED = "EXPIRED",
  CONVERTED = "CONVERTED",
}

export enum ExpenseStatus {
  DRAFT = "DRAFT",
  CONFIRMED = "CONFIRMED",
  POSTED = "POSTED",
  VOIDED = "VOIDED",
}

export enum PaymentMethod {
  CASH = "CASH",
  BANK_TRANSFER = "BANK_TRANSFER",
  CHEQUE = "CHEQUE",
  ONLINE = "ONLINE",
  OTHER = "OTHER",
}

export enum AccountType {
  ASSET = "ASSET",
  LIABILITY = "LIABILITY",
  EQUITY = "EQUITY",
  REVENUE = "REVENUE",
  EXPENSE = "EXPENSE",
}

export enum NormalBalance {
  DEBIT = "DEBIT",
  CREDIT = "CREDIT",
}

export enum PaymentDirection {
  INBOUND = "INBOUND",
  OUTBOUND = "OUTBOUND",
}

export enum RoleCode {
  OWNER = "OWNER",
  ADMIN = "ADMIN",
  ACCOUNTANT = "ACCOUNTANT",
  MANAGER = "MANAGER",
  VIEWER = "VIEWER",
}

export enum BusinessType {
  SOFTWARE_HOUSE = "SOFTWARE_HOUSE",
  IT_SERVICES = "IT_SERVICES",
  CONSULTING = "CONSULTING",
  E_COMMERCE = "E_COMMERCE",
  MANUFACTURING = "MANUFACTURING",
  TRADING = "TRADING",
  CONSTRUCTION = "CONSTRUCTION",
  HEALTHCARE = "HEALTHCARE",
  EDUCATION = "EDUCATION",
  OTHER = "OTHER",
}

export const BusinessTypeLabels: Record<BusinessType, string> = {
  [BusinessType.SOFTWARE_HOUSE]: "Software House",
  [BusinessType.IT_SERVICES]: "IT Services",
  [BusinessType.CONSULTING]: "Consulting",
  [BusinessType.E_COMMERCE]: "E-Commerce",
  [BusinessType.MANUFACTURING]: "Manufacturing",
  [BusinessType.TRADING]: "Trading",
  [BusinessType.CONSTRUCTION]: "Construction",
  [BusinessType.HEALTHCARE]: "Healthcare",
  [BusinessType.EDUCATION]: "Education",
  [BusinessType.OTHER]: "Other",
};
