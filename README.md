# ReverseDB

ReverseDB provides a practical reverse-engineering blueprint for **large legacy Oracle databases** (500+ tables) that include:

- Tables, views, indexes, and constraints
- Triggers
- Stored procedures, functions, and packages
- Scheduled jobs and batch routines

The goal is to produce a reverse-engineered document that clearly identifies:

1. **Transaction types** supported by the database
2. **Reference data** entities
3. **Master data** entities
4. **System parameters** and configuration tables

## Reverse Engineering Approach

### 1) Metadata Inventory

Extract technical metadata from Oracle system views:

- `ALL_TABLES`, `ALL_TAB_COLUMNS`, `ALL_CONSTRAINTS`, `ALL_CONS_COLUMNS`
- `ALL_TRIGGERS`
- `ALL_PROCEDURES`, `ALL_SOURCE`, `ALL_ARGUMENTS`
- `ALL_DEPENDENCIES`

This establishes the full object inventory and dependencies.

### 2) Behavioral Discovery

Analyze procedure/package and trigger source code to detect:

- Insert/update/delete business workflows
- Approval/state transition logic
- Posting/settlement/event processing routines
- Configuration and parameter lookups

### 3) Data Domain Classification

Classify tables using naming patterns, relationships, and usage patterns:

- **Transaction data**: high-volume event tables, journals, line-item tables, status transitions
- **Reference data**: controlled vocabularies, code/lookup lists with stable values
- **Master data**: core business entities (customer, supplier, product, account, location)
- **System parameters**: application behavior/configuration values used at runtime

### 4) Output Document Generation

Produce a consolidated reverse-engineered document with traceability from each conclusion to source objects (table/procedure/trigger).

## Reverse-Engineered Document Template

Use the following structure for each database analyzed.

### A. Executive Summary

- Scope (schemas, number of objects, analysis date)
- Key business capabilities inferred
- Confidence level and open questions

### B. Transaction Types

For each transaction type:

- Transaction name
- Purpose/business outcome
- Core tables involved
- Entry/update/cancel flow
- Trigger/procedure/package participants
- Status lifecycle

### C. Reference Data

For each reference-data table:

- Table name
- Business meaning
- Typical update ownership (admin/system)
- Related foreign keys and consumers

### D. Master Data

For each master-data entity:

- Entity name
- Primary and alternate keys
- Lifecycle operations (create/update/deactivate)
- Downstream transaction usage

### E. System Parameters

For each parameter/config table:

- Parameter name/key
- Default value and allowed range/set
- Runtime impact
- Referencing procedures/packages/triggers

### F. Dependency and Flow Diagrams (optional but recommended)

- Entity relationship overview
- Procedure/trigger dependency graph
- Transaction sequence diagrams

## Minimum Deliverables Checklist

- [ ] Full object inventory and dependency map
- [ ] Documented transaction type catalog
- [ ] Classified reference data catalog
- [ ] Classified master data catalog
- [ ] Classified system parameter catalog
- [ ] Traceability links to Oracle objects (tables/procedures/triggers)
