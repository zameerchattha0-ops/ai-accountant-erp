# CONVERSATIONAL PARTNER ACCOUNTING SPECIFICATIONS & STATUTORY RULES

**Document Reference:** `DOC-ACC-2026-V2`  
**Author:** Senior Chartered Accountant (FCA / CPA) & Lead Financial Controller  
**Scope:** LLM-First Natural Conversational Partner (Claude-style ERP Agent)  
**Status:** BINDING STATUTORY & CONVERSATIONAL GOVERNANCE SPECIFICATION  

---

## 1. STANDARD CORPORATE ASSET CLASSES, USEFUL LIVES & DEPRECIATION SCHEDULES (IAS 16)

Under **IAS 16 (Property, Plant and Equipment)**, depreciation is the systematic allocation of the depreciable amount of an asset over its estimated useful life. Depreciation begins when the asset is **available for use** (IAS 16.55).

### 1.1 Corporate Asset Class Schedule & Accounting Defaults

| Asset Class | COA Code Head | Default Useful Life | Accounting Depreciation Method | Corporate Default Annual Rate | Residual / Salvage Value Convention |
|---|---|:---:|:---:|:---:|:---:|
| **Computer & IT Hardware** *(Laptops, Desktops, Servers, Network Switches, Printers)* | `1520` | **3 Years** | Straight-Line (SLM) | **33.33%** | Nominal / 5% of historical cost |
| **Furniture & Fixtures** *(Executive Desks, Ergonomic Chairs, Conference Tables, Cabinets)* | `1510` | **10 Years** (or 5 yrs for high-wear) | Straight-Line (SLM) | **10.00%** | 5% of historical cost |
| **Office Equipment & Electronics** *(Air Conditioners, High-Cap UPS, Photocopiers, Projectors)* | `1525` | **5 Years** | Straight-Line (SLM) | **20.00%** | 5% of historical cost |
| **Motor Vehicles** *(Commercial Vans, Delivery Bikes, Company Sedans)* | `1540` | **5 Years** | Straight-Line (SLM) | **20.00%** | 10% - 20% of historical cost |
| **Plant & Industrial Machinery** *(Generators, CNC Machines, Boilers, Packaging Lines)* | `1530` | **10 Years** | Straight-Line (SLM) | **10.00%** | 5% - 10% of historical cost |
| **Leasehold Improvements** *(Partitions, False Ceilings, Electrical Infrastructure)* | `1550` | **Shorter of Lease Term or 5 Years** | Straight-Line (SLM) | e.g. **20.00%** | Nil (0%) |
| **Intangible Software & Licenses (IAS 38)** *(ERP Perpetual Licenses, Custom Software)* | `1600` | **3 - 5 Years** | Amortization (SLM) | **20.00% - 33.33%** | Nil (0%) |

### 1.2 Depreciation Timing & Prorating Conventions
Corporate best practice mandates the **Monthly Pro-Rata Convention**:
- Asset acquired/available on or before the 15th of the month: Charge full month depreciation.
- Asset acquired after the 15th: Depreciation commences from the 1st of the following month.
- Monthly Straight-Line Charge Formula:
  $$\text{Monthly Depreciation} = \frac{\text{Historical Cost} - \text{Estimated Residual Value}}{\text{Useful Life (Years)} \times 12}$$

### 1.3 Conversational Smart Defaults (Single High-Leverage Question)
When a user mentions buying a laptop or office furniture, the agent must **not** interrogate the user with a 5-question barrage. It suggests standard defaults in the chat while reflecting them immediately on the Living Draft Voucher Card:
> *"I've drafted the acquisition of the 5 executive tables (PKR 150,000) under **Furniture & Fixtures (Account 1510)** with our standard **10-year useful life (10% straight-line)** and 5% salvage value. Let me know if your company follows a different useful life or if you'd like to adjust this!"*

---

## 2. STATUTORY TAX LAW (PAKISTAN INCOME TAX ORDINANCE, 2001)

Users frequently ask consultative questions during natural chat flow. The agent must provide authoritative, legally grounded answers.

