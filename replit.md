# Disaster Relief Inventory Management System (DRIMS)

## Overview
The Disaster Relief Inventory Management System (DRIMS) is designed to track and manage disaster relief supplies across multiple locations. Its core purpose is to enhance the efficiency and accountability of disaster response by managing donations, recording distributions, monitoring stock in real-time, providing low-stock alerts, and tracking all transactions.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
Built with Flask (Python) for rapid development and deployment.

### Data Model
Utilizes SQLAlchemy ORM with a relational database design, supporting SQLite for development and PostgreSQL for production. Key entities include Items, Depots, Donors, Beneficiaries, Distributors, DisasterEvents, and Transactions. Transactions are double-entry ("IN"/"OUT") for stock calculation and audit trails. Items feature auto-generated SKUs, standardized units, barcode support, and expiry dates tracked at the transaction level for batch management.

### Barcode Scanning for Intake
Supports barcode scanning for efficient donation intake, reducing manual entry and errors. Items can store an optional barcode value, and the intake form allows scanning or manual entry to auto-select items and move to quantity fields.

### Distribution Package Management
Implements a comprehensive workflow for creating, reviewing, and approving distribution packages with five states: Draft, Under Review, Approved, Dispatched, and Delivered.
- **Stock Availability**: Validates requested quantities against available stock across all locations, handling partial fulfillment.
- **Distributor Location Tracking & Automatic Assignment**: Distributors include location data for assigning approved packages to the nearest warehouse, optimizing logistics.
- **Distributor Self-Service Portal**: Distributors can create needs lists, view package statuses, respond to partial fulfillment notifications, and receive in-app alerts for status changes.
- **Multi-Depot Fulfillment**: Logistics staff (Logistics Officer and Logistics Manager) can manually allocate package items from multiple depots, with real-time stock updates, smart auto-fill functions, and per-depot validation. Logistics Officers create draft allocations, which are submitted for review and approved by Logistics Managers. This generates separate OUT transactions for each depot allocation upon dispatch.
- **Smart Depot Filtering**: Package creation and fulfillment forms display only depots with available stock (quantity > 0) for each item, streamlining the allocation process. Depots with existing allocations are preserved in the fulfillment interface even when stock drops to zero, allowing managers to edit or clear those allocations. The system uses separate data attributes (`data-max` for validation limits, `data-available` for auto-fill) to ensure the auto-fill function only selects depots with actual stock while still permitting manual edits to preserved allocations. Zero-stock depots with allocations are visually distinguished with warning icons, light backgrounds, and clear messaging.
- **Audit Trail**: Complete tracking of package lifecycle, including creation, status changes, distributor responses, approvals, dispatch, and delivery.

### Frontend Architecture
Uses server-side rendered HTML templates with Bootstrap 5 and Bootstrap Icons, prioritizing quick deployment, minimal client-side dependencies, accessibility, and mobile-friendliness, incorporating official Government of Jamaica branding.

### Stock Calculation Strategy
Stock levels are dynamically aggregated on-demand from transaction records (summing "IN" and subtracting "OUT") filtered by location and item, ensuring data consistency.

### Stock Validation and Negative Stock Prevention
Comprehensive validation prevents stock levels from falling below zero during distributions, transfers, and package dispatches/fulfillments. Error messages indicate item, depot, available, and requested quantities.

### Three-Tier Hub Hierarchy System
Implements a hierarchical depot structure with three hub types for managing stock distribution and approvals:
- **MAIN Hub**: Central distribution hub (e.g., Pimento JDF) with authority to execute transfers immediately without approval. Can view and approve transfer requests from SUB and AGENCY hubs.
- **SUB Hub**: Regional distribution hubs (e.g., Trelawny, Haining) that report to MAIN hub. Transfer requests require MAIN hub approval before execution.
- **AGENCY Hub**: Independent agency-operated hubs (e.g., Montego Bay, Pimento) that report to MAIN hub. Transfer requests require MAIN hub approval before execution.

**Hub Hierarchy Features:**
- Each SUB and AGENCY hub has a parent_location_id linking to its MAIN hub
- Self-referential relationship enables querying parent/child hub relationships
- Transfer approval workflow based on hub type (MAIN transfers immediate, SUB/AGENCY require approval)

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
Implements Flask-Login with role-based access control (RBAC) for eight user roles: ADMIN, LOGISTICS_MANAGER, LOGISTICS_OFFICER, WAREHOUSE_STAFF, FIELD_PERSONNEL, EXECUTIVE, AUDITOR, and DISTRIBUTOR. Features include secure password hashing, session management, role-aware navigation, and route protection.

**User Management Interface:**
- **ADMIN-only web interface** for creating, editing, and managing user accounts
- Create new users with email, full name, role assignment, and password
- Edit existing users: change roles, activate/deactivate accounts, reset passwords, assign locations
- View user details including last login time and account status
- All user actions are restricted to ADMIN role via route decorators
- CLI commands (`flask create-admin`, `flask create-user`) remain available for initial setup

**Role Hierarchy and Responsibilities:**
- **ADMIN**: Full system access including user management, can add/remove users and assign roles.
- **LOGISTICS_MANAGER**: Supervises logistics operations, allocates items, approves packages, and reviews work done by Logistics Officers. Can dispatch and deliver packages. Part of ODPEM (Office of Disaster Preparedness and Emergency Management).
- **LOGISTICS_OFFICER**: Creates draft allocations for needs lists, manages inventory data, submits work for approval by Logistics Manager, and can dispatch and deliver packages. Part of ODPEM.
- **WAREHOUSE_STAFF**: Can dispatch and deliver packages.
- **FIELD_PERSONNEL, EXECUTIVE, AUDITOR**: Operational and oversight roles.
- **DISTRIBUTOR**: Self-service access to create needs lists, view package status, and respond to partial fulfillment notifications.

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