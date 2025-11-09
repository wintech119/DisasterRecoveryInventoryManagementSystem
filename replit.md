# Disaster Relief Inventory Management System (DRIMS)

## Overview
The Disaster Relief Inventory Management System (DRIMS) tracks and manages disaster relief supplies across multiple locations. Its purpose is to enhance disaster response efficiency and accountability by managing donations, recording distributions, monitoring stock in real-time, providing low-stock alerts, and tracking all transactions. The system aims to provide a robust solution for supply chain management in disaster relief operations.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
Built with Flask (Python) for rapid development and deployment, utilizing SQLAlchemy ORM with a relational database design.

### Data Model
Key entities include Items, Depots, Donors, Beneficiaries, DisasterEvents, NeedsLists, and Transactions. Transactions are double-entry for stock calculation and audit trails. Items feature auto-generated SKUs, standardized units, barcode support, and expiry dates tracked at the transaction level. NeedsLists enable AGENCY hubs to request items from MAIN hubs with approval workflows.

### Barcode Scanning
Supports barcode scanning for efficient donation intake, reducing manual entry and errors.

### Needs List Management
Implements an end-to-end workflow for AGENCY and SUB hubs to request supplies, including preparation, approval, dispatch, and receipt confirmation. Logistics Officers and Managers have global visibility for orchestration and approval. A centralized permission system enforces role-based access control. The system ensures a complete audit trail for all actions.

**Draft Editing Workflow:**
Agency and SUB hub users can create needs lists in Draft status and edit them before submission. Key features include:
-   **Edit Button**: Draft needs lists display an "Edit Needs List" button in the details view
-   **Quantity Preservation**: When reopening a draft for editing, all previously entered quantities, justifications, and metadata are pre-filled
-   **Save as Draft**: Users can save progress without submitting, allowing iterative refinement
-   **Submit to ODPEM**: Distinct submission button that locks the needs list from further editing and changes status to Submitted
-   **Add/Remove Items**: Users can dynamically add or remove items while in Draft status without losing existing data
-   **Gap-Resistant Parsing**: Form parsing handles non-sequential item numbering from removed rows, ensuring no data loss
-   **Permission Enforcement**: Only the owning Agency/SUB hub can edit their Draft needs lists; editing is disabled once submitted

### Distribution Package Management
Manages the creation, review, and approval of distribution packages for AGENCY hubs. It includes stock validation against available inventory across all ODPEM locations (MAIN and SUB hubs) and supports multi-depot fulfillment with smart allocation filtering and real-time stock updates. A comprehensive audit trail tracks the package lifecycle.

### Frontend Architecture
Uses server-side rendered HTML templates with Bootstrap 5 and Bootstrap Icons, focusing on quick deployment, minimal client-side dependencies, accessibility, and mobile-friendliness, incorporating Government of Jamaica branding.

### Stock Management
Stock levels are dynamically aggregated on-demand from transaction records. Comprehensive validation prevents negative stock levels during all inventory movements.

### Three-Tier Hub Orchestration System
Implements a role-based orchestration model with three hub types:
-   **MAIN Hub**: Central distribution, immediate transfers, approves requests from SUB/AGENCY hubs.
-   **SUB Hub**: Regional distribution, transfers require MAIN hub approval.
-   **AGENCY Hub**: Independent, requests items from MAIN hubs, inventory excluded from overall ODPEM displays.
The system features role-based governance, a transfer approval workflow based on hub type, and no parent hub assignments. AGENCY hub inventory is excluded from overall ODPEM displays to maintain separation.

### Stock Transfer with Approval Workflow
Enables stock transfers between depots with hub-based approval rules. MAIN hub users' transfers execute immediately, while SUB/AGENCY hub users' transfers create a TransferRequest for MAIN hub approval. An approval queue allows MAIN hub staff to review, approve, or reject requests, with real-time validation and a full audit trail.

