# Enterprise Business Rules

## FinCore Enterprise: authoritative registry v1.0.0

Banking sessions use `data/financial_metrics.v1.json` and the reviewed PostgreSQL
views in `data/fincore_schema.sql`. [FinCore schema and governance](docs/FINCORE_SCHEMA.md)
specifies the full contracts. Banking generation cannot fall back to media formulas.

| Metric | Definition | Persona |
| --- | --- | --- |
| Daily balance | Posted debits/credits through the institution's business date, using each account's normal side; available balance subtracts active holds at statement time. Currencies remain separate. | `branch_analyst`, assigned branches |
| High-risk cash | Distinct posted USD cash movements by known person and business day, aggregated across accounts; cash-in and cash-out tested separately against strictly greater than USD 10,000. | `compliance_officer` |
| Loan performance | Ledger-derived principal, days since earliest unpaid installment, and simple fixed-rate accrual using contractual ACT/360, ACT/365F or 30E/360 fractions. | `branch_analyst`, assigned branches |

The cash rule is a US reference monitoring signal, based on [FinCEN's CTR FAQ](https://www.fincen.gov/resources/frequently-asked-questions-regarding-fincen-currency-transaction-report-ctr).
It does not file a CTR/SAR, resolve exemptions, translate EUR/EGP into USD, or assert
Egyptian/EU reporting rules. Unknown financial definitions and unsupported filters
are rejected. Risk scores and tiers are governed stored assessments, not invented
model scores. FinCore v1 accepts the reviewed English requests listed in the schema
guide; arbitrary banking question synthesis requires a later governed extension.

## Legacy Chinook compatibility rules

This document specifies the authoritative corporate business formulas, fee structures, and profit distribution rules for transactional queries in the Enterprise Text-to-SQL Platform.

---

## 1. Core Financial Formulas

| Metric | Formula | Description |
| :--- | :--- | :--- |
| **Gross Revenue** | `SUM(UnitPrice * Quantity)` | Total invoiced sales before payment gateway fees or partner disbursements. |
| **Bank Fee** | `Gross Revenue * 0.025` | 2.5% transaction deduction fee retained by the payment gateway or acquiring bank. |
| **Net Revenue** | `Gross Revenue * 0.975` | Total revenue after bank processing fee deduction: `Gross Revenue * (1 - 0.025)`. |
| **Partner Share** | `Net Revenue * 0.70` | 70% share of Net Revenue disbursed to music artists, labels, and content partners. |
| **Company Net Profit** | `Net Revenue * 0.30` | 30% share of Net Revenue retained by the enterprise: `Gross Revenue * 0.975 * 0.30`. |

---

## 2. Standard T-SQL Query Implementations

### A. Total Company Net Profit Across Invoices
```sql
SELECT 
    ROUND(SUM([UnitPrice] * [Quantity]) * 0.975 * 0.30, 2) AS [CompanyNetProfit]
FROM [InvoiceLine];
```

### B. Comprehensive Revenue & Profit Breakdown by Customer
```sql
SELECT 
    [c].[CustomerId],
    [c].[FirstName],
    [c].[LastName],
    ROUND(SUM([il].[UnitPrice] * [il].[Quantity]), 2) AS [GrossRevenue],
    ROUND(SUM([il].[UnitPrice] * [il].[Quantity]) * 0.025, 2) AS [BankProcessingFee],
    ROUND(SUM([il].[UnitPrice] * [il].[Quantity]) * 0.975, 2) AS [NetRevenue],
    ROUND(SUM([il].[UnitPrice] * [il].[Quantity]) * 0.975 * 0.70, 2) AS [PartnerShare],
    ROUND(SUM([il].[UnitPrice] * [il].[Quantity]) * 0.975 * 0.30, 2) AS [CompanyNetProfit]
FROM [Customer] AS [c]
INNER JOIN [Invoice] AS [i] ON [c].[CustomerId] = [i].[CustomerId]
INNER JOIN [InvoiceLine] AS [il] ON [i].[InvoiceId] = [il].[InvoiceId]
GROUP BY [c].[CustomerId], [c].[FirstName], [c].[LastName]
ORDER BY [CompanyNetProfit] DESC;
```

---

## 3. Role-Based Access Governance (RBAC & RLC)

| Role Identity | Permitted Tables | Business Rule Scope |
| :--- | :--- | :--- |
| **`sales_analyst`** | `Customer`, `Invoice`, `InvoiceLine` | Full authority to execute queries calculating Gross Revenue, Bank Fees, Net Revenue, and Company Net Profit. |
| **`inventory_lead`** | `Track`, `Album`, `Artist`, `Genre`, `MediaType` | Strictly restricted from financial and billing data. Cross-boundary table queries are blocked by the AST Guardian Firewall. |
