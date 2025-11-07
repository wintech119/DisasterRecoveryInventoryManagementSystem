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
- **Multi-Depot Fulfillment**: Inventory managers can manually allocate package items from multiple depots, with real-time stock updates, smart auto-fill functions, and per-depot validation. This generates separate OUT transactions for each depot allocation upon dispatch.
- **Audit Trail**: Complete tracking of package lifecycle, including creation, status changes, distributor responses, approvals, dispatch, and delivery.

### Frontend Architecture
Uses server-side rendered HTML templates with Bootstrap 5 and Bootstrap Icons, prioritizing quick deployment, minimal client-side dependencies, accessibility, and mobile-friendliness, incorporating official Government of Jamaica branding.

### Stock Calculation Strategy
Stock levels are dynamically aggregated on-demand from transaction records (summing "IN" and subtracting "OUT") filtered by location and item, ensuring data consistency.

### Stock Validation and Negative Stock Prevention
Comprehensive validation prevents stock levels from falling below zero during distributions, transfers, and package dispatches/fulfillments. Error messages indicate item, depot, available, and requested quantities.

### Stock Transfer Between Depots
Enables inventory managers to transfer stock between depots with real-time stock visibility, live transfer previews, automatic validation, and linked IN/OUT transactions for an audit trail.

### Dashboard Features
Provides a comprehensive overview with KPIs, inventory by category, stock by location, low stock alerts, recent transactions, expiring item alerts, activity by disaster event, and transaction analytics.

### Authentication
Implements Flask-Login with role-based access control (RBAC) for seven user roles: ADMIN, INVENTORY_MANAGER, WAREHOUSE_STAFF, FIELD_PERSONNEL, EXECUTIVE, AUDITOR, and DISTRIBUTOR. Features include secure password hashing, session management, role-aware navigation, and route protection. Distributors have access to self-service features, while inventory managers manage packages and distributors.

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