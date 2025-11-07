# Disaster Relief Inventory Management System (DRIMS)

## Overview
The Disaster Relief Inventory Management System (DRIMS) is an inventory management solution designed to track and manage disaster relief supplies across multiple locations (shelters, depots, parishes). It handles donations, records distributions to beneficiaries, provides real-time stock monitoring, and offers low-stock alerts and comprehensive transaction tracking. The system's core purpose is to enhance the efficiency and accountability of disaster response operations, ensuring effective management of relief efforts.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
The system is built using Flask (Python web framework) for rapid development and deployment, suitable for resource-constrained disaster environments.

### Data Model
Utilizes SQLAlchemy ORM with a relational database design, supporting SQLite for development and PostgreSQL for production. The data model includes core entities like Items, Depots (formerly Locations), Donors, Beneficiaries, Distributors, DisasterEvents, and Transactions. Transactions are designed as double-entry records ("IN"/"OUT") for consistent stock calculation and audit trails. Items feature auto-generated SKUs, standardized unit of measure selection, barcode support for scanner integration, and standardized storage requirements. Expiry dates are tracked at the transaction level (on intake) rather than at the item level, enabling per-batch expiry tracking for perishable goods. An audit trail (`created_by` field) is included in transactions for accountability.

### Barcode Scanning for Intake
The system supports barcode scanning to streamline the donation intake process. Key features include:

**Item Barcode Field**: Items can have an optional barcode value stored in the database (unique, indexed for fast lookups). Barcodes can be added when creating or editing items through the item management interface.

**Barcode Scanner Integration**: The intake form includes a dedicated barcode input field with the following workflow:
1. Warehouse staff scan or manually enter a barcode
2. JavaScript automatically calls the `/api/barcode-lookup` API endpoint
3. The system searches for items by barcode or SKU
4. If found, the item dropdown is auto-selected and focus moves to the quantity field
5. Visual feedback shows success or error messages

**Benefits**: This significantly reduces manual data entry during high-volume donation intake operations, minimizes errors from manual item selection, and speeds up the overall intake process for warehouse staff processing donations.

**Database Schema**: The Item table includes a `barcode` column (VARCHAR(100), unique, indexed) added via database migration.

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
- **Enhanced In-App Notification System**: Prominent notification display with:
  - Real-time alerts for package approvals, dispatches, and deliveries
  - Partial fulfillment alerts with requested vs allocated quantities
  - Navigation badge showing unread notification count
  - Individual and bulk "Mark as Read" functionality
  - Separate sections for unread notifications and notification history
  - Clear action buttons to view packages and respond to alerts
- Response interface to accept or reject partial fulfillment
- Complete visibility into package status throughout the workflow

This self-service capability significantly reduces manual data entry for inventory managers while maintaining complete audit trails and approval workflows. The notification system ensures distributors are immediately aware of any status changes to their packages and can take timely action.

**Multi-Depot Fulfillment with Per-Depot Allocation Tracking**: The system supports manual allocation of package items from multiple depots during package creation and when fulfilling distributor needs lists. Inventory managers can specify exactly how many units of each item should come from which depot, enabling flexible fulfillment when stock is distributed across locations. Key features include:
- **Manual Allocation Interface**: Package creation and fulfillment forms display available stock per depot for each item, allowing managers to allocate specific quantities from specific depots
- **Live Stock Updates**: As managers allocate quantities, the interface shows remaining stock at each depot in real-time, helping them make informed decisions
- **Smart Auto-Fill Functions**: One-click auto-fill from depot with most stock, per-depot quick fill buttons, and clear all allocations
- **Real-Time Progress Tracking**: Visual progress bars with color-coded status (green=full, yellow=partial, red=over-allocated) and instant validation messages
- **Per-Depot Validation**: Server-side validation ensures allocated quantities do not exceed available stock at each depot
- **Allocation Tracking**: PackageItemAllocation table records which depot provides which quantity for each package item
- **Multi-Depot Transaction Generation**: Upon dispatch, the system generates separate OUT transactions for each depot allocation, ensuring accurate inventory deduction at the source depot
- **Allocation Visibility**: Package details view displays depot allocations in expandable rows, clearly showing which depots contribute to each item
- **Distributor Needs List Fulfillment**: Inventory managers can fulfill distributor-created needs lists by allocating stock through a dedicated fulfillment interface with all the smart features

This implementation supports Option B requirements: complete per-depot allocation tracking with individual OUT transactions per depot, maintaining accurate inventory levels across all locations.

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
- **PackageItemAllocation**: Tracks per-depot allocations (package_item_id + depot_id + allocated_qty) with unique constraint preventing duplicate depot allocations per item
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