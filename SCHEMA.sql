-- ============================================
-- DRIMS Database Schema - PostgreSQL DDL
-- Generated: 2025-11-11
-- Total Tables: 23
-- ============================================


CREATE TABLE beneficiary (
	id SERIAL NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	contact VARCHAR(200), 
	parish VARCHAR(120), 
	PRIMARY KEY (id)
)

;



CREATE TABLE disaster_event (
	id SERIAL NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	event_type VARCHAR(100), 
	start_date DATE NOT NULL, 
	end_date DATE, 
	description TEXT, 
	status VARCHAR(50) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
)

;



CREATE TABLE donor (
	id SERIAL NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	contact VARCHAR(200), 
	PRIMARY KEY (id)
)

;



CREATE TABLE item (
	sku VARCHAR(64) NOT NULL, 
	barcode VARCHAR(100), 
	name VARCHAR(200) NOT NULL, 
	category VARCHAR(120), 
	unit VARCHAR(32) NOT NULL, 
	min_qty INTEGER NOT NULL, 
	description TEXT, 
	storage_requirements TEXT, 
	attachment_filename VARCHAR(255), 
	attachment_path VARCHAR(500), 
	PRIMARY KEY (sku)
)

;



CREATE TABLE location (
	id SERIAL NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	hub_type VARCHAR(10) NOT NULL, 
	parent_location_id INTEGER, 
	status VARCHAR(10) NOT NULL, 
	operational_timestamp TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (name), 
	FOREIGN KEY(parent_location_id) REFERENCES location (id)
)

;



