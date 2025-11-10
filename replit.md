# Disaster Relief Inventory Management System (DRIMS)

## Overview
The Disaster Relief Inventory Management System (DRIMS) is designed to track and manage disaster relief supplies across various locations. Its primary goal is to improve the efficiency and accountability of disaster response operations by managing donations, recording distributions, monitoring stock levels in real-time, issuing low-stock alerts, and tracking all transactions. The system aims to provide a robust solution for supply chain management within disaster relief efforts.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
The system is built using Flask, leveraging SQLAlchemy ORM with a relational database design. All timestamps are stored in UTC and displayed in Eastern Standard Time (EST/GMT-5) using the YYYY-MM-DD date format for consistency and clarity.

### Data Model
Key entities include Items, Depots, Donors, Beneficiaries, DisasterEvents, NeedsLists, and Transactions, with a focus on double-entry transactions for auditing and stock calculation. Items feature auto-generated SKUs, standardized units, barcode support, and expiry date tracking. NeedsLists facilitate item requests from AGENCY hubs to MAIN hubs with approval workflows. Line item status labels use standardized fulfilment terminology ("Fulfilled", "Partially Filled", "Unfilled") across all workflow phases for consistency and clarity.

### UI/UX and Frontend
The frontend uses server-side rendered HTML templates with Bootstrap 5 and Bootstrap Icons for rapid deployment, minimal client-side dependencies, accessibility, and mobile-friendliness, aligning with Government of Jamaica branding. Dashboard features include responsive design, hero cards for key metrics, insight panels with Chart.js for data visualizations (stock distribution, fulfillment trends), and an activity feed of recent transactions. Needs List details view uses context-aware table layouts: Draft/Submitted status displays clean two-column layout (Item 70%, Requested Quantity 30%) without redundant per-item status badges, while Planning and Execution phases show multi-column layouts with fill/dispatch details and status indicators. Fulfilment terminology uses "Fill/Filled/Unfilled/Fulfilled" for improved clarity (column headers: "Fill from Hubs", "Filled", "Unfilled"; status values: "Unfilled", "Partially Filled", "Fulfilled", "Over-Filled"). Fulfilment tables feature optimized column distribution (26%, 10%, 30%, 10%, 10%, 14%) with responsive padding (14px desktop, 12px tablet/mobile), proper alignment (numeric columns center-aligned, text columns left-aligned), and flexbox-centered Status column for professional appearance across all devices.