### Dashboard Features
Implements a best-practice layout with responsive design and data visualizations:

**Layout Structure:**
-   **Hero Cards (Top Row)**: Four key metrics cards - Total Hubs, Units in Stock, Active Needs Lists, and Low Stock Alerts with icon boxes and hover effects
-   **Insight Panels (Middle Section)**: Two side-by-side visualization panels:
    -   Stock Distribution Chart: Doughnut chart showing inventory breakdown by category with color-coded segments
    -   Fulfillment Trends Chart: Bar chart displaying needs list completions over the last 7 days
-   **Activity Feed (Lower Section)**: Full-width scrollable feed of recent transactions with IN/OUT badges, item details, location, and timestamps
-   **Sidebar (Right Panel)**: Role-aware quick actions, hub status overview, pending approvals summary, and needs list status breakdown

**Technical Implementation:**
-   Chart.js 4.4.0 integration for interactive data visualizations
-   Server-side data aggregation for chart datasets (category_labels, category_data, fulfillment_labels, fulfillment_data)
-   Responsive Bootstrap 5 grid with 24-32px gutters for optimal spacing
-   Mobile-friendly design with adaptive layouts for different screen sizes
-   Custom CSS for hero card hover effects, activity item interactions, and icon boxes
-   Role-based content display (Quick Actions visible to ADMIN, LOGISTICS_MANAGER, LOGISTICS_OFFICER, WAREHOUSE_STAFF)
-   Real-time KPIs exclude AGENCY hub inventory to maintain separation from ODPEM operations

### Authentication and User Management
Implements Flask-Login with role-based access control (RBAC) for seven user roles: ADMIN, LOGISTICS_MANAGER, LOGISTICS_OFFICER, WAREHOUSE_STAFF, FIELD_PERSONNEL, EXECUTIVE, and AUDITOR. Features include secure password hashing, session management, role-aware navigation, and route protection. An ADMIN-only web interface manages user accounts. AGENCY hub users have a simplified navigation menu focused on Needs Lists and History.

### Universal In-App Notification System
Provides real-time notifications to all user roles for relevant workflow events. The system features role-specific notification triggers to ensure each user receives actionable alerts:

**Notification Triggers by Role:**
-   **Agency Hub Users**: Needs list lifecycle events (submitted, approved, dispatched, received)
-   **Logistics Officers**: New submissions to prepare, approved items ready for dispatch
-   **Logistics Managers**: Fulfillment awaiting approval, completed needs lists for oversight
-   **Warehouse Staff**: Approved items to prepare, dispatch completion confirmations
-   **Auditors**: Completed needs lists ready for audit trail review
-   **Field Personnel**: Items dispatched to agencies (distribution support awareness)
-   **Executives**: Supply delivery completions (high-level oversight)
-   **Admin**: New needs list submissions (system monitoring)

**Technical Architecture:**
The system uses generalized service functions (`create_notifications_for_users`, `create_notifications_for_role`) for flexible fan-out to target recipients. Notifications are automatically created at key workflow transitions with role-appropriate messages and links. The UI features a bell icon with unread badge counter in the navigation for all users, a Bootstrap offcanvas panel for quick access, auto-polling every 30 seconds with visibility-aware pausing, and individual/batch "mark as read" functionality. API endpoints (`/notifications/*`) are role-agnostic and secured with user ownership verification. Backward-compatible `/agency/*` aliases are maintained for existing integrations. Notifications include comprehensive audit trail information (triggered_by, needs_list_number, timestamps) stored in JSON payload. The system supports pagination (20-50 per page), archival flags for retention policies, and composite indexes for efficient queries.

### File Storage
Supports file attachments stored locally with UUID-based filenames, with a modular service for future cloud migration.

### Data Import/Export
Uses Pandas for CSV import and export, facilitating bulk data entry, spreadsheet integration, and data backup.

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
-   **Chart.js**: 4.4.0 (for dashboard data visualizations)