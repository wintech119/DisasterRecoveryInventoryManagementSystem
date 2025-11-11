# Disaster Relief Inventory Management System (DRIMS)

## Overview
The Disaster Relief Inventory Management System (DRIMS) is designed to enhance disaster response efficiency and accountability by tracking and managing relief supplies across various locations. It provides real-time stock monitoring, manages donations, records distributions, issues low-stock alerts, and tracks all transactions, serving as a robust supply chain management solution for disaster relief efforts. The system aims to significantly improve supply chain management for disaster relief, ensuring timely and accurate delivery of aid.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
The system is built with Flask, utilizing SQLAlchemy ORM and a relational database. All timestamps are stored in UTC and displayed in Eastern Standard Time (EST/GMT-5) in YYYY-MM-DD format.

### Data Model
Key entities include Items, Depots, Donors, Beneficiaries, DisasterEvents, NeedsLists, and Transactions. Items feature auto-generated SKUs, standardized units, barcode support, and expiry date tracking. NeedsLists support item requests with approval workflows and standardized fulfillment terminology. User management includes normalized roles (ADMIN, LOGISTICS_MANAGER, LOGISTICS_OFFICER, MAIN_HUB_USER, SUB_HUB_USER, AGENCY_HUB_USER, AUDITOR, INVENTORY_CLERK) and hub assignments, with enhanced user profile fields and audit trails.

### UI/UX and Frontend
The frontend uses server-side rendered HTML templates with Bootstrap 5 and Bootstrap Icons, designed for rapid deployment, accessibility, and mobile-friendliness. Dashboards include responsive design, hero cards for key metrics, Chart.js for data visualizations, and an activity feed. Needs List views adapt layouts based on status for professional appearance.

### Core Features
-   **Progressive Web App (PWA) with Offline Mode**: Comprehensive offline-first architecture for unstable connectivity, featuring a Service Worker for asset caching, Web App Manifest for PWA installation, IndexedDB for local storage of pending operations, and an Offline Sync Engine for background synchronization with backend sync endpoints. Supports offline form submissions for intake, distribution, and needs list creation, with real-time online/offline status indicators and session persistence.
-   **Agency Hub Request List Form**: Accessible interface for item requests with a table-based layout and responsive design.
-   **Barcode Scanning**: Supports barcode scanning for efficient donation intake (online only).
-   **Needs List Management**: Comprehensive workflow for requesting and fulfilling supplies, including concurrency control, stock over-allocation prevention, draft-save functionality, and streamlined views for various fulfillment stages.
-   **Distribution Package Management**: Manages creation, review, and approval of distribution packages with stock validation.
-   **Stock Management**: Dynamically aggregates stock levels from transaction records with validations.
-   **Three-Tier Hub Orchestration**: Role-based system with MAIN, SUB, and AGENCY hubs defining transfer approval workflows and visibility rules.
-   **Stock Transfer with Approval Workflow**: Enables transfers between depots with hub-based approval rules.
-   **Authentication and User Management**: Flask-Login with role-based access control (RBAC), secure password hashing, and session management.
-   **Hub-Based Access Control and Dispatch Workflow**: Implements strict hub-scoped permissions for viewing and dispatching Needs Lists. Dispatch permissions are controlled by a centralized helper function, allowing operational hub users to dispatch when their hub is a source hub in approved fulfilments. Fulfilment preparation is restricted to specific managerial roles, with a "Request Fulfilment Change" workflow for adjustments to approved lists.
-   **Role-Based Dashboard System**: Features 7 role-specific dashboards (Logistics Manager, Logistics Officer, Main Hub User, Sub-Hub User, Agency Hub User, Inventory Clerk, Auditor, System Administrator) with context builders and templates, strict security boundaries, and hub-based access control. Dashboards follow a unified design, incorporate Bootstrap 5 layouts, modern icons, accessibility features, and Chart.js visualizations. Security architecture ensures data isolation between roles and hubs.
-   **Universal In-App Notification System**: Provides real-time, deep-linking notifications for workflow events.
-   **File Storage**: Supports local file attachments with UUID-based filenames.
-   **Data Import/Export**: Uses Pandas for CSV import and export.
-   **Session Management**: Utilizes Flask's built-in session handling.
-   **Status Consistency**: Defines 10 official Needs List statuses consistently displayed across UIs.

## External Dependencies

-   **Core Frameworks**: Flask (3.0.3), Flask-SQLAlchemy (3.1.1), SQLAlchemy (2.0.32).
-   **Database Drivers**: psycopg2-binary (for PostgreSQL), SQLite (for development).
-   **Data Processing**: Pandas (2.2.2).
-   **Configuration Management**: python-dotenv (1.0.1).
-   **Frontend Libraries (CDN)**: Bootstrap (5.3.3), Bootstrap Icons (1.11.3), Chart.js (4.4.0).