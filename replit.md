# Disaster Relief Inventory Management System (DRIMS)

## Overview
The Disaster Relief Inventory Management System (DRIMS) is an inventory management solution designed to track and manage disaster relief supplies across multiple locations (shelters, depots, parishes). It handles donations, records distributions to beneficiaries, provides real-time stock monitoring, and offers low-stock alerts and comprehensive transaction tracking. The system's core purpose is to enhance the efficiency and accountability of disaster response operations, ensuring effective management of relief efforts.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
The system is built using Flask (Python web framework) for rapid development and deployment, suitable for resource-constrained disaster environments.

### Data Model
Utilizes SQLAlchemy ORM with a relational database design, supporting SQLite for development and PostgreSQL for production. The data model includes core entities like Items, Depots (formerly Locations), Donors, Beneficiaries, Distributors, DisasterEvents, and Transactions. Transactions are designed as double-entry records ("IN"/"OUT") for consistent stock calculation and audit trails. Items feature auto-generated SKUs, standardized unit of measure selection, and standardized storage requirements. Expiry dates are tracked at the transaction level (on intake) rather than at the item level, enabling per-batch expiry tracking for perishable goods. An audit trail (`created_by` field) is included in transactions for accountability.

### Distribution Package Management
The system implements a comprehensive distribution package workflow that enables inventory managers to create, review, and approve packages for distributors based on their needs lists. Key features include:

**Workflow States**: Packages progress through five distinct states:
- **Draft**: Initial creation with needs list entry
- **Under Review**: Package submitted for stock availability checking and review
- **Approved**: Package approved by authorized personnel, ready for dispatch
- **Dispatched**: Package sent to distributor with inventory transactions generated
- **Delivered**: Confirmed receipt by distributor

**Stock Availability Checking**: The system automatically validates requested quantities against available stock across all locations. If sufficient stock is unavailable, the package is flagged as "Partial" and allocated quantities are calculated based on available inventory.

**Partial Fulfillment Handling**: When stock is insufficient, the system creates in-app notifications for the distributor showing:
- Items that cannot be fully fulfilled
- Requested quantities vs allocated quantities
- Option to accept partial fulfillment or request revision

Distributors can review partial fulfillment notifications and either accept (allowing the package to proceed to approval) or reject (triggering a revision request). All distributor responses are tracked with timestamps and notes for audit purposes.

**Distributor Location Tracking**: Distributors now include location information (parish, address, GPS coordinates) to enable accurate warehouse assignment. This data is captured during distributor profile creation or updates.

**Automatic Warehouse Assignment**: Approved packages are automatically assigned to the nearest warehouse or outpost based on the distributor's parish or geographic coordinates, optimizing logistics and reducing delivery time. The system uses a priority-based matching system:
1. Parish matching (primary method) - matches distributor parish with location name
2. Legacy organization-based matching (fallback for existing data)
3. GPS-based distance calculation (future enhancement when locations have coordinates)

**Distributor Self-Service Portal**: Distributors with login accounts can now create their own needs lists through a dedicated self-service interface. Key features include:
- **My Needs Lists** dashboard showing all submitted requests and their status
- Ability to create needs lists directly without inventory manager intermediary
- In-app notifications for partial fulfillment alerts
- Response interface to accept or reject partial fulfillment
- Complete visibility into package status throughout the workflow

This self-service capability significantly reduces manual data entry for inventory managers while maintaining complete audit trails and approval workflows.

**Transaction Generation**: Upon approval, the system automatically generates OUT transactions for all package items, updating inventory levels at the assigned warehouse. This ensures inventory accuracy and maintains the complete audit trail.

**Audit Trail**: Complete tracking of package lifecycle including:
- Creation timestamp and creator
- Status change history with timestamps and responsible staff
- Distributor responses with timestamps and notes
- Approval details (who, when, notes)
- Dispatch details (who, when, location)
- Delivery confirmation

**Data Model Entities**:
- **DistributionPackage**: Main package record with workflow status, distributor link, assigned location, and audit fields
- **PackageItem**: Individual items in package with requested_qty and allocated_qty
- **PackageStatusHistory**: Complete audit trail of all status transitions
- **DistributorNotification**: In-app notification system for partial fulfillment alerts and status updates

Future enhancements will include email/SMS notifications for distributors and warehouse staff when packages change status or require action.

### Frontend Architecture
The frontend uses server-side rendered HTML templates with Bootstrap 5 and Bootstrap Icons. This approach prioritizes quick deployment, minimal client-side dependencies, accessibility, and mobile-friendliness. The application incorporates official Government of Jamaica branding, including GOJ Green and Gold colors and the Jamaican coat of arms.

### Stock Calculation Strategy
Stock levels are dynamically aggregated on-demand from transaction records, summing "IN" and subtracting "OUT" transactions, filtered by location and item, ensuring data consistency and a complete audit trail.

### Dashboard Features
The dashboard provides a comprehensive overview with KPIs (total items, total units, low stock items), inventory by category, stock by location, low stock alerts, recent transactions, expiring items alerts, activity by disaster event, operations metrics, and transaction analytics.

### Authentication
The system implements Flask-Login-based authentication with role-based access control (RBAC) supporting seven distinct user roles: ADMIN, INVENTORY_MANAGER, WAREHOUSE_STAFF, FIELD_PERSONNEL, EXECUTIVE, AUDITOR, and DISTRIBUTOR. Features include secure password hashing (Werkzeug), session management, role-aware navigation, automatic population of `created_by` audit fields, and CLI commands for user management. Route protection is enforced using `@login_required` and `@role_required` decorators.

**Role-Specific Capabilities**:
- **DISTRIBUTOR**: Access to self-service needs list creation, package tracking, and partial fulfillment response interface. Linked to distributor profile via `user_id`.
- **INVENTORY_MANAGER**: Full access to package management, distributor management, and approval workflows. Dashboard shows pending needs lists submitted by distributors.
- **WAREHOUSE_STAFF**: Can dispatch and deliver packages, manage stock at assigned locations.
- **ADMIN**: Full system access including user management and all administrative functions.

The architecture also includes a plan for future integration with Keycloak and LDAP for enterprise authentication using Authlib.

### File Storage and Attachments
The system supports file attachments for inventory items (e.g., product photos, specifications). Currently, files are stored locally in `/uploads/items/` with UUID-based secure filenames. A modular `storage_service.py` with a `StorageBackend` abstraction layer is in place to facilitate future migration to cloud storage solutions like AWS S3 or Replit Nexus buckets without application code changes. File uploads are validated for type and size, and protected by authentication.

### Data Import/Export
The Pandas library is used for CSV import and export functionalities, enabling bulk data entry, integration with spreadsheet workflows, data backup, and transfer.

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

The system supports database configuration via the `DATABASE_URL` environment variable. No external APIs or third-party services are currently integrated.