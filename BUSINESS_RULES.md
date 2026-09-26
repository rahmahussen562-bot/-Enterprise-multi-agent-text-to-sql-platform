# Enterprise Business & Revenue Calculation Rules

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