### 2.1 Section 73: Cash Payment Prohibitions & Banking Channel Mandates
* **The Rule for Expenses (Section 73(1) read with Section 21(l)):**
  - Any business expenditure under a single account head exceeding **PKR 50,000** for a single transaction or aggregate transactions must be settled via a **crossed banking instrument** (crossed cheque, crossed pay order, crossed demand draft, or business online banking transfer).
  - Both the paying account and the receiving account must be documented business bank accounts.
  - *Consequence of Violation:* 100% of the expenditure is **disallowed** as a deductible expense by the FBR, added back to taxable income, and taxed at the corporate rate (29% corporate tax + super tax up to 10% + default surcharge u/s 205).
* **The Rule for Assets (Section 73(2) & 73(3)):**
  - Purchase of depreciable assets exceeding **PKR 250,000** paid in cash is prohibited.
  - *Consequence:* Tax depreciation and initial depreciation allowances are **permanently disallowed**.
* **Statutory Exemptions from Section 73:**
  - Utility payments (electricity, gas, water bills).
  - Government taxes, duties, and statutory fees.
  - Freight/cargo charges paid to small unregistered individual transporters.
  - Postage and courier payments below nominal limits.
  - Travel fare paid to scheduled airlines/railways.

---

### 2.2 Section 153: Withholding Tax (WHT) on Goods vs. Services vs. Contracts
When a corporate entity makes a commercial payment, it acts as a statutory Withholding Agent.

#### Statutory Rate Matrix (Finance Act 2024–2025):
| Nature of Transaction | Section Head | Active Taxpayer (Filer) Rate | Inactive (Non-Filer) Rate (10th Sched: 2x) | Annual Exemption Threshold |
|---|---|:---:|:---:|---|
| **Supply of Goods – Corporate Vendor** | S. 153(1)(a) | **5.0%** | **10.0%** | PKR 75,000 / fiscal year |
| **Supply of Goods – Individual / AOP** | S. 153(1)(a) | **5.5%** | **11.0%** | PKR 75,000 / fiscal year |
| **IT & IT-Enabled Services** | S. 153(1)(b) | **4.0%** | **8.0%** | PKR 30,000 / fiscal year |
| **Specified Services** *(Freight, Transport, Hotel, Courier, Security, Cargo)* | S. 153(1)(b) | **7.0%** | **14.0%** | PKR 30,000 / fiscal year |
| **Independent Professional Services** *(Legal, Audit, Tax, Engineering, Medical, Consulting)* | S. 153(1)(b) | **15.0%** | **30.0%** | PKR 30,000 / fiscal year |
| **Other General Services** *(Contractors, Maintenance, Catering)* | S. 153(1)(b) | **14.0%** | **28.0%** | PKR 30,000 / fiscal year |
| **Print / Electronic Media Advertising** | S. 153(1)(b) | **1.5%** | **3.0%** | PKR 30,000 / fiscal year |
| **Execution of Contracts – Corporate** | S. 153(1)(c) | **7.5%** | **15.0%** | PKR 75,000 / fiscal year |
| **Execution of Contracts – Individual / AOP** | S. 153(1)(c) | **8.0%** | **16.0%** | PKR 75,000 / fiscal year |
| **Valid Exemption Certificate u/s 159** | S. 159 | **0.0%** | N/A | Exemption Order Valid |

---

### 2.3 Third Schedule Tax Depreciation vs. IAS 16 Accounting Depreciation
This is the most critical consultative concept for corporate CFOs and accountants. **Accounting profit is not taxable income.**

