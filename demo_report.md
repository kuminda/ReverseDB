# Reverse-Engineered Database Report – `LEGACY_ERP`

_Generated: 2026-07-10 10:28 UTC_

---

## A. Executive Summary

| Item | Count |
|---|---|
| Schema | `LEGACY_ERP` |
| Total tables | 8 |
| Triggers | 3 |
| Procedures / Functions / Packages | 5 |
| Transaction tables | 3 |
| Reference-data tables | 2 |
| Master-data tables | 1 |
| System-parameter tables | 2 |
| Unclassified tables | 0 |



## B. Transaction Types

### `CUSTOMERS`

- **Estimated rows:** 950,000

- **Columns:**

  - `CUSTOMER_ID` (NUMBER)

  - `FULL_NAME` (VARCHAR2)

  - `EMAIL` (VARCHAR2) _(nullable)_

  - `COUNTRY_CODE` (CHAR)

  - `CREATED_DATE` (DATE) _(nullable)_

  - `SEGMENT` (VARCHAR2) _(nullable)_

- **Status / state columns:** n/a

- **Date / timestamp columns:** `CREATED_DATE`

- **References (FK targets):** n/a

- **Triggers:**
  - _(none)_

- **Procedures / packages:**
  - `PKG_ORDER_MGMT`



### `ORDERS`

- **Estimated rows:** 5,200,000

- **Columns:**

  - `ORDER_ID` (NUMBER)

  - `CUSTOMER_ID` (NUMBER)

  - `ORDER_DATE` (DATE)

  - `STATUS` (VARCHAR2)

  - `TOTAL_AMOUNT` (NUMBER) _(nullable)_

  - `CREATED_DATE` (DATE) _(nullable)_

  - `LAST_UPDATED` (TIMESTAMP) _(nullable)_

- **Status / state columns:** `STATUS`

- **Date / timestamp columns:** `ORDER_DATE`, `CREATED_DATE`, `LAST_UPDATED`

- **References (FK targets):** `CUSTOMERS`, `PRODUCT_CATALOG`

- **Triggers:**
  - `TRG_ORDERS_AUDIT`
  - `TRG_ORDERS_STATUS`

- **Procedures / packages:**
  - `PKG_ORDER_MGMT`
  - `PROC_CLOSE_ORDER`



### `ORDER_ITEMS`

- **Estimated rows:** 18,400,000

- **Columns:**

  - `ITEM_ID` (NUMBER)

  - `ORDER_ID` (NUMBER)

  - `PRODUCT_ID` (NUMBER)

  - `QUANTITY` (NUMBER)

  - `UNIT_PRICE` (NUMBER)

  - `APPROVAL_STATUS` (VARCHAR2) _(nullable)_

- **Status / state columns:** `APPROVAL_STATUS`

- **Date / timestamp columns:** n/a

- **References (FK targets):** `ORDERS`, `PRODUCT_CATALOG`

- **Triggers:**
  - `TRG_ITEMS_CALC`

- **Procedures / packages:**
  - `PKG_ORDER_MGMT`
  - `FN_GET_TOTAL`



## C. Reference Data

### `CATEGORIES`

- **Estimated rows:** 42

- **Update ownership:** Admin / System

- **Consumed by (FK):**
  - `PRODUCT_CATALOG`

- **Columns:**

  - `CATEGORY_ID` (NUMBER)

  - `CATEGORY_CODE` (VARCHAR2)

  - `DESCRIPTION` (VARCHAR2)



### `CURRENCIES`

- **Estimated rows:** 150

- **Update ownership:** Admin / System

- **Consumed by (FK):**
  - _(none)_

- **Columns:**

  - `CURRENCY_CODE` (CHAR)

  - `CURRENCY_NAME` (VARCHAR2)

  - `SYMBOL` (VARCHAR2)



## D. Master Data

### `PRODUCT_CATALOG`

- **Estimated rows:** 85,000

- **Primary key:** `PRODUCT_ID`

- **Referenced by (FK):**
  - `ORDERS`
  - `ORDER_ITEMS`

- **Procedures / packages:**
  - `PKG_PRODUCT_UTILS`

- **Columns:**

  - `PRODUCT_ID` (NUMBER)

  - `PRODUCT_CODE` (VARCHAR2)

  - `DESCRIPTION` (VARCHAR2) _(nullable)_

  - `CATEGORY_ID` (NUMBER)

  - `UNIT_PRICE` (NUMBER)

  - `IS_ACTIVE` (CHAR)



## E. System Parameters

### `APP_CONFIG`

- **Estimated rows:** 320

- **Key columns:** `PARAM_NAME`

- **Value columns:** `PARAM_VALUE`

- **Procedures / packages:**
  - _(none)_



### `FEATURE_FLAGS`

- **Estimated rows:** 88

- **Key columns:** n/a

- **Value columns:** `VALUE`

- **Procedures / packages:**
  - _(none)_



## F. Unclassified Tables

_All tables were classified._