CREATE TABLE role (
	id SERIAL NOT NULL, 
	code VARCHAR(50) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;



CREATE TABLE distribution_package (
	id SERIAL NOT NULL, 
	package_number VARCHAR(64) NOT NULL, 
	recipient_agency_id INTEGER NOT NULL, 
	assigned_location_id INTEGER, 
	event_id INTEGER, 
	status VARCHAR(50) NOT NULL, 
	is_partial BOOLEAN NOT NULL, 
	created_by VARCHAR(200) NOT NULL, 
	approved_by VARCHAR(200), 
	approved_at TIMESTAMP WITHOUT TIME ZONE, 
	dispatched_by VARCHAR(200), 
	dispatched_at TIMESTAMP WITHOUT TIME ZONE, 
	delivered_at TIMESTAMP WITHOUT TIME ZONE, 
	notes TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(recipient_agency_id) REFERENCES location (id), 
	FOREIGN KEY(assigned_location_id) REFERENCES location (id), 
	FOREIGN KEY(event_id) REFERENCES disaster_event (id)
)

;



CREATE TABLE transaction (
	id SERIAL NOT NULL, 
	item_sku VARCHAR(64) NOT NULL, 
	ttype VARCHAR(8) NOT NULL, 
	qty INTEGER NOT NULL, 
	location_id INTEGER, 
	donor_id INTEGER, 
	beneficiary_id INTEGER, 
	event_id INTEGER, 
	expiry_date DATE, 
	notes TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	created_by VARCHAR(200), 
	PRIMARY KEY (id), 
	FOREIGN KEY(item_sku) REFERENCES item (sku), 
	FOREIGN KEY(location_id) REFERENCES location (id), 
	FOREIGN KEY(donor_id) REFERENCES donor (id), 
	FOREIGN KEY(beneficiary_id) REFERENCES beneficiary (id), 
	FOREIGN KEY(event_id) REFERENCES disaster_event (id)
)

;



CREATE TABLE "user" (
	id SERIAL NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	password_hash VARCHAR(256) NOT NULL, 
	first_name VARCHAR(100), 
	last_name VARCHAR(100), 
	full_name VARCHAR(200), 
	role VARCHAR(50), 
	is_active BOOLEAN NOT NULL, 
	organization VARCHAR(200), 
	job_title VARCHAR(200), 
	phone VARCHAR(50), 
	timezone VARCHAR(50) NOT NULL, 
	language VARCHAR(10) NOT NULL, 
	notification_preferences TEXT, 
	assigned_location_id INTEGER, 
	last_login_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	created_by_id INTEGER, 
	updated_by_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(assigned_location_id) REFERENCES location (id), 
	FOREIGN KEY(created_by_id) REFERENCES "user" (id), 
	FOREIGN KEY(updated_by_id) REFERENCES "user" (id)
)

;



CREATE TABLE needs_list (
	id SERIAL NOT NULL, 
	list_number VARCHAR(64) NOT NULL, 
	agency_hub_id INTEGER NOT NULL, 
	main_hub_id INTEGER, 
	event_id INTEGER, 
	status VARCHAR(50) NOT NULL, 
	priority VARCHAR(20) NOT NULL, 
	notes TEXT, 
	created_by VARCHAR(200) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	submitted_at TIMESTAMP WITHOUT TIME ZONE, 
	draft_saved_by VARCHAR(200), 
	draft_saved_at TIMESTAMP WITHOUT TIME ZONE, 
	prepared_by VARCHAR(200), 
	prepared_at TIMESTAMP WITHOUT TIME ZONE, 
	fulfilment_notes TEXT, 
	approved_by VARCHAR(200), 
	approved_at TIMESTAMP WITHOUT TIME ZONE, 
	approval_notes TEXT, 
	dispatched_by_id INTEGER, 
	dispatched_at TIMESTAMP WITHOUT TIME ZONE, 
	dispatch_notes TEXT, 
	received_by_id INTEGER, 
	received_at TIMESTAMP WITHOUT TIME ZONE, 
	receipt_notes TEXT, 
	fulfilled_at TIMESTAMP WITHOUT TIME ZONE, 
	reviewed_by VARCHAR(200), 
	reviewed_at TIMESTAMP WITHOUT TIME ZONE, 
	review_notes TEXT, 
	locked_by_id INTEGER, 
	locked_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(agency_hub_id) REFERENCES location (id), 
	FOREIGN KEY(main_hub_id) REFERENCES location (id), 
	FOREIGN KEY(event_id) REFERENCES disaster_event (id), 
	FOREIGN KEY(dispatched_by_id) REFERENCES "user" (id), 
	FOREIGN KEY(received_by_id) REFERENCES "user" (id), 
	FOREIGN KEY(locked_by_id) REFERENCES "user" (id)
)

;



CREATE TABLE package_item (
	id SERIAL NOT NULL, 
	package_id INTEGER NOT NULL, 
	item_sku VARCHAR(64) NOT NULL, 
	requested_qty INTEGER NOT NULL, 
	allocated_qty INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(package_id) REFERENCES distribution_package (id), 
	FOREIGN KEY(item_sku) REFERENCES item (sku)
)

;



CREATE TABLE package_status_history (
	id SERIAL NOT NULL, 
	package_id INTEGER NOT NULL, 
	old_status VARCHAR(50), 
	new_status VARCHAR(50) NOT NULL, 
	changed_by VARCHAR(200) NOT NULL, 
	notes TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(package_id) REFERENCES distribution_package (id)
)

;



CREATE TABLE transfer_request (
	id SERIAL NOT NULL, 
	from_location_id INTEGER NOT NULL, 
	to_location_id INTEGER NOT NULL, 
	item_sku VARCHAR(64) NOT NULL, 
	quantity INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	requested_by INTEGER, 
	requested_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	reviewed_by INTEGER, 
	reviewed_at TIMESTAMP WITHOUT TIME ZONE, 
	notes TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(from_location_id) REFERENCES location (id), 
	FOREIGN KEY(to_location_id) REFERENCES location (id), 
	FOREIGN KEY(item_sku) REFERENCES item (sku), 
	FOREIGN KEY(requested_by) REFERENCES "user" (id), 
	FOREIGN KEY(reviewed_by) REFERENCES "user" (id)
)

;



CREATE TABLE user_hub (
	user_id INTEGER NOT NULL, 
	hub_id INTEGER NOT NULL, 
	assigned_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	assigned_by INTEGER, 
	PRIMARY KEY (user_id, hub_id), 
	FOREIGN KEY(user_id) REFERENCES "user" (id) ON DELETE CASCADE, 
	FOREIGN KEY(hub_id) REFERENCES location (id) ON DELETE CASCADE, 
	FOREIGN KEY(assigned_by) REFERENCES "user" (id)
)

;



CREATE TABLE user_role (
	user_id INTEGER NOT NULL, 
	role_id INTEGER NOT NULL, 
	assigned_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	assigned_by INTEGER, 
	PRIMARY KEY (user_id, role_id), 
	FOREIGN KEY(user_id) REFERENCES "user" (id) ON DELETE CASCADE, 
	FOREIGN KEY(role_id) REFERENCES role (id) ON DELETE CASCADE, 
	FOREIGN KEY(assigned_by) REFERENCES "user" (id)
)

;



CREATE TABLE fulfilment_change_request (
	id SERIAL NOT NULL, 
	needs_list_id INTEGER NOT NULL, 
	requesting_hub_id INTEGER NOT NULL, 
	requested_by_id INTEGER NOT NULL, 
	request_comments TEXT NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	reviewed_by_id INTEGER, 
	reviewed_at TIMESTAMP WITHOUT TIME ZONE, 
	review_comments TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(needs_list_id) REFERENCES needs_list (id), 
	FOREIGN KEY(requesting_hub_id) REFERENCES location (id), 
	FOREIGN KEY(requested_by_id) REFERENCES "user" (id), 
	FOREIGN KEY(reviewed_by_id) REFERENCES "user" (id)
)

;



CREATE TABLE needs_list_fulfilment (
	id SERIAL NOT NULL, 
	needs_list_id INTEGER NOT NULL, 
	item_sku VARCHAR(64) NOT NULL, 
	source_hub_id INTEGER NOT NULL, 
	allocated_qty INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(needs_list_id) REFERENCES needs_list (id), 
	FOREIGN KEY(item_sku) REFERENCES item (sku), 
	FOREIGN KEY(source_hub_id) REFERENCES location (id)
)

;



CREATE TABLE needs_list_item (
	id SERIAL NOT NULL, 
	needs_list_id INTEGER NOT NULL, 
	item_sku VARCHAR(64) NOT NULL, 
	requested_qty INTEGER NOT NULL, 
	justification TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(needs_list_id) REFERENCES needs_list (id), 
	FOREIGN KEY(item_sku) REFERENCES item (sku)
)

;



CREATE TABLE notification (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	hub_id INTEGER, 
	needs_list_id INTEGER, 
	title VARCHAR(200) NOT NULL, 
	message TEXT NOT NULL, 
	type VARCHAR(50) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	link_url VARCHAR(500), 
	payload TEXT, 
	is_archived BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES "user" (id), 
	FOREIGN KEY(hub_id) REFERENCES location (id), 
	FOREIGN KEY(needs_list_id) REFERENCES needs_list (id)
)

;



CREATE TABLE offline_sync_log (
	id SERIAL NOT NULL, 
	client_operation_id VARCHAR(64) NOT NULL, 
	user_id INTEGER NOT NULL, 
	operation_type VARCHAR(50) NOT NULL, 
	hub_id INTEGER NOT NULL, 
	processed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	transaction_id INTEGER, 
	needs_list_id INTEGER, 
	result_data JSON, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_client_operation_user UNIQUE (client_operation_id, user_id), 
	FOREIGN KEY(user_id) REFERENCES "user" (id), 
	FOREIGN KEY(hub_id) REFERENCES location (id), 
	FOREIGN KEY(transaction_id) REFERENCES transaction (id), 
	FOREIGN KEY(needs_list_id) REFERENCES needs_list (id)
)

;



CREATE TABLE package_item_allocation (
	id SERIAL NOT NULL, 
	package_item_id INTEGER NOT NULL, 
	depot_id INTEGER NOT NULL, 
	allocated_qty INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_package_item_depot UNIQUE (package_item_id, depot_id), 
	FOREIGN KEY(package_item_id) REFERENCES package_item (id) ON DELETE CASCADE, 
	FOREIGN KEY(depot_id) REFERENCES location (id)
)

;



CREATE TABLE fulfilment_edit_log (
	id SERIAL NOT NULL, 
	needs_list_id INTEGER NOT NULL, 
	fulfilment_id INTEGER, 
	edit_session_id VARCHAR(64) NOT NULL, 
	edited_by_id INTEGER NOT NULL, 
	edited_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	field_name VARCHAR(100) NOT NULL, 
	value_before TEXT, 
	value_after TEXT, 
	edit_reason TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(needs_list_id) REFERENCES needs_list (id), 
	FOREIGN KEY(fulfilment_id) REFERENCES needs_list_fulfilment (id), 
	FOREIGN KEY(edited_by_id) REFERENCES "user" (id)
)

;



CREATE TABLE needs_list_fulfilment_version (
	id SERIAL NOT NULL, 
	needs_list_id INTEGER NOT NULL, 
	version_number INTEGER NOT NULL, 
	change_request_id INTEGER, 
	adjusted_by_id INTEGER NOT NULL, 
	adjusted_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	adjustment_reason TEXT NOT NULL, 
	fulfilment_snapshot_before JSON NOT NULL, 
	fulfilment_snapshot_after JSON NOT NULL, 
	status_before VARCHAR(50) NOT NULL, 
	status_after VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_needs_list_version UNIQUE (needs_list_id, version_number), 
	FOREIGN KEY(needs_list_id) REFERENCES needs_list (id), 
	FOREIGN KEY(change_request_id) REFERENCES fulfilment_change_request (id), 
	FOREIGN KEY(adjusted_by_id) REFERENCES "user" (id)
)

;


-- ============================================
-- INDEXES
-- ============================================

CREATE INDEX ix_item_barcode ON item (barcode);
CREATE INDEX ix_item_category ON item (category);
CREATE INDEX ix_item_name ON item (name);
CREATE INDEX ix_role_code ON role (code);
CREATE INDEX ix_distribution_package_package_number ON distribution_package (package_number);
CREATE INDEX ix_user_email ON user (email);
CREATE INDEX ix_needs_list_locked_by_id ON needs_list (locked_by_id);
CREATE INDEX ix_needs_list_list_number ON needs_list (list_number);
CREATE INDEX idx_change_request_needs_list ON fulfilment_change_request (needs_list_id);
CREATE INDEX idx_change_request_status_created ON fulfilment_change_request (status, created_at);
CREATE INDEX ix_notification_hub_id ON notification (hub_id);
CREATE INDEX idx_notification_user_status_created ON notification (user_id, status, created_at);
CREATE INDEX ix_notification_user_id ON notification (user_id);
CREATE INDEX idx_notification_hub_created ON notification (hub_id, created_at);
CREATE INDEX ix_notification_is_archived ON notification (is_archived);
CREATE INDEX ix_notification_needs_list_id ON notification (needs_list_id);
CREATE INDEX ix_notification_created_at ON notification (created_at);
CREATE INDEX idx_sync_log_user ON offline_sync_log (user_id);
CREATE INDEX idx_sync_log_client_id ON offline_sync_log (client_operation_id);
CREATE INDEX idx_sync_log_processed_at ON offline_sync_log (processed_at);
CREATE INDEX idx_edit_log_needs_list ON fulfilment_edit_log (needs_list_id);
CREATE INDEX idx_edit_log_session ON fulfilment_edit_log (edit_session_id);
CREATE INDEX ix_fulfilment_edit_log_edit_session_id ON fulfilment_edit_log (edit_session_id);
CREATE INDEX idx_edit_log_edited_at ON fulfilment_edit_log (edited_at);
CREATE INDEX idx_version_needs_list ON needs_list_fulfilment_version (needs_list_id);
CREATE INDEX idx_version_change_request ON needs_list_fulfilment_version (change_request_id);