```
┌───────────────────────────────────────────┬───────────────────────────────────────────┐
│       IAS 16 ACCOUNTING DEPRECIATION      │       THIRD SCHEDULE TAX DEPRECIATION     │
├───────────────────────────────────────────┼───────────────────────────────────────────┤
│ Governing Standard: IFRS / IAS 16         │ Governing Law: ITO 2001, Section 22 & 23  │
│ Method: Straight-Line Method (SLM)        │ Method: Reducing Balance / WDV ONLY       │
│ Base: (Historical Cost - Salvage Value)   │ Base: Written Down Value (WDV)            │
│ Useful Life: Management Estimate          │ Rates: Fixed Statutory Rates:             │
│   - Computers: 33.33% SLM (3 yrs)         │   - Computers / IT Hardware: 30% WDV      │
│   - Furniture: 10% SLM (10 yrs)           │   - Furniture & Fixtures: 15% WDV         │
│   - Machinery: 10% SLM (10 yrs)           │   - Plant & Machinery: 15% WDV            │
│   - Motor Vehicles: 20% SLM (5 yrs)       │   - Motor Vehicles: 15% WDV (Capped!)     │
│ Timing: Pro-rata monthly from ready date  │ Timing: Full year in acquisition year;    │
│                                           │         ZERO depreciation in disposal yr  │
│ Initial Allowance: None under IFRS        │ Initial Allowance (Sec 23): 25% for plant │
│ Passenger Vehicle Cap: None (Actual cost) │ Passenger Vehicle Cap: Capped at PKR 7.5M │
└───────────────────────────────────────────┴───────────────────────────────────────────┘
```

#### Tax Reconciliation & Deferred Tax (IAS 12):
1. In the tax computation, Accounting Depreciation is **added back** to Accounting Net Profit.
2. Tax Depreciation (and Initial Allowance) is **deducted** from profit.
3. The temporary timing difference creates a **Deferred Tax Liability (DTL)** or **Deferred Tax Asset (DTA)** calculated at 29%.

---

## 3. REQUIRED COMPONENTS OF A COMPLIANT "LIVING DRAFT VOUCHER CARD"

