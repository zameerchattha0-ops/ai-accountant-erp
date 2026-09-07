-- Migration: create_extensions_enums_helpers
-- Extensions, enum types, shared helper functions

create extension if not exists pg_trgm;

-- ---- Enumerations ----
create type member_status          as enum ('INVITED','ACTIVE','SUSPENDED','REMOVED');
create type period_status          as enum ('OPEN','CLOSED','LOCKED');
create type account_type_code      as enum ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE');
create type normal_balance_code    as enum ('DEBIT','CREDIT');
create type journal_status         as enum ('DRAFT','VALIDATED','POSTED','REVERSED','VOIDED');
create type quotation_status       as enum ('DRAFT','SENT','ACCEPTED','REJECTED','EXPIRED','CONVERTED');
create type invoice_status         as enum ('DRAFT','ISSUED','PARTIALLY_PAID','PAID','OVERDUE','VOIDED','CREDITED');
create type bill_status            as enum ('DRAFT','OPEN','PARTIALLY_PAID','PAID','OVERDUE','VOIDED');
create type payment_status         as enum ('PENDING','COMPLETED','CANCELLED','REVERSED');
create type payment_direction      as enum ('INFLOW','OUTFLOW');
create type payment_method_code    as enum ('CASH','BANK_TRANSFER','CHEQUE','CARD','ONLINE','OTHER');
create type expense_status         as enum ('DRAFT','SUBMITTED','APPROVED','PAID','REJECTED','CANCELLED');
create type asset_status           as enum ('ACTIVE','FULLY_DEPRECIATED','DISPOSED','SOLD','WRITTEN_OFF');
create type depreciation_method    as enum ('STRAIGHT_LINE','DECLINING_BALANCE','UNITS_OF_PRODUCTION');
create type bank_txn_status        as enum ('UNRECONCILED','MATCHED','RECONCILED');
create type reconciliation_status  as enum ('IN_PROGRESS','COMPLETED');
create type project_status         as enum ('PLANNING','ACTIVE','ON_HOLD','COMPLETED','CANCELLED');
create type business_type_code    as enum ('SOFTWARE_HOUSE','IT_SERVICES','SAAS_STARTUP','DIGITAL_AGENCY','TECHNOLOGY_CONSULTANT','FREELANCER','SMALL_TECH_STARTUP','SERVICE_BUSINESS','OTHER');
create type audit_action_code      as enum ('CREATE','UPDATE','ARCHIVE','POST','REVERSE','CLOSE_PERIOD','REOPEN_PERIOD','AI_ACTION','USER_ACTION','SYSTEM_ACTION');
create type ai_request_status      as enum ('RECEIVED','PLANNING','AWAITING_CONFIRMATION','EXECUTING','COMPLETED','FAILED','CANCELLED');
create type actor_type_code        as enum ('USER','AI','SYSTEM');
create type contact_type_code      as enum ('PRIMARY','BILLING','SHIPPING','TECHNICAL','OTHER');
create type address_type_code      as enum ('BILLING','SHIPPING','REGISTERED','OTHER');
create type billing_type_code      as enum ('FIXED_PRICE','TIME_AND_MATERIALS','RETAINER');
create type service_unit_code      as enum ('HOUR','DAY','MONTH','FIXED','ITEM');
create type tax_direction_code     as enum ('OUTPUT','INPUT');
create type report_status          as enum ('PENDING','RUNNING','COMPLETED','FAILED');

-- ---- Shared helper: maintained updated_at ----
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;
