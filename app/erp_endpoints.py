"""
ERP Endpoints & Direct Task Registry
====================================
Comprehensive catalog of all ERP modules, UI paths, and direct executable tasks.

Every task in the ERP is registered here with:
- Module Name & UI Route
- Direct Tool Slug & Handler Contract
- Execution Nature: OPERATIONAL_TASK (no double-entry impact) vs FINANCIAL_TRANSACTION (balanced journals)
- Mandatory / Required Fields (Strict Zero-Assumption Policy: must ask clarification if missing)
- Standard Questions and Structured Clarification Options
- Formatting helpers for user responses and LLM prompts

Guarantees:
- The LLM never hallucinates random endpoints; it references this authoritative registry.
- Non-transactional requests (e.g. "CREATE A CHART OF ACCOUNT") execute cleanly without forcing fake accounting entries.
- Missing parameters trigger explicit, targeted clarification questions instead of blind assumptions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# Execution Nature
TYPE_OPERATIONAL_TASK = "OPERATIONAL_TASK"        # Master data / setup / CRUD / query (0 journal impact)
TYPE_FINANCIAL_TRANSACTION = "FINANCIAL_TRANSACTION"  # Value movement / perpetual ledger / double entry


ERP_MODULES: Dict[str, Dict[str, Any]] = {
    "accounting": {
        "id": "accounting",
        "name": "Accounting & General Ledger",
        "ui_path": "/accounting",
        "description": "Chart of accounts, general ledger, manual journal entries, and account management",
        "tasks": [
            "create_account",
            "get_chart_of_accounts",
            "search_account",
            "prepare_journal",
            "post_journal",
            "reverse_journal",
            "get_general_ledger",
        ],
    },
    "customers": {
        "id": "customers",
        "name": "Customers & Receivables",
        "ui_path": "/customers",
        "description": "Customer directory, customer ledger, balances, and credit tracking",
        "tasks": [
            "create_customer",
            "search_customer",
            "get_customer",
            "get_customer_ledger",
            "customer_balance",
        ],
    },
    "suppliers": {
        "id": "suppliers",
        "name": "Suppliers & Payables",
        "ui_path": "/suppliers",
        "description": "Supplier directory, supplier ledger, vendor balances, and payables",
        "tasks": [
            "create_supplier",
            "search_supplier",
            "get_supplier",
            "get_supplier_ledger",
            "supplier_balance",
        ],
    },
    "catalogue": {
        "id": "catalogue",
        "name": "Catalogue & Inventory",
        "ui_path": "/catalogue",
        "description": "Products, services, stock tracking, unit pricing, and perpetual inventory movements",
        "tasks": [
            "create_product",
            "update_product",
            "delete_product",
            "search_product",
            "create_service",
            "update_service",
            "delete_service",
            "search_service",
            "get_inventory_status",
        ],
    },
    "banking": {
        "id": "banking",
        "name": "Banking & Cash Management",
        "ui_path": "/banking",
        "description": "Bank accounts, cash accounts, liquidity balances, and inter-bank transfers",
        "tasks": [
            "create_bank_account",
            "list_bank_accounts",
            "record_bank_transfer",
        ],
    },
    "sales": {
        "id": "sales",
        "name": "Sales & Revenue",
        "ui_path": "/sales",
        "description": "Customer quotations, sales invoices, cash sales, credit notes, and customer receipts",
        "tasks": [
            "create_quotation",
            "convert_quotation",
            "create_invoice",
            "record_credit_sale",
            "record_cash_sale",
            "create_credit_note",
            "record_receipt",
        ],
    },
    "purchases": {
        "id": "purchases",
        "name": "Purchases & Procurement",
        "ui_path": "/purchases",
        "description": "Supplier bills, cash purchases, debit notes (purchase returns), and supplier payments",
        "tasks": [
            "create_purchase_bill",
            "record_credit_purchase",
            "record_cash_purchase",
            "create_purchase_return",
            "record_payment",
        ],
    },
    "expenses": {
        "id": "expenses",
        "name": "Expenses & Operational Costs",
        "ui_path": "/expenses",
        "description": "Expense recording, cost classification, expense bills, and settlements",
        "tasks": [
            "record_expense",
            "record_expense_payment",
            "list_expenses",
        ],
    },
    "employees": {
        "id": "employees",
        "name": "Employees & Payroll",
        "ui_path": "/employees",
        "description": "Employee roster, compensation, allowances, payroll runs, and salary disbursements",
        "tasks": [
            "create_employee",
            "search_employee",
            "get_employee",
            "set_employee_allowances",
            "run_payroll",
            "pay_employee_salary",
        ],
    },
    "fixed_assets": {
        "id": "fixed_assets",
        "name": "Fixed Assets",
        "ui_path": "/fixed-assets",
        "description": "Fixed asset register, capitalization, depreciation calculations, and asset disposals",
        "tasks": [
            "register_fixed_asset",
            "search_fixed_asset",
            "get_fixed_asset",
            "record_asset_depreciation",
            "dispose_fixed_asset",
        ],
    },
    "loans": {
        "id": "loans",
        "name": "Loans & Credit Facilities",
        "ui_path": "/banking",
        "description": "Loan borrowing/lending facilities, amortization schedules, installments, and repayments",
        "tasks": [
            "record_loan",
            "record_loan_repayment",
            "list_loans",
            "get_loan_schedule",
            "check_due_loan_installments",
            "record_loan_restructure",
            "write_off_loan",
        ],
    },
    "projects": {
        "id": "projects",
        "name": "Projects & Cost Centers",
        "ui_path": "/projects",
        "description": "Project tracking, budgets, project-level revenue and profitability analysis",
        "tasks": [
            "create_project",
            "get_project",
            "project_profitability",
        ],
    },
    "recurring": {
        "id": "recurring",
        "name": "Recurring Transactions",
        "ui_path": "/settings",
        "description": "Recurring transaction templates, automated execution, and recurring schedules",
        "tasks": [
            "create_recurring_template",
            "get_recurring_templates",
            "get_recurring_template",
            "update_recurring_template",
            "generate_recurring",
            "get_recurring_executions",
        ],
    },
    "reports": {
        "id": "reports",
        "name": "Financial Reports & Intelligence",
        "ui_path": "/reports",
        "description": "Trial balance, profit & loss statement, balance sheet, cash flow, and health metrics",
        "tasks": [
            "generate_trial_balance",
            "generate_balance_sheet",
            "generate_profit_loss",
            "generate_cash_flow",
            "generate_general_ledger",
            "calculate_health",
            "get_health",
        ],
    },
}


# Direct Task Specifications
ERP_TASKS: Dict[str, Dict[str, Any]] = {
    # ---- ACCOUNTING MODULE ---------------------------------------------
    "create_account": {
        "task_id": "create_account",
        "module": "accounting",
        "name": "Create Chart of Accounts Account",
        "tool": "create_account",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Create a new account in the Chart of Accounts without recording any financial transaction or journal entry.",
        "required_fields": ["account_name", "account_type"],
        "optional_fields": ["code", "parent_account_name", "description"],
        "clarification_questions": {
            "account_name": "What is the name of the new account you want to create in the Chart of Accounts?",
            "account_type": "What type of account is this in the Chart of Accounts? Reply with ASSET, LIABILITY, EQUITY, REVENUE, or EXPENSE.",
            "code": "What account code would you like to assign? (Or reply AUTO to automatically assign the next available code).",
        },
        "options": {
            "account_type": ["Expense", "Asset", "Liability", "Revenue", "Equity"],
        },
    },
    "get_chart_of_accounts": {
        "task_id": "get_chart_of_accounts",
        "module": "accounting",
        "name": "View Chart of Accounts",
        "tool": "get_chart_of_accounts",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Retrieve the complete chart of accounts with account types, codes, and hierarchies.",
        "required_fields": [],
        "optional_fields": ["account_type"],
    },
    "search_account": {
        "task_id": "search_account",
        "module": "accounting",
        "name": "Search Account",
        "tool": "search_account",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Search for accounts by name or code.",
        "required_fields": ["query"],
        "optional_fields": [],
    },
    # ---- CUSTOMERS MODULE ----------------------------------------------
    "create_customer": {
        "task_id": "create_customer",
        "module": "customers",
        "name": "Create Customer",
        "tool": "create_customer",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Create a new customer profile in the CRM/Customers master.",
        "required_fields": ["customer_name"],
        "optional_fields": ["email", "phone", "legal_name", "tax_number", "notes"],
        "clarification_questions": {
            "customer_name": "Who is the customer you would like to register?",
        },
    },
    "search_customer": {
        "task_id": "search_customer",
        "module": "customers",
        "name": "Search Customer",
        "tool": "search_customer",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Search customers by name, phone, or email.",
        "required_fields": ["query"],
        "optional_fields": [],
    },
    # ---- SUPPLIERS MODULE ----------------------------------------------
    "create_supplier": {
        "task_id": "create_supplier",
        "module": "suppliers",
        "name": "Create Supplier",
        "tool": "create_supplier",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Create a new supplier / vendor profile in the Suppliers master.",
        "required_fields": ["supplier_name"],
        "optional_fields": ["email", "phone", "legal_name", "tax_number", "notes"],
        "clarification_questions": {
            "supplier_name": "Who is the supplier / vendor you would like to register?",
        },
    },
    "search_supplier": {
        "task_id": "search_supplier",
        "module": "suppliers",
        "name": "Search Supplier",
        "tool": "search_supplier",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Search suppliers by name or contact details.",
        "required_fields": ["query"],
        "optional_fields": [],
    },
    # ---- CATALOGUE MODULE ----------------------------------------------
    "create_product": {
        "task_id": "create_product",
        "module": "catalogue",
        "name": "Create Product",
        "tool": "create_product",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Add a new inventory product to the product catalogue.",
        "required_fields": ["product_name", "sales_price"],
        "optional_fields": ["is_stock_tracked", "cost_price", "unit", "description"],
        "clarification_questions": {
            "product_name": "What is the name of the product you want to add to the catalogue?",
            "sales_price": "What is the selling / sales price for this product?",
        },
    },
    "create_service": {
        "task_id": "create_service",
        "module": "catalogue",
        "name": "Create Service",
        "tool": "create_service",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Add a new billable service to the catalogue.",
        "required_fields": ["service_name", "sales_price"],
        "optional_fields": ["billing_unit", "description"],
        "clarification_questions": {
            "service_name": "What is the name of the service you want to add to the catalogue?",
            "sales_price": "What is the standard billing rate or price for this service?",
        },
    },
    "get_inventory_status": {
        "task_id": "get_inventory_status",
        "module": "catalogue",
        "name": "Inventory & Stock Status",
        "tool": "get_inventory_status",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "View inventory valuation, total units on hand, inward received, outward issued, and stock levels across catalogue products.",
        "required_fields": [],
        "optional_fields": ["product_name", "only_low_stock"],
    },
    # ---- BANKING MODULE ------------------------------------------------
    "create_bank_account": {
        "task_id": "create_bank_account",
        "module": "banking",
        "name": "Create Bank Account",
        "tool": "create_bank_account",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Register a new bank account and its linked general ledger asset account.",
        "required_fields": ["bank_name", "account_name"],
        "optional_fields": ["account_number", "iban", "branch_code"],
        "clarification_questions": {
            "bank_name": "What is the name of the bank (e.g. Meezan Bank, HBL, Standard Chartered)?",
            "account_name": "What is the title or account name for this bank account?",
        },
    },
    "list_bank_accounts": {
        "task_id": "list_bank_accounts",
        "module": "banking",
        "name": "List Bank Accounts",
        "tool": "list_bank_accounts",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "List all configured bank accounts and current balances.",
        "required_fields": [],
        "optional_fields": [],
    },
    # ---- EMPLOYEES MODULE ----------------------------------------------
    "create_employee": {
        "task_id": "create_employee",
        "module": "employees",
        "name": "Create Employee",
        "tool": "create_employee",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Register a new employee in the payroll roster.",
        "required_fields": ["employee_name"],
        "optional_fields": ["salary", "designation", "department", "date_of_joining"],
        "clarification_questions": {
            "employee_name": "What is the full name of the employee to register?",
        },
    },
    # ---- PROJECTS MODULE -----------------------------------------------
    "create_project": {
        "task_id": "create_project",
        "module": "projects",
        "name": "Create Project",
        "tool": "create_project",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Set up a new project or cost center.",
        "required_fields": ["project_name"],
        "optional_fields": ["budget", "billing_type", "customer_name"],
        "clarification_questions": {
            "project_name": "What is the name of the new project?",
        },
    },
    # ---- RECURRING TEMPLATES MODULE ------------------------------------
    "create_recurring_template": {
        "task_id": "create_recurring_template",
        "module": "recurring",
        "name": "Create Recurring Template",
        "tool": "create_recurring_template",
        "execution_type": TYPE_OPERATIONAL_TASK,
        "description": "Create an automated recurring transaction template.",
        "required_fields": ["template_name"],
        "optional_fields": ["frequency", "start_date"],
        "clarification_questions": {
            "template_name": "What should this recurring template be named?",
        },
    },
}


def get_task_spec(task_id: str) -> Optional[Dict[str, Any]]:
    """Return the task specification for *task_id*, or None if not registered."""
    return ERP_TASKS.get(task_id)


def is_operational_task(task_id: str) -> bool:
    """True if *task_id* is an operational task that does NOT post accounting entries."""
    spec = ERP_TASKS.get(task_id)
    if spec:
        return spec.get("execution_type") == TYPE_OPERATIONAL_TASK
    return False


def get_module_for_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Return module metadata for *task_id*."""
    spec = ERP_TASKS.get(task_id)
    if spec:
        return ERP_MODULES.get(spec.get("module", ""))
    return None


