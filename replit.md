# Disaster Relief Inventory Management System (DRIMS)

## Overview
The Disaster Relief Inventory Management System (DRIMS) is designed to track and manage disaster relief supplies across multiple locations. Its core purpose is to enhance the efficiency and accountability of disaster response by managing donations, recording distributions, monitoring stock in real-time, providing low-stock alerts, and tracking all transactions.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
Built with Flask (Python) for rapid development and deployment.

### Data Model
Utilizes SQLAlchemy ORM with a relational database design, supporting SQLite for development and PostgreSQL for production. Key entities include Items, Depots, Donors, Beneficiaries, DisasterEvents, NeedsLists, and Transactions. Transactions are double-entry ("IN"/"OUT") for stock calculation and audit trails. Items feature auto-generated SKUs, standardized units, barcode support, and expiry dates tracked at the transaction level for batch management. NeedsLists enable AGENCY hubs to request items from MAIN hubs with approval workflows.

### Barcode Scanning for Intake
Supports barcode scanning for efficient donation intake, reducing manual entry and errors. Items can store an optional barcode value, and the intake form allows scanning or manual entry to auto-select items and move to quantity fields.

### Needs List Management with Logistics Hierarchy
Implements a role-based workflow for AGENCY and SUB hubs to request supplies with Logistics Officer preparation and Logistics Manager approval:
- **Hub Creation & Submission**: AGENCY and SUB hub staff create needs lists with item quantities, priorities (Low/Medium/High/Urgent), and justifications. They submit lists for logistics review. Each hub type can only see their own needs lists.
- **Logistics Officer Review**: Logistics Officers have **global visibility** on all submitted needs lists regardless of their assigned location, allowing them to orchestrate supply distribution across the entire system. They prepare fulfilments by verifying requests, assigning quantities from source hubs (MAIN/SUB), and submitting for manager approval. Cannot finalize fulfilments independently.
- **Logistics Manager Approval**: Logistics Managers have **global visibility** on all needs lists and final approval authority. They can approve fulfilments (triggering automatic stock transfers), reject fulfilments (returning to submitted status), or directly prepare and approve in one step bypassing the awaiting approval status.
- **Automatic Stock Transfers**: Upon manager approval, the system automatically executes stock transfers: deducts from source hubs (MAIN/SUB), increments to requesting hub (AGENCY/SUB), and creates transaction records marked as "Needs List Fulfilment".
- **Status Workflow**: Draft → Submitted → Fulfilment Prepared → Awaiting Approval → Fulfilled (or Rejected → Submitted). Logistics Managers can bypass Awaiting Approval and directly execute fulfilments.
- **Centralized Permission System**: Seven helper functions (`can_view_needs_list`, `can_edit_needs_list`, `can_submit_needs_list`, `can_prepare_fulfilment`, `can_approve_fulfilment`, `can_reject_fulfilment`, `can_delete_needs_list`) enforce consistent role-based access control across all needs list routes.
- **Hub Independence**: SUB hubs cannot see needs lists from other SUB hubs or AGENCY hubs. AGENCY hubs cannot see needs lists from SUB hubs or other AGENCY hubs. Only Logistics Officers/Managers and ADMIN have cross-hub visibility.
- **Complete Audit Trail**: Tracks who created the list, when submitted, who prepared fulfilment, who approved/rejected, and completion timestamps.
- **Multi-Hub Fulfilment**: Logistics Officers can allocate items from multiple source hubs (MAIN and SUB) to fulfill a single needs list, optimizing stock distribution.

