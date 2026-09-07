-- Migration: banking_payments_receipts_enhancements
-- Adds missing columns for bank account defaults, transfer flags,
-- and creates the v_cash_flow reporting view.

-- 1. Default bank account indicator
ALTER TABLE bank_accounts
  ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT false;

-- 2. Transfer flag on bank transactions (internal bank-to-bank)
ALTER TABLE bank_transactions
  ADD COLUMN IF NOT EXISTS is_transfer BOOLEAN NOT NULL DEFAULT false;

-- 3. Transfer flag on payments (for bank-to-bank transfers)
ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS is_transfer BOOLEAN NOT NULL DEFAULT false;

-- 4. Ensure only one default bank account per organisation
CREATE OR REPLACE FUNCTION trg_bank_accounts_single_default()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.is_default = true THEN
    UPDATE bank_accounts
       SET is_default = false
     WHERE organization_id = NEW.organization_id
       AND id <> NEW.id
       AND is_default = true;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_bank_accounts_single_default ON bank_accounts;
CREATE TRIGGER trg_bank_accounts_single_default
  BEFORE INSERT OR UPDATE OF is_default ON bank_accounts
  FOR EACH ROW
  WHEN (NEW.is_default = true)
  EXECUTE FUNCTION trg_bank_accounts_single_default();

-- 5. Cash Flow reporting view
--    Classifies every posted journal line touching a BANK or CASH account
--    into OPERATING / INVESTING / FINANCING based on the contra account type.
CREATE OR REPLACE VIEW v_cash_flow AS
SELECT
  jl.organization_id,
  je.transaction_date,
  je.id                    AS journal_entry_id,
  je.journal_number,
  je.source_type,
  CASE
    WHEN contra.account_type IN ('REVENUE', 'EXPENSE')        THEN 'OPERATING'::text
    WHEN contra.account_type = 'ASSET'                         THEN 'INVESTING'::text
    WHEN contra.account_type IN ('LIABILITY', 'EQUITY')        THEN 'FINANCING'::text
    ELSE 'OPERATING'::text
  END                      AS cash_flow_category,
  a.id                     AS cash_account_id,
  a.code                   AS cash_account_code,
  a.name                   AS cash_account_name,
  contra.id                AS contra_account_id,
  contra.code              AS contra_account_code,
  contra.name              AS contra_account_name,
  contra.account_type      AS contra_account_type,
  jl.debit,
  jl.credit,
  (jl.debit - jl.credit)   AS net_amount,
  je.description           AS entry_description,
  l2.description           AS contra_description
FROM journal_lines jl
JOIN journal_entries je
  ON je.id = jl.entry_id
 AND je.status = 'POSTED'
JOIN accounts a
  ON a.id = jl.account_id
JOIN account_categories ac
  ON ac.id = a.account_category_id
 AND ac.code IN ('BANK', 'CASH')
-- Contra line: the other side of the journal entry
JOIN journal_lines l2
  ON l2.entry_id = je.id
 AND l2.id <> jl.id
JOIN accounts contra
  ON contra.id = l2.account_id
 AND contra.id <> a.id;

-- 6. Enable RLS on the view (views inherit from underlying tables,
--    but we add an explicit security barrier for clarity)
COMMENT ON VIEW v_cash_flow IS
  'Cash flow statement data. Classifies posted journal lines touching bank/cash accounts into Operating, Investing, Financing activities based on contra account type.';
