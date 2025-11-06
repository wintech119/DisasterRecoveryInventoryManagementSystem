# GOJ Relief Inventory System

## Overview
The GOJ Relief Inventory System is an inventory management solution designed for the Government of Jamaica to track and manage disaster relief supplies. It supports multiple locations (shelters, depots, parishes), handles donations, and records distributions to beneficiaries. The system provides real-time stock monitoring, low-stock alerts, and comprehensive transaction tracking to enhance the efficiency of disaster response operations. Its core purpose is to ensure effective and accountable management of relief efforts.

## User Preferences
Preferred communication style: Simple, everyday language.

## User Roles and Access Levels

The system is designed to support multiple user types with different responsibilities:

### Warehouse Staff
**Primary Responsibilities**: Day-to-day inventory operations
- Record incoming relief supplies (intake transactions)
- Process distributions to beneficiaries
- Update item information including expiry dates and storage requirements
- Monitor stock levels at their assigned location
- Alert managers to low stock or expiring items

**Key Features Used**: Intake forms, Distribution forms, Item management, Location-specific inventory views

### Field Distribution Personnel
**Primary Responsibilities**: On-site distribution of relief supplies
- Execute distributions in the field using mobile devices
- Record beneficiary information
- Link distributions to disaster events for accountability
- Track distributor assignments for audit purposes

**Key Features Used**: Distribution forms, Mobile-friendly interface, Disaster event tracking

### Inventory Managers
**Primary Responsibilities**: Stock oversight and operational planning
- Monitor stock levels across all locations
- Manage low stock alerts and reorder decisions
- Track item expiry dates and storage compliance
- Coordinate transfers between locations
- Oversee distributor assignments and performance
- Manage disaster event operations

**Key Features Used**: Dashboard analytics, Low stock alerts, Expiring items reports, Location management, Distributor management, Disaster event management

### Executive Management
**Primary Responsibilities**: Strategic oversight and decision-making
- View high-level operational metrics and KPIs
- Monitor disaster event response effectiveness
- Track donor contributions and beneficiary reach
- Assess resource allocation across locations
- Review transaction volumes and trends
- Make strategic decisions based on comprehensive data

**Key Features Used**: Executive dashboard with KPIs, Activity by event reports, Transaction analytics, Inventory by category summaries

### System Administrators
**Primary Responsibilities**: System configuration and maintenance
- Configure locations (depots, shelters, parishes)
- Set up disaster events and manage event lifecycle
- Manage user accounts and permissions (when authentication is implemented)
- Maintain item catalog and categories
- Configure system settings and integrations
- Ensure data integrity and system availability

**Key Features Used**: All administrative interfaces, Location management, Disaster event management, Item configuration, Database management tools

### Auditors
**Primary Responsibilities**: Compliance and accountability verification
- Review complete transaction history with timestamps
- Verify disaster event linkages for funding accountability
- Track distributor assignments for all distributions
- Audit donor contributions and beneficiary distributions
- Generate compliance reports for government oversight
- Investigate discrepancies in inventory records

**Key Features Used**: Transaction history with audit trail (created_by field), Disaster event reports, Distributor tracking, Comprehensive transaction logs, Export capabilities for external auditing

**Authentication Status**: ✅ **IMPLEMENTED** - The system now features complete user authentication and role-based access control (RBAC) using Flask-Login. Users must log in to access the system, and their access to features is restricted based on their assigned role. The system supports secure password hashing (Werkzeug), session management, and automatic audit logging of all transactions with the `created_by` field.

## System Architecture

### Application Framework
The system is built using Flask (Python web framework) for its lightweight and flexible nature, enabling rapid development and deployment, especially in resource-constrained disaster environments.

### Data Model
The system utilizes SQLAlchemy ORM with a relational database design. SQLite is used for development, with PostgreSQL support for production environments via the `DATABASE_URL` environment variable. The data model includes core entities such as Items, Locations, Donors, Beneficiaries, Distributors, DisasterEvents, and Transactions. Transactions are designed as double-entry records ("IN"/"OUT") to simplify stock calculation and maintain a single audit trail. Items feature auto-generated SKUs (e.g., ITM-XXXXXX), unit of measure, expiry dates for perishable goods, and storage requirements. Distributors are tracked for accountability in distribution transactions. Disaster events are managed with types, dates, and statuses, allowing transaction linking for event-specific reporting. An audit trail (`created_by` field) is included in transactions for accountability.

### Frontend Architecture
The frontend uses server-side rendered HTML templates with Bootstrap 5 and Bootstrap Icons. This approach prioritizes quick deployment, minimal client-side dependencies, accessibility, and mobile-friendliness for field workers. The application incorporates official Government of Jamaica branding, including GOJ Green and Gold colors, the Jamaican coat of arms, and clean typography.

### Stock Calculation Strategy
Stock levels are dynamically aggregated on-demand from transaction records, summing "IN" and subtracting "OUT" transactions, filtered by location and item. This ensures data consistency and a complete audit trail.

### Dashboard Features
The dashboard provides a comprehensive overview with KPIs (total items, total units, low stock items), inventory by category, stock by location, low stock alerts, recent transactions, expiring items alerts (with color-coded urgency), activity by disaster event, operations metrics, and transaction analytics.

### Authentication
The system implements Flask-Login-based authentication with role-based access control (RBAC). Key features include:
- Secure password hashing using Werkzeug's generate_password_hash
- Session-based login with "remember me" functionality
- User model with six distinct roles: ADMIN, INVENTORY_MANAGER, WAREHOUSE_STAFF, FIELD_PERSONNEL, EXECUTIVE, AUDITOR
- Role-aware navigation that shows/hides menu items based on user permissions
- Automatic population of created_by audit field with current user's name
- CLI commands (flask create-admin, flask create-user) for user management
- Route protection using @login_required and @role_required decorators
- Optional location assignment for warehouse staff users

### Data Import/Export
The Pandas library is used for CSV import and export functionalities, facilitating bulk data entry, integration with spreadsheet workflows, data backup, and transfer.

### Session Management
Flask's built-in session handling is utilized, with a secret key loaded from an environment variable for security.

## External Dependencies

### Core Framework Dependencies
-   **Flask**: 3.0.3
-   **Flask-SQLAlchemy**: 3.1.1
-   **SQLAlchemy**: 2.0.32

### Database Drivers
-   **psycopg2-binary**: For PostgreSQL production deployments.
-   **SQLite**: Built-in for development.

### Data Processing
-   **Pandas**: 2.2.2 (for CSV handling).

### Configuration Management
-   **python-dotenv**: 1.0.1 (for environment variables).

### Frontend Dependencies (CDN-delivered)
-   **Bootstrap**: 5.3.3
-   **Bootstrap Icons**: 1.11.3

The system supports database configuration via the `DATABASE_URL` environment variable. No external APIs or third-party services are currently integrated, ensuring independent operation crucial during disaster scenarios.