### Distribution Package Management
Implements a comprehensive workflow for creating, reviewing, and approving distribution packages destined for AGENCY hubs with five states: Draft, Under Review, Approved, Dispatched, and Delivered.
- **AGENCY Hub Recipients**: All distribution packages are created for specific AGENCY hubs as recipients. ODPEM (via MAIN/SUB hubs) creates packages to fulfill agency needs, allocates stock from their inventory, and dispatches to AGENCY hubs.
- **Stock Availability**: Validates requested quantities against available stock across all ODPEM locations (MAIN and SUB hubs), handling partial fulfillment.
- **Multi-Depot Fulfillment**: Logistics staff (Logistics Officer and Logistics Manager) can manually allocate package items from multiple ODPEM depots (MAIN/SUB hubs only), with real-time stock updates, smart auto-fill functions, and per-depot validation. Logistics Officers create draft allocations, which are submitted for review and approved by Logistics Managers. This generates separate OUT transactions for each depot allocation upon dispatch.
- **Smart Depot Filtering**: Package creation and fulfillment forms display only ODPEM depots (MAIN/SUB hubs) with available stock (quantity > 0) for each item, streamlining the allocation process. AGENCY hubs are excluded from source depots as they are recipients, not sources. Depots with existing allocations are preserved in the fulfillment interface even when stock drops to zero, allowing managers to edit or clear those allocations. The system uses separate data attributes (`data-max` for validation limits, `data-available` for auto-fill) to ensure the auto-fill function only selects depots with actual stock while still permitting manual edits to preserved allocations. Zero-stock depots with allocations are visually distinguished with warning icons, light backgrounds, and clear messaging.
- **Audit Trail**: Complete tracking of package lifecycle, including creation, recipient agency, status changes, approvals, dispatch, and delivery.

### Frontend Architecture
Uses server-side rendered HTML templates with Bootstrap 5 and Bootstrap Icons, prioritizing quick deployment, minimal client-side dependencies, accessibility, and mobile-friendliness, incorporating official Government of Jamaica branding.

### Stock Calculation Strategy
Stock levels are dynamically aggregated on-demand from transaction records (summing "IN" and subtracting "OUT") filtered by location and item, ensuring data consistency.

### Stock Validation and Negative Stock Prevention
Comprehensive validation prevents stock levels from falling below zero during distributions, transfers, and package dispatches/fulfillments. Error messages indicate item, depot, available, and requested quantities.

### Three-Tier Hub Orchestration System
Implements a role-based orchestration model with three hub types for managing stock distribution and approvals:
- **MAIN Hub**: Central distribution hubs (e.g., Pimento JDF) act as orchestrators for all SUB hubs with authority to execute transfers immediately without approval. Any MAIN hub can view and approve transfer requests from any SUB or AGENCY hub.
- **SUB Hub**: Regional distribution hubs (e.g., Trelawny, Haining) governed by all MAIN hubs collectively. No parent assignment capability. Transfer requests require approval from any MAIN hub before execution.
- **AGENCY Hub**: Independent agency-operated hubs (e.g., Montego Bay, Pimento) that can request items from MAIN hubs. Completely independent with no parent hub assignment capability. AGENCY hub stock is excluded from overall ODPEM inventory displays but can receive stock via approved transfers.

**Hub Orchestration Features:**
- Role-based governance: SUB hubs are orchestrated by ALL MAIN hubs, not a specific parent
- Any MAIN hub user can approve transfer requests from any SUB or AGENCY hub
- Transfer approval workflow based purely on hub_type (MAIN transfers immediate, SUB/AGENCY require MAIN approval)
- No parent hub assignments for any hub type - all hubs operate independently with role-based orchestration
- Hub Status tracking (Active/Inactive) with automatic operational timestamp recording when activated
- **AGENCY Hub Inventory Exclusion**: AGENCY hubs are excluded from overall inventory displays, stock summaries, distribution package fulfillment, and stock reports to maintain separation between ODPEM and independent agency inventories. AGENCY hubs remain visible in hub management and can participate in transfers and receive donated stock.

