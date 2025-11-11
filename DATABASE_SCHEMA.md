# DRIMS Database Schema Documentation
**Disaster Relief Inventory Management System**

**Database Type:** PostgreSQL (compatible with PostgreSQL 12+)  
**ORM:** SQLAlchemy 2.0.32  
**Generated:** November 11, 2025

---

## Table of Contents
1. [Core Entities](#core-entities)
2. [Inventory & Transactions](#inventory--transactions)
3. [User Management & Security](#user-management--security)
4. [Distribution & Needs Management](#distribution--needs-management)
5. [Audit & Tracking](#audit--tracking)
6. [Offline Mode](#offline-mode)
7. [Indexes & Constraints](#indexes--constraints)
8. [Entity Relationship Diagram](#entity-relationship-diagram)

---

## Core Entities

### `location` (Depot/Hub)
Physical locations for inventory storage (warehouses, shelters, hubs).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| name | VARCHAR(120) | NOT NULL, UNIQUE | Hub name (e.g., "Kingston Depot") |
| hub_type | VARCHAR(10) | NOT NULL, DEFAULT 'MAIN' | Hub classification: MAIN, SUB, AGENCY |
| parent_location_id | INTEGER | FOREIGN KEY → location.id | Parent hub (null for MAIN hubs) |
| status | VARCHAR(10) | NOT NULL, DEFAULT 'Active' | Active or Inactive |
| operational_timestamp | TIMESTAMP | NULL | Last activation timestamp |

**Relationships:**
- Self-referencing: `parent_hub` → `sub_hubs` (one-to-many)

**Business Logic:**
- **MAIN hubs**: Central warehouses (no parent)
- **SUB hubs**: Regional warehouses (parent = MAIN hub)
- **AGENCY hubs**: Field distribution points (parent = SUB or MAIN hub)

---

### `item`
Inventory items/supplies with SKU tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| sku | VARCHAR(64) | PRIMARY KEY | Auto-generated SKU (e.g., "ITEM-000001") |
| barcode | VARCHAR(100) | UNIQUE, INDEXED | External barcode for scanner input |
| name | VARCHAR(200) | NOT NULL, INDEXED | Item name |
| category | VARCHAR(120) | INDEXED | Food, Water, Hygiene, Medical, etc. |
| unit | VARCHAR(32) | NOT NULL, DEFAULT 'unit' | Unit of measure (pcs, kg, L, boxes) |
| min_qty | INTEGER | NOT NULL, DEFAULT 0 | Low stock threshold |
| description | TEXT | NULL | Detailed description |
| storage_requirements | TEXT | NULL | Storage instructions |
| attachment_filename | VARCHAR(255) | NULL | Original uploaded file name |
| attachment_path | VARCHAR(500) | NULL | File storage path |

**Note:** Stock quantities are **computed dynamically** from the `transaction` table, not stored directly.

---

### `disaster_event`
Disaster events for tracking relief operations.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| name | VARCHAR(200) | NOT NULL | Event name (e.g., "Hurricane Beryl 2024") |
| event_type | VARCHAR(100) | NULL | Hurricane, Earthquake, Flood, etc. |
| start_date | DATE | NOT NULL | Event start date |
| end_date | DATE | NULL | Event end date (null if ongoing) |
| description | TEXT | NULL | Event details |
| status | VARCHAR(50) | NOT NULL, DEFAULT 'Active' | Active or Closed |
| created_at | TIMESTAMP | DEFAULT NOW() | Record creation timestamp |

---

### `donor`
Donor entities (individuals, organizations).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| name | VARCHAR(200) | NOT NULL | Donor name |
| contact | VARCHAR(200) | NULL | Contact information |

---

### `beneficiary`
Beneficiaries receiving aid.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| name | VARCHAR(200) | NOT NULL | Beneficiary name |
| contact | VARCHAR(200) | NULL | Contact information |
| parish | VARCHAR(120) | NULL | Geographic location |

---

## Inventory & Transactions

### `transaction`
All inventory movements (intake, distribution, transfers).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| item_sku | VARCHAR(64) | NOT NULL, FOREIGN KEY → item.sku | Item being moved |
| ttype | VARCHAR(8) | NOT NULL | Transaction type: "IN" or "OUT" |
| qty | INTEGER | NOT NULL | Quantity (positive for IN, OUT) |
| location_id | INTEGER | FOREIGN KEY → location.id | Hub location |
| donor_id | INTEGER | FOREIGN KEY → donor.id | Donor (for intake) |
| beneficiary_id | INTEGER | FOREIGN KEY → beneficiary.id | Beneficiary (for distribution) |
| event_id | INTEGER | FOREIGN KEY → disaster_event.id | Associated disaster event |
| expiry_date | DATE | NULL | Item batch expiry date |
| notes | TEXT | NULL | Additional notes |
| created_at | TIMESTAMP | DEFAULT NOW() | Transaction timestamp (UTC) |
| created_by | VARCHAR(200) | NULL | User who created transaction |

**Stock Calculation Logic:**
```sql
-- Current stock at a location for an item:
SELECT SUM(CASE WHEN ttype = 'IN' THEN qty ELSE -qty END) AS stock
FROM transaction
WHERE item_sku = ? AND location_id = ?
```

---

### `transfer_request`
Hub-to-hub stock transfer requests with approval workflow.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| from_location_id | INTEGER | NOT NULL, FOREIGN KEY → location.id | Source hub |
| to_location_id | INTEGER | NOT NULL, FOREIGN KEY → location.id | Destination hub |
| item_sku | VARCHAR(64) | NOT NULL, FOREIGN KEY → item.sku | Item to transfer |
| quantity | INTEGER | NOT NULL | Transfer quantity |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'PENDING' | PENDING, APPROVED, REJECTED, COMPLETED |
| requested_by | INTEGER | FOREIGN KEY → user.id | Requester user ID |
| requested_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Request timestamp |
| reviewed_by | INTEGER | FOREIGN KEY → user.id | Reviewer user ID |
| reviewed_at | TIMESTAMP | NULL | Review timestamp |
| notes | TEXT | NULL | Request notes |

**Approval Rules:**
- SUB → SUB: Requires MAIN hub approval
- SUB → AGENCY: Approved by SUB hub manager
- MAIN → SUB: Approved by MAIN hub logistics

---

## User Management & Security

### `user`
System users with authentication and profile data.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| email | VARCHAR(200) | NOT NULL, UNIQUE, INDEXED | User email (login) |
| password_hash | VARCHAR(256) | NOT NULL | Bcrypt password hash |
| first_name | VARCHAR(100) | NULL | User first name |
| last_name | VARCHAR(100) | NULL | User last name |
| full_name | VARCHAR(200) | NULL | **Legacy field** (deprecated) |
| role | VARCHAR(50) | NULL | **Legacy field** (deprecated) |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | Account active status |
| organization | VARCHAR(200) | NULL | Organization name |
| job_title | VARCHAR(200) | NULL | Job title |
| phone | VARCHAR(50) | NULL | Phone number |
| timezone | VARCHAR(50) | NOT NULL, DEFAULT 'America/Jamaica' | User timezone (EST/GMT-5) |
| language | VARCHAR(10) | NOT NULL, DEFAULT 'en' | Language preference |
| notification_preferences | TEXT | NULL | JSON string for notification settings |
| assigned_location_id | INTEGER | FOREIGN KEY → location.id | **Legacy field** (deprecated) |
| last_login_at | TIMESTAMP | NULL | Last successful login |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Account creation |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |
| created_by_id | INTEGER | FOREIGN KEY → user.id | Admin who created account |
| updated_by_id | INTEGER | FOREIGN KEY → user.id | Admin who last updated |

**Authentication:**
- Password hashing: Werkzeug `generate_password_hash()` (Bcrypt)
- Session management: Flask-Login

**Migration Note:** Legacy `role` and `assigned_location_id` fields maintained for backward compatibility. New system uses `user_role` and `user_hub` many-to-many tables.

---

### `role`
Normalized role definitions.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| code | VARCHAR(50) | NOT NULL, UNIQUE, INDEXED | Role code (e.g., "LOGISTICS_MANAGER") |
| name | VARCHAR(100) | NOT NULL | Display name |
| description | TEXT | NULL | Role description |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Record creation |

**Standard Roles:**
- `ADMIN` - System Administrator
- `LOGISTICS_MANAGER` - Logistics Manager (national oversight)
- `LOGISTICS_OFFICER` - Logistics Officer (operations)
- `MAIN_HUB_USER` - Main Hub User (warehouse staff)
- `SUB_HUB_USER` - Sub-Hub User (regional warehouse)
- `AGENCY_HUB_USER` - Agency Hub User (field staff)
- `AUDITOR` - Auditor (read-only access)
- `INVENTORY_CLERK` - Inventory Clerk (data entry)

---

### `user_role`
Many-to-many relationship: Users ↔ Roles.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| user_id | INTEGER | PRIMARY KEY, FOREIGN KEY → user.id | User ID |
| role_id | INTEGER | PRIMARY KEY, FOREIGN KEY → role.id | Role ID |
| assigned_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Assignment timestamp |
| assigned_by | INTEGER | FOREIGN KEY → user.id | Admin who assigned role |

**Composite Primary Key:** `(user_id, role_id)`

**Cascade Deletes:** User/role deletion removes assignments.

---

### `user_hub`
Many-to-many relationship: Users ↔ Hubs (access control).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| user_id | INTEGER | PRIMARY KEY, FOREIGN KEY → user.id | User ID |
| hub_id | INTEGER | PRIMARY KEY, FOREIGN KEY → location.id | Hub ID |
| assigned_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Assignment timestamp |
| assigned_by | INTEGER | FOREIGN KEY → user.id | Admin who assigned access |

**Composite Primary Key:** `(user_id, hub_id)`

**Purpose:** Controls which hubs a user can view/manage.

---

### `notification`
In-app notifications for workflow events.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| user_id | INTEGER | NOT NULL, FOREIGN KEY → user.id, INDEXED | Recipient user |
| hub_id | INTEGER | FOREIGN KEY → location.id, INDEXED | Related hub |
| needs_list_id | INTEGER | FOREIGN KEY → needs_list.id, INDEXED | Related needs list |
| title | VARCHAR(200) | NOT NULL | Notification title |
| message | TEXT | NOT NULL | Notification message |
| type | VARCHAR(50) | NOT NULL | submitted, approved, dispatched, received, comment |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'unread' | unread, read, archived |
| link_url | VARCHAR(500) | NULL | Deep link URL |
| payload | TEXT | NULL | JSON payload (extensibility) |
| is_archived | BOOLEAN | NOT NULL, DEFAULT FALSE, INDEXED | Archive status |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW(), INDEXED | Creation timestamp |

**Indexes:**
- `idx_notification_user_status_created` (user_id, status, created_at)
- `idx_notification_hub_created` (hub_id, created_at)

---

## Distribution & Needs Management

### `distribution_package`
Distribution packages for AGENCY hubs (legacy system).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| package_number | VARCHAR(64) | NOT NULL, UNIQUE, INDEXED | Package number (e.g., "PKG-000001") |
| recipient_agency_id | INTEGER | NOT NULL, FOREIGN KEY → location.id | AGENCY hub recipient |
| assigned_location_id | INTEGER | FOREIGN KEY → location.id | **Deprecated** warehouse field |
| event_id | INTEGER | FOREIGN KEY → disaster_event.id | Associated disaster event |
| status | VARCHAR(50) | NOT NULL, DEFAULT 'Draft' | Draft, Under Review, Approved, Dispatched, Delivered |
| is_partial | BOOLEAN | NOT NULL, DEFAULT FALSE | True if stock insufficient |
| created_by | VARCHAR(200) | NOT NULL | Creator username |
| approved_by | VARCHAR(200) | NULL | Approver username |
| approved_at | TIMESTAMP | NULL | Approval timestamp |
| dispatched_by | VARCHAR(200) | NULL | Dispatcher username |
| dispatched_at | TIMESTAMP | NULL | Dispatch timestamp |
| delivered_at | TIMESTAMP | NULL | Delivery timestamp |
| notes | TEXT | NULL | Package notes |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |

---

### `package_item`
Line items in distribution packages.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| package_id | INTEGER | NOT NULL, FOREIGN KEY → distribution_package.id | Parent package |
| item_sku | VARCHAR(64) | NOT NULL, FOREIGN KEY → item.sku | Item SKU |
| requested_qty | INTEGER | NOT NULL | Quantity requested |
| allocated_qty | INTEGER | NOT NULL, DEFAULT 0 | Total allocated (sum of depot allocations) |

---

### `package_item_allocation`
Per-depot allocations for package items.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| package_item_id | INTEGER | NOT NULL, FOREIGN KEY → package_item.id | Package item |
| depot_id | INTEGER | NOT NULL, FOREIGN KEY → location.id | Source depot |
| allocated_qty | INTEGER | NOT NULL | Quantity from this depot |

**Unique Constraint:** `(package_item_id, depot_id)` - One allocation per depot per item.

---

### `package_status_history`
Audit trail for package status changes.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| package_id | INTEGER | NOT NULL, FOREIGN KEY → distribution_package.id | Package ID |
| old_status | VARCHAR(50) | NULL | Previous status |
| new_status | VARCHAR(50) | NOT NULL | New status |
| changed_by | VARCHAR(200) | NOT NULL | User who changed status |
| notes | TEXT | NULL | Change notes |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Change timestamp |

---

### `needs_list`
Supply requests from AGENCY/SUB hubs (modern system).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| list_number | VARCHAR(64) | NOT NULL, UNIQUE, INDEXED | List number (e.g., "NL-000001") |
| agency_hub_id | INTEGER | NOT NULL, FOREIGN KEY → location.id | Requesting AGENCY/SUB hub |
| main_hub_id | INTEGER | FOREIGN KEY → location.id | **Legacy field** (may be null) |
| event_id | INTEGER | FOREIGN KEY → disaster_event.id | Associated disaster event |
| status | VARCHAR(50) | NOT NULL, DEFAULT 'Draft' | See status list below |
| priority | VARCHAR(20) | NOT NULL, DEFAULT 'Medium' | Low, Medium, High, Urgent |
| notes | TEXT | NULL | Agency notes |
| created_by | VARCHAR(200) | NOT NULL | Creator username |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| submitted_at | TIMESTAMP | NULL | Submission timestamp |
| draft_saved_by | VARCHAR(200) | NULL | Last user to save draft |
| draft_saved_at | TIMESTAMP | NULL | Draft save timestamp |
| prepared_by | VARCHAR(200) | NULL | Logistics Officer who prepared |
| prepared_at | TIMESTAMP | NULL | Preparation timestamp |
| fulfilment_notes | TEXT | NULL | Logistics Officer notes |
| approved_by | VARCHAR(200) | NULL | Logistics Manager who approved |
| approved_at | TIMESTAMP | NULL | Approval timestamp |
| approval_notes | TEXT | NULL | Logistics Manager notes |
| dispatched_by_id | INTEGER | FOREIGN KEY → user.id | User who dispatched |
| dispatched_at | TIMESTAMP | NULL | Dispatch timestamp |
| dispatch_notes | TEXT | NULL | Dispatch notes |
| received_by_id | INTEGER | FOREIGN KEY → user.id | Agency user who confirmed receipt |
| received_at | TIMESTAMP | NULL | Receipt timestamp |
| receipt_notes | TEXT | NULL | Receipt confirmation notes |
| fulfilled_at | TIMESTAMP | NULL | Fulfilment completion |
| reviewed_by | VARCHAR(200) | NULL | **Deprecated** |
| reviewed_at | TIMESTAMP | NULL | **Deprecated** |
| review_notes | TEXT | NULL | **Deprecated** |
| locked_by_id | INTEGER | FOREIGN KEY → user.id, INDEXED | User editing fulfilment (concurrency lock) |
| locked_at | TIMESTAMP | NULL | Lock acquisition time |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |

**Status Values (10 official states):**
1. **Draft** - Being created by agency
2. **Submitted** - Awaiting logistics review
3. **Fulfilment Prepared** - Logistics Officer prepared allocation
4. **Awaiting Approval** - Awaiting Logistics Manager approval
5. **Approved** - Ready for dispatch
6. **Dispatched** - Items sent to agency
7. **Received** - Agency confirmed receipt
8. **Completed** - Fulfilment finalized
9. **Rejected** - Request denied
10. **Change Requested** - Agency requested modifications

---

### `needs_list_item`
Line items in needs lists.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| needs_list_id | INTEGER | NOT NULL, FOREIGN KEY → needs_list.id | Parent needs list |
| item_sku | VARCHAR(64) | NOT NULL, FOREIGN KEY → item.sku | Item SKU |
| requested_qty | INTEGER | NOT NULL | Quantity requested |
| justification | TEXT | NULL | Why item is needed |

---

### `needs_list_fulfilment`
Fulfilment allocations for needs list items.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| needs_list_id | INTEGER | NOT NULL, FOREIGN KEY → needs_list.id | Needs list |
| item_sku | VARCHAR(64) | NOT NULL, FOREIGN KEY → item.sku | Item SKU |
| source_hub_id | INTEGER | NOT NULL, FOREIGN KEY → location.id | MAIN/SUB hub supplying stock |
| allocated_qty | INTEGER | NOT NULL | Quantity from this source |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Allocation timestamp |

**Business Logic:** Multiple source hubs can fulfill a single needs list item.

---

### `fulfilment_change_request`
Requests from warehouse users to modify approved fulfilments.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| needs_list_id | INTEGER | NOT NULL, FOREIGN KEY → needs_list.id | Related needs list |
| requesting_hub_id | INTEGER | NOT NULL, FOREIGN KEY → location.id | Sub-hub requesting change |
| requested_by_id | INTEGER | NOT NULL, FOREIGN KEY → user.id | Warehouse user |
| request_comments | TEXT | NOT NULL | Why change is needed |
| status | VARCHAR(50) | NOT NULL, DEFAULT 'Pending Review' | Pending Review, In Progress, Approved & Resent, Rejected, Clarification Needed |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Request timestamp |
| reviewed_by_id | INTEGER | FOREIGN KEY → user.id | Logistics Officer/Manager |
| reviewed_at | TIMESTAMP | NULL | Review timestamp |
| review_comments | TEXT | NULL | Logistics response |

**Indexes:**
- `idx_change_request_status_created` (status, created_at)
- `idx_change_request_needs_list` (needs_list_id)

---

### `needs_list_fulfilment_version`
Audit trail for fulfilment adjustments (before/after snapshots).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| needs_list_id | INTEGER | NOT NULL, FOREIGN KEY → needs_list.id | Needs list |
| version_number | INTEGER | NOT NULL | Sequential version number |
| change_request_id | INTEGER | FOREIGN KEY → fulfilment_change_request.id | Related change request (null for proactive adjustments) |
| adjusted_by_id | INTEGER | NOT NULL, FOREIGN KEY → user.id | User who made adjustment |
| adjusted_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Adjustment timestamp |
| adjustment_reason | TEXT | NOT NULL | Why adjustment was made |
| fulfilment_snapshot_before | JSON | NOT NULL | Before state (JSON) |
| fulfilment_snapshot_after | JSON | NOT NULL | After state (JSON) |
| status_before | VARCHAR(50) | NOT NULL | Needs list status before |
| status_after | VARCHAR(50) | NOT NULL | Needs list status after |

**Unique Constraint:** `(needs_list_id, version_number)`

**Indexes:**
- `idx_version_needs_list` (needs_list_id)
- `idx_version_change_request` (change_request_id)

---

## Audit & Tracking

### `fulfilment_edit_log`
Post-completion edits to delivered needs lists.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| needs_list_id | INTEGER | NOT NULL, FOREIGN KEY → needs_list.id | Needs list |
| fulfilment_id | INTEGER | FOREIGN KEY → needs_list_fulfilment.id | Specific fulfilment line (null for list-level edits) |
| edit_session_id | VARCHAR(64) | NOT NULL, INDEXED | UUID grouping edits from same save |
| edited_by_id | INTEGER | NOT NULL, FOREIGN KEY → user.id | User who edited |
| edited_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Edit timestamp |
| field_name | VARCHAR(100) | NOT NULL | Field edited (e.g., 'allocated_qty', 'dispatch_notes') |
| value_before | TEXT | NULL | Previous value |
| value_after | TEXT | NULL | New value |
| edit_reason | TEXT | NULL | Why correction was needed |

**Indexes:**
- `idx_edit_log_needs_list` (needs_list_id)
- `idx_edit_log_edited_at` (edited_at)
- `idx_edit_log_session` (edit_session_id)

**Purpose:** Tracks corrections to completed needs lists after receipt confirmation.

---

## Offline Mode

### `offline_sync_log`
Tracks processed offline operations for idempotency.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing ID |
| client_operation_id | VARCHAR(64) | NOT NULL | Client-generated UUID |
| user_id | INTEGER | NOT NULL, FOREIGN KEY → user.id | User who created operation |
| operation_type | VARCHAR(50) | NOT NULL | intake, distribution, needs_list_create |
| hub_id | INTEGER | NOT NULL, FOREIGN KEY → location.id | Hub where operation occurred |
| processed_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Server processing timestamp |
| transaction_id | INTEGER | FOREIGN KEY → transaction.id | Created transaction (if applicable) |
| needs_list_id | INTEGER | FOREIGN KEY → needs_list.id | Created needs list (if applicable) |
| result_data | JSON | NULL | Sync result for replay responses |

**Unique Constraint:** `(client_operation_id, user_id)` - **Critical for idempotency**

**Indexes:**
- `idx_sync_log_client_id` (client_operation_id)
- `idx_sync_log_user` (user_id)
- `idx_sync_log_processed_at` (processed_at)

**Purpose:** 
- Prevents duplicate processing of offline operations
- Enforces exactly-once semantics for offline form submissions
- Stores results for replay when clients retry

---

## Indexes & Constraints Summary

### Primary Keys
All tables use auto-incrementing `INTEGER` primary keys except:
- `item` (uses `sku` as VARCHAR primary key)
- `user_role` (composite: user_id, role_id)
- `user_hub` (composite: user_id, hub_id)

### Foreign Key Constraints
All foreign keys use `ON DELETE` behavior appropriate to relationship:
- `user_role`, `user_hub`: `CASCADE` (delete assignments when user/role/hub deleted)
- Most others: Default `NO ACTION` (prevent deletion if referenced)

### Unique Constraints
- `location.name`
- `item.barcode`
- `user.email`
- `role.code`
- `distribution_package.package_number`
- `needs_list.list_number`
- `package_item_allocation`: (package_item_id, depot_id)
- `needs_list_fulfilment_version`: (needs_list_id, version_number)
- `offline_sync_log`: (client_operation_id, user_id)

### Performance Indexes
See individual table sections for composite indexes on:
- Notifications (user + status + date)
- Change requests (status + date)
- Fulfilment versions (needs_list, change_request)
- Edit logs (needs_list, session, date)
- Sync logs (client_id, user, date)

---

## Entity Relationship Diagram

### Core Inventory Flow
```
disaster_event ──┐
                 │
                 ├──> transaction ──> location (MAIN/SUB/AGENCY)
                 │         ├──> item
                 │         ├──> donor
                 │         └──> beneficiary
                 │
                 └──> needs_list ──> needs_list_item ──> item
                           │              
                           └──> needs_list_fulfilment ──> location (source hub)
```

### User & Access Control
```
user ──┬──> user_role ──> role
       │
       └──> user_hub ──> location
```

### Needs List Workflow
```
needs_list ──┬──> needs_list_item
             │
             ├──> needs_list_fulfilment (allocations)
             │
             ├──> fulfilment_change_request (post-approval changes)
             │
             ├──> needs_list_fulfilment_version (audit trail)
             │
             ├──> fulfilment_edit_log (post-completion edits)
             │
             └──> notification (workflow events)
```

---

## Migration Notes for Your PostgreSQL Environment

### Compatible Features
✅ **Direct Compatibility:**
- All data types are standard PostgreSQL
- Foreign key constraints fully supported
- JSON columns for flexible data storage
- Composite unique constraints
- Multi-column indexes

### Recommended Migration Steps

1. **Schema Creation:**
   ```sql
   -- Run SQLAlchemy migrations OR
   -- Use exported DDL scripts from db.create_all()
   ```

2. **Initial Data:**
   - Seed `role` table with 8 standard roles
   - Create at least one ADMIN user
   - Create initial MAIN hub(s)

3. **Performance Tuning:**
   ```sql
   -- Add additional indexes if needed
   CREATE INDEX idx_transaction_location_item ON transaction(location_id, item_sku);
   CREATE INDEX idx_transaction_created ON transaction(created_at DESC);
   ```

4. **Archival Strategy:**
   ```sql
   -- Partition transaction table by created_at (recommended for large datasets)
   -- Archive old notifications (> 90 days)
   -- Purge offline_sync_log entries (> 30 days)
   ```

### Authentication Integration for KeyCloak/LDAP

**Current System:** Flask-Login with password hash in `user.password_hash`

**Migration Path:**
1. Keep `user` table structure
2. Replace password authentication with LDAP/KeyCloak
3. Map KeyCloak roles → DRIMS `role.code` values
4. Sync KeyCloak groups → `user_hub` assignments

**Suggested Approach:**
```python
# Replace password check with KeyCloak/LDAP validation
def authenticate_user(email, password):
    # Call KeyCloak/LDAP API
    keycloak_user = keycloak_client.authenticate(email, password)
    
    # Find or create DRIMS user
    user = User.query.filter_by(email=email).first()
    if not user:
        user = create_user_from_keycloak(keycloak_user)
    
    # Sync roles from KeyCloak groups
    sync_roles_from_keycloak(user, keycloak_user.groups)
    
    return user
```

---

## Estimated Database Size

**For 1 Year Operation (10 hubs, 500 items, 1000 users):**

| Table | Est. Rows | Est. Size |
|-------|-----------|-----------|
| transaction | 100,000 | 15 MB |
| needs_list | 5,000 | 2 MB |
| needs_list_fulfilment | 25,000 | 3 MB |
| notification | 50,000 | 8 MB |
| user | 1,000 | 500 KB |
| item | 500 | 200 KB |
| Other tables | - | 2 MB |
| **Total** | **~180,000** | **~30 MB** |

**Note:** Indexes add ~30% overhead. Plan for 50 MB with indexes.

---

## Database Maintenance Recommendations

### Daily Tasks
- Monitor transaction volume
- Check for locked needs lists (stuck locks)

### Weekly Tasks
- Archive read notifications (> 30 days)
- Purge offline_sync_log (> 30 days)
- Review fulfilment_edit_log for anomalies

### Monthly Tasks
- Analyze query performance
- Rebuild indexes if needed
- Archive completed disaster events

### Backup Strategy
- **Full backup:** Daily
- **Incremental:** Every 6 hours
- **Retention:** 30 days minimum
- **Disaster recovery:** Off-site replication

---

**End of Schema Documentation**

For implementation questions or KeyCloak/LDAP integration assistance, contact the development team.