def format_operational_summary(task_id: str, data: Dict[str, Any]) -> str:
    """Format an informative, human-readable summary referencing the exact ERP Module and Path."""
    spec = ERP_TASKS.get(task_id)
    mod = get_module_for_task(task_id)
    mod_name = mod["name"] if mod else "System"
    mod_path = mod["ui_path"] if mod else "/"

    if task_id == "create_account":
        name = data.get("name") or "Account"
        code = data.get("code") or ""
        acct_type = data.get("account_type") or "EXPENSE"
        code_str = f" (Code: {code})" if code else ""
        reused = data.get("reused_existing")
        action = "Reused existing" if reused else "Successfully created"
        return f"{action} account '{name}'{code_str} of type {acct_type} in the Chart of Accounts under {mod_name} (`{mod_path}`)."

    if task_id == "create_customer":
        name = data.get("name") or "Customer"
        reused = data.get("reused")
        action = "Reused existing" if reused else "Successfully registered"
        return f"{action} customer '{name}' in the CRM directory under {mod_name} (`{mod_path}`)."

    if task_id == "create_supplier":
        name = data.get("name") or "Supplier"
        reused = data.get("reused")
        action = "Reused existing" if reused else "Successfully registered"
        return f"{action} supplier '{name}' in the Vendor directory under {mod_name} (`{mod_path}`)."

    if task_id == "create_product":
        name = data.get("name") or "Product"
        price = data.get("unit_price")
        price_str = f" with price Rs. {price:,.2f}" if price is not None else ""
        return f"Successfully added product '{name}'{price_str} to the catalogue under {mod_name} (`{mod_path}`)."

    if task_id == "create_service":
        name = data.get("name") or "Service"
        rate = data.get("standard_rate")
        rate_str = f" with rate Rs. {rate:,.2f}" if rate is not None else ""
        return f"Successfully added service '{name}'{rate_str} to the catalogue under {mod_name} (`{mod_path}`)."

    if task_id == "get_inventory_status":
        val = data.get("total_valuation", 0.0)
        on_hand = data.get("total_units_on_hand", 0.0)
        out_cnt = data.get("out_of_stock_count", 0)
        items_cnt = data.get("product_count", len(data.get("products", [])))
        return f"Inventory status retrieved from {mod_name} (`{mod_path}`): Total Valuation: Rs. {val:,.2f} across {on_hand:,.1f} units on hand ({items_cnt} products, {out_cnt} out of stock)."

    if task_id == "create_bank_account":
        acct_name = data.get("account_name") or "Bank Account"
        bank_name = data.get("bank_name") or ""
        bank_str = f" at {bank_name}" if bank_name else ""
        return f"Successfully created bank account '{acct_name}'{bank_str} under {mod_name} (`{mod_path}`)."

    if task_id == "create_employee":
        name = data.get("full_name") or "Employee"
        return f"Successfully registered employee '{name}' in the personnel roster under {mod_name} (`{mod_path}`)."

    if task_id == "create_project":
        name = data.get("name") or "Project"
        return f"Successfully created project '{name}' under {mod_name} (`{mod_path}`)."

    return f"Successfully completed {task_id} under {mod_name} (`{mod_path}`)."


def build_erp_directory_prompt() -> str:
    """Generate structured markdown of all ERP modules, paths, and endpoints for LLM awareness."""
    lines = [
        "AUTHORITATIVE ERP MODULE & DIRECT TASK REGISTRY:",
        "The ERP consists of the following 14 dedicated modules and exact direct endpoints.",
        "Users can execute ANY task within ANY module directly by conversational query.",
        "Never hallucinate non-existent endpoints or invent URL paths.",
        "",
    ]
    for mod_id, mod in ERP_MODULES.items():
        lines.append(f"Module: {mod['name']} | UI Path: `{mod['ui_path']}`")
        lines.append(f"  Description: {mod['description']}")
        lines.append("  Executable Tasks:")
        for t_id in mod["tasks"]:
            spec = ERP_TASKS.get(t_id)
            if spec:
                req = ", ".join(spec["required_fields"]) if spec["required_fields"] else "none"
                lines.append(f"    - {t_id}: {spec['description']} (Required fields: {req})")
            else:
                lines.append(f"    - {t_id}")
        lines.append("")
    return "\n".join(lines)

