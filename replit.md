# Disaster Relief Inventory Management System (DRIMS)

## Overview
The Disaster Relief Inventory Management System (DRIMS) is designed to track and manage disaster relief supplies across various locations. Its primary goal is to improve the efficiency and accountability of disaster response operations by managing donations, recording distributions, monitoring stock levels in real-time, issuing low-stock alerts, and tracking all transactions. The system aims to provide a robust solution for supply chain management within disaster relief efforts.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
The system is built using Flask, leveraging SQLAlchemy ORM with a relational database design.

### Data Model
Key entities include Items, Depots, Donors, Beneficiaries, DisasterEvents, NeedsLists, and Transactions, with a focus on double-entry transactions for auditing and stock calculation. Items feature auto-generated SKUs, standardized units, barcode support, and expiry date tracking. NeedsLists facilitate item requests from AGENCY hubs to MAIN hubs with approval workflows.

### UI/UX and Frontend
The frontend uses server-side rendered HTML templates with Bootstrap 5 and Bootstrap Icons for rapid deployment, minimal client-side dependencies, accessibility, and mobile-friendliness, aligning with Government of Jamaica branding. Dashboard features include responsive design, hero cards for key metrics, insight panels with Chart.js for data visualizations (stock distribution, fulfillment trends), and an activity feed of recent transactions.

### Core Features
-   **Barcode Scanning**: Supports barcode scanning for efficient donation intake.
-   **Needs List Management**: Comprehensive workflow for AGENCY and SUB hubs to request supplies, including draft editing, submission, approval, dispatch, and receipt. Features:
    -   **Concurrency Control**: Lock-based editing prevention with visual banners and automatic lock extension
    -   **Stock Over-Allocation Prevention**: Real-time validation with auto-reset to maximum available stock and inline warnings
    -   **Draft-Save Functionality**: Both Logistics Officers and Managers can save work-in-progress allocations without triggering workflow transitions or stock movements. Draft saves display "Fulfilment Prepared" status with grey badge, show last saved timestamp and user, extend editing lock, and support collaborative editing (Officer saves draft → Manager edits/saves → Manager approves while preserving Officer's preparation attribution)
    -   **Real-Time Data Accuracy**: Single source of truth architecture ensures "Awaiting Approval" view always reflects current database allocations. Backend-computed line items payload eliminates stale data from template/client-side calculations, providing accurate item-level allocations, totals, and Fully Allocated/Partial/Unallocated counts synchronized with latest saved allocations
    -   **Completed Page Layout**: Clean termination at Fulfilment Summary Table for Completed status. Summary Panel and Items Table sections are conditionally excluded when status is 'Completed', ensuring the page displays only Timeline, Role-Specific Panels, and Fulfilment Summary Table for a polished archived view
    -   **Centralized Draft Fulfilments View**: Both Logistics Officers and Managers have a dedicated "Draft Fulfilments" tab showing ALL in-progress allocations (status='Fulfilment Prepared') with columns for List Number, Requesting Hub, Priority, Last Saved By (draft_saved_by with fallback to prepared_by), Last Updated On (draft_saved_at with fallback to updated_at), Status (grey "Draft" badge), and "Continue Fulfilment" action button. Lists are sorted by most recent update first (updated_at DESC) for easy access to current work. Separate "Awaiting Approval" tab shows only status='Awaiting Approval' lists ready for final review
-   **Distribution Package Management**: Manages creation, review, and approval of distribution packages, including stock validation across multiple depots, smart allocation filtering, and real-time stock updates.
-   **Stock Management**: Stock levels are dynamically aggregated from transaction records with validations to prevent negative stock.
-   **Three-Tier Hub Orchestration**: Role-based system with MAIN, SUB, and AGENCY hubs, defining transfer approval workflows and visibility rules. AGENCY hub inventory is excluded from overall ODPEM displays.
-   **Stock Transfer with Approval Workflow**: Enables transfers between depots with hub-based approval rules; MAIN hub transfers are immediate, while SUB/AGENCY require MAIN hub approval.
-   **Authentication and User Management**: Implements Flask-Login with role-based access control (RBAC) for seven user roles, secure password hashing, session management, and an ADMIN-only user management interface.
-   **Universal In-App Notification System**: Provides real-time, deep-linking notifications for workflow events across all user roles, with role-specific triggers, a bell icon with unread badge, and "mark as read" functionality.
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