### Stock Transfer Between Depots with Approval Workflow
Enables logistics staff to transfer stock between depots with hub-based approval rules:
- **MAIN Hub Users**: Transfers execute immediately without approval. Can access the Transfer Approval Queue to review and approve/reject requests from SUB and AGENCY hubs.
- **SUB/AGENCY Hub Users**: Transfers create a TransferRequest for MAIN hub approval. Users can view their pending requests on the transfer page.
- **Approval Queue**: MAIN hub staff can view all pending transfer requests, verify stock availability, and approve (executes transfer) or reject requests.
- **Real-time validation**: Stock availability is checked before approval to prevent negative stock.
- **Audit trail**: All transfer requests track requester, reviewer, timestamps, and status (PENDING/APPROVED/REJECTED).
- **Linked transactions**: Approved transfers generate IN/OUT transactions with full audit trail.

### Dashboard Features
Provides a comprehensive overview with KPIs, inventory by category, stock by location, low stock alerts, recent transactions, expiring item alerts, activity by disaster event, and transaction analytics.

### Authentication and User Management
Implements Flask-Login with role-based access control (RBAC) for seven user roles: ADMIN, LOGISTICS_MANAGER, LOGISTICS_OFFICER, WAREHOUSE_STAFF, FIELD_PERSONNEL, EXECUTIVE, and AUDITOR. Features include secure password hashing, session management, role-aware navigation, and route protection.

**User Management Interface:**
- **ADMIN-only web interface** for creating, editing, and managing user accounts
- Create new users with email, full name, role assignment, and password
- Edit existing users: change roles, activate/deactivate accounts, reset passwords, assign locations
- View user details including last login time and account status
- All user actions are restricted to ADMIN role via route decorators
- CLI commands (`flask create-admin`, `flask create-user`) remain available for initial setup

**Role Hierarchy and Responsibilities:**
- **ADMIN**: Full system access including user management, can add/remove users and assign roles.
- **LOGISTICS_MANAGER**: Supervises logistics operations, allocates items, approves packages, and reviews work done by Logistics Officers. **Full access to Needs List workflow** - can prepare fulfilments by allocating stock from MAIN/SUB hubs AND provide final approval to execute stock transfers. Can dispatch and deliver packages. Part of ODPEM (Office of Disaster Preparedness and Emergency Management).
- **LOGISTICS_OFFICER**: Creates draft allocations for distribution packages, manages inventory data, submits work for approval by Logistics Manager. **Prepares Needs List fulfilments** by reviewing requests, assigning quantities, and selecting source hubs (MAIN/SUB), then submitting for manager approval. Cannot finalize fulfilments independently. Can dispatch and deliver packages. Part of ODPEM.
- **WAREHOUSE_STAFF**: Can dispatch and deliver packages. When assigned to AGENCY hubs, can create and submit needs lists, view received packages, and track hub-specific transactions.
- **FIELD_PERSONNEL, EXECUTIVE, AUDITOR**: Operational and oversight roles.

**AGENCY Hub User Experience:**
- AGENCY hub users have a simplified navigation menu with only essential features: Needs Lists, Packages, and History.
- They can create and submit supply requests to ODPEM, view the status of their requests through the approval workflow, and receive packages from ODPEM hubs.
- A workflow guide is displayed on needs list detail pages to help users understand the complete process from draft to fulfillment.

### File Storage and Attachments
Supports file attachments (e.g., product photos) stored locally in `/uploads/items/` with UUID-based filenames. A modular `storage_service.py` allows future migration to cloud storage.

### Data Import/Export
Uses the Pandas library for CSV import and export, enabling bulk data entry, integration with spreadsheets, and data backup.

### Session Management
Utilizes Flask's built-in session handling with a secret key from environment variables.

## External Dependencies

### Core Framework Dependencies
-   **Flask**: 3.0.3
-   **Flask-SQLAlchemy**: 3.1.1
-   **SQLAlchemy**: 2.0.32

### Database Drivers
-   **psycopg2-binary**: For PostgreSQL.
-   **SQLite**: Built-in for development.

### Data Processing
-   **Pandas**: 2.2.2 (for CSV handling).

### Configuration Management
-   **python-dotenv**: 1.0.1 (for environment variables).

### Frontend Dependencies (CDN-delivered)
-   **Bootstrap**: 5.3.3
-   **Bootstrap Icons**: 1.11.3