The real-time preview pane displays a live, reactive voucher card that updates synchronously with every conversational turn:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 📋 LIVING DRAFT VOUCHER: BANK PAYMENT VOUCHER (BPV-2026-0042)          │
│ Status: [ VALIDATED & COMPLIANT ]              Date: 16-Nov-2026       │
│ Fiscal Period: FY 2026-27 (Q2)                 Currency: PKR           │
├────────────────────────────────────────────────────────────────────────┤
│ Counterparty: Shabbir Furniture (Pvt) Ltd                              │
│ Role: Supplier (AP) | NTN: 4129841-2 | STRN: 3270-1928-11             │
│ Tax Profile: Active Taxpayer (Filer) - ATL Verified ✓                  │
├────────────────────────────────────────────────────────────────────────┤
│ LINE DISTRIBUTION:                                                     │
│ #  Account Code & Title          Narration             Debit (PKR)   Credit (PKR) │
│ 1  1510 Furniture & Fixtures     5 Executive Tables    150,000.00          0.00   │
│ 2  2120 WHT Payable u/s 153      5% WHT on Goods             0.00      7,500.00   │
│ 3  1020-01 Meezan Bank Ops       Crossed Chq #892101         0.00    142,500.00   │
├────────────────────────────────────────────────────────────────────────┤
│ TOTALS:                          PKR 150,000.00        PKR 150,000.00  │
│ VARIANCE:                        PKR 0.00 (PERFECT BALANCE ✓)          │
├────────────────────────────────────────────────────────────────────────┤
│ 🛡️ STATUTORY COMPLIANCE INDICATORS:                                    │
│ • Section 73 (Banking Channel): PASS ✓ (Settled via Bank Cheque)      │
│ • Section 153 (Tax Deduction):  PASS ✓ (5% Corporate Goods Deducted)  │
│ • Duplicate Payment Scan:       CLEAN ✓ (No matching vendor payments)  │
│ • Asset Capitalization Card:    SCHEDULED (Asset Class: Furniture, 10y)│
└────────────────────────────────────────────────────────────────────────┘
```

### Essential Card Metadata Fields:
1. **Voucher Identification:** Voucher Type, Temporary Draft ID, Effective Date, Currency.
2. **Counterparty Forensic Header:** Legal Name, Party Role, NTN/STRN, ATL Filer Status.
3. **Double-Entry Distribution Grid:** Line #, Tier-4 Account Code, Account Title, Narration, Debit amount, Credit amount.
4. **Balancing Footing:** Total Debits, Total Credits, Difference ($\Delta$). Variance must be zero before posting.
5. **Tax & Statutory Badges:** Section 73 indicator, Section 153 WHT breakdown, Sales Tax recovery status.
6. **Subledger & Asset Linkage:** Associated PO number, Bill reference, Fixed Asset card parameters.

---

## 4. SKEPTICAL SAFEGUARDS: WHEN MUST THE AGENT PUSH BACK OR WARN?

The AI must act with professional skepticism (ISA 200). It must push back or flag critical hazards in these 7 scenarios:

### Safeguard 1: Cash Payment Exceeding PKR 50,000 for Expenses (Section 73)
- **Condition:** Payment Method = `CASH` and Amount $>$ PKR 50,000.
- **Pushback:**
  > *"⚠️ **Statutory Tax Warning (Section 73 ITO 2001):** You are recording a cash payment of **PKR {amount:,.2f}**. Under Section 73 read with Section 21(l), any business expenditure exceeding PKR 50,000 paid in cash is **100% disallowed as a tax deduction**. This will result in an immediate 29% corporate income tax penalty. I strongly advise settling via crossed cheque or online bank transfer. Would you like me to switch the payment method to your business bank account?"*

### Safeguard 2: Cash Payment Exceeding PKR 250,000 for Capital Assets (Section 73(2))
- **Condition:** Nature = `FIXED_ASSET`, Payment Method = `CASH`, Amount $>$ PKR 250,000.
- **Pushback:**
  > *"⛔ **Critical Capital Asset Restriction (Section 73(2)):** Cash purchases of capital assets exceeding PKR 250,000 permanently forfeit all depreciation deductions and initial tax allowances. This payment **must** be executed through a crossed banking channel."*

### Safeguard 3: Aggressive Expensing of High-Value Durable Assets (Capitalization Evasion)
- **Condition:** User attempts to expense durable assets (e.g., *"Book 10 Dell laptops at PKR 1.2M as office repair/supplies expense"*).
- **Pushback:**
  > *"⚠️ **Accounting Standard Pushback (IAS 16 vs IAS 1):** These laptops are durable operational assets with a useful life exceeding 3 years. Booking capital equipment as an operating expense violates IFRS and will be rejected by statutory auditors and the FBR as improper profit suppression. I have drafted these under **Computer & IT Equipment (Account 1520)** with monthly straight-line depreciation. This protects your compliance while ensuring legitimate tax depreciation claims."*

### Safeguard 4: Ambiguous Vendor Tax Status (Filer vs Non-Filer Risk)
- **Condition:** Vendor has no verified NTN on record, or ATL status is unverified.
- **Pushback:**
  > *"🔍 **Tax Audit Alert (Section 153 & 10th Schedule):** We do not have a verified NTN for **{vendor_name}**. If they are a Non-Filer, the law mandates a **100% withholding surcharge (e.g., 10% instead of 5%)**. If we under-withhold, our company is personally liable for the unpaid tax plus 12% surcharge u/s 161/205. Should we deduct the standard Filer rate (assuming NTN will be provided) or apply the precautionary Non-Filer rate?"*

### Safeguard 5: Invoice Structuring / Smurfing Detection
- **Condition:** Multiple cash vouchers between PKR 40,000 and PKR 49,999 recorded for the same party within 72 hours.
- **Pushback:**
  > *"🚨 **Forensic Audit Flag (Section 73 Aggregation):** Detected 3 consecutive cash payments of PKR 48,000 to the same vendor. Tax authorities treat invoice splitting under a single account head as structured evasion of Section 73. These payments must be consolidated and paid via banking channels."*

### Safeguard 6: Sole Proprietor / Director Personal Drawings vs Business Expense
- **Condition:** Business funds used for non-business goods (groceries, school fees, personal jewellery, holiday travel).
- **Pushback:**
  > *"⚠️ **Entity Segregation Pushback (Section 21(h)):** Personal and family living expenses cannot be charged against company revenue. I have drafted this payment as **Owner's Drawings (Account 3200)** / **Director's Loan (Account 2200)**, reducing equity rather than inflating business expenses."*

### Safeguard 7: Naked Name with Zero Ledger Evidence
- **Condition:** User says *"Paid 80,000 to Kamran"* with zero matching vendor bills, payroll cards, or partner records.
- **Pushback:**
  > *"I want to make sure Kamran's payment is booked to the exact right ledger. Is Kamran an employee (salary/advance), an external vendor (paying an invoice), or a partner/director (drawings)?"*
