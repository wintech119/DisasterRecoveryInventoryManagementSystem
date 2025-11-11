# Disaster Relief Inventory Management System (DRIMS)

## Overview
The Disaster Relief Inventory Management System (DRIMS) is designed to enhance disaster response efficiency and accountability by tracking and managing relief supplies across various locations. It provides real-time stock monitoring, manages donations, records distributions, issues low-stock alerts, and tracks all transactions, serving as a robust supply chain management solution for disaster relief efforts.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
The system is built with Flask, utilizing SQLAlchemy ORM and a relational database. All timestamps are stored in UTC and displayed in Eastern Standard Time (EST/GMT-5) in YYYY-MM-DD format.

### Data Model
Key entities include Items, Depots, Donors, Beneficiaries, DisasterEvents, NeedsLists, and Transactions. Items feature auto-generated SKUs, standardized units, barcode support, and expiry date tracking. NeedsLists support item requests from AGENCY hubs to MAIN hubs with approval workflows and standardized fulfillment terminology ("Fulfilled", "Partially Filled", "Unfilled").

**User Management Schema (November 2025)**:
- Normalized user management with separate Role, UserRole, and UserHub tables
- Many-to-many relationships allow users to have multiple roles and hub assignments
- Enhanced user profile fields: first_name, last_name, organization, job_title, phone, timezone, language, notification_preferences
- Audit trail with created_by, updated_by, and updated_at timestamps
- Helper methods: `has_role()`, `has_any_role()`, `has_hub_access()` for cleaner authorization logic
- Property `display_name` combines first_name + last_name for UI display
- Legacy fields (full_name, role, assigned_location_id) retained for backwards compatibility during transition
- **New Governance Model Roles (Active)**: ADMIN (System Administrator), LOGISTICS_MANAGER, LOGISTICS_OFFICER, MAIN_HUB_USER (for Main Hub operations), SUB_HUB_USER (for Sub-Hub operations), AGENCY_HUB_USER (for Agency Hub operations), AUDITOR (read-only oversight), INVENTORY_CLERK (inventory operations)
- **Legacy Roles (Deprecated)**: WAREHOUSE_STAFF, WAREHOUSE_SUPERVISOR, WAREHOUSE_OFFICER, FIELD_PERSONNEL, EXECUTIVE - kept for backwards compatibility, WAREHOUSE_SUPERVISOR maps to SUB_HUB_USER permissions for dispatch operations

### UI/UX and Frontend
The frontend uses server-side rendered HTML templates with Bootstrap 5 and Bootstrap Icons for rapid deployment, accessibility, and mobile-friendliness, aligning with Government of Jamaica branding. Dashboards include responsive design, hero cards for key metrics, Chart.js for data visualizations (stock distribution, fulfillment trends), and an activity feed. Needs List details views adapt layouts based on status, optimizing column distribution and alignment for professional appearance across devices.

### Core Features
-   **Agency Hub Request List Form**: Accessible interface for item requests with table-based layout, hover effects, auto-focus, accessible remove buttons, responsive design, and keyboard shortcuts.
-   **Barcode Scanning**: Supports barcode scanning for efficient donation intake.
-   **Needs List Management**: Comprehensive workflow for AGENCY and SUB hubs to request supplies, including:
    -   Concurrency control, stock over-allocation prevention, and draft-save functionality.
    -   Real-time data accuracy with backend-computed line items.
    -   Streamlined views for "Fulfilment Prepared" (Draft Fulfilments), "Awaiting Approval", and "Approved for Dispatch" lists.
-   **Distribution Package Management**: Manages creation, review, and approval of distribution packages, including stock validation and real-time updates.
-   **Stock Management**: Dynamically aggregates stock levels from transaction records with validations to prevent negative stock.
-   **Three-Tier Hub Orchestration**: Role-based system with MAIN, SUB, and AGENCY hubs defining transfer approval workflows and visibility rules.
-   **Stock Transfer with Approval Workflow**: Enables transfers between depots with hub-based approval rules.
-   **Authentication and User Management**: Flask-Login with role-based access control (RBAC) for nine user roles, secure password hashing, session management, and an ADMIN-only user management interface.
-   **Hub-Based Access Control and Dispatch Workflow**: Implements strict hub-scoped permissions where SUB_HUB_USERs can view and dispatch Needs Lists where their hub is either the requesting hub OR a source hub in fulfilments. MAIN_HUB_USERs have similar visibility for Main hubs, while AGENCY_HUB_USERs can only view their own requests. **Dispatch Permissions (November 2025)**: Centralized `can_dispatch_from_hub()` helper function controls dispatch access - operational hub users (MAIN_HUB_USER, SUB_HUB_USER, INVENTORY_CLERK, legacy WAREHOUSE_SUPERVISOR) can dispatch when their hub (checked via `has_hub_access()` for multi-hub assignments or `assigned_location_id` for legacy users) is a source hub in approved fulfilments. Dispatch is only available for "Approved" and "Resent for Dispatch" statuses. **Prepare Fulfilment**: Restricted to ADMIN, LOGISTICS_MANAGER, LOGISTICS_OFFICER only - operational hub users cannot prepare allocations. Includes a "Request Fulfilment Change" workflow where Sub-Hub users request adjustments to approved lists. Logistics Managers can reopen and edit Approved/Resent for Dispatch fulfilments via a prominent "Edit Fulfilment" button when active change requests exist. Managers can either edit allocations (with mandatory adjustment_reason and automatic versioning) OR respond without editing to reject/clarify. Change request statuses track workflow progress (Pending Review → In Progress → Approved & Resent/Rejected/Clarification Needed), and audit timestamps (reviewed_by/at) are set only when Managers commit decisions, not when merely viewing.
-   **Role-Based Dashboard System (November 2025)**: Centralized dashboard architecture with role-specific context builders and templates. Central `get_dashboard_context()` function routes users to specialized dashboard experiences: **Logistics Manager** dashboard provides government-level oversight with all hubs visibility, approval queues, and system-wide stock metrics; **Logistics Officer** dashboard focuses on fulfilment preparation workflows with submitted needs lists and pending allocations; **Main Hub User** dashboard displays hub stock levels, linked sub-hub requests, and dispatches; **Sub-Hub User** dashboard shows single hub scope with dispatch responsibilities and incoming transfers. Legacy role compatibility maintained (WAREHOUSE_SUPERVISOR → SUB_HUB_USER, etc.) with safe fallback to basic dashboard for unmapped roles. All dashboards use responsive Bootstrap 5 layouts with hero cards, work queues, and Chart.js visualizations.
-   **Universal In-App Notification System**: Provides real-time, deep-linking notifications for workflow events across all user roles.
-   **File Storage**: Supports local file attachments with UUID-based filenames, designed for future cloud migration.
-   **Data Import/Export**: Uses Pandas for CSV import and export.
-   **Session Management**: Utilizes Flask's built-in session handling with environment variable-configured secret keys.
-   **Status Consistency**: Defines 10 official Needs List statuses (Draft, Submitted, Fulfilment Prepared, Awaiting Approval, Approved, Resent for Dispatch, Dispatched, Received, Completed, Rejected) consistently displayed across UIs.

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
-   **Chart.js**: 4.4.0 (for dashboard data visualizations)