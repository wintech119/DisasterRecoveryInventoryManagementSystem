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
-   **Progressive Web App (PWA) with Offline Mode (EXPERIMENTAL - DISABLED BY DEFAULT)**: Comprehensive offline-first architecture for unstable connectivity. **Status**: Feature infrastructure complete with 2/3 security fixes implemented. Session encryption pending - **disabled by default** until Phase 2 completion. Enable with `OFFLINE_MODE_ENABLED=true` environment variable for testing only. Features include: Service Worker for asset caching, Web App Manifest for PWA installation, IndexedDB for local storage, Offline Sync Engine with automatic background synchronization, offline form submissions (intake, distribution, needs list creation), online/offline status indicators. **Security**: Idempotency enforcement via OfflineSyncLog table prevents duplicate syncs; strict hub-level access control prevents unauthorized operations; session encryption infrastructure created but not yet integrated (tokens currently stored in plaintext when enabled).
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

## Offline Mode Architecture (November 2025 - Experimental)

**Status**: DISABLED BY DEFAULT - Enable with `OFFLINE_MODE_ENABLED=true` for testing only

### Implementation Status

**✅ Completed (Production-Ready)**:
1. **Idempotency Enforcement**: 
   - OfflineSyncLog database model with UNIQUE constraint on (client_operation_id, user_id)
   - All sync handlers check for duplicates before processing
   - Duplicate operations return cached results from result_data JSON field
   - Prevents double-processing of queued operations

2. **Strict Hub Access Control**:
   - `can_access_hub()` function enforces explicit hub assignments for ALL users
   - Removed blanket access for admin/logistics roles in offline operations
   - Validates hub access via UserHub table and legacy assigned_location_id
   - Prevents replay attacks where users queue operations for unauthorized hubs

**⚠️ Partial Implementation (NOT Production-Ready)**:
3. **Session Encryption**:
   - ✅ Web Crypto API module created (`static/js/offline-encryption.js`)
   - ✅ PBKDF2 key derivation (100,000 iterations) + AES-GCM encryption
   - ✅ Random salt and IV generation for each encryption operation
   - ✅ PIN verification hash support
   - ❌ NOT YET integrated into `offline-storage.js`
   - ❌ No PIN entry UI implemented
   - ❌ Session tokens currently stored in **plaintext** in IndexedDB when offline mode enabled

### Security Status

**Current Risk**: Session tokens stored in plaintext in browser IndexedDB when offline mode is enabled. Anyone with device/browser access can extract credentials.

**Recommendation**: Keep offline mode disabled (`OFFLINE_MODE_ENABLED=false`, the default) until Phase 2 encryption work is complete.

### Architecture Components

1. **Service Worker** (`static/service-worker.js`): 
   - Caches core assets (CSS, JS, templates) for offline access
   - Version-based cache management
   - Cache-first strategy with network fallback
   - Excludes user-specific data to prevent stale information

2. **IndexedDB Wrapper** (`static/js/offline-storage.js`):
   - `pendingOperations` store: Queues operations with operation_type, hub_id, payload, timestamp, retry_count
   - `offline_session` store: Session tokens (currently plaintext - encryption pending)
   - `sync_metadata` store: Tracks last successful sync timestamp
   - Automatic 30-day cleanup (when implemented)

3. **Offline Sync Engine** (`static/js/offline.js`):
   - Background sync every 30 seconds when online
   - Exponential backoff on failures (max 5 retries)
   - Batch processing for efficient network usage
   - Client-generated UUIDs for idempotent operations

4. **Backend Sync API** (`/api/offline/sync` in app.py):
   - Processes intake, distribution, needs_list_create operations
   - OfflineSyncLog table enforces idempotency with duplicate checks
   - Hub-based access control validation via `can_access_hub()`
   - Returns success/failure status with error messages

5. **Form Integration**:
   - `templates/intake.html`: Offline banner + queueing logic
   - `templates/distribute.html`: Offline banner + queueing logic
   - `templates/needs_list_form.html`: Offline banner + line items queueing (create mode only)

### Phase 2 Roadmap (Estimated 1-2 hours)

**Required for Production Deployment**:
1. **Integrate Encryption Module**:
   - Wire `OfflineEncryption` class into `offline-storage.js` storeSession()/getSession()
   - Encrypt session tokens before IndexedDB storage
   - Decrypt on retrieval with user-provided PIN

2. **Add PIN Entry UI**:
   - Modal prompt for offline PIN setup on first offline operation
   - PIN verification on subsequent offline access
   - Secure salt storage alongside encrypted data

3. **Cleanup Job**:
   - Add periodic task to purge OfflineSyncLog entries older than 30 days
   - Prevent unbounded table growth

**Testing**:
- Regression test idempotency (duplicate sync attempts)
- Regression test hub access control (cross-hub replay attacks)
- Test encryption/decryption flow with PIN
- Test offline → online sync with all operation types

### Enabling Offline Mode (For Testing Only)

Set environment variable:
```
OFFLINE_MODE_ENABLED=true
```

**⚠️ WARNING**: Only enable for testing in development. Session tokens will be stored in plaintext until Phase 2 encryption integration is complete.