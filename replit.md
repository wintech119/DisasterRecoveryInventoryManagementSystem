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
-   **Sub-Hub Warehouse Roles and Dispatch Workflow**: Separates planning/approval from physical dispatch operations with strict, hub-scoped access controls for Warehouse Supervisors and Officers. Includes a "Request Fulfilment Change" workflow for warehouse users to request adjustments to approved lists, with Manager review, editing, versioning, and resend notifications.
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