### Core Features
-   **Agency Hub Request List Form**: Modern, accessible interface for requesting items with single header row (Items | Quantity | Justification) following international UI/UX best practices (ISO 9241-110, WCAG 2.1). Features include table-based layout with hover effects, auto-focus on new rows, accessible remove buttons with ARIA labels, sequential reindexing to prevent data loss, responsive design for mobile devices, and keyboard shortcuts (Ctrl/Cmd+Enter to submit).
-   **Barcode Scanning**: Supports barcode scanning for efficient donation intake.
-   **Needs List Management**: Comprehensive workflow for AGENCY and SUB hubs to request supplies, including draft editing, submission, approval, dispatch, and receipt. Features:
    -   **Concurrency Control**: Lock-based editing prevention with visual banners and automatic lock extension
    -   **Stock Over-Allocation Prevention**: Real-time validation with auto-reset to maximum available stock and inline warnings
    -   **Draft-Save Functionality**: Both Logistics Officers and Managers can save work-in-progress allocations without triggering workflow transitions or stock movements. Draft saves display "Fulfilment Prepared" status with grey badge, show last saved timestamp and user, extend editing lock, and support collaborative editing (Officer saves draft → Manager edits/saves → Manager approves while preserving Officer's preparation attribution)
    -   **Real-Time Data Accuracy**: Single source of truth architecture ensures "Awaiting Approval" view always reflects current database allocations. Backend-computed line items payload eliminates stale data from template/client-side calculations, providing accurate item-level allocations, totals, and Fulfilled/Partially Filled/Unfilled counts synchronized with latest saved allocations
    -   **Completed Page Layout**: Clean termination at Fulfilment Summary Table for Completed status. Summary Panel and Items Table sections are conditionally excluded when status is 'Completed', ensuring the page displays only Timeline, Role-Specific Panels, and Fulfilment Summary Table for a polished archived view
    -   **Centralized Draft Fulfilments View**: Both Logistics Officers and Managers have a dedicated "Draft Fulfilments" tab showing ALL in-progress allocations (status='Fulfilment Prepared') with columns for List Number, Requesting Hub, Priority, Last Saved By (draft_saved_by with fallback to prepared_by), Last Updated On (draft_saved_at with fallback to updated_at), Status (grey "Draft" badge), and "Continue Fulfilment" action button. Lists are sorted by most recent update first (updated_at DESC) for easy access to current work. Separate "Awaiting Approval" tab shows only status='Awaiting Approval' lists ready for final review
    -   **Approved for Dispatch View**: Logistics Officers have a dedicated "Approved for Dispatch" tab showing all Manager-approved needs lists (status='Approved') ready for dispatch. Features include green row highlighting for at-a-glance identification, approver name and approval timestamp display, green success badge, and "Proceed to Dispatch" action button. Lists sorted by approval date (approved_at DESC) for efficient workflow coordination
-   **Distribution Package Management**: Manages creation, review, and approval of distribution packages, including stock validation across multiple depots, smart allocation filtering, and real-time stock updates.
-   **Stock Management**: Stock levels are dynamically aggregated from transaction records with validations to prevent negative stock.
-   **Three-Tier Hub Orchestration**: Role-based system with MAIN, SUB, and AGENCY hubs, defining transfer approval workflows and visibility rules. AGENCY hub inventory is excluded from overall ODPEM displays.
-   **Stock Transfer with Approval Workflow**: Enables transfers between depots with hub-based approval rules; MAIN hub transfers are immediate, while SUB/AGENCY require MAIN hub approval.
-   **Authentication and User Management**: Implements Flask-Login with role-based access control (RBAC) for nine user roles (Admin, Warehouse Supervisor, Warehouse Officer, Warehouse Staff, Field Personnel, Logistics Officer, Logistics Manager, Executive, Auditor), secure password hashing, session management, and an ADMIN-only user management interface. Warehouse Supervisors and Warehouse Officers must be assigned to Sub-Hubs and have dedicated dashboards for dispatch operations.
-   **Sub-Hub Warehouse Roles and Dispatch Workflow**: Separates planning/approval from physical dispatch operations. Logistics Officers and Managers plan and approve fulfilments, while Warehouse Supervisors and Officers at Sub-Hubs physically dispatch items. Warehouse users receive hub-scoped notifications when lists are approved for their hub, see ready-to-dispatch queues filtered by their assigned hub, and can only dispatch items from their assigned location. Logistics users can view approved lists but cannot dispatch - they see monitoring-only interfaces. The system tracks which warehouse user dispatched each order and validates hub assignments to prevent unauthorized dispatch operations.
-   **Universal In-App Notification System**: Provides real-time, deep-linking notifications for workflow events across all user roles, with role-specific triggers, a bell icon with unread badge, and "mark as read" functionality. All notifications include proper deep links to specific needs lists (`/needs-lists/{id}` or `/needs-lists/{id}/prepare` for Officers), ensuring users can navigate directly to relevant resources from the notification panel.
-   **File Storage**: Supports local file attachments with UUID-based filenames, designed for future cloud migration.
-   **Data Import/Export**: Uses Pandas for CSV import and export for bulk data and integration.
-   **Session Management**: Utilizes Flask's built-in session handling with environment variable-configured secret keys.
-   **Status Consistency**: Defines 9 official Needs List statuses (Draft, Submitted, Fulfilment Prepared, Awaiting Approval, Approved, Dispatched, Received, Completed, Rejected) consistently displayed across UIs, with migration scripts for legacy statuses.

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