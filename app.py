import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, case
from functools import wraps
from urllib.parse import urlparse, urljoin
import pandas as pd
import secrets
from storage_service import get_storage, allowed_file, validate_file_size
from status_helpers import get_line_item_status, get_needs_list_status_display, LineItemStatus
from date_utils import (
    format_date, 
    format_datetime, 
    format_datetime_full, 
    format_time,
    format_datetime_iso_est,
    format_relative_time
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
db_url = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------- Models ----------
class Depot(db.Model):
    __tablename__ = 'location'  # Keep existing table name for backward compatibility
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)  # e.g., Parish depot / shelter
    hub_type = db.Column(db.String(10), nullable=False, default='MAIN')  # MAIN, SUB, AGENCY
    parent_location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=True)  # Parent hub for SUB/AGENCY
    status = db.Column(db.String(10), nullable=False, default='Active')  # Active or Inactive
    operational_timestamp = db.Column(db.DateTime, nullable=True)  # Last time hub was activated
    
    parent_hub = db.relationship("Depot", remote_side=[id], backref="sub_hubs")

class Item(db.Model):
    sku = db.Column(db.String(64), primary_key=True)
    barcode = db.Column(db.String(100), nullable=True, unique=True, index=True)  # Barcode for scanner input
    name = db.Column(db.String(200), nullable=False, index=True)
    category = db.Column(db.String(120), nullable=True, index=True)       # e.g., Food, Water, Hygiene, Medical
    unit = db.Column(db.String(32), nullable=False, default="unit")        # Unit of measure: e.g., pcs, kg, L, boxes
    min_qty = db.Column(db.Integer, nullable=False, default=0)             # threshold for "low stock"
    description = db.Column(db.Text, nullable=True)
    storage_requirements = db.Column(db.Text, nullable=True)               # e.g., "Keep refrigerated", "Store in cool dry place"
    attachment_filename = db.Column(db.String(255), nullable=True)         # Original filename of uploaded document/image
    attachment_path = db.Column(db.String(500), nullable=True)             # Storage path (local or S3/Nexus URL in future)

class Donor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=False)
    contact = db.Column(db.String(200), nullable=True)

class Beneficiary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    contact = db.Column(db.String(200), nullable=True)
    parish = db.Column(db.String(120), nullable=True)

class DisasterEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    event_type = db.Column(db.String(100), nullable=True)  # Hurricane, Earthquake, Flood, etc.
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False, default="Active")  # Active, Closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_sku = db.Column(db.String(64), db.ForeignKey("item.sku"), nullable=False)
    ttype = db.Column(db.String(8), nullable=False)  # "IN" or "OUT"
    qty = db.Column(db.Integer, nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donor.id"), nullable=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiary.id"), nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey("disaster_event.id"), nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)  # Expiry date for this batch of items
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(200), nullable=True)  # User who created the transaction (for audit)

    item = db.relationship("Item")
    location = db.relationship("Depot")
    donor = db.relationship("Donor")
    beneficiary = db.relationship("Beneficiary")
    event = db.relationship("DisasterEvent")

class TransferRequest(db.Model):
    """Transfer requests for hub-to-hub stock movements requiring approval"""
    id = db.Column(db.Integer, primary_key=True)
    from_location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    to_location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    item_sku = db.Column(db.String(64), db.ForeignKey("item.sku"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='PENDING')  # PENDING, APPROVED, REJECTED, COMPLETED
    requested_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    from_location = db.relationship("Depot", foreign_keys=[from_location_id])
    to_location = db.relationship("Depot", foreign_keys=[to_location_id])
    item = db.relationship("Item")
    requester = db.relationship("User", foreign_keys=[requested_by])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

class Role(db.Model):
    """Roles table for normalized role management"""
    __tablename__ = 'role'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)  # e.g., LOGISTICS_MANAGER
    name = db.Column(db.String(100), nullable=False)  # Display name
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    users = db.relationship('UserRole', back_populates='role', cascade='all, delete-orphan')


class UserRole(db.Model):
    """Many-to-many relationship between users and roles"""
    __tablename__ = 'user_role'
    __table_args__ = (
        db.PrimaryKeyConstraint('user_id', 'role_id'),
    )
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id', ondelete='CASCADE'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    user = db.relationship('User', foreign_keys=[user_id], back_populates='user_roles')
    role = db.relationship('Role', back_populates='users')
    assigner = db.relationship('User', foreign_keys=[assigned_by])


class UserHub(db.Model):
    """Many-to-many relationship between users and hubs for scoping access"""
    __tablename__ = 'user_hub'
    __table_args__ = (
        db.PrimaryKeyConstraint('user_id', 'hub_id'),
    )
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    hub_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='CASCADE'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    user = db.relationship('User', foreign_keys=[user_id], back_populates='user_hubs')
    hub = db.relationship('Depot')
    assigner = db.relationship('User', foreign_keys=[assigned_by])


class User(UserMixin, db.Model):
    __tablename__ = 'user'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Authentication fields
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    
    # Name fields - NEW SCHEMA
    first_name = db.Column(db.String(100), nullable=True)  # Nullable during migration
    last_name = db.Column(db.String(100), nullable=True)  # Nullable during migration
    
    # Legacy field - kept for backwards compatibility during migration
    full_name = db.Column(db.String(200), nullable=True)
    
    # Legacy role field - kept for backwards compatibility during migration
    role = db.Column(db.String(50), nullable=True)
    
    # Status and profile fields
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    organization = db.Column(db.String(200), nullable=True)
    job_title = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    timezone = db.Column(db.String(50), default='America/Jamaica', nullable=False)  # EST/GMT-5
    language = db.Column(db.String(10), default='en', nullable=False)
    notification_preferences = db.Column(db.Text, nullable=True)  # JSON string
    
    # Legacy location field - kept for backwards compatibility during migration
    assigned_location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=True)
    
    # Audit fields
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    # Relationships
    user_roles = db.relationship('UserRole', foreign_keys='UserRole.user_id', back_populates='user', cascade='all, delete-orphan')
    user_hubs = db.relationship('UserHub', foreign_keys='UserHub.user_id', back_populates='user', cascade='all, delete-orphan')
    assigned_location = db.relationship("Depot", foreign_keys=[assigned_location_id])  # Legacy
    creator = db.relationship('User', foreign_keys=[created_by_id], remote_side='User.id')
    updater = db.relationship('User', foreign_keys=[updated_by_id], remote_side='User.id')
    
    def set_password(self, password):
        """Hash and set the user's password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password against hash"""
        return check_password_hash(self.password_hash, password)
    
    def get_id(self):
        """Required by Flask-Login"""
        return str(self.id)
    
    @property
    def display_name(self):
        """Get display name from first_name and last_name, fallback to full_name"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.full_name:
            return self.full_name
        return self.email
    
    @property
    def roles(self):
        """Get list of role codes assigned to this user"""
        return [ur.role.code for ur in self.user_roles]
    
    @property
    def hubs(self):
        """Get list of hubs assigned to this user"""
        return [uh.hub for uh in self.user_hubs]
    
    def has_role(self, role_code):
        """Check if user has a specific role"""
        return role_code in self.roles
    
    def has_any_role(self, *role_codes):
        """Check if user has any of the specified roles"""
        return any(role_code in self.roles for role_code in role_codes)
    
    def has_hub_access(self, hub_id):
        """Check if user has access to a specific hub"""
        return any(uh.hub_id == hub_id for uh in self.user_hubs)

class Notification(db.Model):
    """In-app notifications for Agency Hub users to track workflow updates"""
    __tablename__ = 'notification'
    __table_args__ = (
        db.Index('idx_notification_user_status_created', 'user_id', 'status', 'created_at'),
        db.Index('idx_notification_hub_created', 'hub_id', 'created_at'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    hub_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=True, index=True)
    needs_list_id = db.Column(db.Integer, db.ForeignKey('needs_list.id'), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), nullable=False)  # submitted, approved, dispatched, received, comment
    status = db.Column(db.String(20), default='unread', nullable=False)  # unread, read, archived
    link_url = db.Column(db.String(500), nullable=True)  # URL to navigate to related resource
    payload = db.Column(db.Text, nullable=True)  # JSON payload for extensibility (e.g., triggered_by info)
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    user = db.relationship('User', backref='notifications')
    hub = db.relationship('Depot')
    needs_list = db.relationship('NeedsList')

class DistributionPackage(db.Model):
    """Distribution packages for relief operations delivered to AGENCY hubs"""
    id = db.Column(db.Integer, primary_key=True)
    package_number = db.Column(db.String(64), unique=True, nullable=False, index=True)  # e.g., PKG-000001
    recipient_agency_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)  # AGENCY hub that will receive this package
    assigned_location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=True)  # Warehouse/outpost (deprecated, kept for compatibility)
    event_id = db.Column(db.Integer, db.ForeignKey("disaster_event.id"), nullable=True)
    status = db.Column(db.String(50), nullable=False, default="Draft")  # Draft, Under Review, Approved, Dispatched, Delivered
    is_partial = db.Column(db.Boolean, default=False, nullable=False)  # True if stock insufficient for full fulfillment
    created_by = db.Column(db.String(200), nullable=False)
    approved_by = db.Column(db.String(200), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    dispatched_by = db.Column(db.String(200), nullable=True)
    dispatched_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    recipient_agency = db.relationship("Depot", foreign_keys=[recipient_agency_id])
    assigned_location = db.relationship("Depot", foreign_keys=[assigned_location_id])
    event = db.relationship("DisasterEvent")
    items = db.relationship("PackageItem", back_populates="package", cascade="all, delete-orphan")
    status_history = db.relationship("PackageStatusHistory", back_populates="package", cascade="all, delete-orphan")

class PackageItem(db.Model):
    """Items in a distribution package"""
    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(db.Integer, db.ForeignKey("distribution_package.id"), nullable=False)
    item_sku = db.Column(db.String(64), db.ForeignKey("item.sku"), nullable=False)
    requested_qty = db.Column(db.Integer, nullable=False)  # Quantity requested for agency
    allocated_qty = db.Column(db.Integer, nullable=False, default=0)  # Total quantity allocated (sum of all depot allocations)
    
    package = db.relationship("DistributionPackage", back_populates="items")
    item = db.relationship("Item")
    allocations = db.relationship("PackageItemAllocation", back_populates="package_item", cascade="all, delete-orphan")

class PackageItemAllocation(db.Model):
    """Per-depot allocation for package items - tracks which depots fulfill which quantities"""
    __tablename__ = 'package_item_allocation'
    __table_args__ = (
        db.UniqueConstraint('package_item_id', 'depot_id', name='uq_package_item_depot'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    package_item_id = db.Column(db.Integer, db.ForeignKey("package_item.id", ondelete="CASCADE"), nullable=False)
    depot_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    allocated_qty = db.Column(db.Integer, nullable=False)  # Quantity to be fulfilled from this depot
    
    package_item = db.relationship("PackageItem", back_populates="allocations")
    depot = db.relationship("Depot")

class PackageStatusHistory(db.Model):
    """Audit trail of package status changes"""
    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(db.Integer, db.ForeignKey("distribution_package.id"), nullable=False)
    old_status = db.Column(db.String(50), nullable=True)
    new_status = db.Column(db.String(50), nullable=False)
    changed_by = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    package = db.relationship("DistributionPackage", back_populates="status_history")

class NeedsList(db.Model):
    """Needs lists created by AGENCY and SUB hubs for logistics review and fulfilment"""
    __tablename__ = 'needs_list'
    id = db.Column(db.Integer, primary_key=True)
    list_number = db.Column(db.String(64), unique=True, nullable=False, index=True)  # e.g., NL-000001
    agency_hub_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)  # AGENCY/SUB hub creating the needs list
    main_hub_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=True)  # Legacy field, may be null
    event_id = db.Column(db.Integer, db.ForeignKey("disaster_event.id"), nullable=True)
    
    # Status: Draft, Submitted, Fulfilment Prepared, Awaiting Approval, Approved, Dispatched, Received, Completed, Rejected
    status = db.Column(db.String(50), nullable=False, default="Draft")
    priority = db.Column(db.String(20), nullable=False, default="Medium")  # Low, Medium, High, Urgent
    notes = db.Column(db.Text, nullable=True)
    
    # Creation tracking
    created_by = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    
    # Draft tracking (Both Logistics Officer and Manager can save drafts)
    draft_saved_by = db.Column(db.String(200), nullable=True)  # User who last saved draft
    draft_saved_at = db.Column(db.DateTime, nullable=True)  # When draft was last saved
    
    # Fulfilment preparation tracking (Logistics Officer)
    prepared_by = db.Column(db.String(200), nullable=True)  # Logistics Officer who prepared fulfilment
    prepared_at = db.Column(db.DateTime, nullable=True)
    fulfilment_notes = db.Column(db.Text, nullable=True)  # Notes from Logistics Officer
    
    # Approval tracking (Logistics Manager)
    approved_by = db.Column(db.String(200), nullable=True)  # Logistics Manager who approved
    approved_at = db.Column(db.DateTime, nullable=True)
    approval_notes = db.Column(db.Text, nullable=True)  # Notes from Logistics Manager
    
    # Dispatch tracking (Logistics Officer/Manager) - Uses FK for referential integrity
    dispatched_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # User who dispatched items
    dispatched_at = db.Column(db.DateTime, nullable=True)  # When items were dispatched
    dispatch_notes = db.Column(db.Text, nullable=True)  # Notes from dispatcher
    
    # Receipt tracking (Agency Hub) - Uses FK for referential integrity
    received_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # Agency user who confirmed receipt
    received_at = db.Column(db.DateTime, nullable=True)  # When receipt was confirmed
    receipt_notes = db.Column(db.Text, nullable=True)  # Notes from agency on receipt
    
    # Fulfilment completion tracking
    fulfilled_at = db.Column(db.DateTime, nullable=True)
    
    # Legacy review fields (deprecated but kept for backward compatibility)
    reviewed_by = db.Column(db.String(200), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    
    # Concurrency control for fulfilment editing (Logistics Officers/Managers)
    locked_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)  # User currently editing
    locked_at = db.Column(db.DateTime, nullable=True)  # When lock was acquired/extended
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    agency_hub = db.relationship("Depot", foreign_keys=[agency_hub_id])
    main_hub = db.relationship("Depot", foreign_keys=[main_hub_id])
    event = db.relationship("DisasterEvent")
    dispatched_by_user = db.relationship("User", foreign_keys=[dispatched_by_id])
    received_by_user = db.relationship("User", foreign_keys=[received_by_id])
    locked_by_user = db.relationship("User", foreign_keys=[locked_by_id])  # User holding the edit lock
    items = db.relationship("NeedsListItem", back_populates="needs_list", cascade="all, delete-orphan")
    fulfilments = db.relationship("NeedsListFulfilment", back_populates="needs_list", cascade="all, delete-orphan")
    change_requests = db.relationship("FulfilmentChangeRequest", back_populates="needs_list", cascade="all, delete-orphan")
    fulfilment_versions = db.relationship("NeedsListFulfilmentVersion", back_populates="needs_list", cascade="all, delete-orphan")

class NeedsListItem(db.Model):
    """Items requested in an agency/sub hub's needs list"""
    __tablename__ = 'needs_list_item'
    id = db.Column(db.Integer, primary_key=True)
    needs_list_id = db.Column(db.Integer, db.ForeignKey("needs_list.id"), nullable=False)
    item_sku = db.Column(db.String(64), db.ForeignKey("item.sku"), nullable=False)
    requested_qty = db.Column(db.Integer, nullable=False)
    justification = db.Column(db.Text, nullable=True)  # Why this item is needed
    
    needs_list = db.relationship("NeedsList", back_populates="items")
    item = db.relationship("Item")

class NeedsListFulfilment(db.Model):
    """Fulfilment allocations for needs list items - tracks which source hubs will supply which quantities"""
    __tablename__ = 'needs_list_fulfilment'
    id = db.Column(db.Integer, primary_key=True)
    needs_list_id = db.Column(db.Integer, db.ForeignKey("needs_list.id"), nullable=False)
    item_sku = db.Column(db.String(64), db.ForeignKey("item.sku"), nullable=False)
    source_hub_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)  # MAIN or SUB hub supplying stock
    allocated_qty = db.Column(db.Integer, nullable=False)  # Quantity to be supplied from this source
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    needs_list = db.relationship("NeedsList", back_populates="fulfilments")
    item = db.relationship("Item")
    source_hub = db.relationship("Depot")

class FulfilmentChangeRequest(db.Model):
    """Requests from Warehouse users to modify approved fulfilment allocations"""
    __tablename__ = 'fulfilment_change_request'
    __table_args__ = (
        db.Index('idx_change_request_status_created', 'status', 'created_at'),
        db.Index('idx_change_request_needs_list', 'needs_list_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    needs_list_id = db.Column(db.Integer, db.ForeignKey("needs_list.id"), nullable=False)
    requesting_hub_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)  # Sub-Hub where request originates
    requested_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)  # Warehouse Supervisor/Officer
    request_comments = db.Column(db.Text, nullable=False)  # Why change is needed
    status = db.Column(db.String(50), nullable=False, default="Pending Review")  # Pending Review, In Progress, Approved & Resent, Rejected, Clarification Needed
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # Logistics Officer/Manager who processed
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_comments = db.Column(db.Text, nullable=True)  # Logistics team response
    
    needs_list = db.relationship("NeedsList", back_populates="change_requests")
    requesting_hub = db.relationship("Depot", foreign_keys=[requesting_hub_id])
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])

class NeedsListFulfilmentVersion(db.Model):
    """Audit trail for fulfilment adjustments with before/after snapshots"""
    __tablename__ = 'needs_list_fulfilment_version'
    __table_args__ = (
        db.UniqueConstraint('needs_list_id', 'version_number', name='uq_needs_list_version'),
        db.Index('idx_version_needs_list', 'needs_list_id'),
        db.Index('idx_version_change_request', 'change_request_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    needs_list_id = db.Column(db.Integer, db.ForeignKey("needs_list.id"), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)  # Sequential version per needs_list
    change_request_id = db.Column(db.Integer, db.ForeignKey("fulfilment_change_request.id"), nullable=True)  # Nullable for proactive adjustments
    
    adjusted_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    adjusted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    adjustment_reason = db.Column(db.Text, nullable=False)
    
    fulfilment_snapshot_before = db.Column(db.JSON, nullable=False)  # Before state
    fulfilment_snapshot_after = db.Column(db.JSON, nullable=False)  # After state
    status_before = db.Column(db.String(50), nullable=False)  # Needs list status before
    status_after = db.Column(db.String(50), nullable=False)  # Needs list status after
    
    needs_list = db.relationship("NeedsList", back_populates="fulfilment_versions")
    change_request = db.relationship("FulfilmentChangeRequest")
    adjusted_by = db.relationship("User", lazy='joined')

class FulfilmentEditLog(db.Model):
    """Audit trail for post-completion fulfilment edits (after receipt confirmation)
    
    This model tracks corrections to completed needs lists made by Logistics staff
    after the requesting hub has confirmed receipt. Unlike NeedsListFulfilmentVersion
    which tracks pre-approval allocation adjustments, this tracks post-completion
    corrections to delivered quantities, references, notes, or delivery metadata.
    """
    __tablename__ = 'fulfilment_edit_log'
    __table_args__ = (
        db.Index('idx_edit_log_needs_list', 'needs_list_id'),
        db.Index('idx_edit_log_edited_at', 'edited_at'),
        db.Index('idx_edit_log_session', 'edit_session_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    needs_list_id = db.Column(db.Integer, db.ForeignKey("needs_list.id"), nullable=False)
    fulfilment_id = db.Column(db.Integer, db.ForeignKey("needs_list_fulfilment.id"), nullable=True)  # Specific fulfilment line item edited (null for needs-list level edits)
    
    # Edit session grouping - multiple field edits from same save action share same session_id
    edit_session_id = db.Column(db.String(64), nullable=False, index=True)  # UUID to group related edits
    
    edited_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    edited_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # What was edited
    field_name = db.Column(db.String(100), nullable=False)  # e.g., 'allocated_qty', 'dispatch_notes', 'dispatched_at'
    value_before = db.Column(db.Text, nullable=True)
    value_after = db.Column(db.Text, nullable=True)
    
    # Context
    edit_reason = db.Column(db.Text, nullable=True)  # Why this correction was needed
    
    needs_list = db.relationship("NeedsList")
    fulfilment = db.relationship("NeedsListFulfilment")
    edited_by = db.relationship("User", lazy='joined')

# ---------- Flask-Login Configuration ----------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "warning"

# ---------- Jinja2 Template Filters for Date/Time Formatting ----------
app.jinja_env.filters['format_date'] = format_date
app.jinja_env.filters['format_datetime'] = format_datetime
app.jinja_env.filters['format_datetime_full'] = format_datetime_full
app.jinja_env.filters['format_time'] = format_time
app.jinja_env.filters['format_datetime_iso_est'] = format_datetime_iso_est
app.jinja_env.filters['format_relative_time'] = format_relative_time

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------- Role Constants (New Governance Model) ----------
# Current active roles aligned with governance model
ROLE_ADMIN = "ADMIN"
ROLE_LOGISTICS_MANAGER = "LOGISTICS_MANAGER"
ROLE_LOGISTICS_OFFICER = "LOGISTICS_OFFICER"
ROLE_MAIN_HUB_USER = "MAIN_HUB_USER"
ROLE_SUB_HUB_USER = "SUB_HUB_USER"
ROLE_AGENCY_HUB_USER = "AGENCY_HUB_USER"
ROLE_AUDITOR = "AUDITOR"
ROLE_INVENTORY_CLERK = "INVENTORY_CLERK"

# Legacy roles (deprecated - kept for backwards compatibility during transition)
ROLE_WAREHOUSE_STAFF = "WAREHOUSE_STAFF"
ROLE_WAREHOUSE_SUPERVISOR = "WAREHOUSE_SUPERVISOR"
ROLE_WAREHOUSE_OFFICER = "WAREHOUSE_OFFICER"
ROLE_FIELD_PERSONNEL = "FIELD_PERSONNEL"
ROLE_EXECUTIVE = "EXECUTIVE"

ALL_ROLES = [
    ROLE_ADMIN,
    ROLE_LOGISTICS_MANAGER,
    ROLE_LOGISTICS_OFFICER,
    ROLE_MAIN_HUB_USER,
    ROLE_SUB_HUB_USER,
    ROLE_AGENCY_HUB_USER,
    ROLE_AUDITOR,
    ROLE_INVENTORY_CLERK
]

# ---------- Utility ----------
def is_safe_url(target):
    """Validate that a redirect URL is safe (internal to the application)"""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def role_required(*allowed_roles):
    """Decorator to restrict access to specific roles - supports new role structure"""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("login"))
            
            # Check new role structure (user_roles many-to-many)
            user_roles = current_user.roles  # This is a list of role codes
            has_permission = any(role in allowed_roles for role in user_roles)
            
            # Backwards compatibility: check legacy role field if new structure empty
            if not user_roles and current_user.role:
                has_permission = current_user.role in allowed_roles
            
            if not has_permission:
                flash("You don't have permission to access this page.", "danger")
                return redirect(url_for("dashboard"))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def normalize_name(s: str) -> str:
    return " ".join((s or "").strip().lower().split())

def generate_sku() -> str:
    """Generate a unique SKU for an item"""
    while True:
        # Generate format: ITM-XXXXXX where X is alphanumeric
        sku = f"ITM-{secrets.token_hex(3).upper()}"
        # Check if SKU already exists
        if not Item.query.filter_by(sku=sku).first():
            return sku

def get_stock_query():
    # Stock = sum(IN) - sum(OUT) grouped by item
    stock_expr = func.sum(
        case((Transaction.ttype == "IN", Transaction.qty), else_=-Transaction.qty)
    ).label("stock")
    return db.session.query(Item, stock_expr).join(Transaction, Item.sku == Transaction.item_sku, isouter=True).group_by(Item.sku)

def get_stock_by_location():
    # Returns dict: {(item_sku, location_id): stock_qty}
    stock_expr = func.sum(
        case((Transaction.ttype == "IN", Transaction.qty), else_=-Transaction.qty)
    ).label("stock")
    rows = db.session.query(
        Transaction.item_sku,
        Transaction.location_id,
        stock_expr
    ).group_by(Transaction.item_sku, Transaction.location_id).all()
    
    return {(item_sku, loc_id): stock for item_sku, loc_id, stock in rows}

# ---------- Role-Based Dashboard Context Builders ----------

def get_dashboard_context(user):
    """
    Central dashboard context builder that routes to role-specific builders.
    Returns a dictionary with dashboard data tailored to the user's role and permissions.
    
    Args:
        user: Current user object with role and hub assignments
        
    Returns:
        dict: Dashboard context with role-specific metrics, tables, and actions
    """
    from datetime import datetime, timedelta, date
    
    # Determine primary role (users can have multiple roles, prioritize in order)
    role_priority = [
        ROLE_ADMIN,
        ROLE_LOGISTICS_MANAGER,
        ROLE_LOGISTICS_OFFICER,
        ROLE_MAIN_HUB_USER,
        ROLE_SUB_HUB_USER,
        ROLE_AGENCY_HUB_USER,
        ROLE_AUDITOR,
        ROLE_INVENTORY_CLERK
    ]
    
    primary_role = None
    
    # Check new role structure (user_roles many-to-many)
    for role in role_priority:
        if user.has_role(role):
            primary_role = role
            break
    
    # Backwards compatibility: check legacy role field if new structure empty
    if not primary_role and user.role:
        # Map legacy roles to modern equivalents
        legacy_role_mapping = {
            'WAREHOUSE_SUPERVISOR': ROLE_SUB_HUB_USER,
            'WAREHOUSE_OFFICER': ROLE_MAIN_HUB_USER,
            'WAREHOUSE_STAFF': ROLE_INVENTORY_CLERK,
            'FIELD_PERSONNEL': ROLE_AGENCY_HUB_USER,
            'EXECUTIVE': ROLE_AUDITOR
        }
        
        # Try direct match first (for roles that exist in both systems)
        if user.role in role_priority:
            primary_role = user.role
        # Then try legacy mapping
        elif user.role in legacy_role_mapping:
            primary_role = legacy_role_mapping[user.role]
    
    # Route to appropriate dashboard builder
    if primary_role == ROLE_ADMIN:
        return build_system_administrator_dashboard(user)
    elif primary_role == ROLE_LOGISTICS_MANAGER:
        return build_logistics_manager_dashboard(user)
    elif primary_role == ROLE_LOGISTICS_OFFICER:
        return build_logistics_officer_dashboard(user)
    elif primary_role == ROLE_MAIN_HUB_USER:
        return build_main_hub_dashboard(user)
    elif primary_role == ROLE_SUB_HUB_USER:
        return build_sub_hub_dashboard(user)
    elif primary_role == ROLE_AGENCY_HUB_USER:
        return build_agency_hub_dashboard(user)
    elif primary_role == ROLE_AUDITOR:
        return build_auditor_dashboard(user)
    elif primary_role == ROLE_INVENTORY_CLERK:
        return build_inventory_clerk_dashboard(user)
    else:
        # Fallback to basic view
        return build_basic_dashboard(user)

def build_logistics_manager_dashboard(user):
    """
    Build dashboard context for Logistics Manager role.
    Full visibility of government hubs, needs lists, and stock.
    Compact, modern design with national overview.
    """
    from datetime import datetime, timedelta, date
    
    context = {'role': 'Logistics Manager', 'template': 'logistics_manager'}
    
    # Hub queries
    main_hubs = Depot.query.filter_by(hub_type='MAIN').all()
    sub_hubs = Depot.query.filter_by(hub_type='SUB').all()
    agency_hubs = Depot.query.filter_by(hub_type='AGENCY').all()
    
    # Active/Inactive counts by hub type
    main_active = sum(1 for h in main_hubs if h.status == 'Active')
    main_inactive = len(main_hubs) - main_active
    sub_active = sum(1 for h in sub_hubs if h.status == 'Active')
    sub_inactive = len(sub_hubs) - sub_active
    agency_active = sum(1 for h in agency_hubs if h.status == 'Active')
    agency_inactive = len(agency_hubs) - agency_active
    
    # Open Needs Lists count (Submitted + Fulfilment Prepared + Awaiting Approval)
    open_needs_count = NeedsList.query.filter(
        NeedsList.status.in_(['Submitted', 'Fulfilment Prepared', 'Awaiting Approval'])
    ).count()
    
    # Government stock summary (Main + Sub hubs only, exclude Agency)
    government_hubs = [h for h in main_hubs + sub_hubs if h.status == 'Active']
    stock_map = get_stock_by_location()
    all_items = Item.query.all()
    total_stock_units = 0
    
    # Compact KPI Cards
    context['kpi_cards'] = {
        'main_hubs_active': main_active,
        'main_hubs_total': len(main_hubs),
        'sub_hubs_active': sub_active,
        'sub_hubs_total': len(sub_hubs),
        'agency_hubs_active': agency_active,
        'agency_hubs_total': len(agency_hubs),
        'total_gov_stock': 0,
        'open_needs_lists': open_needs_count
    }
    
    # Hub Status & Stock Overview (Main + Sub only)
    hub_overview = []
    category_totals = {}
    
    for hub in main_hubs + sub_hubs:
        hub_total = 0
        last_activity = None
        
        # Calculate stock at this hub
        for item in all_items:
            qty = stock_map.get((item.sku, hub.id), 0)
            hub_total += qty
            
            # Track category totals (only for active gov hubs)
            if hub.status == 'Active' and qty > 0:
                cat = item.category or 'Uncategorized'
                category_totals[cat] = category_totals.get(cat, 0) + qty
        
        # Add to government stock total (active hubs only)
        if hub.status == 'Active':
            total_stock_units += hub_total
        
        # Find last transaction at this hub
        last_txn = Transaction.query.filter_by(location_id=hub.id)\
                                    .order_by(Transaction.created_at.desc()).first()
        
        if last_txn:
            last_activity = last_txn.created_at
        
        hub_overview.append({
            'id': hub.id,
            'name': hub.name,
            'hub_type': hub.hub_type,
            'status': hub.status,
            'stock_count': hub_total,
            'last_activity': last_activity
        })
    
    # Sort: Main first, then Sub; then by name
    hub_overview.sort(key=lambda x: (0 if x['hub_type'] == 'MAIN' else 1, x['name']))
    
    context['kpi_cards']['total_gov_stock'] = total_stock_units
    context['hub_overview'] = hub_overview
    
    # Active vs Inactive Hub Snapshot
    context['hub_status_summary'] = {
        'main': {'active': main_active, 'inactive': main_inactive},
        'sub': {'active': sub_active, 'inactive': sub_inactive},
        'agency': {'active': agency_active, 'inactive': agency_inactive}
    }
    
    # Category Distribution (for chart)
    context['category_distribution'] = sorted(
        [{'category': k, 'total': v} for k, v in category_totals.items()],
        key=lambda x: x['total'],
        reverse=True
    )
    
    # Needs Lists requiring review/approval
    context['needs_lists_queue'] = {
        'submitted': NeedsList.query.filter_by(status='Submitted')\
                              .order_by(NeedsList.submitted_at.asc()).limit(10).all(),
        'fulfilment_prepared': NeedsList.query.filter_by(status='Fulfilment Prepared')\
                                        .order_by(NeedsList.prepared_at.asc()).limit(10).all(),
        'awaiting_approval': NeedsList.query.filter_by(status='Awaiting Approval')\
                                       .order_by(NeedsList.prepared_at.asc()).limit(10).all()
    }
    
    # Recent approvals/rejections (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    context['recent_decisions'] = {
        'approved': NeedsList.query.filter(
            NeedsList.status.in_(['Approved', 'Dispatched', 'Received', 'Completed']),
            NeedsList.approved_at >= thirty_days_ago
        ).order_by(NeedsList.approved_at.desc()).limit(10).all(),
        'rejected': NeedsList.query.filter_by(status='Rejected')\
                             .filter(NeedsList.approved_at >= thirty_days_ago)\
                             .order_by(NeedsList.approved_at.desc()).limit(5).all()
    }
    
    return context

def build_logistics_officer_dashboard(user):
    """
    Build dashboard context for Logistics Officer role.
    Focus on needs lists to review and prepare fulfilment for.
    """
    from datetime import datetime, timedelta
    
    context = {'role': 'Logistics Officer', 'template': 'logistics_officer'}
    
    # Needs Lists awaiting review (Submitted status)
    submitted_lists = NeedsList.query.filter_by(status='Submitted')\
                               .order_by(NeedsList.submitted_at.asc()).all()
    
    # Needs Lists with prepared fulfilment (pending LM approval)
    prepared_lists = NeedsList.query.filter_by(status='Fulfilment Prepared')\
                              .order_by(NeedsList.prepared_at.desc()).all()
    
    awaiting_approval = NeedsList.query.filter_by(status='Awaiting Approval')\
                                 .order_by(NeedsList.prepared_at.desc()).all()
    
    context['cards'] = {
        'submitted_count': len(submitted_lists),
        'prepared_count': len(prepared_lists),
        'awaiting_count': len(awaiting_approval),
        'my_prepared_count': NeedsList.query.filter(
            NeedsList.prepared_by == user.display_name,
            NeedsList.status.in_(['Fulfilment Prepared', 'Awaiting Approval', 'Approved'])
        ).count()
    }
    
    # Queue of needs lists to work on
    context['work_queues'] = {
        'submitted': submitted_lists[:15],
        'fulfilment_prepared': prepared_lists[:10],
        'awaiting_approval': awaiting_approval[:10]
    }
    
    # Recent activity by this officer
    my_recent = NeedsList.query.filter_by(prepared_by=user.display_name)\
                         .order_by(NeedsList.prepared_at.desc()).limit(10).all()
    
    context['my_recent_work'] = my_recent
    
    # Government stock availability (for fulfilment planning)
    stock_map = get_stock_by_location()
    government_hubs = Depot.query.filter(Depot.hub_type.in_(['MAIN', 'SUB'])).all()
    
    total_stock = sum(
        stock_map.get((item.sku, hub.id), 0)
        for item in Item.query.all()
        for hub in government_hubs
    )
    
    context['stock_overview'] = {
        'total_units': total_stock,
        'government_hubs_count': len(government_hubs)
    }
    
    return context

def build_main_hub_dashboard(user):
    """
    Build dashboard context for Main Hub User role.
    Scoped to their Main Hub + visibility of linked Sub-Hub requests.
    """
    from datetime import datetime, timedelta
    
    context = {'role': 'Main Hub User', 'template': 'main_hub'}
    
    # Verify user is assigned to a MAIN hub
    if not user.assigned_location_id:
        context['error'] = "You must be assigned to a hub."
        return context
    
    main_hub = Depot.query.get(user.assigned_location_id)
    if not main_hub or main_hub.hub_type != 'MAIN':
        context['error'] = "Main Hub dashboard requires assignment to a MAIN hub."
        return context
    
    context['hub'] = main_hub
    
    # Current stock at Main Hub
    stock_map = get_stock_by_location()
    items = Item.query.all()
    hub_stock = []
    total_stock_value = 0
    low_stock_count = 0
    
    for item in items:
        stock = stock_map.get((item.sku, main_hub.id), 0)
        if stock > 0:
            is_low = stock < (item.min_qty or 10)
            if is_low:
                low_stock_count += 1
            hub_stock.append({
                'item': item,
                'stock': stock,
                'is_low': is_low
            })
            total_stock_value += stock
    
    context['cards'] = {
        'total_stock': total_stock_value,
        'low_stock_count': low_stock_count,
        'unique_items': len([s for s in hub_stock if s['stock'] > 0])
    }
    
    # Needs Lists involving this Main Hub
    # As a source hub in fulfilments
    needs_lists_as_source = db.session.query(NeedsList).join(
        NeedsListFulfilment, NeedsList.id == NeedsListFulfilment.needs_list_id
    ).filter(
        NeedsListFulfilment.source_hub_id == main_hub.id,
        NeedsList.status.in_(['Approved', 'Resent for Dispatch'])
    ).distinct().order_by(NeedsList.approved_at.desc()).all()
    
    context['cards']['pending_dispatches'] = len(needs_lists_as_source)
    
    # Linked Sub-Hubs (those reporting to this Main Hub)
    linked_sub_hubs = Depot.query.filter_by(
        parent_location_id=main_hub.id,
        hub_type='SUB'
    ).all()
    
    context['cards']['linked_sub_hubs'] = len(linked_sub_hubs)
    
    # Needs Lists from linked hubs
    sub_hub_requests = NeedsList.query.filter(
        NeedsList.agency_hub_id.in_([h.id for h in linked_sub_hubs])
    ).order_by(NeedsList.created_at.desc()).limit(15).all()
    
    context['work_queues'] = {
        'ready_to_dispatch': needs_lists_as_source[:10],
        'sub_hub_requests': sub_hub_requests
    }
    
    context['hub_stock'] = sorted(hub_stock, key=lambda x: x['stock'], reverse=True)[:20]
    context['linked_hubs'] = linked_sub_hubs
    
    return context

def build_sub_hub_dashboard(user):
    """
    Build dashboard context for Sub-Hub User role.
    Strictly scoped to their own Sub-Hub.
    """
    from datetime import datetime, timedelta
    
    context = {'role': 'Sub-Hub User', 'template': 'sub_hub'}
    
    # Verify user is assigned to a SUB hub
    if not user.assigned_location_id:
        context['error'] = "You must be assigned to a hub."
        return context
    
    sub_hub = Depot.query.get(user.assigned_location_id)
    if not sub_hub or sub_hub.hub_type != 'SUB':
        context['error'] = "Sub-Hub dashboard requires assignment to a SUB hub."
        return context
    
    context['hub'] = sub_hub
    
    # Current stock at Sub-Hub
    stock_map = get_stock_by_location()
    items = Item.query.all()
    hub_stock = []
    total_stock_value = 0
    low_stock_count = 0
    
    for item in items:
        stock = stock_map.get((item.sku, sub_hub.id), 0)
        if stock > 0:
            is_low = stock < (item.min_qty or 10)
            if is_low:
                low_stock_count += 1
            hub_stock.append({
                'item': item,
                'stock': stock,
                'is_low': is_low
            })
            total_stock_value += stock
    
    # Own Needs Lists
    own_needs_lists = NeedsList.query.filter_by(agency_hub_id=sub_hub.id)\
                               .order_by(NeedsList.created_at.desc()).all()
    
    draft_count = sum(1 for nl in own_needs_lists if nl.status == 'Draft')
    submitted_count = sum(1 for nl in own_needs_lists if nl.status == 'Submitted')
    in_progress_count = sum(1 for nl in own_needs_lists if nl.status in ['Fulfilment Prepared', 'Awaiting Approval', 'Approved'])
    
    context['cards'] = {
        'total_stock': total_stock_value,
        'low_stock_count': low_stock_count,
        'draft_lists': draft_count,
        'submitted_lists': submitted_count,
        'in_progress_lists': in_progress_count
    }
    
    # Ready to dispatch (Approved needs lists where this hub is a source)
    ready_to_dispatch = db.session.query(NeedsList).join(
        NeedsListFulfilment, NeedsList.id == NeedsListFulfilment.needs_list_id
    ).filter(
        NeedsList.status.in_(['Approved', 'Resent for Dispatch']),
        NeedsListFulfilment.source_hub_id == sub_hub.id
    ).distinct().order_by(NeedsList.approved_at.desc()).all()
    
    context['cards']['ready_to_dispatch'] = len(ready_to_dispatch)
    
    # Recent dispatch activity (last 14 days)
    fourteen_days_ago = datetime.utcnow() - timedelta(days=14)
    recent_dispatches = db.session.query(NeedsList).join(
        NeedsListFulfilment, NeedsList.id == NeedsListFulfilment.needs_list_id
    ).filter(
        NeedsList.status == 'Dispatched',
        NeedsList.dispatched_at >= fourteen_days_ago,
        NeedsListFulfilment.source_hub_id == sub_hub.id
    ).distinct().order_by(NeedsList.dispatched_at.desc()).all()
    
    context['work_queues'] = {
        'own_needs_lists': own_needs_lists[:10],
        'ready_to_dispatch': ready_to_dispatch[:10],
        'recent_dispatches': recent_dispatches
    }
    
    context['hub_stock'] = sorted(hub_stock, key=lambda x: x['stock'], reverse=True)[:20]
    
    # Pending incoming transfers
    pending_transfers = NeedsList.query.filter(
        NeedsList.agency_hub_id == sub_hub.id,
        NeedsList.status.in_(['Approved', 'Dispatched'])
    ).order_by(NeedsList.created_at.desc()).limit(10).all()
    
    context['pending_transfers'] = pending_transfers
    
    return context

def build_agency_hub_dashboard(user):
    """
    Build dashboard context for Agency Hub User role.
    Scoped to their agency's requests and allocations only.
    Agency hubs do NOT see government internal stock or fulfilment details.
    """
    from datetime import datetime, timedelta
    
    context = {'role': 'Agency Hub User', 'template': 'agency_hub'}
    
    # Default KPI cards for error states
    default_kpi = {
        'needs_lists_submitted': 0,
        'approved_vs_pending_approved': 0,
        'approved_vs_pending_pending': 0,
        'total_allocations': 0,
        'last_allocation_date': None
    }
    context['kpi_cards'] = default_kpi.copy()
    context['work_queues'] = {'my_needs_lists': [], 'transfers_received': []}
    
    # Verify user is assigned to an AGENCY hub
    if not user.assigned_location_id:
        context['error'] = "You must be assigned to a hub."
        return context
    
    agency_hub = Depot.query.get(user.assigned_location_id)
    if not agency_hub or agency_hub.hub_type != 'AGENCY':
        context['error'] = "Agency Hub dashboard requires assignment to an AGENCY hub."
        return context
    
    context['hub'] = agency_hub
    
    # Needs Lists submitted by this agency (no fulfilment details exposed)
    agency_needs_lists = NeedsList.query.filter_by(agency_hub_id=agency_hub.id)\
                                  .order_by(NeedsList.created_at.desc()).all()
    
    submitted_count = sum(1 for nl in agency_needs_lists if nl.status == 'Submitted')
    approved_count = sum(1 for nl in agency_needs_lists if nl.status in ['Approved', 'Dispatched', 'Received', 'Completed'])
    pending_count = sum(1 for nl in agency_needs_lists if nl.status in ['Fulfilment Prepared', 'Awaiting Approval'])
    
    # Last allocation received (dispatched means sent to agency, no gov hub details)
    last_allocation = NeedsList.query.filter_by(agency_hub_id=agency_hub.id)\
                               .filter(NeedsList.status.in_(['Dispatched', 'Received', 'Completed']))\
                               .order_by(NeedsList.dispatched_at.desc()).first()
    
    last_allocation_date = last_allocation.dispatched_at if last_allocation and last_allocation.dispatched_at else None
    
    # Total allocations received (completed needs lists)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    total_allocations = NeedsList.query.filter(
        NeedsList.agency_hub_id == agency_hub.id,
        NeedsList.status.in_(['Received', 'Completed']),
        NeedsList.received_at.isnot(None),
        NeedsList.received_at >= thirty_days_ago
    ).count()
    
    context['kpi_cards'] = {
        'needs_lists_submitted': submitted_count,
        'approved_vs_pending_approved': approved_count,
        'approved_vs_pending_pending': pending_count,
        'total_allocations': total_allocations,
        'last_allocation_date': last_allocation_date
    }
    
    # Work queues - Convert to DTOs to prevent accessing government fulfilment data
    # DTOs are simple dicts without ORM relationships
    my_needs_lists_dto = []
    for nl in agency_needs_lists[:15]:
        my_needs_lists_dto.append({
            'id': nl.id,
            'list_number': nl.list_number,
            'status': nl.status,
            'created_at': nl.created_at,
            'submitted_at': nl.submitted_at,
            'dispatched_at': nl.dispatched_at
        })
    
    transfers_received_query = NeedsList.query.filter(
        NeedsList.agency_hub_id == agency_hub.id,
        NeedsList.status.in_(['Dispatched', 'Received'])
    ).order_by(NeedsList.dispatched_at.desc()).limit(10).all()
    
    transfers_received_dto = []
    for nl in transfers_received_query:
        transfers_received_dto.append({
            'id': nl.id,
            'list_number': nl.list_number,
            'status': nl.status,
            'dispatched_at': nl.dispatched_at
        })
    
    context['work_queues'] = {
        'my_needs_lists': my_needs_lists_dto,
        'transfers_received': transfers_received_dto
    }
    
    return context

def build_inventory_clerk_dashboard(user):
    """
    Build dashboard context for Inventory Clerk role.
    Operational dashboard focused on daily intake/distribution at assigned hub.
    """
    from datetime import datetime, date
    
    context = {'role': 'Inventory Clerk', 'template': 'inventory_clerk'}
    
    # Verify user is assigned to a hub
    if not user.assigned_location_id:
        context['error'] = "You must be assigned to a hub."
        return context
    
    clerk_hub = Depot.query.get(user.assigned_location_id)
    if not clerk_hub:
        context['error'] = "Invalid hub assignment."
        return context
    
    context['hub'] = clerk_hub
    
    # Today's transactions
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    todays_intakes = Transaction.query.filter(
        Transaction.location_id == clerk_hub.id,
        Transaction.ttype == 'IN',
        Transaction.created_at >= today_start,
        Transaction.created_at <= today_end
    ).all()
    
    todays_distributions = Transaction.query.filter(
        Transaction.location_id == clerk_hub.id,
        Transaction.ttype == 'OUT',
        Transaction.created_at >= today_start,
        Transaction.created_at <= today_end
    ).all()
    
    # Current stock
    stock_map = get_stock_by_location()
    items = Item.query.all()
    stock_lines_count = sum(1 for item in items if stock_map.get((item.sku, clerk_hub.id), 0) > 0)
    
    context['kpi_cards'] = {
        'todays_intakes': sum(t.qty for t in todays_intakes),
        'todays_distributions': sum(t.qty for t in todays_distributions),
        'stock_lines': stock_lines_count,
        'pending_entries': 0  # Placeholder for future feature
    }
    
    # Recent transactions
    recent_transactions = Transaction.query.filter_by(location_id=clerk_hub.id)\
                                     .order_by(Transaction.created_at.desc()).limit(20).all()
    
    context['recent_transactions'] = recent_transactions
    
    return context

def build_auditor_dashboard(user):
    """
    Build dashboard context for Auditor/M&E Officer role.
    Read-only oversight with fulfilment metrics and exception tracking.
    """
    from datetime import datetime, timedelta
    
    context = {'role': 'Auditor', 'template': 'auditor'}
    
    # Default KPI cards for error states
    context['kpi_cards'] = {
        'total_needs_lists': 0,
        'approved_fulfilled_approved': 0,
        'approved_fulfilled_fulfilled': 0,
        'on_time_percentage': 0,
        'total_items_dispatched': 0,
        'active_hubs': 0
    }
    context['fulfilment_log'] = []
    context['exceptions'] = []
    
    # Date range for metrics (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # Needs Lists metrics
    total_needs_lists = NeedsList.query.count()
    approved_lists = NeedsList.query.filter(
        NeedsList.status.in_(['Approved', 'Dispatched', 'Received', 'Completed'])
    ).count()
    fulfilled_lists = NeedsList.query.filter_by(status='Completed').count()
    
    # On-time fulfilment (simplified: within 14 days of submission)
    # Guard against missing timestamps
    on_time_count = NeedsList.query.filter(
        NeedsList.status == 'Completed',
        NeedsList.fulfilled_at.isnot(None),
        NeedsList.submitted_at.isnot(None)
    ).all()
    
    on_time_fulfilled = 0
    for nl in on_time_count:
        try:
            if nl.fulfilled_at and nl.submitted_at and (nl.fulfilled_at - nl.submitted_at).days <= 14:
                on_time_fulfilled += 1
        except (AttributeError, TypeError):
            continue  # Skip if timestamps are invalid
    
    on_time_percentage = round((on_time_fulfilled / len(on_time_count) * 100)) if on_time_count else 0
    
    # Government hubs only (Main + Sub)
    gov_hubs = Depot.query.filter(Depot.hub_type.in_(['MAIN', 'SUB'])).all()
    stock_map = get_stock_by_location()
    total_items_dispatched = sum(
        stock_map.get((item.sku, hub.id), 0)
        for item in Item.query.all()
        for hub in gov_hubs
    )
    
    active_hubs = Depot.query.filter_by(status='Active').count()
    
    context['kpi_cards'] = {
        'total_needs_lists': total_needs_lists,
        'approved_fulfilled_approved': approved_lists,
        'approved_fulfilled_fulfilled': fulfilled_lists,
        'on_time_percentage': on_time_percentage,
        'total_items_dispatched': total_items_dispatched,
        'active_hubs': active_hubs
    }
    
    # Fulfilment log (last 30 days) - guard against missing updated_at
    fulfilment_log = NeedsList.query.filter(
        NeedsList.updated_at.isnot(None),
        NeedsList.updated_at >= thirty_days_ago
    ).order_by(NeedsList.updated_at.desc()).limit(50).all()
    
    # Exceptions (partial fulfilments, change requests, delays)
    exceptions = NeedsList.query.filter(
        db.or_(
            NeedsList.status == 'Resent for Dispatch',
            NeedsList.adjustment_reason.isnot(None)
        )
    ).order_by(NeedsList.updated_at.desc()).limit(20).all()
    
    context['fulfilment_log'] = fulfilment_log
    context['exceptions'] = exceptions
    
    return context

def build_system_administrator_dashboard(user):
    """
    Build dashboard context for System Administrator role.
    Focus on configuration, users, and hubs - no stock/fulfilment metrics.
    """
    from datetime import datetime, timedelta
    
    context = {'role': 'System Administrator', 'template': 'system_administrator'}
    
    # User metrics
    active_users = User.query.filter_by(is_active=True).count()
    total_users = User.query.count()
    
    # Hub metrics
    total_hubs = Depot.query.count()
    active_hubs = Depot.query.filter_by(status='Active').count()
    main_hubs = Depot.query.filter_by(hub_type='MAIN').count()
    sub_hubs = Depot.query.filter_by(hub_type='SUB').count()
    agency_hubs = Depot.query.filter_by(hub_type='AGENCY').count()
    
    # Pending user approvals (placeholder - no approval system yet)
    pending_approvals = 0
    
    context['kpi_cards'] = {
        'active_users': active_users,
        'total_users': total_users,
        'active_hubs': active_hubs,
        'total_hubs': total_hubs,
        'main_hubs': main_hubs,
        'sub_hubs': sub_hubs,
        'agency_hubs': agency_hubs,
        'pending_approvals': pending_approvals
    }
    
    # Recent user changes (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_users = User.query.filter(
        User.created_at >= thirty_days_ago
    ).order_by(User.created_at.desc()).limit(20).all()
    
    # Recent hub changes
    recent_hubs = Depot.query.order_by(Depot.id.desc()).limit(15).all()
    
    context['recent_users'] = recent_users
    context['recent_hubs'] = recent_hubs
    
    return context

def build_basic_dashboard(user):
    """
    Fallback dashboard for roles not yet implemented.
    Shows basic stats only.
    """
    context = {'role': 'Basic', 'template': 'basic'}
    
    context['cards'] = {
        'total_hubs': Depot.query.count(),
        'total_items': Item.query.count(),
        'active_events': DisasterEvent.query.filter_by(status='Active').count()
    }
    
    context['message'] = "Welcome to DRIMS. Your role-specific dashboard is being prepared."
    
    return context

def ensure_seed_data():
    # Seed locations
    if Depot.query.count() == 0:
        for name in ["Kingston & St. Andrew Depot", "St. Catherine Depot", "St. James Depot", "Clarendon Depot"]:
            db.session.add(Depot(name=name))
    # Seed categories via a sample item (not necessary, categories are free text)
    db.session.commit()

# ---------- Distribution Package Helper Functions ----------

def generate_package_number():
    """Generate a unique package number in format PKG-NNNNNN"""
    last_package = DistributionPackage.query.order_by(DistributionPackage.id.desc()).first()
    if last_package:
        last_num = int(last_package.package_number.split('-')[1])
        new_num = last_num + 1
    else:
        new_num = 1
    return f"PKG-{new_num:06d}"

def generate_needs_list_number():
    """Generate a unique needs list number in format NL-NNNNNN"""
    last_list = NeedsList.query.order_by(NeedsList.id.desc()).first()
    if last_list:
        last_num = int(last_list.list_number.split('-')[1])
        new_num = last_num + 1
    else:
        new_num = 1
    return f"NL-{new_num:06d}"

def get_fulfillment_class(fulfillment_rate):
    """Return CSS class token based on fulfillment rate threshold"""
    if fulfillment_rate >= 100:
        return 'text-success'
    elif fulfillment_rate >= 50:
        return 'text-warning'
    else:
        return 'text-danger'


def compute_dispatch_summary(needs_list):
    """
    Compute dispatch summary metrics for Dispatched/Received workflow states
    
    Args:
        needs_list: NeedsList object with eager-loaded fulfilments and items
        
    Returns:
        dict with keys:
            - total_requested_qty: Sum of all requested quantities
            - total_dispatched_qty: Sum of all dispatched quantities (from fulfilments)
            - item_count: Number of distinct items in the needs list
    """
    total_requested_qty = 0
    total_dispatched_qty = 0
    
    # Calculate totals from real backend data
    for item_entry in needs_list.items:
        total_requested_qty += item_entry.requested_qty
        
        # Sum allocated quantities from fulfilments for this item
        # In Dispatched status, allocated_qty represents the actually dispatched quantity
        for fulfilment in needs_list.fulfilments:
            if fulfilment.item_sku == item_entry.item_sku:
                total_dispatched_qty += fulfilment.allocated_qty
    
    return {
        'total_requested_qty': total_requested_qty,
        'total_dispatched_qty': total_dispatched_qty,
        'item_count': len(needs_list.items)
    }

def prepare_completed_context(needs_list, current_user):
    """
    Prepare comprehensive context for completed needs list view
    
    Args:
        needs_list: NeedsList object with fulfilments eagerly loaded
        current_user: Current logged-in user
        
    Returns:
        dict: Context with summary, items, timeline, and role-specific data
    """
    # Calculate summary metrics
    total_items = len(needs_list.items)
    total_requested_qty = 0
    total_dispatched_qty = 0
    items_data = []
    
    # Build per-item details with source hubs
    for item_entry in needs_list.items:
        item_requested = item_entry.requested_qty
        item_dispatched = 0
        source_hubs = []
        
        # Aggregate dispatched quantities from fulfilments
        for fulfilment in needs_list.fulfilments:
            if fulfilment.item_sku == item_entry.item_sku:
                item_dispatched += fulfilment.allocated_qty
                source_hubs.append({
                    'hub_name': fulfilment.source_hub.name,
                    'qty': fulfilment.allocated_qty
                })
        
        total_requested_qty += item_requested
        total_dispatched_qty += item_dispatched
        
        # Calculate item-level metrics
        # For Completed status, received_qty equals dispatched_qty (confirmed by agency)
        item_received = item_dispatched
        item_fulfillment_pct = int((item_received / item_requested * 100)) if item_requested > 0 else 0
        item_shortfall = max(item_requested - item_received, 0)
        
        # Determine fulfilment status
        if item_fulfillment_pct >= 100:
            fulfilment_status = 'Fully Fulfilled'
            status_badge_class = 'text-bg-success'
        elif item_fulfillment_pct > 0:
            fulfilment_status = 'Partially Fulfilled'
            status_badge_class = 'text-bg-warning'
        else:
            fulfilment_status = 'Not Fulfilled'
            status_badge_class = 'text-bg-danger'
        
        items_data.append({
            'item_name': item_entry.item.name,
            'sku': item_entry.item_sku,
            'unit': item_entry.item.unit,
            'requested_qty': item_requested,
            'dispatched_qty': item_dispatched,
            'received_qty': item_received,
            'fulfillment_pct': item_fulfillment_pct,
            'shortfall': item_shortfall,
            'fulfilment_status': fulfilment_status,
            'status_badge_class': status_badge_class,
            'source_hubs': source_hubs,
            'justification': item_entry.justification,
            'has_shortfall': item_shortfall > 0
        })
    
    # Calculate overall metrics
    # For Completed status, total received equals total dispatched
    total_received_qty = total_dispatched_qty
    fulfillment_rate = int((total_received_qty / total_requested_qty * 100)) if total_requested_qty > 0 else 0
    shortfall_qty = max(total_requested_qty - total_received_qty, 0)
    fulfillment_class = get_fulfillment_class(fulfillment_rate)
    
    # Build timeline events from NeedsList fields
    timeline = []
    
    if needs_list.created_at:
        timeline.append({
            'milestone': 'Created',
            'label': 'Needs List Created',
            'timestamp': needs_list.created_at,
            'actor': needs_list.created_by or 'System',
            'notes': None,
            'icon': 'bi-file-earmark-plus'
        })
    
    if needs_list.submitted_at:
        timeline.append({
            'milestone': 'Submitted',
            'label': 'Submitted to ODPEM',
            'timestamp': needs_list.submitted_at,
            'actor': needs_list.created_by or 'System',
            'notes': None,
            'icon': 'bi-send'
        })
    
    if needs_list.prepared_at and needs_list.prepared_by:
        timeline.append({
            'milestone': 'Prepared',
            'label': 'Fulfilment Prepared',
            'timestamp': needs_list.prepared_at,
            'actor': needs_list.prepared_by,
            'notes': needs_list.fulfilment_notes,
            'icon': 'bi-gear'
        })
    
    if needs_list.approved_at and needs_list.approved_by:
        timeline.append({
            'milestone': 'Approved',
            'label': 'Approved by Manager',
            'timestamp': needs_list.approved_at,
            'actor': needs_list.approved_by,
            'notes': needs_list.approval_notes,
            'icon': 'bi-person-check'
        })
    
    if needs_list.dispatched_at:
        dispatcher_name = needs_list.dispatched_by_user.display_name if needs_list.dispatched_by_user else 'System'
        timeline.append({
            'milestone': 'Dispatched',
            'label': 'Items Dispatched',
            'timestamp': needs_list.dispatched_at,
            'actor': dispatcher_name,
            'notes': needs_list.dispatch_notes,
            'icon': 'bi-truck'
        })
    
    if needs_list.received_at:
        receiver_name = needs_list.received_by_user.display_name if needs_list.received_by_user else 'System'
        timeline.append({
            'milestone': 'Received',
            'label': 'Receipt Confirmed',
            'timestamp': needs_list.received_at,
            'actor': receiver_name,
            'notes': needs_list.receipt_notes,
            'icon': 'bi-check-circle'
        })
    
    if needs_list.fulfilled_at:
        timeline.append({
            'milestone': 'Completed',
            'label': 'Workflow Completed',
            'timestamp': needs_list.fulfilled_at,
            'actor': receiver_name if needs_list.received_by_user else 'System',
            'notes': None,
            'icon': 'bi-check-circle-fill'
        })
    
    # Sort timeline chronologically
    timeline.sort(key=lambda x: x['timestamp'])
    
    # Role-specific data
    roles = {
        'agency': {
            'can_download_pdf': current_user.has_any_role(ROLE_ADMIN) or (
                current_user.assigned_location_id and 
                current_user.assigned_location_id == needs_list.agency_hub_id
            ),
            'total_received': total_dispatched_qty,
            'dispatch_sources': list(set([hub['hub_name'] for item in items_data for hub in item['source_hubs']])),
            'confirmed_by': needs_list.received_by_user.display_name if needs_list.received_by_user else None,
            'confirmed_at': needs_list.received_at
        },
        'officer': {
            'approved_qty': total_dispatched_qty,  # In this workflow, what was allocated was what was approved
            'has_discrepancies': shortfall_qty > 0,
            'shortfall_items': [item for item in items_data if item['has_shortfall']],
            'dispatch_details': {
                'dispatcher': needs_list.dispatched_by_user.display_name if needs_list.dispatched_by_user else None,
                'dispatch_date': needs_list.dispatched_at,
                'dispatch_notes': needs_list.dispatch_notes
            }
        },
        'manager': {
            'variance_summary': {
                'requested': total_requested_qty,
                'approved': total_dispatched_qty,  # Allocated = Approved in this workflow
                'dispatched': total_dispatched_qty,
                'received': total_dispatched_qty,  # Assuming received = dispatched for completed status
                'variance': 0  # approved - dispatched
            },
            'full_timeline': timeline,
            'verified_completed': needs_list.status == 'Completed' and needs_list.received_at is not None
        }
    }
    
    return {
        'summary': {
            'total_items': total_items,
            'total_requested_qty': total_requested_qty,
            'total_dispatched_qty': total_dispatched_qty,
            'total_received_qty': total_received_qty,
            'fulfillment_rate': fulfillment_rate,
            'shortfall_qty': shortfall_qty,
            'fulfillment_class': fulfillment_class,
            'dispatch_date': needs_list.dispatched_at,
            'receipt_date': needs_list.received_at,
            'confirmed_by': needs_list.received_by_user.display_name if needs_list.received_by_user else None
        },
        'items': items_data,
        'timeline': timeline,
        'roles': roles
    }

# ---------- Needs List Permission Helpers ----------

def can_view_needs_list(user, needs_list):
    """
    Check if user can view a specific needs list.
    
    Hub-based access control:
    - ADMIN/LOGISTICS: Global visibility
    - SUB_HUB_USER: Can view if their hub is the requesting hub OR a source hub in fulfilments
    - MAIN_HUB_USER: Can view if their hub is the requesting hub OR a source hub in fulfilments
    - AGENCY_HUB_USER: Can only view if their hub is the requesting hub
    - AUDITOR: Global visibility (read-only)
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # ADMIN has full access
    if user.has_role(ROLE_ADMIN):
        return (True, None)
    
    # Logistics Officers and Managers have global visibility
    if user.has_any_role(ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER):
        return (True, None)
    
    # Auditors have global read-only access
    if user.has_role(ROLE_AUDITOR):
        return (True, None)
    
    # Hub-based access control - require hub assignment
    if not user.assigned_location_id:
        return (False, "You must be assigned to a hub to view needs lists.")
    
    user_depot = Depot.query.get(user.assigned_location_id)
    if not user_depot:
        return (False, "Invalid hub assignment.")
    
    # SUB_HUB_USER: Can view if their hub is requesting hub OR a source hub
    if user.has_role(ROLE_SUB_HUB_USER):
        # Check if they own this needs list (are the requesting hub)
        if user_depot.id == needs_list.agency_hub_id:
            return (True, None)
        
        # Check if their hub is a source hub for this needs list
        has_fulfilment = NeedsListFulfilment.query.filter_by(
            needs_list_id=needs_list.id,
            source_hub_id=user.assigned_location_id
        ).first()
        
        if has_fulfilment:
            return (True, None)
        
        return (False, "You can only view needs lists where your hub is involved.")
    
    # MAIN_HUB_USER: Can view if their hub is requesting hub OR a source hub
    if user.has_role(ROLE_MAIN_HUB_USER):
        # Check if they own this needs list
        if user_depot.id == needs_list.agency_hub_id:
            return (True, None)
        
        # Check if their hub is a source hub for this needs list
        has_fulfilment = NeedsListFulfilment.query.filter_by(
            needs_list_id=needs_list.id,
            source_hub_id=user.assigned_location_id
        ).first()
        
        if has_fulfilment:
            return (True, None)
        
        return (False, "You can only view needs lists where your hub is involved.")
    
    # AGENCY_HUB_USER: Can only view their own needs lists
    if user.has_role(ROLE_AGENCY_HUB_USER):
        if user_depot.id == needs_list.agency_hub_id:
            return (True, None)
        return (False, "You can only view needs lists from your agency hub.")
    
    # Fallback for any other hub-based users (legacy compatibility)
    if user_depot.id == needs_list.agency_hub_id:
        return (True, None)
    
    return (False, "You don't have permission to view this needs list.")

def can_edit_needs_list(user, needs_list):
    """
    Check if user can edit a needs list (only Draft status, only owning hub).
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Only draft needs lists can be edited
    if needs_list.status != 'Draft':
        return (False, "Only draft needs lists can be edited.")
    
    # ADMIN can edit
    if user.has_role(ROLE_ADMIN):
        return (True, None)
    
    # Only the owning hub can edit their draft
    if user.assigned_location_id:
        user_depot = Depot.query.get(user.assigned_location_id)
        if user_depot and user_depot.id == needs_list.agency_hub_id:
            return (True, None)
    
    return (False, "Only the owning hub can edit this needs list.")

def can_submit_needs_list(user, needs_list):
    """
    Check if user can submit a draft needs list for logistics review.
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Must be in Draft status
    if needs_list.status != 'Draft':
        return (False, "Only draft needs lists can be submitted.")
    
    # ADMIN can submit
    if user.has_role(ROLE_ADMIN):
        return (True, None)
    
    # Only SUB/AGENCY hub users from the owning hub can submit
    if not user.assigned_location_id:
        return (False, "You must be assigned to a hub to submit needs lists.")
    
    user_depot = Depot.query.get(user.assigned_location_id)
    if not user_depot:
        return (False, "Invalid hub assignment.")
    
    if user_depot.hub_type not in ['AGENCY', 'SUB']:
        return (False, "Only AGENCY and SUB hubs can submit needs lists.")
    
    if user_depot.id != needs_list.agency_hub_id:
        return (False, "Only the owning hub can submit this needs list.")
    
    return (True, None)

def can_prepare_fulfilment(user, needs_list):
    """
    Check if user can prepare/edit fulfilment allocations.
    
    Logistics Managers can also edit Approved/Resent for Dispatch needs lists
    if there's an active Fulfilment Change Request.
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Only ADMIN, Logistics Officers, and Logistics Managers can prepare
    if not user.has_any_role(ROLE_ADMIN, ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER):
        return (False, "Only logistics staff can prepare fulfilments.")
    
    # Check if there's an active change request for this needs list
    active_change_request = FulfilmentChangeRequest.query.filter_by(
        needs_list_id=needs_list.id
    ).filter(
        FulfilmentChangeRequest.status.in_(['Pending Review', 'In Progress'])
    ).first()
    
    # Logistics Managers can edit if:
    # 1. Normal statuses (Submitted, Fulfilment Prepared, Awaiting Approval), OR
    # 2. Approved/Resent for Dispatch WITH an active change request
    if user.has_role(ROLE_LOGISTICS_MANAGER):
        if needs_list.status in ['Submitted', 'Fulfilment Prepared', 'Awaiting Approval']:
            return (True, None)
        elif needs_list.status in ['Approved', 'Resent for Dispatch'] and active_change_request:
            return (True, None)
        else:
            return (False, "This needs list is not in an editable state.")
    
    # Logistics Officers can only edit Submitted or Fulfilment Prepared
    if user.has_role(ROLE_LOGISTICS_OFFICER):
        if needs_list.status in ['Submitted', 'Fulfilment Prepared']:
            return (True, None)
        elif needs_list.status == 'Awaiting Approval':
            return (False, "Cannot edit fulfilment after submitting for approval. Please contact a Logistics Manager.")
        else:
            return (False, "This needs list is not in an editable state.")
    
    # ADMIN fallback
    if needs_list.status not in ['Submitted', 'Fulfilment Prepared', 'Awaiting Approval', 'Approved', 'Resent for Dispatch']:
        return (False, "This needs list is not in an editable state.")
    
    return (True, None)

def can_approve_fulfilment(user, needs_list):
    """
    Check if user can approve and execute a fulfilment.
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Must be in correct status
    if needs_list.status not in ['Awaiting Approval', 'Fulfilment Prepared']:
        return (False, "Only needs lists awaiting approval can be approved.")
    
    # Only ADMIN and Logistics Managers can approve
    if not user.has_any_role(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER):
        return (False, "Only Logistics Managers can approve fulfilments.")
    
    return (True, None)

def can_reject_fulfilment(user, needs_list):
    """
    Check if user can reject a fulfilment.
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Must be in correct status
    if needs_list.status not in ['Awaiting Approval', 'Fulfilment Prepared']:
        return (False, "Only needs lists awaiting approval can be rejected.")
    
    # Only ADMIN and Logistics Managers can reject
    if not user.has_any_role(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER):
        return (False, "Only Logistics Managers can reject fulfilments.")
    
    return (True, None)

def can_delete_needs_list(user, needs_list):
    """
    Check if user can delete a needs list (only Draft, only owning hub).
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Only draft needs lists can be deleted
    if needs_list.status != 'Draft':
        return (False, "Only draft needs lists can be deleted.")
    
    # ADMIN can delete
    if user.has_role(ROLE_ADMIN):
        return (True, None)
    
    # Only the owning hub can delete their draft
    if not user.assigned_location_id:
        return (False, "You must be assigned to a hub.")
    
    user_depot = Depot.query.get(user.assigned_location_id)
    if not user_depot:
        return (False, "Invalid hub assignment.")
    
    if user_depot.id != needs_list.agency_hub_id:
        return (False, "Only the owning hub can delete this needs list.")
    
    return (True, None)

def can_dispatch_from_hub(user, needs_list, source_hub_id=None):
    """
    Check if user can dispatch items from a specific hub for a needs list.
    
    This is the authoritative dispatch permission check for operational hub users.
    Supports both new normalized governance model and legacy role assignments.
    
    Permissions:
    - ADMIN, LOGISTICS_MANAGER, LOGISTICS_OFFICER: Global dispatch rights
    - MAIN_HUB_USER, SUB_HUB_USER, INVENTORY_CLERK: Can dispatch if their hub
      is a source hub in the approved fulfilment
    - WAREHOUSE_SUPERVISOR (legacy): Treated as SUB_HUB_USER for dispatch
    
    Args:
        user: User object
        needs_list: NeedsList object
        source_hub_id: Optional specific hub ID to check (if None, checks user's hub assignments)
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Status validation: Allow dispatch only for Approved and Resent for Dispatch
    # Do not allow re-dispatch of already dispatched items
    valid_statuses = ['Approved', 'Resent for Dispatch']
    if needs_list.status not in valid_statuses:
        return (False, f"Cannot dispatch items for needs lists with status '{needs_list.status}'.")
    
    # ADMIN and Logistics staff have global dispatch rights
    if user.has_any_role(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER):
        return (True, None)
    
    # Operational hub users: MAIN_HUB_USER, SUB_HUB_USER, INVENTORY_CLERK
    # Also include legacy WAREHOUSE_SUPERVISOR (maps to SUB_HUB_USER permissions)
    operational_roles = [
        ROLE_MAIN_HUB_USER, 
        ROLE_SUB_HUB_USER, 
        ROLE_INVENTORY_CLERK,
        ROLE_WAREHOUSE_SUPERVISOR  # Legacy role
    ]
    
    if not user.has_any_role(*operational_roles):
        return (False, "You don't have permission to dispatch items.")
    
    # Get source hub IDs from this needs list's fulfilments
    fulfilments = NeedsListFulfilment.query.filter_by(needs_list_id=needs_list.id).all()
    source_hub_ids = {f.source_hub_id for f in fulfilments if f.source_hub_id}
    
    if not source_hub_ids:
        return (False, "No fulfilment sources defined for this needs list.")
    
    # If a specific source hub is provided, check only that hub
    if source_hub_id:
        if source_hub_id not in source_hub_ids:
            return (False, f"Hub {source_hub_id} is not a source hub for this needs list.")
        
        # Check if user has access to this specific hub
        if user.has_hub_access(source_hub_id):
            return (True, None)
        
        # Fallback to legacy assigned_location_id
        if user.assigned_location_id == source_hub_id:
            return (True, None)
        
        return (False, "You don't have access to this hub.")
    
    # No specific hub provided - check if user has access to ANY source hub
    # First check new multi-hub assignments
    for hub_id in source_hub_ids:
        if user.has_hub_access(hub_id):
            return (True, None)
    
    # Fallback to legacy single assigned_location_id
    if user.assigned_location_id and user.assigned_location_id in source_hub_ids:
        return (True, None)
    
    return (False, "You can only dispatch items from hubs where you are assigned as a source.")

def is_warehouse_user_assigned_to_source_hub(user, needs_list):
    """
    Check if a warehouse user is assigned to any of the source hubs for a needs list.
    
    DEPRECATED: Use can_dispatch_from_hub() instead for proper permission checking.
    
    Args:
        user: The warehouse user (Warehouse Supervisor or Warehouse Officer)
        needs_list: The NeedsList object
    
    Returns:
        bool: True if user is assigned to at least one source hub
    """
    if not user.assigned_location_id:
        return False
    
    # Get all source hubs from fulfilments
    fulfilments = NeedsListFulfilment.query.filter_by(needs_list_id=needs_list.id).all()
    source_hub_ids = {f.source_hub_id for f in fulfilments}
    
    return user.assigned_location_id in source_hub_ids

def can_dispatch_needs_list(user, needs_list):
    """
    Check if user can dispatch an approved needs list.
    
    This enforces the strict "Approved" status requirement for initial dispatch workflow.
    For more flexible dispatch permission checking (including Resent for Dispatch, etc.),
    use can_dispatch_from_hub() directly.
    
    Dispatch permissions:
    - ADMIN: Can dispatch any approved needs list
    - LOGISTICS_MANAGER/OFFICER: Can dispatch any approved needs list
    - SUB_HUB_USER, MAIN_HUB_USER, INVENTORY_CLERK: Can dispatch if their hub is a source hub
    - WAREHOUSE_SUPERVISOR (legacy): Can dispatch if their hub is a source hub
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Strict status gate: Only "Approved" status for initial dispatch
    if needs_list.status != 'Approved':
        return (False, "Only approved needs lists can be dispatched.")
    
    # Delegate to the authoritative dispatch permission helper
    return can_dispatch_from_hub(user, needs_list)

def can_confirm_receipt(user, needs_list):
    """
    Check if user can confirm receipt of a dispatched needs list.
    Only the Agency Hub that requested the items can confirm receipt.
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Must be in Dispatched status
    if needs_list.status != 'Dispatched':
        return (False, "Only dispatched needs lists can have receipt confirmed.")
    
    # ADMIN can always confirm
    if user.has_role(ROLE_ADMIN):
        return (True, None)
    
    # User must be assigned to the agency hub that owns this needs list
    if not user.assigned_location_id:
        return (False, "You must be assigned to a hub to confirm receipt.")
    
    user_depot = Depot.query.get(user.assigned_location_id)
    if not user_depot:
        return (False, "Invalid hub assignment.")
    
    if user_depot.id != needs_list.agency_hub_id:
        return (False, "Only the requesting hub can confirm receipt.")
    
    return (True, None)

# ---------- Concurrency Control - Lock Management Functions ----------
LOCK_TIMEOUT_SECONDS = 900  # 15 minutes

def is_lock_expired(needs_list, timeout_seconds=LOCK_TIMEOUT_SECONDS):
    """
    Check if a needs list lock has expired based on timeout.
    
    Args:
        needs_list: NeedsList instance
        timeout_seconds: Lock timeout in seconds (default: 900 = 15 minutes)
    
    Returns:
        bool: True if lock expired or no lock exists, False if lock is still active
    """
    if not needs_list.locked_at:
        return True
    
    time_since_lock = datetime.utcnow() - needs_list.locked_at
    return time_since_lock.total_seconds() >= timeout_seconds

def get_lock_status(needs_list, current_user):
    """
    Get comprehensive lock status information for a needs list.
    
    Args:
        needs_list: NeedsList instance
        current_user: Current user object
    
    Returns:
        dict: {
            'is_locked': bool,
            'is_locked_by_current_user': bool,
            'can_edit': bool,
            'locked_by_user': User object or None,
            'locked_at': datetime or None,
            'lock_duration_minutes': int or None,
            'lock_message': str or None
        }
    """
    # Check if lock exists and is not expired
    if not needs_list.locked_by_id or is_lock_expired(needs_list):
        return {
            'is_locked': False,
            'is_locked_by_current_user': False,
            'can_edit': True,
            'locked_by_user': None,
            'locked_at': None,
            'lock_duration_minutes': None,
            'lock_message': None
        }
    
    # Lock exists and is active
    locked_by_user = needs_list.locked_by_user
    is_locked_by_current = needs_list.locked_by_id == current_user.id
    time_since_lock = datetime.utcnow() - needs_list.locked_at
    duration_minutes = int(time_since_lock.total_seconds() / 60)
    
    if is_locked_by_current:
        message = "You are currently editing this Needs List."
    else:
        user_name = locked_by_user.display_name if locked_by_user else "Unknown User"
        message = f"This Needs List is currently being fulfilled by {user_name} (started {duration_minutes} minute{'s' if duration_minutes != 1 else ''} ago). Please try again later."
    
    return {
        'is_locked': True,
        'is_locked_by_current_user': is_locked_by_current,
        'can_edit': is_locked_by_current,
        'locked_by_user': locked_by_user,
        'locked_at': needs_list.locked_at,
        'lock_duration_minutes': duration_minutes,
        'lock_message': message
    }

def acquire_lock(needs_list, user):
    """
    Acquire or extend lock for a needs list.
    
    Args:
        needs_list: NeedsList instance
        user: User attempting to acquire lock
    
    Returns:
        tuple: (success: bool, message: str or None)
    """
    try:
        # Check if lock is expired or doesn't exist
        if is_lock_expired(needs_list):
            # Acquire new lock
            needs_list.locked_by_id = user.id
            needs_list.locked_at = datetime.utcnow()
            db.session.flush()  # Ensure atomic lock acquisition
            return (True, "Lock acquired successfully.")
        
        # Lock exists and is active
        if needs_list.locked_by_id == user.id:
            # Same user - extend the lock
            needs_list.locked_at = datetime.utcnow()
            db.session.flush()
            return (True, "Lock extended successfully.")
        else:
            # Different user holds the lock
            locked_by = needs_list.locked_by_user
            user_name = locked_by.display_name if locked_by else "Unknown User"
            time_since_lock = datetime.utcnow() - needs_list.locked_at
            duration_minutes = int(time_since_lock.total_seconds() / 60)
            message = f"This Needs List is currently being fulfilled by {user_name} (started {duration_minutes} minute{'s' if duration_minutes != 1 else ''} ago)."
            return (False, message)
    
    except Exception as e:
        db.session.rollback()
        return (False, f"Error acquiring lock: {str(e)}")

def release_lock(needs_list, user=None):
    """
    Release lock for a needs list.
    
    Args:
        needs_list: NeedsList instance
        user: User attempting to release (optional, for validation)
    
    Returns:
        tuple: (success: bool, message: str or None)
    """
    try:
        # If user is provided, verify they own the lock
        if user and needs_list.locked_by_id and needs_list.locked_by_id != user.id:
            return (False, "You cannot release a lock held by another user.")
        
        # Release the lock
        needs_list.locked_by_id = None
        needs_list.locked_at = None
        db.session.flush()
        return (True, "Lock released successfully.")
    
    except Exception as e:
        db.session.rollback()
        return (False, f"Error releasing lock: {str(e)}")

def extend_lock(needs_list, user):
    """
    Extend an existing lock for a needs list (heartbeat functionality).
    
    Args:
        needs_list: NeedsList instance
        user: User attempting to extend lock
    
    Returns:
        tuple: (success: bool, message: str or None)
    """
    try:
        # Verify user owns the lock
        if needs_list.locked_by_id != user.id:
            return (False, "You do not hold the lock for this Needs List.")
        
        # Check if lock has expired
        if is_lock_expired(needs_list):
            return (False, "Lock has expired. Please reload the page.")
        
        # Extend the lock timestamp
        needs_list.locked_at = datetime.utcnow()
        db.session.flush()
        return (True, "Lock extended successfully.")
    
    except Exception as e:
        db.session.rollback()
        return (False, f"Error extending lock: {str(e)}")

def check_stock_availability(items_requested):
    """
    Check stock availability for requested items and calculate allocated quantities.
    
    Args:
        items_requested: List of tuples [(item_sku, requested_qty), ...]
    
    Returns:
        dict: {
            'is_partial': bool,
            'items': [{'sku': str, 'requested_qty': int, 'allocated_qty': int, 'available_stock': int}, ...]
        }
    """
    stock_map = get_stock_by_location()
    # Exclude AGENCY hubs from overall stock availability calculations
    locations = Depot.query.filter(Depot.hub_type != 'AGENCY').all()
    
    result_items = []
    is_partial = False
    
    for item_sku, requested_qty in items_requested:
        # Calculate total available stock across all locations
        available_stock = sum(stock_map.get((item_sku, loc.id), 0) for loc in locations)
        
        # Determine allocated quantity (can't exceed available stock)
        allocated_qty = min(requested_qty, max(0, available_stock))
        
        if allocated_qty < requested_qty:
            is_partial = True
        
        result_items.append({
            'sku': item_sku,
            'requested_qty': requested_qty,
            'allocated_qty': allocated_qty,
            'available_stock': available_stock
        })
    
    return {
        'is_partial': is_partial,
        'items': result_items
    }

def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate approximate distance between two GPS coordinates using Haversine formula.
    Returns distance in kilometers.
    """
    from math import radians, sin, cos, sqrt, atan2
    
    R = 6371  # Earth radius in kilometers
    
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = sin(dlat/2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    
    return R * c

def record_package_status_change(package, old_status, new_status, changed_by, notes=None):
    """
    Record a package status change in the audit trail.
    
    Args:
        package: DistributionPackage object
        old_status: str - previous status
        new_status: str - new status
        changed_by: str - user who made the change
        notes: str - optional notes about the change
    """
    history = PackageStatusHistory(
        package_id=package.id,
        old_status=old_status,
        new_status=new_status,
        changed_by=changed_by,
        notes=notes
    )
    db.session.add(history)
    db.session.commit()
    return history

# ---------- Authentication Routes ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        if not email or not password:
            flash("Please enter both email and password.", "danger")
            return redirect(url_for("login"))
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash("Your account has been deactivated. Please contact an administrator.", "danger")
                return redirect(url_for("login"))
            
            login_user(user, remember=True)
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            
            flash(f"Welcome back, {user.full_name}!", "success")
            
            # Validate next parameter to prevent open redirect vulnerability
            next_page = request.args.get("next")
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))
    
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

# ---------- Routes ----------
@app.route("/")
@login_required
def dashboard():
    """
    Role-based dashboard route.
    Uses get_dashboard_context() to build role-specific views.
    """
    # Get role-specific dashboard context
    ctx = get_dashboard_context(current_user)
    
    # Handle error conditions
    if 'error' in ctx:
        flash(ctx['error'], "danger")
        return redirect(url_for("login"))
    
    # Route to role-specific template
    template_name = ctx.get('template', 'basic')
    
    if template_name == 'logistics_manager':
        return render_template("dashboard_logistics_manager.html", **ctx)
    elif template_name == 'logistics_officer':
        return render_template("dashboard_logistics_officer.html", **ctx)
    elif template_name == 'main_hub':
        return render_template("dashboard_main_hub.html", **ctx)
    elif template_name == 'sub_hub':
        return render_template("dashboard_sub_hub.html", **ctx)
    else:
        # Fallback to basic dashboard
        return render_template("dashboard_basic.html", **ctx)

@app.route("/warehouse-dashboard")
@role_required(ROLE_ADMIN, ROLE_SUB_HUB_USER)
def warehouse_dashboard():
    """
    Legacy warehouse dashboard route - now redirects to main dashboard.
    Kept for backward compatibility.
    """
    return redirect(url_for("dashboard"))

@app.route("/items")
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK, ROLE_SUB_HUB_USER, ROLE_MAIN_HUB_USER, ROLE_AUDITOR)
def items():
    q = request.args.get("q", "").strip()
    cat = request.args.get("category", "").strip()
    hub_filter = request.args.get("hub", "").strip()
    
    # Get all items
    query = Item.query
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(func.lower(Item.name).like(like) | func.lower(Item.sku).like(like))
    if cat:
        query = query.filter(func.lower(Item.category) == cat.lower())
    
    all_items = query.order_by(Item.name.asc()).all()
    
    # Get stock by location for all items
    stock_map = get_stock_by_location()
    
    # For Sub-Hub users: show only their assigned Sub-Hub
    if current_user.has_role(ROLE_SUB_HUB_USER):
        if not current_user.assigned_location_id:
            flash("You must be assigned to a hub to view inventory.", "danger")
            return redirect(url_for("dashboard"))
        
        assigned_hub = Depot.query.get(current_user.assigned_location_id)
        if not assigned_hub or assigned_hub.hub_type != 'SUB':
            flash("Inventory access is only available for Sub-Hub assignments.", "danger")
            return redirect(url_for("dashboard"))
        
        # Sub-Hub users can only see their assigned hub
        locations = [assigned_hub]
        all_hubs = [assigned_hub]
    else:
        # Exclude AGENCY hubs from overall inventory displays
        locations_query = Depot.query.filter(Depot.hub_type != 'AGENCY')
        
        # Apply hub filter if specified (for Logistics Manager/Officer)
        if hub_filter:
            try:
                hub_id = int(hub_filter)
                locations_query = locations_query.filter(Depot.id == hub_id)
            except ValueError:
                pass
        
        locations = locations_query.order_by(Depot.name.asc()).all()
        
        # Get all ODPEM hubs for filter dropdown
        all_hubs = Depot.query.filter(Depot.hub_type != 'AGENCY').order_by(Depot.name.asc()).all()
    
    return render_template("items.html", items=all_items, q=q, cat=cat, 
                          locations=locations, stock_map=stock_map, 
                          all_hubs=all_hubs, hub_filter=hub_filter)

@app.route("/items/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK)
def item_new():
    if request.method == "POST":
        from datetime import datetime as dt
        name = request.form["name"].strip()
        barcode = request.form.get("barcode", "").strip() or None
        category = request.form.get("category", "").strip() or None
        unit = request.form.get("unit", "unit").strip() or "unit"
        min_qty = int(request.form.get("min_qty", "0") or 0)
        description = request.form.get("description", "").strip() or None
        storage_requirements = request.form.get("storage_requirements", "").strip() or None

        # Check for barcode uniqueness
        if barcode:
            existing_barcode = Item.query.filter_by(barcode=barcode).first()
            if existing_barcode:
                flash(f"Barcode '{barcode}' is already used by item '{existing_barcode.name}' [{existing_barcode.sku}].", "danger")
                return redirect(url_for("item_new"))

        # Duplicate suggestion by normalized name+category+unit
        norm = normalize_name(name)
        existing = Item.query.filter(func.lower(Item.name) == norm, Item.category == category, Item.unit == unit).first()
        if existing:
            flash(f"Possible duplicate found: '{existing.name}' in category '{existing.category or '—'}' (unit: {existing.unit}). Consider editing that item instead.", "warning")
            return redirect(url_for("item_edit", item_sku=existing.sku))

        # Generate SKU
        sku = generate_sku()
        item = Item(sku=sku, barcode=barcode, name=name, category=category, unit=unit, min_qty=min_qty, 
                   description=description, storage_requirements=storage_requirements)
        
        # Handle file upload
        if "attachment" in request.files:
            file = request.files["attachment"]
            if file and file.filename and allowed_file(file.filename):
                if validate_file_size(file):
                    try:
                        storage = get_storage()
                        storage_path, original_filename = storage.save_file(file, file.filename, folder="items")
                        item.attachment_path = storage_path
                        item.attachment_filename = original_filename
                    except Exception as e:
                        flash(f"Error uploading file: {str(e)}", "warning")
                else:
                    flash("File size exceeds 10MB limit.", "warning")
            elif file and file.filename:
                flash("File type not allowed. Please upload PNG, JPG, PDF, DOC, DOCX, TXT, CSV, or XLSX files.", "warning")
        
        db.session.add(item)
        db.session.commit()
        flash(f"Item created with SKU: {sku}", "success")
        return redirect(url_for("items"))
    return render_template("item_form.html", item=None)

@app.route("/items/<item_sku>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK)
def item_edit(item_sku):
    from datetime import datetime as dt
    item = Item.query.get_or_404(item_sku)
    if request.method == "POST":
        barcode = request.form.get("barcode", "").strip() or None
        
        # Check for barcode uniqueness (excluding current item)
        if barcode:
            existing_barcode = Item.query.filter(Item.barcode == barcode, Item.sku != item_sku).first()
            if existing_barcode:
                flash(f"Barcode '{barcode}' is already used by item '{existing_barcode.name}' [{existing_barcode.sku}].", "danger")
                return redirect(url_for("item_edit", item_sku=item_sku))
        
        item.barcode = barcode
        item.name = request.form["name"].strip()
        item.category = request.form.get("category", "").strip() or None
        item.unit = request.form.get("unit", "unit").strip() or "unit"
        item.min_qty = int(request.form.get("min_qty", "0") or 0)
        item.description = request.form.get("description", "").strip() or None
        item.storage_requirements = request.form.get("storage_requirements", "").strip() or None
        
        # Handle file upload
        if "attachment" in request.files:
            file = request.files["attachment"]
            if file and file.filename and allowed_file(file.filename):
                if validate_file_size(file):
                    try:
                        storage = get_storage()
                        # Delete old file if exists
                        if item.attachment_path:
                            storage.delete_file(item.attachment_path)
                        # Save new file
                        storage_path, original_filename = storage.save_file(file, file.filename, folder="items")
                        item.attachment_path = storage_path
                        item.attachment_filename = original_filename
                    except Exception as e:
                        flash(f"Error uploading file: {str(e)}", "warning")
                else:
                    flash("File size exceeds 10MB limit.", "warning")
            elif file and file.filename:
                flash("File type not allowed. Please upload PNG, JPG, PDF, DOC, DOCX, TXT, CSV, or XLSX files.", "warning")
            
        db.session.commit()
        flash("Item updated.", "success")
        return redirect(url_for("items"))
    return render_template("item_form.html", item=item)

@app.route("/intake", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK)
def intake():
    items = Item.query.order_by(Item.name.asc()).all()
    locations = Depot.query.order_by(Depot.name.asc()).all()
    events = DisasterEvent.query.filter_by(status="Active").order_by(DisasterEvent.start_date.desc()).all()
    if request.method == "POST":
        item_sku = request.form["item_sku"]
        qty = int(request.form["qty"])
        location_id = int(request.form["location_id"]) if request.form.get("location_id") else None
        
        # Depot is required for inventory tracking
        if not location_id:
            flash("Please select a location for intake.", "danger")
            return redirect(url_for("intake"))
        
        donor_name = request.form.get("donor_name", "").strip() or None
        event_id = int(request.form["event_id"]) if request.form.get("event_id") else None
        expiry_date_str = request.form.get("expiry_date", "").strip() or None
        
        # Disaster event is required for all intake operations
        if not event_id:
            flash("Please select a disaster event for intake.", "danger")
            return redirect(url_for("intake"))
        
        donor = None
        if donor_name:
            donor = Donor.query.filter_by(name=donor_name).first()
            if not donor:
                donor = Donor(name=donor_name)
                db.session.add(donor)
                db.session.flush()
        notes = request.form.get("notes", "").strip() or None
        
        # Parse expiry date
        expiry_date = None
        if expiry_date_str:
            from datetime import datetime as dt
            expiry_date = dt.strptime(expiry_date_str, "%Y-%m-%d").date()

        tx = Transaction(item_sku=item_sku, ttype="IN", qty=qty, location_id=location_id,
                         donor_id=donor.id if donor else None, event_id=event_id, 
                         expiry_date=expiry_date, notes=notes,
                         created_by=current_user.display_name)
        db.session.add(tx)
        db.session.commit()
        flash("Intake recorded.", "success")
        return redirect(url_for("dashboard"))
    return render_template("intake.html", items=items, locations=locations, events=events)

@app.route("/api/barcode-lookup")
@login_required
def barcode_lookup():
    barcode = request.args.get("barcode", "").strip()
    if not barcode:
        return jsonify({"success": False, "message": "Barcode is required"}), 400
    
    # Try to find item by barcode or SKU
    item = Item.query.filter((Item.barcode == barcode) | (Item.sku == barcode)).first()
    
    if item:
        return jsonify({
            "success": True,
            "item": {
                "sku": item.sku,
                "name": item.name,
                "category": item.category,
                "unit": item.unit,
                "barcode": item.barcode
            }
        })
    else:
        return jsonify({"success": False, "message": f"No item found with barcode: {barcode}"}), 404

# ---------- Lock Management API Endpoints ----------
@app.route("/api/needs-lists/<int:list_id>/extend-lock", methods=["POST"])
@login_required
def api_extend_lock(list_id):
    """Extend lock for a needs list (heartbeat functionality)"""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    success, message = extend_lock(needs_list, current_user)
    
    if success:
        db.session.commit()
        return jsonify({
            "success": True,
            "message": message,
            "locked_at": format_datetime_iso_est(needs_list.locked_at) if needs_list.locked_at else None
        })
    else:
        return jsonify({"success": False, "message": message}), 403

@app.route("/api/needs-lists/<int:list_id>/release-lock", methods=["POST"])
@login_required
def api_release_lock(list_id):
    """Release lock for a needs list"""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    success, message = release_lock(needs_list, current_user)
    
    if success:
        db.session.commit()
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "message": message}), 403

@app.route("/api/needs-lists/<int:list_id>/lock-status", methods=["GET"])
@login_required
def api_lock_status(list_id):
    """Get current lock status for a needs list"""
    needs_list = NeedsList.query.get_or_404(list_id)
    lock_status = get_lock_status(needs_list, current_user)
    
    return jsonify({
        "success": True,
        "lock_status": {
            "is_locked": lock_status['is_locked'],
            "is_locked_by_current_user": lock_status['is_locked_by_current_user'],
            "can_edit": lock_status['can_edit'],
            "locked_by_name": lock_status['locked_by_user'].full_name if lock_status['locked_by_user'] else None,
            "locked_at": format_datetime_iso_est(lock_status['locked_at']) if lock_status['locked_at'] else None,
            "lock_duration_minutes": lock_status['lock_duration_minutes'],
            "lock_message": lock_status['lock_message']
        }
    })

@app.route("/distribute", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK, ROLE_AGENCY_HUB_USER)
def distribute():
    items = Item.query.order_by(Item.name.asc()).all()
    locations = Depot.query.order_by(Depot.name.asc()).all()
    events = DisasterEvent.query.filter_by(status="Active").order_by(DisasterEvent.start_date.desc()).all()
    if request.method == "POST":
        item_sku = request.form["item_sku"]
        qty = int(request.form["qty"])
        location_id = int(request.form["location_id"]) if request.form.get("location_id") else None
        beneficiary_name = request.form.get("beneficiary_name", "").strip() or None
        parish = request.form.get("parish", "").strip() or None
        event_id = int(request.form["event_id"]) if request.form.get("event_id") else None
        
        beneficiary = None
        if beneficiary_name:
            beneficiary = Beneficiary.query.filter_by(name=beneficiary_name).first()
            if not beneficiary:
                beneficiary = Beneficiary(name=beneficiary_name, parish=parish)
                db.session.add(beneficiary)
                db.session.flush()
        notes = request.form.get("notes", "").strip() or None

        # Check stock at the specific location
        if location_id:
            stock_map = get_stock_by_location()
            location_stock = stock_map.get((item_sku, location_id), 0)
            if location_stock < qty:
                loc_name = Depot.query.get(location_id).name
                flash(f"Insufficient stock at {loc_name}. Available: {location_stock}, Requested: {qty}", "danger")
                return redirect(url_for("distribute"))
        else:
            flash("Please select a location for distribution.", "danger")
            return redirect(url_for("distribute"))

        tx = Transaction(item_sku=item_sku, ttype="OUT", qty=qty, location_id=location_id,
                         beneficiary_id=beneficiary.id if beneficiary else None, 
                         event_id=event_id, notes=notes,
                         created_by=current_user.display_name)
        db.session.add(tx)
        db.session.commit()
        flash("Distribution recorded.", "success")
        return redirect(url_for("dashboard"))
    return render_template("distribute.html", items=items, locations=locations, events=events)

@app.route("/transactions")
@login_required
def transactions():
    # Get sorting parameters from query string
    sort_by = request.args.get("sort_by", "created_at")
    order = request.args.get("order", "desc")
    
    # Build the query
    query = Transaction.query
    
    # Sub-Hub users should only see transactions for their assigned Sub-Hub
    if current_user.has_role(ROLE_SUB_HUB_USER):
        if not current_user.assigned_location_id:
            flash("You must be assigned to a hub to view transaction history.", "danger")
            return redirect(url_for("warehouse_dashboard"))
        
        assigned_hub = Depot.query.get(current_user.assigned_location_id)
        if not assigned_hub or assigned_hub.hub_type != 'SUB':
            flash("Transaction history is only available for Sub-Hub assignments.", "danger")
            return redirect(url_for("warehouse_dashboard"))
        
        # Filter to only show transactions for their assigned Sub-Hub
        query = query.filter(Transaction.location_id == current_user.assigned_location_id)
    
    # AGENCY hub users should only see transactions for their own hub
    elif current_user.assigned_location_id:
        user_depot = Depot.query.get(current_user.assigned_location_id)
        if user_depot and user_depot.hub_type == 'AGENCY':
            # Filter to only show transactions for this AGENCY hub
            query = query.filter(Transaction.location_id == current_user.assigned_location_id)
    
    # Apply sorting based on parameters
    if sort_by == "created_at":
        sort_column = Transaction.created_at
    elif sort_by == "type":
        sort_column = Transaction.ttype
    elif sort_by == "item":
        query = query.join(Item, Transaction.item_sku == Item.sku)
        sort_column = Item.name
    elif sort_by == "qty":
        sort_column = Transaction.qty
    elif sort_by == "depot":
        query = query.join(Depot, Transaction.location_id == Depot.id, isouter=True)
        sort_column = Depot.name
    else:
        sort_column = Transaction.created_at
    
    # Apply order direction
    if order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())
    
    rows = query.limit(500).all()
    return render_template("transactions.html", rows=rows, sort_by=sort_by, order=order)

@app.route("/reports/stock")
@login_required
def report_stock():
    # Sub-Hub users should only see stock for their assigned Sub-Hub
    if current_user.has_role(ROLE_SUB_HUB_USER):
        if not current_user.assigned_location_id:
            flash("You must be assigned to a hub to view stock reports.", "danger")
            return redirect(url_for("warehouse_dashboard"))
        
        assigned_hub = Depot.query.get(current_user.assigned_location_id)
        if not assigned_hub or assigned_hub.hub_type != 'SUB':
            flash("Stock reports are only available for Sub-Hub assignments.", "danger")
            return redirect(url_for("warehouse_dashboard"))
        
        # Only show their assigned Sub-Hub
        locations = [assigned_hub]
    else:
        # Exclude AGENCY hubs from overall stock reports
        locations = Depot.query.filter(Depot.hub_type != 'AGENCY').order_by(Depot.name.asc()).all()
    
    items = Item.query.order_by(Item.category.asc(), Item.name.asc()).all()
    stock_map = get_stock_by_location()
    
    return render_template("report_stock.html", items=items, locations=locations, stock_map=stock_map)

@app.route("/export/items.csv")
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER)
def export_items():
    items = Item.query.all()
    df = pd.DataFrame([{
        "sku": it.sku,
        "name": it.name,
        "category": it.category or "",
        "unit": it.unit,
        "min_qty": it.min_qty,
        "description": it.description or "",
    } for it in items])
    csv_path = "items_export.csv"
    df.to_csv(csv_path, index=False)
    return send_file(csv_path, as_attachment=True, download_name="items.csv", mimetype="text/csv")

@app.route("/import/items", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER)
def import_items():
    if request.method == "POST":
        f = request.files.get("file")
        if not f:
            flash("No file uploaded.", "warning")
            return redirect(url_for("import_items"))
        df = pd.read_csv(f)
        created, skipped = 0, 0
        for _, row in df.iterrows():
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            category = str(row.get("category", "")).strip() or None
            unit = str(row.get("unit", "unit")).strip() or "unit"
            min_qty = int(row.get("min_qty", 0) or 0)
            description = str(row.get("description", "")).strip() or None

            norm = normalize_name(name)
            existing = Item.query.filter(func.lower(Item.name) == norm, Item.category == category, Item.unit == unit).first()
            if existing:
                skipped += 1
                continue
            # Generate SKU for imported items
            sku = generate_sku()
            item = Item(sku=sku, name=name, category=category, unit=unit, min_qty=min_qty, description=description)
            db.session.add(item)
            created += 1
        db.session.commit()
        flash(f"Import complete. Created {created}, skipped {skipped} duplicates.", "info")
        return redirect(url_for("items"))
    return render_template("import_items.html")

@app.route("/depots")
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK)
def depots():
    locs = Depot.query.order_by(Depot.name.asc()).all()
    # Get stock counts per location
    stock_by_loc = {}
    for loc in locs:
        stock_rows = db.session.query(
            func.sum(case((Transaction.ttype == "IN", Transaction.qty), else_=-Transaction.qty))
        ).filter(Transaction.location_id == loc.id).scalar()
        stock_by_loc[loc.id] = stock_rows or 0
    return render_template("depots.html", locations=locs, stock_by_loc=stock_by_loc)

@app.route("/locations/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def depot_new():
    if request.method == "POST":
        name = request.form["name"].strip()
        hub_type = request.form.get("hub_type", "MAIN")
        parent_location_id = request.form.get("parent_location_id")
        status = request.form.get("status", "Active")
        
        if not name:
            flash("Depot name is required.", "danger")
            return redirect(url_for("depot_new"))
        
        if not hub_type:
            flash("Hub type is required.", "danger")
            return redirect(url_for("depot_new"))
        
        # AGENCY hubs are independent - reject any parent hub assignment
        if hub_type == 'AGENCY' and parent_location_id:
            flash("AGENCY hubs are independent and cannot have a parent hub.", "danger")
            return redirect(url_for("depot_new"))
        
        # SUB hubs don't need a parent - they're orchestrated by ALL MAIN hubs
        # Clear any parent_location_id for SUB hubs
        if hub_type == 'SUB':
            parent_location_id = None
        
        # Validate parent hub if specified (should never happen, but defensive check)
        if parent_location_id:
            parent_hub = Depot.query.get(parent_location_id)
            if not parent_hub or parent_hub.hub_type != 'MAIN':
                flash("Parent hub must be a MAIN hub.", "danger")
                return redirect(url_for("depot_new"))
        
        # Check for duplicates
        existing = Depot.query.filter_by(name=name).first()
        if existing:
            flash(f"Depot '{name}' already exists.", "warning")
            return redirect(url_for("depots"))
        
        # Create new depot with hub hierarchy and status
        location = Depot(
            name=name,
            hub_type=hub_type,
            parent_location_id=None,  # Always None - no parent hub assignments
            status=status,
            operational_timestamp=datetime.utcnow() if status == 'Active' else None
        )
        db.session.add(location)
        db.session.commit()
        flash(f"Hub '{name}' created successfully as a {hub_type} hub with status: {status}.", "success")
        return redirect(url_for("depots"))
    
    # GET request - provide list of MAIN hubs for parent selection
    main_hubs = Depot.query.filter_by(hub_type='MAIN').order_by(Depot.name.asc()).all()
    return render_template("depot_form.html", depot=None, main_hubs=main_hubs)

@app.route("/locations/<int:location_id>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def depot_edit(location_id):
    location = Depot.query.get_or_404(location_id)
    if request.method == "POST":
        name = request.form["name"].strip()
        hub_type = request.form.get("hub_type", "MAIN")
        parent_location_id = request.form.get("parent_location_id")
        new_status = request.form.get("status", "Active")
        
        if not name:
            flash("Depot name is required.", "danger")
            return redirect(url_for("depot_edit", location_id=location_id))
        
        if not hub_type:
            flash("Hub type is required.", "danger")
            return redirect(url_for("depot_edit", location_id=location_id))
        
        # AGENCY hubs are independent - reject any parent hub assignment
        if hub_type == 'AGENCY' and parent_location_id:
            flash("AGENCY hubs are independent and cannot have a parent hub.", "danger")
            return redirect(url_for("depot_edit", location_id=location_id))
        
        # SUB hubs don't need a parent - they're orchestrated by ALL MAIN hubs
        # Clear any parent_location_id for SUB hubs
        if hub_type == 'SUB':
            parent_location_id = None
        
        # Validate parent hub if specified (should never happen, but defensive check)
        if parent_location_id:
            # Prevent self-referencing
            if int(parent_location_id) == location_id:
                flash("A hub cannot be its own parent hub.", "danger")
                return redirect(url_for("depot_edit", location_id=location_id))
            
            # If a parent is specified, verify it's a MAIN hub
            parent_hub = Depot.query.get(parent_location_id)
            if not parent_hub or parent_hub.hub_type != 'MAIN':
                flash("Parent hub must be a MAIN hub.", "danger")
                return redirect(url_for("depot_edit", location_id=location_id))
        
        # Check for duplicates (excluding current location)
        existing = Depot.query.filter(Depot.name == name, Depot.id != location_id).first()
        if existing:
            flash(f"Depot '{name}' already exists.", "warning")
            return redirect(url_for("depot_edit", location_id=location_id))
        
        # Update depot with hub hierarchy
        location.name = name
        location.hub_type = hub_type
        location.parent_location_id = None  # Always None - no parent hub assignments
        
        # Handle status change and update operational_timestamp when activated
        old_status = location.status
        location.status = new_status
        
        # Record operational timestamp when hub is activated
        if old_status != 'Active' and new_status == 'Active':
            location.operational_timestamp = datetime.utcnow()
            flash(f"Hub '{name}' updated and activated. Operational timestamp recorded.", "success")
        else:
            flash(f"Hub '{name}' updated successfully as a {hub_type} hub with status: {new_status}.", "success")
        
        db.session.commit()
        return redirect(url_for("depots"))
    
    # GET request - provide list of MAIN hubs for parent selection
    main_hubs = Depot.query.filter_by(hub_type='MAIN').order_by(Depot.name.asc()).all()
    return render_template("depot_form.html", depot=location, main_hubs=main_hubs)

@app.route("/locations/<int:location_id>/inventory")
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK)
def depot_inventory(location_id):
    location = Depot.query.get_or_404(location_id)
    
    # AGENCY hub inventory is private - block access
    if location.hub_type == 'AGENCY':
        flash("AGENCY hub inventory is private and cannot be accessed.", "warning")
        return redirect(url_for("depots"))
    
    # Get all items with stock at this location
    stock_expr = func.sum(
        case((Transaction.ttype == "IN", Transaction.qty), else_=-Transaction.qty)
    ).label("stock")
    
    rows = db.session.query(Item, stock_expr).join(
        Transaction, Item.sku == Transaction.item_sku
    ).filter(
        Transaction.location_id == location_id
    ).group_by(Item.sku).order_by(Item.category.asc(), Item.name.asc()).all()
    
    return render_template("depot_inventory.html", depot=location, rows=rows)

# ---------- Distribution Package Routes ----------

@app.route("/packages")
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK)
def packages():
    """List all distribution packages with filters"""
    status_filter = request.args.get("status")
    
    query = DistributionPackage.query
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    packages_list = query.order_by(DistributionPackage.created_at.desc()).all()
    
    # Define status options for filter
    status_options = ["Draft", "Under Review", "Approved", "Dispatched", "Delivered"]
    
    return render_template("packages.html", 
                         packages=packages_list, 
                         status_filter=status_filter,
                         status_options=status_options)

@app.route("/packages/create", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def package_create():
    """Create a new distribution package for an AGENCY hub"""
    if request.method == "POST":
        recipient_agency_id = request.form.get("recipient_agency_id")
        event_id = request.form.get("event_id") or None
        notes = request.form.get("notes", "").strip() or None
        
        if not recipient_agency_id:
            flash("Recipient agency is required.", "danger")
            return redirect(url_for("package_create"))
        
        # Parse items from form (dynamic fields: item_sku_N, item_requested_N, depot_allocation_N_DEPOT)
        items_data = []
        item_index = 0
        stock_map = get_stock_by_location()
        # Exclude AGENCY hubs from package fulfillment - they're independent agencies
        locations = Depot.query.filter(Depot.hub_type != 'AGENCY').all()
        depot_name_to_id = {loc.name: loc.id for loc in locations}
        
        while True:
            sku_key = f"item_sku_{item_index}"
            requested_key = f"item_requested_{item_index}"
            
            if sku_key not in request.form:
                break
            
            sku = request.form[sku_key].strip()
            requested_str = request.form.get(requested_key, "").strip()
            
            if sku and requested_str:
                try:
                    requested_qty = int(requested_str)
                    
                    if requested_qty <= 0:
                        flash(f"Requested quantity must be greater than 0 for item {sku}.", "danger")
                        return redirect(url_for("package_create"))
                    
                    # Parse per-depot allocations
                    depot_allocations = []
                    total_allocated = 0
                    
                    for loc in locations:
                        depot_field_name = f"depot_allocation_{item_index}_{loc.name.replace(' ', '_')}"
                        depot_qty_str = request.form.get(depot_field_name, "").strip()
                        
                        if depot_qty_str:
                            depot_qty = int(depot_qty_str)
                            
                            if depot_qty > 0:
                                # Validate against depot stock
                                available_at_depot = stock_map.get((sku, loc.id), 0)
                                
                                if depot_qty > available_at_depot:
                                    flash(f"Item {sku}: Cannot allocate {depot_qty} from {loc.name}. Only {available_at_depot} available.", "danger")
                                    return redirect(url_for("package_create"))
                                
                                depot_allocations.append({
                                    'depot_id': loc.id,
                                    'depot_name': loc.name,
                                    'qty': depot_qty
                                })
                                total_allocated += depot_qty
                    
                    # Validate total allocation
                    if total_allocated > requested_qty:
                        flash(f"Item {sku}: Total allocated ({total_allocated}) cannot exceed requested quantity ({requested_qty}).", "danger")
                        return redirect(url_for("package_create"))
                    
                    items_data.append({
                        'sku': sku,
                        'requested_qty': requested_qty,
                        'allocated_qty': total_allocated,
                        'depot_allocations': depot_allocations
                    })
                except ValueError as e:
                    flash(f"Invalid quantity values for item {sku}: {str(e)}", "danger")
                    return redirect(url_for("package_create"))
            
            item_index += 1
        
        if not items_data:
            flash("At least one item with quantity is required.", "danger")
            return redirect(url_for("package_create"))
        
        # Determine if package is partial
        is_partial = any(item['allocated_qty'] < item['requested_qty'] for item in items_data)
        
        # Create package
        package = DistributionPackage(
            package_number=generate_package_number(),
            recipient_agency_id=int(recipient_agency_id),
            event_id=int(event_id) if event_id else None,
            status="Draft",
            is_partial=is_partial,
            created_by=current_user.display_name,
            notes=notes
        )
        db.session.add(package)
        db.session.flush()  # Get package.id
        
        # Add package items and depot allocations
        for item_data in items_data:
            package_item = PackageItem(
                package_id=package.id,
                item_sku=item_data['sku'],
                requested_qty=item_data['requested_qty'],
                allocated_qty=item_data['allocated_qty']
            )
            db.session.add(package_item)
            db.session.flush()  # Get package_item.id
            
            # Add per-depot allocations
            for depot_allocation in item_data['depot_allocations']:
                allocation = PackageItemAllocation(
                    package_item_id=package_item.id,
                    depot_id=depot_allocation['depot_id'],
                    allocated_qty=depot_allocation['qty']
                )
                db.session.add(allocation)
        
        # Record initial status
        record_package_status_change(package, None, "Draft", current_user.display_name, "Package created")
        
        db.session.commit()
        
        flash(f"Package {package.package_number} created successfully.", "success")
        return redirect(url_for("package_details", package_id=package.id))
    
    # GET request
    # Get AGENCY hubs as potential recipients
    agency_hubs = Depot.query.filter_by(hub_type='AGENCY').order_by(Depot.name).all()
    events = DisasterEvent.query.filter_by(status="Active").order_by(DisasterEvent.start_date.desc()).all()
    items = Item.query.order_by(Item.name).all()
    # Exclude AGENCY hubs from package fulfillment source - they're recipients, not sources
    locations = Depot.query.filter(Depot.hub_type != 'AGENCY').order_by(Depot.name).all()
    stock_map = get_stock_by_location()
    
    return render_template("package_form.html", 
                         agency_hubs=agency_hubs,
                         events=events,
                         items=items,
                         locations=locations,
                         stock_map=stock_map)

@app.route("/stock-transfer", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK)
def stock_transfer():
    """Transfer stock between depots with approval workflow based on hub type"""
    if request.method == "POST":
        item_sku = request.form.get("item_sku")
        from_depot_id = request.form.get("from_depot_id")
        to_depot_id = request.form.get("to_depot_id")
        quantity_str = request.form.get("quantity")
        notes = request.form.get("notes", "").strip()
        
        if not all([item_sku, from_depot_id, to_depot_id, quantity_str]):
            flash("All fields are required.", "danger")
            return redirect(url_for("stock_transfer"))
        
        try:
            quantity = int(quantity_str)
            from_depot_id = int(from_depot_id)
            to_depot_id = int(to_depot_id)
            
            if quantity <= 0:
                flash("Quantity must be greater than zero.", "danger")
                return redirect(url_for("stock_transfer"))
            
            if from_depot_id == to_depot_id:
                flash("Source and destination depots must be different.", "danger")
                return redirect(url_for("stock_transfer"))
            
            # Verify item exists
            item = Item.query.filter_by(sku=item_sku).first()
            if not item:
                flash("Item not found.", "danger")
                return redirect(url_for("stock_transfer"))
            
            # Verify depots exist
            from_depot = Depot.query.get(from_depot_id)
            to_depot = Depot.query.get(to_depot_id)
            if not from_depot or not to_depot:
                flash("Depot not found.", "danger")
                return redirect(url_for("stock_transfer"))
            
            # Check available stock at source depot
            stock_map = get_stock_by_location()
            available_stock = stock_map.get((item_sku, from_depot_id), 0)
            
            if quantity > available_stock:
                flash(f"Insufficient stock at {from_depot.name}. Available: {available_stock}, Requested: {quantity}", "danger")
                return redirect(url_for("stock_transfer"))
            
            # Determine user's hub type based on their assigned location
            # Only ADMIN role can execute transfers without assigned location
            if not current_user.assigned_location_id:
                if current_user.role == 'ADMIN':
                    user_hub_type = 'MAIN'  # ADMIN has MAIN hub privileges
                else:
                    flash("You must have an assigned depot to perform transfers. Please contact an administrator.", "danger")
                    return redirect(url_for("stock_transfer"))
            else:
                user_depot = Depot.query.get(current_user.assigned_location_id)
                if not user_depot:
                    flash("Your assigned depot could not be found. Please contact an administrator.", "danger")
                    return redirect(url_for("stock_transfer"))
                
                user_hub_type = user_depot.hub_type
                
                # SUB/AGENCY users can only transfer from their assigned depot
                if user_hub_type in ['SUB', 'AGENCY'] and from_depot_id != current_user.assigned_location_id:
                    flash(f"You can only transfer stock from your assigned depot: {user_depot.name}", "danger")
                    return redirect(url_for("stock_transfer"))
            
            # Check hub type to determine if approval is needed
            # MAIN hub can transfer immediately, SUB/AGENCY need approval
            if user_hub_type == 'MAIN':
                # MAIN hub: Execute transfer immediately
                transfer_note = f"Stock transfer to {to_depot.name}. {notes}" if notes else f"Stock transfer to {to_depot.name}"
                out_transaction = Transaction(
                    item_sku=item_sku,
                    ttype="OUT",
                    qty=quantity,
                    location_id=from_depot_id,
                    notes=transfer_note,
                    created_by=current_user.display_name
                )
                db.session.add(out_transaction)
                
                in_note = f"Stock transfer from {from_depot.name}. {notes}" if notes else f"Stock transfer from {from_depot.name}"
                in_transaction = Transaction(
                    item_sku=item_sku,
                    ttype="IN",
                    qty=quantity,
                    location_id=to_depot_id,
                    notes=in_note,
                    created_by=current_user.display_name
                )
                db.session.add(in_transaction)
                
                db.session.commit()
                
                flash(f"Successfully transferred {quantity} units of {item.name} from {from_depot.name} to {to_depot.name}.", "success")
            else:
                # SUB or AGENCY hub: Create transfer request for approval
                transfer_request = TransferRequest(
                    from_location_id=from_depot_id,
                    to_location_id=to_depot_id,
                    item_sku=item_sku,
                    quantity=quantity,
                    status='PENDING',
                    requested_by=current_user.id,
                    notes=notes
                )
                db.session.add(transfer_request)
                db.session.commit()
                
                flash(f"Transfer request submitted for approval. {quantity} units of {item.name} from {from_depot.name} to {to_depot.name}. This will be reviewed by MAIN hub staff.", "info")
            
            return redirect(url_for("stock_transfer"))
            
        except ValueError:
            flash("Invalid input values.", "danger")
            return redirect(url_for("stock_transfer"))
    
    # GET request
    items = Item.query.order_by(Item.name).all()
    depots = Depot.query.order_by(Depot.name).all()
    stock_map = get_stock_by_location()
    
    # Get pending transfer requests for this user's depot (if SUB/AGENCY)
    pending_requests = []
    if current_user.assigned_location:
        user_depot = Depot.query.get(current_user.assigned_location_id)
        if user_depot and user_depot.hub_type in ['SUB', 'AGENCY']:
            pending_requests = TransferRequest.query.filter(
                TransferRequest.from_location_id == current_user.assigned_location_id,
                TransferRequest.status == 'PENDING'
            ).order_by(TransferRequest.requested_at.desc()).all()
    
    return render_template("stock_transfer.html",
                         items=items,
                         depots=depots,
                         stock_map=stock_map,
                         pending_requests=pending_requests)

@app.route("/transfer-requests")
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def transfer_requests():
    """Approval queue for MAIN hub staff to review transfer requests"""
    # Only show approval queue to users from MAIN hub
    if current_user.assigned_location:
        user_depot = Depot.query.get(current_user.assigned_location_id)
        if not user_depot or user_depot.hub_type != 'MAIN':
            flash("Only MAIN hub staff can access the transfer approval queue.", "warning")
            return redirect(url_for("dashboard"))
    
    # Get all pending transfer requests
    pending_requests = TransferRequest.query.filter_by(status='PENDING').order_by(TransferRequest.requested_at.desc()).all()
    
    # Get recently reviewed requests (last 30 days)
    from datetime import timedelta
    cutoff_date = datetime.utcnow() - timedelta(days=30)
    reviewed_requests = TransferRequest.query.filter(
        TransferRequest.status.in_(['APPROVED', 'REJECTED']),
        TransferRequest.reviewed_at >= cutoff_date
    ).order_by(TransferRequest.reviewed_at.desc()).limit(50).all()
    
    stock_map = get_stock_by_location()
    
    return render_template("transfer_requests.html",
                         pending_requests=pending_requests,
                         reviewed_requests=reviewed_requests,
                         stock_map=stock_map)

@app.route("/transfer-requests/<int:request_id>/approve", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def approve_transfer_request(request_id):
    """Approve a transfer request and execute the transfer"""
    # Verify user is from MAIN hub
    if current_user.assigned_location:
        user_depot = Depot.query.get(current_user.assigned_location_id)
        if not user_depot or user_depot.hub_type != 'MAIN':
            flash("Only MAIN hub staff can approve transfer requests.", "danger")
            return redirect(url_for("dashboard"))
    
    transfer_request = TransferRequest.query.get_or_404(request_id)
    
    if transfer_request.status != 'PENDING':
        flash("This transfer request has already been reviewed.", "warning")
        return redirect(url_for("transfer_requests"))
    
    # Verify stock availability
    stock_map = get_stock_by_location()
    available_stock = stock_map.get((transfer_request.item_sku, transfer_request.from_location_id), 0)
    
    if transfer_request.quantity > available_stock:
        flash(f"Cannot approve: Insufficient stock. Available: {available_stock}, Requested: {transfer_request.quantity}", "danger")
        return redirect(url_for("transfer_requests"))
    
    # Execute the transfer
    from_depot = transfer_request.from_location
    to_depot = transfer_request.to_location
    item = transfer_request.item
    
    transfer_note = f"Approved transfer to {to_depot.name}. {transfer_request.notes}" if transfer_request.notes else f"Approved transfer to {to_depot.name}"
    out_transaction = Transaction(
        item_sku=transfer_request.item_sku,
        ttype="OUT",
        qty=transfer_request.quantity,
        location_id=transfer_request.from_location_id,
        notes=transfer_note,
        created_by=current_user.display_name
    )
    db.session.add(out_transaction)
    
    in_note = f"Approved transfer from {from_depot.name}. {transfer_request.notes}" if transfer_request.notes else f"Approved transfer from {from_depot.name}"
    in_transaction = Transaction(
        item_sku=transfer_request.item_sku,
        ttype="IN",
        qty=transfer_request.quantity,
        location_id=transfer_request.to_location_id,
        notes=in_note,
        created_by=current_user.display_name
    )
    db.session.add(in_transaction)
    
    # Update transfer request status
    transfer_request.status = 'APPROVED'
    transfer_request.reviewed_by = current_user.id
    transfer_request.reviewed_at = datetime.utcnow()
    
    db.session.commit()
    
    flash(f"Transfer request approved and executed. {transfer_request.quantity} units of {item.name} transferred from {from_depot.name} to {to_depot.name}.", "success")
    return redirect(url_for("transfer_requests"))

@app.route("/transfer-requests/<int:request_id>/reject", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def reject_transfer_request(request_id):
    """Reject a transfer request"""
    # Verify user is from MAIN hub
    if current_user.assigned_location:
        user_depot = Depot.query.get(current_user.assigned_location_id)
        if not user_depot or user_depot.hub_type != 'MAIN':
            flash("Only MAIN hub staff can reject transfer requests.", "danger")
            return redirect(url_for("dashboard"))
    
    transfer_request = TransferRequest.query.get_or_404(request_id)
    
    if transfer_request.status != 'PENDING':
        flash("This transfer request has already been reviewed.", "warning")
        return redirect(url_for("transfer_requests"))
    
    # Update transfer request status
    transfer_request.status = 'REJECTED'
    transfer_request.reviewed_by = current_user.id
    transfer_request.reviewed_at = datetime.utcnow()
    
    db.session.commit()
    
    from_depot = transfer_request.from_location
    to_depot = transfer_request.to_location
    item = transfer_request.item
    
    flash(f"Transfer request rejected. {transfer_request.quantity} units of {item.name} from {from_depot.name} to {to_depot.name}.", "warning")
    return redirect(url_for("transfer_requests"))

# ---------- NEEDS LIST ROUTES ----------

@app.route("/needs-lists")
@login_required
def needs_lists():
    """View needs lists - different views based on user role and hub type"""
    user_depot = None
    if current_user.assigned_location_id:
        user_depot = Depot.query.get(current_user.assigned_location_id)
    
    # Sub-Hub User view: All relevant statuses for their Sub-Hub
    if current_user.has_role(ROLE_SUB_HUB_USER):
        if not current_user.assigned_location_id:
            flash("You must be assigned to a hub to view needs lists.", "danger")
            return redirect(url_for("warehouse_dashboard"))
        
        assigned_hub = Depot.query.get(current_user.assigned_location_id)
        if not assigned_hub or assigned_hub.hub_type != 'SUB':
            flash("Needs list access is only available for Sub-Hub assignments.", "danger")
            return redirect(url_for("warehouse_dashboard"))
        
        # Show all needs lists where their Sub-Hub is the fulfilment/dispatch hub OR the requesting hub
        # This ensures Sub-Hub users see lists they're involved with (either as source or requester)
        hub_needs_lists = db.session.query(NeedsList).outerjoin(
            NeedsListFulfilment, NeedsList.id == NeedsListFulfilment.needs_list_id
        ).filter(
            db.or_(
                NeedsListFulfilment.source_hub_id == assigned_hub.id,
                NeedsList.agency_hub_id == assigned_hub.id
            ),
            NeedsList.status.in_(['Submitted', 'Fulfilment Prepared', 'Awaiting Approval', 'Approved', 'Resent for Dispatch', 'Dispatched', 'Received', 'Completed'])
        ).distinct().order_by(NeedsList.updated_at.desc()).all()
        
        # Organize lists by status for better UI presentation
        approved_lists = [nl for nl in hub_needs_lists if nl.status in ['Approved', 'Resent for Dispatch']]
        dispatched_lists = [nl for nl in hub_needs_lists if nl.status == 'Dispatched']
        received_lists = [nl for nl in hub_needs_lists if nl.status == 'Received']
        completed_lists = [nl for nl in hub_needs_lists if nl.status == 'Completed']
        
        return render_template("warehouse_needs_lists.html", 
                             approved_lists=approved_lists,
                             dispatched_lists=dispatched_lists,
                             received_lists=received_lists,
                             completed_lists=completed_lists,
                             assigned_hub=assigned_hub)
    
    # Role-based views for Logistics Officers and Managers
    elif current_user.has_role(ROLE_LOGISTICS_OFFICER):
        # Logistics Officer view: All submitted needs lists awaiting fulfilment preparation
        submitted_lists = NeedsList.query.filter_by(status='Submitted').order_by(NeedsList.submitted_at.desc()).all()
        # Draft Fulfilments: Show ALL drafts (not just their own) for visibility and collaboration
        draft_fulfilments = NeedsList.query.filter_by(status='Fulfilment Prepared').order_by(NeedsList.updated_at.desc()).all()
        # Their prepared lists that are awaiting approval (submitted for approval)
        awaiting_lists = NeedsList.query.filter_by(status='Awaiting Approval').filter_by(prepared_by=current_user.display_name).order_by(NeedsList.prepared_at.desc()).all()
        # Approved for Dispatch: Lists approved by Manager and ready for dispatch
        approved_lists = NeedsList.query.filter_by(status='Approved').order_by(NeedsList.approved_at.desc()).all()
        return render_template("logistics_officer_needs_lists.html", submitted_lists=submitted_lists, draft_fulfilments=draft_fulfilments, awaiting_lists=awaiting_lists, approved_lists=approved_lists)
    
    elif current_user.has_role(ROLE_LOGISTICS_MANAGER):
        # Logistics Manager view: Can do EVERYTHING - prepare AND approve
        submitted_lists = NeedsList.query.filter_by(status='Submitted').order_by(NeedsList.submitted_at.desc()).all()
        # Draft Fulfilments: Show ALL drafts for review and editing
        draft_fulfilments = NeedsList.query.filter_by(status='Fulfilment Prepared').order_by(NeedsList.updated_at.desc()).all()
        # Awaiting Approval: Only those ready for final approval (Officer submitted them)
        awaiting_approval = NeedsList.query.filter_by(status='Awaiting Approval').order_by(NeedsList.prepared_at.desc()).all()
        approved_lists = NeedsList.query.filter(NeedsList.status.in_(['Approved', 'Dispatched', 'Received', 'Completed'])).order_by(NeedsList.approved_at.desc()).limit(20).all()
        rejected_lists = NeedsList.query.filter_by(status='Rejected').order_by(NeedsList.updated_at.desc()).limit(20).all()
        return render_template("logistics_manager_needs_lists.html", submitted_lists=submitted_lists, draft_fulfilments=draft_fulfilments, awaiting_approval=awaiting_approval, approved_lists=approved_lists, rejected_lists=rejected_lists)
    
    # Hub-based views for AGENCY and SUB hubs
    elif user_depot and user_depot.hub_type in ['AGENCY', 'SUB']:
        # AGENCY/SUB hub view: See only their own needs lists
        lists = NeedsList.query.filter_by(agency_hub_id=user_depot.id).order_by(NeedsList.created_at.desc()).all()
        return render_template("agency_needs_lists.html", needs_lists=lists, user_depot=user_depot)
    
    else:
        # Admin or other users: See all needs lists
        all_lists = NeedsList.query.order_by(NeedsList.created_at.desc()).all()
        return render_template("all_needs_lists.html", needs_lists=all_lists)

@app.route("/needs-lists/create", methods=["GET", "POST"])
@login_required
def needs_list_create():
    """Create a new needs list - AGENCY and SUB hubs only"""
    # Verify user is from AGENCY or SUB hub
    if not current_user.assigned_location_id:
        flash("You must be assigned to an AGENCY or SUB hub to create needs lists.", "danger")
        return redirect(url_for("dashboard"))
    
    user_depot = Depot.query.get(current_user.assigned_location_id)
    if not user_depot or user_depot.hub_type not in ['AGENCY', 'SUB']:
        flash("Only AGENCY and SUB hub staff can create needs lists.", "danger")
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        event_id = request.form.get("event_id") or None
        priority = request.form.get("priority", "Medium")
        notes = request.form.get("notes", "").strip() or None
        
        # Parse items from form - collect all item_sku_* keys to handle gaps from removed rows
        items_data = []
        item_indices = set()
        for key in request.form.keys():
            if key.startswith("item_sku_"):
                try:
                    index = int(key.split("_")[-1])
                    item_indices.add(index)
                except ValueError:
                    continue
        
        # Process each item by index
        for item_index in sorted(item_indices):
            sku = request.form.get(f"item_sku_{item_index}", "").strip()
            if sku:
                try:
                    qty_str = request.form.get(f"item_qty_{item_index}", "0").strip()
                    requested_qty = int(qty_str) if qty_str else 0
                    justification = request.form.get(f"item_justification_{item_index}", "").strip() or None
                    
                    if requested_qty > 0:
                        items_data.append({
                            'sku': sku,
                            'requested_qty': requested_qty,
                            'justification': justification
                        })
                except ValueError:
                    flash(f"Invalid quantity for item {sku}.", "danger")
                    return redirect(url_for("needs_list_create"))
        
        if not items_data:
            flash("At least one item with quantity is required.", "danger")
            return redirect(url_for("needs_list_create"))
        
        # Create needs list
        needs_list = NeedsList(
            list_number=generate_needs_list_number(),
            agency_hub_id=user_depot.id,
            event_id=int(event_id) if event_id else None,
            status="Draft",
            priority=priority,
            notes=notes,
            created_by=current_user.display_name
        )
        db.session.add(needs_list)
        db.session.flush()
        
        # Add items
        for item_data in items_data:
            needs_list_item = NeedsListItem(
                needs_list_id=needs_list.id,
                item_sku=item_data['sku'],
                requested_qty=item_data['requested_qty'],
                justification=item_data['justification']
            )
            db.session.add(needs_list_item)
        
        db.session.commit()
        
        flash(f"Needs list {needs_list.list_number} created successfully.", "success")
        return redirect(url_for("needs_list_details", list_id=needs_list.id))
    
    # GET request
    events = DisasterEvent.query.filter_by(status="Active").order_by(DisasterEvent.start_date.desc()).all()
    items = Item.query.order_by(Item.name).all()
    
    return render_template("needs_list_form.html", events=events, items=items, user_depot=user_depot)

@app.route("/needs-lists/<int:list_id>")
@login_required
def needs_list_details(list_id):
    """View needs list details"""
    # Eagerly load fulfilments and users to avoid lazy loading issues
    needs_list = NeedsList.query.options(
        db.joinedload(NeedsList.fulfilments).joinedload(NeedsListFulfilment.source_hub),
        db.joinedload(NeedsList.dispatched_by_user),
        db.joinedload(NeedsList.received_by_user)
    ).get_or_404(list_id)
    
    # Permission check using centralized helper
    allowed, error_msg = can_view_needs_list(current_user, needs_list)
    if not allowed:
        flash(error_msg, "danger")
        return redirect(url_for("dashboard"))
    
    # Get user depot if assigned
    user_depot = None
    if current_user.assigned_location_id:
        user_depot = Depot.query.get(current_user.assigned_location_id)
    
    # Get MAIN hubs for submission (if draft and owned by agency/sub hub)
    main_hubs = []
    if user_depot and user_depot.hub_type in ['AGENCY', 'SUB'] and needs_list.status == 'Draft' and user_depot.id == needs_list.agency_hub_id:
        main_hubs = Depot.query.filter_by(hub_type='MAIN').order_by(Depot.name).all()
    
    # Get stock availability for logistics staff
    stock_map = {}
    if current_user.has_any_role(ROLE_ADMIN, ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER):
        stock_map = get_stock_by_location()
    
    # Prepare completed context for enhanced Completed view
    completed_context = None
    if needs_list.status == 'Completed':
        completed_context = prepare_completed_context(needs_list, current_user)
    
    # Compute dispatch summary for Dispatched/Received views
    dispatch_summary = None
    if needs_list.status in ['Dispatched', 'Received']:
        dispatch_summary = compute_dispatch_summary(needs_list)
    
    # Build comprehensive line items payload with all metrics computed server-side
    # This is the single source of truth for allocation data
    line_items = []
    summary_counts = {'fully_allocated': 0, 'partially_allocated': 0, 'unallocated': 0}
    
    for item_entry in needs_list.items:
        # Calculate allocated quantity and build fulfilments list from database
        allocated_qty = 0
        fulfilments_list = []
        
        for fulfilment in needs_list.fulfilments:
            if fulfilment.item_sku == item_entry.item_sku:
                allocated_qty += fulfilment.allocated_qty
                fulfilments_list.append({
                    'source_hub_name': fulfilment.source_hub.name,
                    'source_hub_id': fulfilment.source_hub_id,
                    'allocated_qty': fulfilment.allocated_qty
                })
        
        # Calculate derived metrics
        requested_qty = item_entry.requested_qty
        remaining_qty = max(requested_qty - allocated_qty, 0)
        fulfillment_pct = int((allocated_qty / requested_qty * 100)) if requested_qty > 0 else 0
        
        # Build metrics dict for status helper
        item_metrics = {
            'requested_qty': requested_qty,
            'allocated_qty': allocated_qty,
            'dispatched_qty': allocated_qty,  # In current impl, dispatched = allocated
            'received_qty': allocated_qty if needs_list.status in ['Received', 'Completed'] else 0
        }
        
        # Get centralized status
        item_status = get_line_item_status(needs_list, item_metrics)
        
        # Update summary counts based on allocation status
        if allocated_qty == 0:
            summary_counts['unallocated'] += 1
        elif allocated_qty < requested_qty:
            summary_counts['partially_allocated'] += 1
        else:
            summary_counts['fully_allocated'] += 1
        
        # Build comprehensive line item payload
        line_items.append({
            'id': item_entry.id,
            'item_name': item_entry.item.name,
            'item_sku': item_entry.item_sku,
            'unit': item_entry.item.unit,
            'justification': item_entry.justification,
            'requested_qty': requested_qty,
            'allocated_qty': allocated_qty,
            'remaining_qty': remaining_qty,
            'fulfillment_pct': fulfillment_pct,
            'fulfilments': fulfilments_list,
            'status': item_status
        })
    
    # Get consistent header status display
    header_status = get_needs_list_status_display(needs_list)
    
    # Check if current user can dispatch this needs list (for hub users and admins)
    can_dispatch = False
    if needs_list.status in ['Approved', 'Resent for Dispatch']:
        # Use the new can_dispatch_from_hub helper which includes all operational roles
        can_dispatch, _ = can_dispatch_from_hub(current_user, needs_list)
    
    # Fetch change requests for this needs list
    change_requests = FulfilmentChangeRequest.query.filter_by(
        needs_list_id=needs_list.id
    ).options(
        db.joinedload(FulfilmentChangeRequest.requested_by),
        db.joinedload(FulfilmentChangeRequest.requesting_hub),
        db.joinedload(FulfilmentChangeRequest.reviewed_by)
    ).order_by(FulfilmentChangeRequest.created_at.desc()).all()
    
    return render_template("needs_list_details.html", 
                         needs_list=needs_list, 
                         user_depot=user_depot, 
                         stock_map=stock_map, 
                         main_hubs=main_hubs,
                         completed_context=completed_context,
                         dispatch_summary=dispatch_summary,
                         line_items=line_items,
                         summary_counts=summary_counts,
                         header_status=header_status,
                         can_dispatch=can_dispatch,
                         change_requests=change_requests)

@app.route("/needs-lists/<int:list_id>/submit", methods=["POST"])
@login_required
def needs_list_submit(list_id):
    """Submit needs list for logistics review - AGENCY and SUB hubs only"""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    # Permission check using centralized helper
    allowed, error_msg = can_submit_needs_list(current_user, needs_list)
    if not allowed:
        flash(error_msg, "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # Submit for logistics review
    needs_list.status = 'Submitted'
    needs_list.submitted_at = datetime.utcnow()
    db.session.commit()
    
    # Create notification for agency hub users
    create_notification_for_agency_hub(
        needs_list=needs_list,
        title="Needs List Submitted",
        message=f"Your needs list {needs_list.list_number} has been submitted for ODPEM review.",
        notification_type="submitted",
        triggered_by_user=current_user
    )
    
    # Notify Logistics Officers about new submission to prepare
    create_notifications_for_role(
        role=ROLE_LOGISTICS_OFFICER,
        title="New Needs List Submitted",
        message=f"Needs list {needs_list.list_number} from {needs_list.agency_hub.name} needs fulfillment preparation.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}/prepare",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "submitted_by": current_user.display_name,
            "submitted_by_id": current_user.id
        },
        needs_list_id=needs_list.id
    )
    
    # Notify Logistics Managers about new submission for oversight
    create_notifications_for_role(
        role=ROLE_LOGISTICS_MANAGER,
        title="New Needs List Submitted",
        message=f"Needs list {needs_list.list_number} submitted by {needs_list.agency_hub.name} for review.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "submitted_by": current_user.display_name,
            "submitted_by_id": current_user.id
        },
        needs_list_id=needs_list.id
    )
    
    # Notify Admins about new needs list submissions for system monitoring
    create_notifications_for_role(
        role=ROLE_ADMIN,
        title="Needs List Submitted",
        message=f"New needs list {needs_list.list_number} submitted by {needs_list.agency_hub.name} for system monitoring.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "submitted_by": current_user.display_name,
            "submitted_by_id": current_user.id,
            "event_type": "system_monitoring"
        },
        needs_list_id=needs_list.id
    )
    
    flash(f"Needs list {needs_list.list_number} submitted successfully for logistics review.", "success")
    return redirect(url_for("needs_list_details", list_id=list_id))

@app.route("/needs-lists/<int:list_id>/edit", methods=["GET", "POST"])
@login_required
def needs_list_edit(list_id):
    """Edit a draft needs list - AGENCY and SUB hubs only"""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    # Permission check using centralized helper
    allowed, error_msg = can_edit_needs_list(current_user, needs_list)
    if not allowed:
        flash(error_msg, "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # Get user depot
    user_depot = Depot.query.get(current_user.assigned_location_id)
    if not user_depot or user_depot.hub_type not in ['AGENCY', 'SUB']:
        flash("Only AGENCY and SUB hub staff can edit needs lists.", "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    if request.method == "POST":
        event_id = request.form.get("event_id") or None
        priority = request.form.get("priority", "Medium")
        notes = request.form.get("notes", "").strip() or None
        
        # Parse items from form - collect all item_sku_* keys to handle gaps from removed rows
        items_data = []
        item_indices = set()
        for key in request.form.keys():
            if key.startswith("item_sku_"):
                try:
                    index = int(key.split("_")[-1])
                    item_indices.add(index)
                except ValueError:
                    continue
        
        # Process each item by index
        for item_index in sorted(item_indices):
            sku = request.form.get(f"item_sku_{item_index}", "").strip()
            if sku:
                try:
                    qty_str = request.form.get(f"item_qty_{item_index}", "0").strip()
                    requested_qty = int(qty_str) if qty_str else 0
                    justification = request.form.get(f"item_justification_{item_index}", "").strip() or None
                    
                    if requested_qty > 0:
                        items_data.append({
                            'sku': sku,
                            'requested_qty': requested_qty,
                            'justification': justification
                        })
                except ValueError:
                    flash(f"Invalid quantity for item {sku}.", "danger")
                    return redirect(url_for("needs_list_edit", list_id=list_id))
        
        if not items_data:
            flash("At least one item with quantity is required.", "danger")
            return redirect(url_for("needs_list_edit", list_id=list_id))
        
        # Update needs list metadata
        needs_list.event_id = int(event_id) if event_id else None
        needs_list.priority = priority
        needs_list.notes = notes
        needs_list.updated_at = datetime.utcnow()
        
        # Delete existing items and add updated ones
        NeedsListItem.query.filter_by(needs_list_id=needs_list.id).delete()
        db.session.flush()
        
        # Add updated items
        for item_data in items_data:
            needs_list_item = NeedsListItem(
                needs_list_id=needs_list.id,
                item_sku=item_data['sku'],
                requested_qty=item_data['requested_qty'],
                justification=item_data['justification']
            )
            db.session.add(needs_list_item)
        
        # Save as draft
        db.session.commit()
        flash(f"Needs list {needs_list.list_number} saved as draft. Review below and submit when ready.", "success")
        
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # GET request - show form with existing values
    events = DisasterEvent.query.filter_by(status="Active").order_by(DisasterEvent.start_date.desc()).all()
    items = Item.query.order_by(Item.name).all()
    
    return render_template("needs_list_form.html", 
                          events=events, 
                          items=items, 
                          user_depot=user_depot,
                          needs_list=needs_list,
                          is_edit=True)

@app.route("/needs-lists/<int:list_id>/prepare", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER)
def needs_list_prepare(list_id):
    """Prepare/edit fulfilment for a needs list - Logistics Officers and Managers"""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    # Permission check using centralized helper
    allowed, error_msg = can_prepare_fulfilment(current_user, needs_list)
    if not allowed:
        flash(error_msg, "warning")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # Get lock status before processing
    lock_status = get_lock_status(needs_list, current_user)
    
    if request.method == "POST":
        # Verify current user holds the lock before allowing editing
        if lock_status['is_locked'] and not lock_status['is_locked_by_current_user']:
            flash(lock_status['lock_message'], "warning")
            return redirect(url_for("needs_list_details", list_id=list_id))
        
        # Verify lock hasn't expired
        if lock_status['is_locked_by_current_user'] and is_lock_expired(needs_list):
            flash("Your editing session has expired. Please reload the page to continue.", "warning")
            return redirect(url_for("needs_list_prepare", list_id=list_id))
        fulfilment_notes = request.form.get("fulfilment_notes", "").strip() or None
        
        # Get current stock availability for validation
        stock_map = get_stock_by_location()
        
        # Delete existing fulfilment allocations if re-preparing
        NeedsListFulfilment.query.filter_by(needs_list_id=needs_list.id).delete(synchronize_session=False)
        db.session.flush()
        
        # Parse fulfilment allocations from form
        allocations_created = 0
        item_index = 0
        while True:
            sku_field = f"item_sku_{item_index}"
            if sku_field not in request.form:
                break
            
            sku = request.form.get(sku_field)
            if sku:
                # Get all depot allocations for this item
                depot_index = 0
                while True:
                    depot_field = f"depot_{item_index}_{depot_index}"
                    qty_field = f"qty_{item_index}_{depot_index}"
                    
                    if depot_field not in request.form:
                        break
                    
                    depot_id = request.form.get(depot_field)
                    qty_str = request.form.get(qty_field, "0").strip()
                    
                    if depot_id and qty_str:
                        try:
                            allocated_qty = int(qty_str)
                            if allocated_qty > 0:
                                depot_id_int = int(depot_id)
                                
                                # Validate against available stock
                                available_stock = stock_map.get((sku, depot_id_int), 0)
                                if allocated_qty > available_stock:
                                    item = Item.query.filter_by(sku=sku).first()
                                    depot = Depot.query.get(depot_id_int)
                                    item_name = item.name if item else sku
                                    depot_name = depot.name if depot else f"Hub #{depot_id}"
                                    flash(
                                        f"Cannot allocate {allocated_qty} units of {item_name} from {depot_name}. "
                                        f"Only {available_stock} units available.",
                                        "danger"
                                    )
                                    return redirect(url_for("needs_list_prepare", list_id=list_id))
                                
                                fulfilment = NeedsListFulfilment(
                                    needs_list_id=needs_list.id,
                                    item_sku=sku,
                                    source_hub_id=depot_id_int,
                                    allocated_qty=allocated_qty
                                )
                                db.session.add(fulfilment)
                                allocations_created += 1
                        except ValueError:
                            flash(f"Invalid quantity for item {sku}.", "danger")
                            return redirect(url_for("needs_list_prepare", list_id=list_id))
                    
                    depot_index += 1
            
            item_index += 1
        
        if allocations_created == 0:
            flash("At least one allocation is required.", "danger")
            return redirect(url_for("needs_list_prepare", list_id=list_id))
        
        # Determine which action was requested: "save_draft", "submit", or "approve"
        action = request.form.get("action", "submit")
        is_manager = current_user.has_role(ROLE_LOGISTICS_MANAGER)
        
        if action == "save_draft":
            # Save as Draft - both Officer and Manager can do this
            needs_list.status = 'Fulfilment Prepared'
            needs_list.draft_saved_by = current_user.display_name
            needs_list.draft_saved_at = datetime.utcnow()
            needs_list.fulfilment_notes = fulfilment_notes
            
            # Extend lock to keep editing session active
            extend_lock(needs_list, current_user)
            
            db.session.commit()
            
            flash(f"Draft saved successfully. Last saved by {current_user.display_name}.", "success")
            return redirect(url_for("needs_list_prepare", list_id=list_id))
        
        elif action == "approve" and is_manager:
            # Check if this is editing due to a change request (via form parameter)
            editing_change_request_id = request.form.get("change_request_id", type=int)
            
            if editing_change_request_id:
                # This is a resend after change request
                adjustment_reason = request.form.get("adjustment_reason", "").strip()
                
                if not adjustment_reason:
                    flash("Adjustment reason is required when updating fulfilment via change request.", "danger")
                    return redirect(url_for("needs_list_prepare", list_id=list_id, change_request_id=editing_change_request_id))
                
                # Get change request
                change_request = FulfilmentChangeRequest.query.get_or_404(editing_change_request_id)
                
                # Capture BEFORE snapshot by loading the CURRENT fulfilments before we save the new ones
                # Note: We deleted and recreated fulfilments earlier in this POST, so we need to
                # reconstruct the before state from the last version or original approval
                # For now, we'll note this is the "after" state and before was the approved state
                # TODO: Capture true before state - for v1 we'll just note the change
                
                # Create after snapshot from current (newly created) fulfilments
                updated_fulfilments = NeedsListFulfilment.query.filter_by(needs_list_id=needs_list.id).all()
                after_snapshot = {
                    "items": [],
                    "status": 'Resent for Dispatch',
                    "fulfilment_notes": fulfilment_notes
                }
                for fulfilment in updated_fulfilments:
                    after_snapshot["items"].append({
                        "item_sku": fulfilment.item_sku,
                        "source_hub_id": fulfilment.source_hub_id,
                        "source_hub_name": fulfilment.source_hub.name,
                        "allocated_qty": fulfilment.allocated_qty
                    })
                
                # Create a minimal before snapshot (we don't have the exact before state in this flow)
                before_snapshot = {
                    "items": [],
                    "status": needs_list.status,
                    "fulfilment_notes": needs_list.fulfilment_notes,
                    "note": "Before state not captured - this represents the state after Manager adjustment"
                }
                
                # Get next version number
                last_version = NeedsListFulfilmentVersion.query.filter_by(
                    needs_list_id=needs_list.id
                ).order_by(NeedsListFulfilmentVersion.version_number.desc()).first()
                next_version = (last_version.version_number + 1) if last_version else 1
                
                # Create version record
                version = NeedsListFulfilmentVersion(
                    needs_list_id=needs_list.id,
                    version_number=next_version,
                    change_request_id=editing_change_request_id,
                    adjusted_by_id=current_user.id,
                    adjusted_at=datetime.utcnow(),
                    adjustment_reason=adjustment_reason,
                    fulfilment_snapshot_before=before_snapshot,
                    fulfilment_snapshot_after=after_snapshot,
                    status_before=needs_list.status,
                    status_after='Resent for Dispatch'
                )
                db.session.add(version)
                
                # Update change request status and mark as reviewed
                change_request.status = 'Approved & Resent'
                if not change_request.reviewed_by_id:
                    change_request.reviewed_by_id = current_user.id
                    change_request.reviewed_at = datetime.utcnow()
                
                # Set needs list status to Resent for Dispatch
                needs_list.status = 'Resent for Dispatch'
                needs_list.approved_by = current_user.display_name
                needs_list.approved_at = datetime.utcnow()
                needs_list.fulfilment_notes = fulfilment_notes
                
                # Clear draft fields
                needs_list.draft_saved_by = None
                needs_list.draft_saved_at = None
                
                # Release lock
                release_lock(needs_list, current_user)
                
                db.session.commit()
                
                # Notify Sub-Hub users at the requesting hub
                requesting_hub_id = change_request.requesting_hub_id
                sub_hub_users = User.query.join(
                    UserRole, User.id == UserRole.user_id
                ).join(
                    Role, UserRole.role_id == Role.id
                ).filter(
                    Role.code == ROLE_SUB_HUB_USER,
                    User.assigned_location_id == requesting_hub_id
                ).all()
                
                sub_hub_user_ids = [user.id for user in sub_hub_users]
                create_notifications_for_users(
                    user_ids=sub_hub_user_ids,
                    title="Updated Fulfilment Received",
                    message=f"Updated fulfilment for needs list {needs_list.list_number} has been resent. Review and dispatch as required.",
                    notification_type="success",
                    link_url=f"/needs-lists/{needs_list.id}",
                    payload_data={
                        "needs_list_number": needs_list.list_number,
                        "updated_by": current_user.display_name,
                        "adjustment_reason": adjustment_reason
                    },
                    needs_list_id=needs_list.id
                )
                
                flash(f"Fulfilment updated and resent to {change_request.requesting_hub.name}. Warehouse team has been notified.", "success")
            else:
                # Normal approval (not from change request)
                needs_list.status = 'Approved'
                
                # Preserve Officer's preparation info if it exists, otherwise set Manager as preparer
                if not needs_list.prepared_by or not needs_list.prepared_at:
                    needs_list.prepared_by = current_user.display_name
                    needs_list.prepared_at = datetime.utcnow()
                
                needs_list.approved_by = current_user.display_name
                needs_list.approved_at = datetime.utcnow()
                needs_list.fulfilment_notes = fulfilment_notes
                
                # Clear draft fields on final approval
                needs_list.draft_saved_by = None
                needs_list.draft_saved_at = None
                
                # Release lock on completion
                release_lock(needs_list, current_user)
                
                db.session.commit()
                
                flash(f"Needs list {needs_list.list_number} approved successfully. Ready for dispatch.", "success")
        
        else:
            # Logistics Officer: Submit for manager approval (default action)
            needs_list.status = 'Awaiting Approval'
            needs_list.prepared_by = current_user.display_name
            needs_list.prepared_at = datetime.utcnow()
            needs_list.fulfilment_notes = fulfilment_notes
            
            # Clear draft fields on submission
            needs_list.draft_saved_by = None
            needs_list.draft_saved_at = None
            
            # Release lock on completion
            release_lock(needs_list, current_user)
            
            db.session.commit()
            
            # Notify Logistics Managers about approval needed
            create_notifications_for_role(
                role=ROLE_LOGISTICS_MANAGER,
                title="Approval Needed",
                message=f"Needs list {needs_list.list_number} from {needs_list.agency_hub.name} is ready for your approval.",
                notification_type="approval_needed",
                link_url=f"/needs-lists/{needs_list.id}",
                payload_data={
                    "needs_list_number": needs_list.list_number,
                    "agency_hub": needs_list.agency_hub.name,
                    "prepared_by": current_user.display_name,
                    "prepared_by_id": current_user.id
                },
                needs_list_id=needs_list.id
            )
            
            flash(f"Fulfilment for {needs_list.list_number} prepared and submitted for manager approval.", "success")
        
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # GET request: Show fulfilment preparation form
    # Check if this is triggered by a change request (via parameter OR detect active ones)
    change_request_id = request.args.get("change_request_id", type=int)
    change_request = None
    
    # If no change_request_id parameter, check for active Pending Review requests
    if not change_request_id:
        active_request = FulfilmentChangeRequest.query.filter_by(
            needs_list_id=needs_list.id,
            status='Pending Review'
        ).first()
        if active_request:
            change_request = active_request
            change_request_id = active_request.id
    else:
        change_request = FulfilmentChangeRequest.query.get_or_404(change_request_id)
    
    if change_request:
        # Verify the change request belongs to this needs list
        if change_request.needs_list_id != needs_list.id:
            flash("Invalid change request.", "danger")
            return redirect(url_for("needs_list_details", list_id=list_id))
        
        # Only Logistics Managers can edit via change request
        if not current_user.has_role(ROLE_LOGISTICS_MANAGER):
            flash("Only Logistics Managers can edit fulfilments via change requests.", "danger")
            return redirect(url_for("needs_list_details", list_id=list_id))
        
        # Transition change request to 'In Progress' when Manager opens editor
        # Don't set reviewed_by/at yet - only when they commit a decision
        if change_request.status == 'Pending Review':
            change_request.status = 'In Progress'
            db.session.commit()
            flash("You are now editing this fulfilment in response to a change request.", "info")
    
    # Attempt to acquire lock for editing
    success, message = acquire_lock(needs_list, current_user)
    
    if success:
        db.session.commit()  # Commit lock acquisition
    else:
        # Another user holds the lock - show read-only view with message
        flash(message, "info")
    
    # Get lock status after acquisition attempt for UI rendering
    lock_status = get_lock_status(needs_list, current_user)
    
    # Get stock availability across all MAIN and SUB hubs
    stock_map = get_stock_by_location()
    odpem_hubs = Depot.query.filter(Depot.hub_type.in_(['MAIN', 'SUB'])).order_by(Depot.name).all()
    
    # Get existing fulfilment allocations if editing
    existing_fulfilments = NeedsListFulfilment.query.filter_by(needs_list_id=needs_list.id).all()
    
    # Organize existing allocations by item_sku -> {source_hub_id: allocated_qty}
    existing_allocations = {}
    for fulfilment in existing_fulfilments:
        if fulfilment.item_sku not in existing_allocations:
            existing_allocations[fulfilment.item_sku] = {}
        existing_allocations[fulfilment.item_sku][fulfilment.source_hub_id] = fulfilment.allocated_qty
    
    return render_template("needs_list_prepare.html", 
                         needs_list=needs_list, 
                         stock_map=stock_map, 
                         odpem_hubs=odpem_hubs,
                         existing_allocations=existing_allocations,
                         lock_status=lock_status,
                         change_request=change_request)

@app.route("/needs-lists/<int:list_id>/approve", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER)
def needs_list_approve(list_id):
    """Approve fulfilment and execute stock transfers - Logistics Managers only"""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    # Permission check using centralized helper
    allowed, error_msg = can_approve_fulfilment(current_user, needs_list)
    if not allowed:
        flash(error_msg, "warning")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    approval_notes = request.form.get("approval_notes", "").strip() or None
    
    # Verify fulfilment allocations exist
    fulfilments = NeedsListFulfilment.query.filter_by(needs_list_id=needs_list.id).all()
    
    if not fulfilments:
        flash("No fulfilment allocations found. Please prepare fulfilment first.", "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # Update needs list status to Approved (stock transfers will happen during dispatch)
    needs_list.status = 'Approved'
    needs_list.approved_by = current_user.display_name
    needs_list.approved_at = datetime.utcnow()
    needs_list.approval_notes = approval_notes
    db.session.commit()
    
    # Create notification for agency hub users
    create_notification_for_agency_hub(
        needs_list=needs_list,
        title="Needs List Approved",
        message=f"Your needs list {needs_list.list_number} has been approved by {current_user.display_name} and is ready for dispatch.",
        notification_type="approved",
        triggered_by_user=current_user
    )
    
    # Notify warehouse supervisors and officers at source hubs to prepare for dispatch
    create_notification_for_warehouse_users_at_source_hubs(
        needs_list=needs_list,
        title="New Approved Needs List Received",
        message=f"Needs List {needs_list.list_number} has been approved for dispatch at your Sub-Hub. Requested by {needs_list.agency_hub.name}, approved by {current_user.display_name}.",
        notification_type="task_assigned",
        triggered_by_user=current_user
    )
    
    flash(f"Needs list {needs_list.list_number} approved successfully. Ready for dispatch.", "success")
    return redirect(url_for("needs_list_details", list_id=list_id))

@app.route("/needs-lists/<int:list_id>/reject", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER)
def needs_list_reject(list_id):
    """Reject fulfilment - Logistics Managers only"""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    # Permission check using centralized helper
    allowed, error_msg = can_reject_fulfilment(current_user, needs_list)
    if not allowed:
        flash(error_msg, "warning")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    approval_notes = request.form.get("approval_notes", "").strip() or None
    
    # Delete fulfilment allocations and reset to submitted
    NeedsListFulfilment.query.filter_by(needs_list_id=needs_list.id).delete()
    
    needs_list.status = 'Submitted'
    needs_list.approved_by = current_user.display_name
    needs_list.approved_at = datetime.utcnow()
    needs_list.approval_notes = approval_notes
    needs_list.prepared_by = None
    needs_list.prepared_at = None
    needs_list.fulfilment_notes = None
    db.session.commit()
    
    flash(f"Fulfilment for {needs_list.list_number} rejected. Needs list returned to submitted status.", "warning")
    return redirect(url_for("needs_list_details", list_id=list_id))

@app.route("/needs-lists/<int:list_id>/dispatch", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_SUB_HUB_USER, ROLE_MAIN_HUB_USER, ROLE_INVENTORY_CLERK, ROLE_WAREHOUSE_SUPERVISOR)
def needs_list_dispatch(list_id):
    """Dispatch approved needs list - Creates stock transactions and updates status to Dispatched
    Authorized users: Admins, Logistics staff, Hub users (Main/Sub/Inventory Clerk), and legacy Warehouse Supervisors at source hubs."""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    # Permission check using centralized helper
    allowed, error_msg = can_dispatch_needs_list(current_user, needs_list)
    if not allowed:
        flash(error_msg, "warning")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    dispatch_notes = request.form.get("dispatch_notes", "").strip() or None
    
    # Verify fulfilment allocations exist
    fulfilments = NeedsListFulfilment.query.filter_by(needs_list_id=needs_list.id).all()
    if not fulfilments:
        flash("No fulfilment allocations found. Cannot dispatch.", "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # Validate stock availability before creating transactions
    requesting_hub = Depot.query.get(needs_list.agency_hub_id)
    stock_validation_errors = []
    
    for fulfilment in fulfilments:
        source_hub = Depot.query.get(fulfilment.source_hub_id)
        
        # Calculate current stock at source hub
        in_stock = db.session.query(func.sum(Transaction.qty)).filter(
            Transaction.item_sku == fulfilment.item_sku,
            Transaction.location_id == fulfilment.source_hub_id,
            Transaction.ttype == 'IN'
        ).scalar() or 0
        
        out_stock = db.session.query(func.sum(Transaction.qty)).filter(
            Transaction.item_sku == fulfilment.item_sku,
            Transaction.location_id == fulfilment.source_hub_id,
            Transaction.ttype == 'OUT'
        ).scalar() or 0
        
        available = in_stock - out_stock
        
        if available < fulfilment.allocated_qty:
            item = Item.query.get(fulfilment.item_sku)
            stock_validation_errors.append(
                f"{item.name} at {source_hub.name}: Requested {fulfilment.allocated_qty}, Available {available}"
            )
    
    if stock_validation_errors:
        flash("Insufficient stock to dispatch: " + "; ".join(stock_validation_errors), "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # Create stock movement transactions
    for fulfilment in fulfilments:
        source_hub = Depot.query.get(fulfilment.source_hub_id)
        
        # OUT transaction from source hub
        out_txn = Transaction(
            item_sku=fulfilment.item_sku,
            location_id=fulfilment.source_hub_id,
            ttype="OUT",
            qty=fulfilment.allocated_qty,
            created_by=current_user.display_name,
            notes=f"Dispatched for Needs List: {needs_list.list_number} to {requesting_hub.name}",
            event_id=needs_list.event_id
        )
        db.session.add(out_txn)
        
        # IN transaction to requesting hub
        in_txn = Transaction(
            item_sku=fulfilment.item_sku,
            location_id=needs_list.agency_hub_id,
            ttype="IN",
            qty=fulfilment.allocated_qty,
            created_by=current_user.display_name,
            notes=f"Dispatched from Needs List: {needs_list.list_number} from {source_hub.name}",
            event_id=needs_list.event_id
        )
        db.session.add(in_txn)
    
    # Update needs list status and dispatch tracking
    needs_list.status = 'Dispatched'
    needs_list.dispatched_by_id = current_user.id
    needs_list.dispatched_at = datetime.utcnow()
    needs_list.dispatch_notes = dispatch_notes
    
    # If not yet approved, mark as approved during dispatch
    if needs_list.status in ['Awaiting Approval', 'Fulfilment Prepared']:
        needs_list.approved_by = current_user.display_name
        needs_list.approved_at = datetime.utcnow()
    
    db.session.commit()
    
    # Create notification for agency hub users
    create_notification_for_agency_hub(
        needs_list=needs_list,
        title="Items Dispatched",
        message=f"Items for needs list {needs_list.list_number} have been dispatched by {current_user.display_name}. Please confirm receipt when items arrive.",
        notification_type="dispatched",
        triggered_by_user=current_user
    )
    
    # Notify Inventory Clerks about dispatch completion
    create_notifications_for_role(
        role=ROLE_INVENTORY_CLERK,
        title="Dispatch Completed",
        message=f"Needs list {needs_list.list_number} to {needs_list.agency_hub.name} has been dispatched.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "dispatched_by": current_user.display_name,
            "dispatched_by_id": current_user.id
        },
        needs_list_id=needs_list.id
    )
    
    # Notify Agency Hub users about items dispatched for receipt
    create_notifications_for_role(
        role=ROLE_AGENCY_HUB_USER,
        title="Items Dispatched to Your Hub",
        message=f"Items for needs list {needs_list.list_number} dispatched to {needs_list.agency_hub.name}. Please confirm receipt when items arrive.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "dispatched_by": current_user.display_name,
            "dispatched_by_id": current_user.id,
            "event_type": "dispatched_for_receipt"
        },
        needs_list_id=needs_list.id
    )
    
    flash(f"Needs list {needs_list.list_number} dispatched successfully. Stock transfers completed and {requesting_hub.name} will be notified.", "success")
    return redirect(url_for("needs_list_details", list_id=list_id))

@app.route("/needs-lists/<int:list_id>/confirm-receipt", methods=["POST"])
@login_required
def needs_list_confirm_receipt(list_id):
    """Confirm receipt of dispatched items - Agency Hub users only"""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    # Permission check using centralized helper
    allowed, error_msg = can_confirm_receipt(current_user, needs_list)
    if not allowed:
        flash(error_msg, "warning")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    receipt_notes = request.form.get("receipt_notes", "").strip() or None
    
    # Update needs list to Completed status
    needs_list.status = 'Completed'
    needs_list.received_by_id = current_user.id
    needs_list.received_at = datetime.utcnow()
    needs_list.receipt_notes = receipt_notes
    needs_list.fulfilled_at = datetime.utcnow()  # Mark as fully fulfilled
    
    db.session.commit()
    
    # Create notification for agency hub users
    create_notification_for_agency_hub(
        needs_list=needs_list,
        title="Receipt Confirmed",
        message=f"Receipt has been confirmed for needs list {needs_list.list_number} by {current_user.display_name}. Request is now completed.",
        notification_type="received",
        triggered_by_user=current_user
    )
    
    # Notify Auditors about completed transactions for audit trail review
    create_notifications_for_role(
        role=ROLE_AUDITOR,
        title="Needs List Completed",
        message=f"Needs list {needs_list.list_number} from {needs_list.agency_hub.name} has been completed and is ready for audit review.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "received_by": current_user.display_name,
            "received_by_id": current_user.id,
            "completed_at": format_datetime_iso_est(datetime.utcnow())
        },
        needs_list_id=needs_list.id
    )
    
    # Notify Logistics Managers about completion for oversight
    create_notifications_for_role(
        role=ROLE_LOGISTICS_MANAGER,
        title="Needs List Completed",
        message=f"Needs list {needs_list.list_number} to {needs_list.agency_hub.name} has been completed successfully.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "received_by": current_user.display_name,
            "received_by_id": current_user.id
        },
        needs_list_id=needs_list.id
    )
    
    # Notify Auditors about completed deliveries for oversight
    create_notifications_for_role(
        role=ROLE_AUDITOR,
        title="Supply Delivery Completed",
        message=f"Needs list {needs_list.list_number} delivery to {needs_list.agency_hub.name} has been successfully completed.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "event_type": "delivery_completed"
        },
        needs_list_id=needs_list.id
    )
    
    flash(f"Receipt confirmed for needs list {needs_list.list_number}. Request is now completed.", "success")
    return redirect(url_for("needs_list_details", list_id=list_id))

@app.route("/needs-lists/<int:list_id>/edit-completed", methods=["POST"])
@login_required
def edit_completed_fulfilment(list_id):
    """Edit completed fulfilment records (post-receipt corrections) - Logistics staff only
    
    This route allows authorized users (ADMIN, LOGISTICS_MANAGER, LOGISTICS_OFFICER) to make
    corrections to completed needs lists after receipt has been confirmed. All changes are
    audit-logged with session grouping.
    """
    from uuid import uuid4
    
    needs_list = NeedsList.query.get_or_404(list_id)
    
    # Permission check - Only ADMIN, LOGISTICS_MANAGER, LOGISTICS_OFFICER
    if not current_user.has_any_role(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER):
        flash("You don't have permission to edit completed fulfilments.", "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # Verify needs list is completed and receipt is confirmed
    if needs_list.status != 'Completed':
        flash("Only completed needs lists can be edited using this function.", "warning")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    if not needs_list.received_by_id:
        flash("Receipt must be confirmed before corrections can be made.", "warning")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # Generate session ID for grouping all edits from this save action
    edit_session_id = str(uuid4())
    edit_reason = request.form.get("edit_reason", "").strip()
    
    if not edit_reason:
        flash("Edit reason is required for audit trail.", "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    changes_made = []
    
    try:
        # Edit needs-list level fields
        
        # Dispatch notes
        new_dispatch_notes = request.form.get("dispatch_notes", "").strip() or None
        if new_dispatch_notes != needs_list.dispatch_notes:
            log_entry = FulfilmentEditLog(
                needs_list_id=needs_list.id,
                fulfilment_id=None,  # Needs-list level edit
                edit_session_id=edit_session_id,
                edited_by_id=current_user.id,
                field_name='dispatch_notes',
                value_before=needs_list.dispatch_notes or '',
                value_after=new_dispatch_notes or '',
                edit_reason=edit_reason
            )
            db.session.add(log_entry)
            needs_list.dispatch_notes = new_dispatch_notes
            changes_made.append("dispatch notes")
        
        # Receipt notes
        new_receipt_notes = request.form.get("receipt_notes", "").strip() or None
        if new_receipt_notes != needs_list.receipt_notes:
            log_entry = FulfilmentEditLog(
                needs_list_id=needs_list.id,
                fulfilment_id=None,
                edit_session_id=edit_session_id,
                edited_by_id=current_user.id,
                field_name='receipt_notes',
                value_before=needs_list.receipt_notes or '',
                value_after=new_receipt_notes or '',
                edit_reason=edit_reason
            )
            db.session.add(log_entry)
            needs_list.receipt_notes = new_receipt_notes
            changes_made.append("receipt notes")
        
        # Dispatched at
        new_dispatched_at_str = request.form.get("dispatched_at", "").strip()
        if new_dispatched_at_str:
            new_dispatched_at = datetime.strptime(new_dispatched_at_str, '%Y-%m-%dT%H:%M')
            if new_dispatched_at != needs_list.dispatched_at:
                log_entry = FulfilmentEditLog(
                    needs_list_id=needs_list.id,
                    fulfilment_id=None,
                    edit_session_id=edit_session_id,
                    edited_by_id=current_user.id,
                    field_name='dispatched_at',
                    value_before=str(needs_list.dispatched_at) if needs_list.dispatched_at else '',
                    value_after=str(new_dispatched_at),
                    edit_reason=edit_reason
                )
                db.session.add(log_entry)
                needs_list.dispatched_at = new_dispatched_at
                changes_made.append("dispatch date/time")
        
        # Received at
        new_received_at_str = request.form.get("received_at", "").strip()
        if new_received_at_str:
            new_received_at = datetime.strptime(new_received_at_str, '%Y-%m-%dT%H:%M')
            if new_received_at != needs_list.received_at:
                log_entry = FulfilmentEditLog(
                    needs_list_id=needs_list.id,
                    fulfilment_id=None,
                    edit_session_id=edit_session_id,
                    edited_by_id=current_user.id,
                    field_name='received_at',
                    value_before=str(needs_list.received_at) if needs_list.received_at else '',
                    value_after=str(new_received_at),
                    edit_reason=edit_reason
                )
                db.session.add(log_entry)
                needs_list.received_at = new_received_at
                changes_made.append("receipt date/time")
        
        # Edit fulfilment line item quantities
        fulfilment_ids = request.form.getlist("fulfilment_ids")
        for fulfilment_id in fulfilment_ids:
            fulfilment = NeedsListFulfilment.query.get(int(fulfilment_id))
            if fulfilment and fulfilment.needs_list_id == needs_list.id:
                new_qty_str = request.form.get(f"delivered_qty_{fulfilment_id}", "").strip()
                if new_qty_str:
                    new_qty = int(new_qty_str)
                    if new_qty != fulfilment.allocated_qty:
                        log_entry = FulfilmentEditLog(
                            needs_list_id=needs_list.id,
                            fulfilment_id=fulfilment.id,
                            edit_session_id=edit_session_id,
                            edited_by_id=current_user.id,
                            field_name='allocated_qty',
                            value_before=str(fulfilment.allocated_qty),
                            value_after=str(new_qty),
                            edit_reason=edit_reason
                        )
                        db.session.add(log_entry)
                        fulfilment.allocated_qty = new_qty
                        changes_made.append(f"delivered quantity for fulfilment #{fulfilment.id}")
        
        if changes_made:
            db.session.commit()
            flash(f"Corrections saved and audit-logged: {', '.join(changes_made)}. Session ID: {edit_session_id[:8]}...", "success")
        else:
            flash("No changes detected.", "info")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error saving corrections: {str(e)}", "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    return redirect(url_for("needs_list_details", list_id=list_id))

@app.route("/needs-lists/<int:list_id>/completed-report")
@login_required
def needs_list_completed_report(list_id):
    """Download PDF summary report for completed needs list - Agency Hub users and Admins"""
    needs_list = NeedsList.query.options(
        db.joinedload(NeedsList.fulfilments).joinedload(NeedsListFulfilment.source_hub),
        db.joinedload(NeedsList.dispatched_by_user),
        db.joinedload(NeedsList.received_by_user)
    ).get_or_404(list_id)
    
    # Permission check - Only agency hub users or admins can download
    if not current_user.has_role(ROLE_ADMIN):
        if not current_user.assigned_location_id or current_user.assigned_location_id != needs_list.agency_hub_id:
            flash("You don't have permission to download this report.", "danger")
            return redirect(url_for("needs_list_details", list_id=list_id))
    
    # Only allow for completed needs lists
    if needs_list.status != 'Completed':
        flash("PDF reports are only available for completed needs lists.", "warning")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # Prepare context for PDF rendering
    completed_context = prepare_completed_context(needs_list, current_user)
    
    # TODO: Implement PDF generation using WeasyPrint
    # For now, return a placeholder message
    flash("PDF download feature is coming soon. This will generate a comprehensive summary report.", "info")
    return redirect(url_for("needs_list_details", list_id=list_id))

@app.route("/needs-lists/<int:list_id>/delete", methods=["POST"])
@login_required
def needs_list_delete(list_id):
    """Delete a draft needs list - AGENCY hubs only"""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    # Permission check using centralized helper
    allowed, error_msg = can_delete_needs_list(current_user, needs_list)
    if not allowed:
        flash(error_msg, "danger")
        return redirect(url_for("needs_lists"))
    
    list_number = needs_list.list_number
    db.session.delete(needs_list)
    db.session.commit()
    
    flash(f"Needs list {list_number} deleted successfully.", "success")
    return redirect(url_for("needs_lists"))

@app.route("/needs-lists/<int:list_id>/request-change", methods=["POST"])
@role_required(ROLE_SUB_HUB_USER)
def fulfilment_change_request_create(list_id):
    """Create a fulfilment change request - Sub-Hub users only"""
    needs_list = NeedsList.query.get_or_404(list_id)
    
    if needs_list.status != 'Approved':
        flash("Change requests can only be made for approved needs lists.", "warning")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    if not current_user.assigned_location_id:
        flash("You must be assigned to a Sub-Hub to request fulfilment changes.", "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    assigned_hub = Depot.query.get(current_user.assigned_location_id)
    if not assigned_hub or assigned_hub.hub_type != 'SUB':
        flash("Only Sub-Hub warehouse users can request fulfilment changes.", "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    hub_fulfilments = NeedsListFulfilment.query.filter_by(
        needs_list_id=needs_list.id,
        source_hub_id=assigned_hub.id
    ).all()
    
    if not hub_fulfilments:
        flash(f"Your Sub-Hub ({assigned_hub.name}) has no fulfilment allocations for this needs list. Only hubs with assigned fulfilments can request changes.", "danger")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    request_comments = request.form.get("request_comments", "").strip()
    
    if not request_comments:
        flash("Please provide a reason for the fulfilment change request.", "warning")
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    change_request = FulfilmentChangeRequest(
        needs_list_id=needs_list.id,
        requesting_hub_id=assigned_hub.id,
        requested_by_id=current_user.id,
        request_comments=request_comments,
        status="Pending Review"
    )
    
    db.session.add(change_request)
    db.session.commit()
    
    import json
    
    create_notifications_for_role(
        role=ROLE_LOGISTICS_OFFICER,
        title="Fulfilment Change Requested",
        message=f"Fulfilment change requested by {current_user.display_name} at {assigned_hub.name} for needs list {needs_list.list_number}.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "requesting_hub": assigned_hub.name,
            "requested_by": current_user.display_name,
            "requested_by_id": current_user.id,
            "change_request_id": change_request.id
        },
        needs_list_id=needs_list.id
    )
    
    create_notifications_for_role(
        role=ROLE_LOGISTICS_MANAGER,
        title="Fulfilment Change Requested",
        message=f"Fulfilment change requested by {current_user.display_name} at {assigned_hub.name} for needs list {needs_list.list_number}.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "requesting_hub": assigned_hub.name,
            "requested_by": current_user.display_name,
            "requested_by_id": current_user.id,
            "change_request_id": change_request.id
        },
        needs_list_id=needs_list.id
    )
    
    flash(f"Change request submitted successfully. The Logistics team will review your request.", "success")
    return redirect(url_for("needs_list_details", list_id=list_id))

@app.route("/change-requests/<int:request_id>/process", methods=["POST"])
@role_required(ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER)
def fulfilment_change_request_process(request_id):
    """Process fulfilment change request - Logistics Officers and Managers only"""
    change_request = FulfilmentChangeRequest.query.get_or_404(request_id)
    
    # Allow processing of Pending Review or In Progress requests
    # In Progress means Manager opened editor but decided to reject/clarify instead
    if change_request.status not in ['Pending Review', 'In Progress']:
        flash("This change request has already been processed.", "warning")
        return redirect(url_for("needs_list_details", list_id=change_request.needs_list_id))
    
    action = request.form.get("action")
    review_comments = request.form.get("review_comments", "").strip()
    
    if not review_comments:
        flash("Please provide a response to the warehouse team.", "warning")
        return redirect(url_for("needs_list_details", list_id=change_request.needs_list_id))
    
    if action == "approve":
        # Only Logistics Managers can edit and resend fulfilments
        if not current_user.has_role(ROLE_LOGISTICS_MANAGER):
            flash("Only Logistics Managers can approve and update fulfilments. Please escalate to a Manager.", "warning")
            return redirect(url_for("needs_list_details", list_id=change_request.needs_list_id))
        
        # For approve action, redirect to edit fulfilment instead of just marking as approved
        change_request.review_comments = review_comments
        change_request.reviewed_by_id = current_user.id
        change_request.reviewed_at = datetime.utcnow()
        change_request.status = 'In Progress'
        db.session.commit()
        
        flash("Redirecting to edit fulfilment. Please adjust allocations and approve to resend to Sub-Hub.", "info")
        return redirect(url_for("needs_list_prepare", list_id=change_request.needs_list_id, change_request_id=change_request.id))
    
    elif action == "reject":
        change_request.status = 'Rejected'
        flash_message = "Change request rejected."
        notification_title = "Fulfilment Change Request Rejected"
        notification_message = f"Your change request for needs list {change_request.needs_list.list_number} has been rejected."
        notification_type = "alert"
    elif action == "clarify":
        change_request.status = 'Clarification Needed'
        flash_message = "Clarification requested from warehouse team."
        notification_title = "Clarification Needed on Change Request"
        notification_message = f"The Logistics team needs more information about your change request for needs list {change_request.needs_list.list_number}."
        notification_type = "info"
    else:
        flash("Invalid action.", "danger")
        return redirect(url_for("needs_list_details", list_id=change_request.needs_list_id))
    
    change_request.review_comments = review_comments
    change_request.reviewed_by_id = current_user.id
    change_request.reviewed_at = datetime.utcnow()
    
    db.session.commit()
    
    create_notifications_for_users(
        user_ids=[change_request.requested_by_id],
        title=notification_title,
        message=notification_message,
        notification_type=notification_type,
        link_url=f"/needs-lists/{change_request.needs_list_id}",
        payload_data={
            "needs_list_number": change_request.needs_list.list_number,
            "reviewed_by": current_user.display_name,
            "reviewed_by_id": current_user.id,
            "review_comments": review_comments,
            "change_request_id": change_request.id
        },
        needs_list_id=change_request.needs_list_id
    )
    
    flash(flash_message, "success")
    return redirect(url_for("needs_list_details", list_id=change_request.needs_list_id))

@app.route("/packages/<int:package_id>/fulfill", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def package_fulfill(package_id):
    """Fulfill distributor needs list by allocating stock from depots"""
    package = DistributionPackage.query.get_or_404(package_id)
    
    if package.status != "Draft":
        flash("Only draft packages can be fulfilled.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    if request.method == "POST":
        stock_map = get_stock_by_location()
        # Exclude AGENCY hubs from package fulfillment - they're independent agencies
        locations = Depot.query.filter(Depot.hub_type != 'AGENCY').all()
        
        # Process depot allocations for each item
        for pkg_item in package.items:
            # Clear existing allocations first
            PackageItemAllocation.query.filter_by(package_item_id=pkg_item.id).delete()
            
            depot_allocations = []
            total_allocated = 0
            
            for loc in locations:
                depot_field_name = f"depot_allocation_{pkg_item.id}_{loc.name.replace(' ', '_')}"
                depot_qty_str = request.form.get(depot_field_name, "").strip()
                
                if depot_qty_str:
                    depot_qty = int(depot_qty_str)
                    
                    if depot_qty > 0:
                        # Validate against depot stock
                        available_at_depot = stock_map.get((pkg_item.item_sku, loc.id), 0)
                        
                        if depot_qty > available_at_depot:
                            flash(f"Item {pkg_item.item.name}: Cannot allocate {depot_qty} from {loc.name}. Only {available_at_depot} available.", "danger")
                            return redirect(url_for("package_fulfill", package_id=package_id))
                        
                        depot_allocations.append({
                            'depot_id': loc.id,
                            'qty': depot_qty
                        })
                        total_allocated += depot_qty
            
            # Validate total allocation
            if total_allocated > pkg_item.requested_qty:
                flash(f"Item {pkg_item.item.name}: Total allocated ({total_allocated}) cannot exceed requested quantity ({pkg_item.requested_qty}).", "danger")
                return redirect(url_for("package_fulfill", package_id=package_id))
            
            # Update allocated quantity
            pkg_item.allocated_qty = total_allocated
            
            # Save depot allocations
            for depot_allocation in depot_allocations:
                allocation = PackageItemAllocation(
                    package_item_id=pkg_item.id,
                    depot_id=depot_allocation['depot_id'],
                    allocated_qty=depot_allocation['qty']
                )
                db.session.add(allocation)
        
        # Check if package is partial
        is_partial = any(item.allocated_qty < item.requested_qty for item in package.items)
        package.is_partial = is_partial
        package.updated_at = datetime.utcnow()
        
        # Record update in audit trail
        record_package_status_change(package, "Draft", "Draft", current_user.display_name, 
                                    "Depot allocations updated by inventory manager")
        
        db.session.commit()
        
        flash(f"Draft saved! Allocations for package {package.package_number} have been saved. You can continue editing or submit for review from the package details page.", "success")
        return redirect(url_for("package_details", package_id=package_id))
    
    # GET request - show fulfillment form
    items = Item.query.order_by(Item.name).all()
    # Exclude AGENCY hubs from package fulfillment - they're independent agencies
    locations = Depot.query.filter(Depot.hub_type != 'AGENCY').order_by(Depot.name).all()
    stock_map = get_stock_by_location()
    events = DisasterEvent.query.filter_by(status="Active").order_by(DisasterEvent.start_date.desc()).all()
    
    # Build filtered depot lists per package item (only show depots with stock > 0)
    item_depot_options = {}
    for pkg_item in package.items:
        available_depots = []
        for loc in locations:
            stock_qty = stock_map.get((pkg_item.item_sku, loc.id), 0)
            # Find existing allocation for this depot
            existing_allocation = next((alloc for alloc in pkg_item.allocations if alloc.depot_id == loc.id), None)
            allocated_qty = existing_allocation.allocated_qty if existing_allocation else 0
            
            # Include depot if it has stock OR if there's an existing allocation (for editing)
            if stock_qty > 0 or existing_allocation:
                available_depots.append({
                    'depot': loc,
                    'depot_id': loc.id,
                    'depot_name': loc.name,
                    'available_qty': stock_qty,
                    'allocated_qty': allocated_qty,
                    'has_allocation': existing_allocation is not None
                })
        
        item_depot_options[pkg_item.id] = available_depots
    
    return render_template("package_fulfill.html", 
                         package=package,
                         items=items,
                         locations=locations,
                         stock_map=stock_map,
                         events=events,
                         item_depot_options=item_depot_options)

@app.route("/packages/<int:package_id>")
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK)
def package_details(package_id):
    """View package details with full audit trail"""
    package = DistributionPackage.query.get_or_404(package_id)
    
    # Get stock availability for display
    stock_map = get_stock_by_location()
    # Exclude AGENCY hubs from overall stock calculations
    locations = Depot.query.filter(Depot.hub_type != 'AGENCY').all()
    
    # Calculate current stock and stock by depot for each item
    for pkg_item in package.items:
        pkg_item.current_stock = sum(stock_map.get((pkg_item.item_sku, loc.id), 0) for loc in locations)
        
        # Add stock breakdown by depot
        pkg_item.stock_by_depot = []
        for loc in locations:
            stock_qty = stock_map.get((pkg_item.item_sku, loc.id), 0)
            pkg_item.stock_by_depot.append({
                'depot_name': loc.name,
                'depot_id': loc.id,
                'stock': stock_qty
            })
    
    return render_template("package_details.html", package=package)

@app.route("/packages/<int:package_id>/submit_review", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def package_submit_review(package_id):
    """Submit package for review (Draft → Under Review)"""
    package = DistributionPackage.query.get_or_404(package_id)
    
    if package.status != "Draft":
        flash("Only draft packages can be submitted for review.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    old_status = package.status
    package.status = "Under Review"
    package.updated_at = datetime.utcnow()
    
    record_package_status_change(package, old_status, "Under Review", current_user.display_name, 
                                "Package submitted for review")
    
    db.session.commit()
    
    flash(f"Package {package.package_number} submitted for review.", "success")
    return redirect(url_for("package_details", package_id=package_id))

@app.route("/packages/<int:package_id>/approve", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER)
def package_approve(package_id):
    """Approve package (Under Review → Approved)"""
    package = DistributionPackage.query.get_or_404(package_id)
    
    if package.status != "Under Review":
        flash("Only packages under review can be approved.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    approval_notes = request.form.get("approval_notes", "").strip() or None
    
    old_status = package.status
    package.status = "Approved"
    package.approved_by = current_user.display_name
    package.approved_at = datetime.utcnow()
    package.updated_at = datetime.utcnow()
    
    record_package_status_change(package, old_status, "Approved", current_user.display_name, approval_notes)
    
    db.session.commit()
    
    flash(f"Package {package.package_number} approved.", "success")
    return redirect(url_for("package_details", package_id=package_id))

@app.route("/packages/<int:package_id>/dispatch", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK)
def package_dispatch(package_id):
    """Dispatch package (Approved → Dispatched) and generate OUT transactions"""
    package = DistributionPackage.query.get_or_404(package_id)
    
    if package.status != "Approved":
        flash("Only approved packages can be dispatched.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    if not package.assigned_location_id:
        flash("Package must be assigned to a warehouse before dispatch.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    dispatch_notes = request.form.get("dispatch_notes", "").strip() or None
    
    # CRITICAL: Validate stock availability at dispatch time to prevent negative stock
    stock_map = get_stock_by_location()
    for pkg_item in package.items:
        for allocation in pkg_item.allocations:
            if allocation.allocated_qty > 0:
                # Check current stock at this depot
                current_stock = stock_map.get((pkg_item.item_sku, allocation.depot_id), 0)
                
                if allocation.allocated_qty > current_stock:
                    flash(f"Cannot dispatch: {pkg_item.item.name} has insufficient stock at {allocation.depot.name}. "
                          f"Available: {current_stock}, Required: {allocation.allocated_qty}. "
                          f"Stock may have changed since allocation.", "danger")
                    return redirect(url_for("package_details", package_id=package_id))
    
    # Generate OUT transactions per depot allocation (multi-depot support)
    for pkg_item in package.items:
        for allocation in pkg_item.allocations:
            if allocation.allocated_qty > 0:
                transaction = Transaction(
                    item_sku=pkg_item.item_sku,
                    ttype="OUT",
                    qty=allocation.allocated_qty,
                    location_id=allocation.depot_id,  # Transaction from specific depot
                    event_id=package.event_id,
                    notes=f"Dispatched from {allocation.depot.name} via package {package.package_number}",
                    created_by=current_user.display_name
                )
                db.session.add(transaction)
    
    old_status = package.status
    package.status = "Dispatched"
    package.dispatched_by = current_user.display_name
    package.dispatched_at = datetime.utcnow()
    package.updated_at = datetime.utcnow()
    
    record_package_status_change(package, old_status, "Dispatched", current_user.display_name, dispatch_notes)
    
    db.session.commit()
    
    flash(f"Package {package.package_number} dispatched successfully. Inventory updated.", "success")
    return redirect(url_for("package_details", package_id=package_id))

@app.route("/packages/<int:package_id>/deliver", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_INVENTORY_CLERK)
def package_deliver(package_id):
    """Mark package as delivered (Dispatched → Delivered)"""
    package = DistributionPackage.query.get_or_404(package_id)
    
    if package.status != "Dispatched":
        flash("Only dispatched packages can be marked as delivered.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    delivery_notes = request.form.get("delivery_notes", "").strip() or None
    
    old_status = package.status
    package.status = "Delivered"
    package.delivered_at = datetime.utcnow()
    package.updated_at = datetime.utcnow()
    
    record_package_status_change(package, old_status, "Delivered", current_user.display_name, delivery_notes)
    
    db.session.commit()
    
    flash(f"Package {package.package_number} marked as delivered.", "success")
    return redirect(url_for("package_details", package_id=package_id))

@app.route("/disaster-events")
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def disaster_events():
    events = DisasterEvent.query.order_by(DisasterEvent.start_date.desc()).all()
    # Get transaction counts per event
    event_txn_count = {}
    for ev in events:
        count = Transaction.query.filter_by(event_id=ev.id).count()
        event_txn_count[ev.id] = count
    return render_template("disaster_events.html", events=events, event_txn_count=event_txn_count)

@app.route("/disaster-events/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def disaster_event_new():
    from datetime import datetime as dt, date
    
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Event name is required.", "danger")
            return redirect(url_for("disaster_event_new"))
        
        event_type = request.form.get("event_type", "").strip() or None
        start_date_str = request.form.get("start_date", "").strip()
        end_date_str = request.form.get("end_date", "").strip() or None
        description = request.form.get("description", "").strip() or None
        status = request.form.get("status", "Active").strip()
        
        if not start_date_str:
            flash("Start date is required.", "danger")
            return redirect(url_for("disaster_event_new"))
        
        start_date = dt.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = dt.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
        
        today = date.today()
        if start_date > today:
            flash("Start date cannot be in the future.", "danger")
            return redirect(url_for("disaster_event_new"))
        
        if end_date and end_date > today:
            flash("End date cannot be in the future.", "danger")
            return redirect(url_for("disaster_event_new"))
        
        event = DisasterEvent(name=name, event_type=event_type, start_date=start_date, 
                            end_date=end_date, description=description, status=status)
        db.session.add(event)
        db.session.commit()
        flash(f"Disaster event '{name}' created successfully.", "success")
        return redirect(url_for("disaster_events"))
    
    today = date.today().strftime("%Y-%m-%d")
    return render_template("disaster_event_form.html", event=None, today=today)

@app.route("/disaster-events/<int:event_id>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def disaster_event_edit(event_id):
    from datetime import datetime as dt, date
    
    event = DisasterEvent.query.get_or_404(event_id)
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Event name is required.", "danger")
            return redirect(url_for("disaster_event_edit", event_id=event_id))
        
        event_type = request.form.get("event_type", "").strip() or None
        start_date_str = request.form.get("start_date", "").strip()
        end_date_str = request.form.get("end_date", "").strip() or None
        description = request.form.get("description", "").strip() or None
        status = request.form.get("status", "Active").strip()
        
        if not start_date_str:
            flash("Start date is required.", "danger")
            return redirect(url_for("disaster_event_edit", event_id=event_id))
        
        start_date = dt.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = dt.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
        
        today = date.today()
        if start_date > today:
            flash("Start date cannot be in the future.", "danger")
            return redirect(url_for("disaster_event_edit", event_id=event_id))
        
        if end_date and end_date > today:
            flash("End date cannot be in the future.", "danger")
            return redirect(url_for("disaster_event_edit", event_id=event_id))
        
        event.name = name
        event.event_type = event_type
        event.start_date = start_date
        event.end_date = end_date
        event.description = description
        event.status = status
        db.session.commit()
        flash(f"Disaster event updated successfully.", "success")
        return redirect(url_for("disaster_events"))
    
    today = date.today().strftime("%Y-%m-%d")
    return render_template("disaster_event_form.html", event=event, today=today)

# ---------- User Management Routes ----------
@app.route("/users")
@role_required(ROLE_ADMIN)
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("users.html", users=all_users)

@app.route("/users/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def user_new():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        organization = request.form.get("organization", "").strip()
        job_title = request.form.get("job_title", "").strip()
        phone = request.form.get("phone", "").strip()
        role = request.form["role"]
        password = request.form["password"]
        password_confirm = request.form["password_confirm"]
        assigned_location_id = request.form.get("assigned_location_id") or None
        
        if not email or not first_name or not last_name or not role or not password:
            flash("Email, first name, last name, role, and password are required.", "danger")
            return redirect(url_for("user_new"))
        
        if password != password_confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("user_new"))
        
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return redirect(url_for("user_new"))
        
        # Validate role exists in database
        role_obj = Role.query.filter_by(code=role).first()
        if not role_obj:
            flash("Invalid role selected.", "danger")
            return redirect(url_for("user_new"))
        
        # Validate SUB_HUB_USER role requires SUB hub assignment
        if role == ROLE_SUB_HUB_USER:
            if not assigned_location_id:
                flash("Sub-Hub Users must be assigned to a Sub-Hub.", "danger")
                return redirect(url_for("user_new"))
            
            assigned_depot = Depot.query.get(int(assigned_location_id))
            if not assigned_depot:
                flash("Invalid hub assignment.", "danger")
                return redirect(url_for("user_new"))
            
            if assigned_depot.hub_type != 'SUB':
                flash("Sub-Hub User role can only be assigned to Sub-Hubs.", "danger")
                return redirect(url_for("user_new"))
        
        existing = User.query.filter_by(email=email).first()
        if existing:
            flash(f"User with email '{email}' already exists.", "warning")
            return redirect(url_for("user_new"))
        
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            organization=organization,
            job_title=job_title,
            phone=phone,
            full_name=f"{first_name} {last_name}",
            role=role,
            timezone='America/Jamaica',
            language='en',
            is_active=True,
            assigned_location_id=int(assigned_location_id) if assigned_location_id else None,
            created_by_id=current_user.id
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.flush()
        
        # Create role assignment
        role_obj = Role.query.filter_by(code=role).first()
        if role_obj:
            user_role = UserRole(user_id=user.id, role_id=role_obj.id, assigned_at=datetime.utcnow())
            db.session.add(user_role)
        
        # Create hub assignment if provided
        if assigned_location_id:
            user_hub = UserHub(user_id=user.id, hub_id=int(assigned_location_id), assigned_at=datetime.utcnow())
            db.session.add(user_hub)
        
        db.session.commit()
        
        flash(f"User '{first_name} {last_name}' created successfully.", "success")
        return redirect(url_for("users"))
    
    locations = Depot.query.order_by(Depot.name.asc()).all()
    roles = Role.query.order_by(Role.name.asc()).all()
    return render_template("user_form.html", user=None, roles=roles, locations=locations)

@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def user_edit(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        organization = request.form.get("organization", "").strip()
        job_title = request.form.get("job_title", "").strip()
        phone = request.form.get("phone", "").strip()
        role = request.form["role"]
        is_active = request.form.get("is_active") == "on"
        assigned_location_id = request.form.get("assigned_location_id") or None
        password = request.form.get("password", "").strip()
        password_confirm = request.form.get("password_confirm", "").strip()
        
        if not email or not first_name or not last_name or not role:
            flash("Email, first name, last name, and role are required.", "danger")
            return redirect(url_for("user_edit", user_id=user_id))
        
        # Validate role exists in database
        role_obj = Role.query.filter_by(code=role).first()
        if not role_obj:
            flash("Invalid role selected.", "danger")
            return redirect(url_for("user_edit", user_id=user_id))
        
        # Validate SUB_HUB_USER role requires SUB hub assignment
        if role == ROLE_SUB_HUB_USER:
            if not assigned_location_id:
                flash("Sub-Hub Users must be assigned to a Sub-Hub.", "danger")
                return redirect(url_for("user_edit", user_id=user_id))
            
            assigned_depot = Depot.query.get(int(assigned_location_id))
            if not assigned_depot:
                flash("Invalid hub assignment.", "danger")
                return redirect(url_for("user_edit", user_id=user_id))
            
            if assigned_depot.hub_type != 'SUB':
                flash("Sub-Hub User role can only be assigned to Sub-Hubs.", "danger")
                return redirect(url_for("user_edit", user_id=user_id))
        
        existing = User.query.filter(User.email == email, User.id != user_id).first()
        if existing:
            flash(f"Email '{email}' is already used by another user.", "warning")
            return redirect(url_for("user_edit", user_id=user_id))
        
        if password:
            if password != password_confirm:
                flash("Passwords do not match.", "danger")
                return redirect(url_for("user_edit", user_id=user_id))
            if len(password) < 8:
                flash("Password must be at least 8 characters.", "danger")
                return redirect(url_for("user_edit", user_id=user_id))
            user.set_password(password)
        
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.organization = organization
        user.job_title = job_title
        user.phone = phone
        user.full_name = f"{first_name} {last_name}"
        user.role = role
        user.is_active = is_active
        user.assigned_location_id = int(assigned_location_id) if assigned_location_id else None
        user.updated_by_id = current_user.id
        user.updated_at = datetime.utcnow()
        
        # Update role assignment - preserve existing if unchanged
        current_roles = user.roles
        if not current_roles or (len(current_roles) == 1 and current_roles[0] != role):
            # Only update if role changed or no role exists
            UserRole.query.filter_by(user_id=user.id).delete()
            role_obj = Role.query.filter_by(code=role).first()
            if role_obj:
                user_role = UserRole(user_id=user.id, role_id=role_obj.id, assigned_at=datetime.utcnow())
                db.session.add(user_role)
        
        # Update hub assignment - preserve existing if unchanged
        current_hub_ids = [h.id for h in user.hubs]
        new_hub_id = int(assigned_location_id) if assigned_location_id else None
        if len(current_hub_ids) != 1 or (current_hub_ids and current_hub_ids[0] != new_hub_id):
            # Only update if hub changed or no single hub exists
            UserHub.query.filter_by(user_id=user.id).delete()
            if new_hub_id:
                user_hub = UserHub(user_id=user.id, hub_id=new_hub_id, assigned_at=datetime.utcnow())
                db.session.add(user_hub)
        
        db.session.commit()
        flash(f"User '{first_name} {last_name}' updated successfully.", "success")
        return redirect(url_for("users"))
    
    locations = Depot.query.order_by(Depot.name.asc()).all()
    roles = Role.query.order_by(Role.name.asc()).all()
    return render_template("user_form.html", user=user, roles=roles, locations=locations)

# ---------- CLI for DB ----------
@app.cli.command("init-db")
def init_db():
    db.create_all()
    ensure_seed_data()
    print("Database initialized.")

@app.cli.command("create-admin")
def create_admin():
    """Create an admin user for the system"""
    import getpass
    
    print("\n=== Create Administrator Account ===\n")
    
    email = input("Enter admin email: ").strip().lower()
    if not email:
        print("Error: Email cannot be empty")
        return
    
    # Check if user already exists
    existing = User.query.filter_by(email=email).first()
    if existing:
        print(f"Error: User with email '{email}' already exists")
        return
    
    full_name = input("Enter full name: ").strip()
    if not full_name:
        print("Error: Full name cannot be empty")
        return
    
    password = getpass.getpass("Enter password: ")
    password_confirm = getpass.getpass("Confirm password: ")
    
    if password != password_confirm:
        print("Error: Passwords do not match")
        return
    
    if len(password) < 8:
        print("Error: Password must be at least 8 characters")
        return
    
    # Create admin user
    admin = User(
        email=email,
        full_name=full_name,
        role=ROLE_ADMIN,
        is_active=True
    )
    admin.set_password(password)
    
    db.session.add(admin)
    db.session.commit()
    
    print(f"\n✓ Admin user '{full_name}' created successfully!")
    print(f"  Email: {email}")
    print(f"  Role: Administrator\n")

@app.cli.command("create-user")
def create_user():
    """Create a user with a specific role"""
    import getpass
    
    print("\n=== Create User Account ===\n")
    
    email = input("Enter email: ").strip().lower()
    if not email:
        print("Error: Email cannot be empty")
        return
    
    existing = User.query.filter_by(email=email).first()
    if existing:
        print(f"Error: User with email '{email}' already exists")
        return
    
    full_name = input("Enter full name: ").strip()
    if not full_name:
        print("Error: Full name cannot be empty")
        return
    
    print("\nAvailable roles:")
    print("1. Warehouse Staff")
    print("2. Field Personnel")
    print("3. Logistics Officer")
    print("4. Logistics Manager")
    print("5. Executive Management")
    print("6. System Administrator")
    print("7. Auditor")
    
    role_choice = input("\nSelect role (1-7): ").strip()
    role_map = {
        "1": ROLE_WAREHOUSE_STAFF,
        "2": ROLE_FIELD_PERSONNEL,
        "3": ROLE_LOGISTICS_OFFICER,
        "4": ROLE_LOGISTICS_MANAGER,
        "5": ROLE_EXECUTIVE,
        "6": ROLE_ADMIN,
        "7": ROLE_AUDITOR
    }
    
    if role_choice not in role_map:
        print("Error: Invalid role selection")
        return
    
    role = role_map[role_choice]
    
    # Optional: assign location for warehouse staff
    assigned_location_id = None
    if role == ROLE_WAREHOUSE_STAFF:
        locations = Depot.query.all()
        if locations:
            print("\nAvailable locations:")
            for idx, loc in enumerate(locations, 1):
                print(f"{idx}. {loc.name}")
            
            loc_choice = input("\nAssign to location (number, or leave blank for none): ").strip()
            if loc_choice and loc_choice.isdigit():
                loc_idx = int(loc_choice) - 1
                if 0 <= loc_idx < len(locations):
                    assigned_location_id = locations[loc_idx].id
    
    password = getpass.getpass("\nEnter password: ")
    password_confirm = getpass.getpass("Confirm password: ")
    
    if password != password_confirm:
        print("Error: Passwords do not match")
        return
    
    if len(password) < 8:
        print("Error: Password must be at least 8 characters")
        return
    
    user = User(
        email=email,
        full_name=full_name,
        role=role,
        is_active=True,
        assigned_location_id=assigned_location_id
    )
    user.set_password(password)
    
    db.session.add(user)
    db.session.commit()
    
    print(f"\n✓ User '{full_name}' created successfully!")
    print(f"  Email: {email}")
    print(f"  Role: {role}\n")

@app.cli.command("migrate-dispatch-receipt")
def migrate_dispatch_receipt():
    """Add dispatch and receipt tracking columns to needs_list table"""
    from sqlalchemy import text
    
    print("\n=== Migrating Needs List Table for Dispatch/Receipt Workflow ===\n")
    
    # Check database type
    db_url = app.config["SQLALCHEMY_DATABASE_URI"]
    is_postgres = db_url.startswith("postgres")
    
    try:
        with db.engine.connect() as conn:
            # Check if columns already exist
            if is_postgres:
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='needs_list' AND column_name='dispatched_by_id'
                """))
            else:  # SQLite
                result = conn.execute(text("PRAGMA table_info(needs_list)"))
                columns = [row[1] for row in result.fetchall()]
                already_exists = 'dispatched_by_id' in columns
                
                if already_exists:
                    print("✓ Columns already exist. No migration needed.")
                    return
            
            # Add new columns
            print("Adding dispatch and receipt tracking columns...")
            
            conn.execute(text("""
                ALTER TABLE needs_list 
                ADD COLUMN dispatched_by_id INTEGER
            """))
            conn.execute(text("""
                ALTER TABLE needs_list 
                ADD COLUMN dispatched_at TIMESTAMP
            """))
            conn.execute(text("""
                ALTER TABLE needs_list 
                ADD COLUMN dispatch_notes TEXT
            """))
            conn.execute(text("""
                ALTER TABLE needs_list 
                ADD COLUMN received_by_id INTEGER
            """))
            conn.execute(text("""
                ALTER TABLE needs_list 
                ADD COLUMN received_at TIMESTAMP
            """))
            conn.execute(text("""
                ALTER TABLE needs_list 
                ADD COLUMN receipt_notes TEXT
            """))
            
            conn.commit()
            
            print("✓ Migration completed successfully!")
            print("  Added columns:")
            print("    - dispatched_by_id (INTEGER, FK to user.id)")
            print("    - dispatched_at (TIMESTAMP)")
            print("    - dispatch_notes (TEXT)")
            print("    - received_by_id (INTEGER, FK to user.id)")
            print("    - received_at (TIMESTAMP)")
            print("    - receipt_notes (TEXT)")
            print("\nWorkflow: Draft → Submitted → Prepared → Awaiting Approval → Approved → Dispatched → Received → Completed\n")
            
    except Exception as e:
        print(f"✗ Migration failed: {str(e)}")
        print("  Note: If columns already exist, you can ignore this error.")

@app.cli.command("create-notification-table")
def create_notification_table():
    """Create the notification table for in-app notifications"""
    from sqlalchemy import text
    
    print("\n=== Creating Notification Table ===\n")
    
    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS notification (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES "user"(id),
                    hub_id INTEGER REFERENCES location(id),
                    needs_list_id INTEGER REFERENCES needs_list(id),
                    title VARCHAR(200) NOT NULL,
                    message TEXT NOT NULL,
                    type VARCHAR(50) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'unread',
                    link_url VARCHAR(500),
                    payload TEXT,
                    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_notification_user_id ON notification(user_id)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_notification_hub_id ON notification(hub_id)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_notification_needs_list_id ON notification(needs_list_id)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_notification_created_at ON notification(created_at)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_notification_is_archived ON notification(is_archived)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_notification_user_status_created ON notification(user_id, status, created_at)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_notification_hub_created ON notification(hub_id, created_at)
            """))
            
            conn.commit()
        
        print("✓ Notification table created successfully!")
        print("  Indexes:")
        print("    - idx_notification_user_status_created (user_id, status, created_at)")
        print("    - idx_notification_hub_created (hub_id, created_at)")
        print("\n")
        
    except Exception as e:
        print(f"✗ Migration failed: {str(e)}")

# ---------- Notification API Routes ----------

@app.route("/notifications/unread-count")
@login_required
def notifications_unread_count():
    """Get unread notification count for the current user"""
    count = Notification.query.filter(
        Notification.user_id == current_user.id,
        Notification.status == 'unread',
        Notification.is_archived == False
    ).count()
    
    return jsonify({"count": count})

# Keep old route for backward compatibility
@app.route("/agency/notifications/unread-count")
@login_required
def agency_notifications_unread_count():
    """Deprecated: Use /notifications/unread-count instead"""
    return notifications_unread_count()

@app.route("/notifications/list")
@login_required
def notifications_list():
    """Get paginated list of notifications for the current user"""
    # Pagination parameters
    page = request.args.get('page', 1, type=int)
    limit = min(request.args.get('limit', 20, type=int), 50)  # Max 50 per page
    offset = (page - 1) * limit
    
    # Query notifications for this user (non-archived only by default)
    query = Notification.query.filter(
        Notification.user_id == current_user.id,
        Notification.is_archived == False
    ).order_by(Notification.created_at.desc())
    
    total = query.count()
    notifications = query.offset(offset).limit(limit).all()
    
    # Serialize notifications
    notifications_data = []
    for notif in notifications:
        notifications_data.append({
            "id": notif.id,
            "title": notif.title,
            "message": notif.message,
            "type": notif.type,
            "status": notif.status,
            "link_url": notif.link_url,
            "created_at": format_datetime_full(notif.created_at),
            "created_at_iso": format_datetime_iso_est(notif.created_at),
        })
    
    return jsonify({
        "notifications": notifications_data,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": total > (page * limit)
    })

# Keep old route for backward compatibility
@app.route("/agency/notifications/list")
@login_required
def agency_notifications_list():
    """Deprecated: Use /notifications/list instead"""
    return notifications_list()

@app.route("/notifications/<int:notification_id>/mark-read", methods=["POST"])
@login_required
def notification_mark_read(notification_id):
    """Mark a single notification as read"""
    notification = Notification.query.get_or_404(notification_id)
    
    # Security: verify this notification belongs to the current user
    if notification.user_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403
    
    notification.status = 'read'
    db.session.commit()
    
    return jsonify({"success": True, "id": notification_id})

# Keep old route for backward compatibility
@app.route("/agency/notifications/<int:notification_id>/mark-read", methods=["POST"])
@login_required
def agency_notification_mark_read(notification_id):
    """Deprecated: Use /notifications/<id>/mark-read instead"""
    return notification_mark_read(notification_id)

@app.route("/notifications/mark-all-read", methods=["POST"])
@login_required
def notifications_mark_all_read():
    """Mark all unread notifications as read for the current user"""
    count = Notification.query.filter(
        Notification.user_id == current_user.id,
        Notification.status == 'unread',
        Notification.is_archived == False
    ).update({"status": "read"})
    
    db.session.commit()
    
    return jsonify({"success": True, "marked_count": count})

# Keep old route for backward compatibility
@app.route("/agency/notifications/mark-all-read", methods=["POST"])
@login_required
def agency_notifications_mark_all_read():
    """Deprecated: Use /notifications/mark-all-read instead"""
    return notifications_mark_all_read()

@app.route("/notifications/history")
@login_required
def notifications_history():
    """Full notification history page for all users"""
    # Get all notifications (including archived) for this user
    notifications = Notification.query.filter(
        Notification.user_id == current_user.id
    ).order_by(Notification.created_at.desc()).all()
    
    return render_template("notifications_history.html", notifications=notifications)

# Keep old route for backward compatibility
@app.route("/agency/notifications/history")
@login_required
def agency_notifications_history():
    """Deprecated: Use /notifications/history instead"""
    return notifications_history()

# ---------- Notification Service ----------

def create_notifications_for_users(user_ids, title, message, notification_type, link_url=None, payload_data=None, needs_list_id=None, hub_id=None):
    """
    Create notifications for specific users.
    
    Args:
        user_ids: List of user IDs to notify
        title: Notification title
        message: Notification message
        notification_type: Type of notification (submitted, approved, dispatched, received, etc.)
        link_url: Optional URL to link to
        payload_data: Optional dict of additional data for audit trail
        needs_list_id: Optional needs list ID
        hub_id: Optional hub ID
    """
    try:
        import json
        
        if not user_ids:
            print(f"Warning: No users specified for notification")
            return
        
        # Build payload JSON
        payload_json = json.dumps(payload_data) if payload_data else None
        
        # Create notification for each user
        for user_id in user_ids:
            notification = Notification(
                user_id=user_id,
                hub_id=hub_id,
                needs_list_id=needs_list_id,
                title=title,
                message=message,
                type=notification_type,
                status='unread',
                link_url=link_url,
                payload=payload_json,
                is_archived=False
            )
            db.session.add(notification)
        
        db.session.commit()
        print(f"Created {len(user_ids)} notifications for {notification_type} event")
        
    except Exception as e:
        print(f"Error creating notifications: {str(e)}")
        db.session.rollback()

def create_notifications_for_role(role, title, message, notification_type, link_url=None, payload_data=None, needs_list_id=None, hub_id=None):
    """
    Create notifications for all active users with a specific role.
    
    Args:
        role: User role to notify (e.g., ROLE_LOGISTICS_MANAGER)
        title: Notification title
        message: Notification message
        notification_type: Type of notification
        link_url: Optional URL to link to
        payload_data: Optional dict of additional data for audit trail
        needs_list_id: Optional needs list ID
        hub_id: Optional hub ID
    """
    try:
        # Get all active users with this role
        users = User.query.filter(
            User.role == role,
            User.is_active == True
        ).all()
        
        user_ids = [user.id for user in users]
        
        if not user_ids:
            print(f"Warning: No active users found with role {role}")
            return
        
        create_notifications_for_users(
            user_ids=user_ids,
            title=title,
            message=message,
            notification_type=notification_type,
            link_url=link_url,
            payload_data=payload_data,
            needs_list_id=needs_list_id,
            hub_id=hub_id
        )
        
    except Exception as e:
        print(f"Error creating role notifications: {str(e)}")

def create_notification_for_agency_hub(needs_list, title, message, notification_type, triggered_by_user=None):
    """
    Create notifications for all active users assigned to an agency hub.
    
    Args:
        needs_list: NeedsList object
        title: Notification title (e.g., "Needs List Approved")
        message: Notification message (e.g., "Your Needs List NL-000004 has been approved")
        notification_type: Type of notification (submitted, approved, dispatched, received, comment)
        triggered_by_user: User who triggered the notification (for audit trail)
    """
    try:
        import json
        
        # Get all active users assigned to the agency hub
        agency_users = User.query.filter(
            User.assigned_location_id == needs_list.agency_hub_id,
            User.is_active == True
        ).all()
        
        if not agency_users:
            print(f"Warning: No active users found for agency hub {needs_list.agency_hub_id}")
            return
        
        # Build link URL to the needs list detail page
        link_url = f"/needs-lists/{needs_list.id}"
        
        # Build payload for audit trail
        payload_data = {
            "needs_list_number": needs_list.list_number,
            "triggered_by": triggered_by_user.display_name if triggered_by_user else "System",
            "triggered_by_id": triggered_by_user.id if triggered_by_user else None,
        }
        payload_json = json.dumps(payload_data)
        
        # Create notification for each agency user
        for user in agency_users:
            notification = Notification(
                user_id=user.id,
                hub_id=needs_list.agency_hub_id,
                needs_list_id=needs_list.id,
                title=title,
                message=message,
                type=notification_type,
                status='unread',
                link_url=link_url,
                payload=payload_json,
                is_archived=False
            )
            db.session.add(notification)
        
        db.session.commit()
        print(f"Created {len(agency_users)} notifications for {notification_type} event on {needs_list.list_number}")
        
    except Exception as e:
        print(f"Error creating notifications: {str(e)}")
        db.session.rollback()

def create_notification_for_warehouse_users_at_source_hubs(needs_list, title, message, notification_type, triggered_by_user=None):
    """
    Create notifications for warehouse supervisors and officers at source hubs.
    Only notifies users assigned to the source hubs that will fulfill this needs list.
    
    Args:
        needs_list: NeedsList object
        title: Notification title
        message: Notification message
        notification_type: Type of notification (e.g., "approved")
        triggered_by_user: User who triggered the notification (for audit trail)
    """
    try:
        import json
        
        # Get all source hubs from fulfilments
        fulfilments = NeedsListFulfilment.query.filter_by(needs_list_id=needs_list.id).all()
        source_hub_ids = {f.source_hub_id for f in fulfilments}
        
        if not source_hub_ids:
            print(f"Warning: No source hubs found for needs list {needs_list.list_number}")
            return
        
        # Get all warehouse supervisors and officers assigned to these source hubs
        warehouse_users = User.query.filter(
            User.role.in_([ROLE_WAREHOUSE_SUPERVISOR, ROLE_WAREHOUSE_OFFICER]),
            User.assigned_location_id.in_(source_hub_ids),
            User.is_active == True
        ).all()
        
        if not warehouse_users:
            print(f"Warning: No warehouse users found at source hubs for needs list {needs_list.list_number}")
            return
        
        # Build link URL to the needs list detail page
        link_url = f"/needs-lists/{needs_list.id}"
        
        # Build payload for audit trail
        payload_data = {
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name if needs_list.agency_hub else None,
            "triggered_by": triggered_by_user.display_name if triggered_by_user else "System",
            "triggered_by_id": triggered_by_user.id if triggered_by_user else None,
        }
        payload_json = json.dumps(payload_data)
        
        # Create notification for each warehouse user
        for user in warehouse_users:
            notification = Notification(
                user_id=user.id,
                hub_id=user.assigned_location_id,
                needs_list_id=needs_list.id,
                title=title,
                message=message,
                type=notification_type,
                status='unread',
                link_url=link_url,
                payload=payload_json,
                is_archived=False
            )
            db.session.add(notification)
        
        db.session.commit()
        print(f"Created {len(warehouse_users)} warehouse user notifications for {notification_type} event on {needs_list.list_number}")
        
    except Exception as e:
        print(f"Error creating warehouse notifications: {str(e)}")
        db.session.rollback()

@app.route("/uploads/<path:file_path>")
@login_required
def serve_upload(file_path):
    """Serve uploaded files with authentication"""
    try:
        storage = get_storage()
        full_path = storage.get_file_path(file_path)
        if not storage.file_exists(file_path):
            flash("File not found.", "error")
            return redirect(url_for("items"))
        return send_file(full_path)
    except Exception as e:
        flash(f"Error accessing file: {str(e)}", "error")
        return redirect(url_for("items"))

# ---------- Offline Sync API Endpoints ----------

@app.route("/api/offline/sync", methods=["POST"])
@login_required
def sync_offline_operation():
    """
    Sync offline queued operations to the server.
    Handles intake, distribution, and needs list creation operations.
    """
    try:
        operation = request.get_json()
        
        if not operation:
            return jsonify({"success": False, "error": "No operation data provided"}), 400
        
        operation_type = operation.get("type")
        hub_id = operation.get("hub_id")
        payload = operation.get("payload", {})
        client_id = operation.get("client_id")
        
        # Verify user has access to this hub
        if not can_access_hub(current_user, hub_id):
            return jsonify({"success": False, "error": "Access denied to this hub"}), 403
        
        # Route to appropriate handler based on operation type
        if operation_type == "intake":
            return handle_offline_intake(hub_id, payload, client_id)
        elif operation_type == "distribution":
            return handle_offline_distribution(hub_id, payload, client_id)
        elif operation_type == "needs_list_create":
            return handle_offline_needs_list(hub_id, payload, client_id)
        else:
            return jsonify({"success": False, "error": f"Unknown operation type: {operation_type}"}), 400
            
    except Exception as e:
        print(f"[Offline Sync] Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

def can_access_hub(user, hub_id):
    """Check if user has access to the specified hub"""
    if not hub_id:
        return False
    
    # Admin and Logistics roles have access to all hubs
    if user.has_any_role([ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER]):
        return True
    
    # Check if user has hub access via UserHub table
    if user.has_hub_access(hub_id):
        return True
    
    # Check legacy assigned_location_id
    if user.assigned_location_id == hub_id:
        return True
    
    return False

def handle_offline_intake(hub_id, payload, client_id):
    """Handle offline intake (donation/stock in) operation"""
    try:
        item_sku = payload.get("item_sku")
        quantity = payload.get("quantity")
        donor_name = payload.get("donor_name")
        notes = payload.get("notes", "")
        expiry_date_str = payload.get("expiry_date")
        
        # Validate item exists
        item = Item.query.filter_by(sku=item_sku).first()
        if not item:
            return jsonify({"success": False, "error": f"Item {item_sku} not found"}), 404
        
        # Validate hub exists
        hub = Depot.query.get(hub_id)
        if not hub:
            return jsonify({"success": False, "error": f"Hub {hub_id} not found"}), 404
        
        # Create or get donor
        donor = None
        if donor_name:
            donor = Donor.query.filter_by(name=donor_name).first()
            if not donor:
                donor = Donor(name=donor_name)
                db.session.add(donor)
                db.session.flush()
        
        # Parse expiry date if provided
        expiry_date = None
        if expiry_date_str:
            try:
                expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
            except:
                pass
        
        # Create transaction
        transaction = Transaction(
            item_sku=item_sku,
            ttype="IN",
            qty=quantity,
            location_id=hub_id,
            donor_id=donor.id if donor else None,
            expiry_date=expiry_date,
            notes=f"[Offline Sync - {client_id}] {notes}",
            created_by=current_user.username,
            created_at=datetime.utcnow()
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        return jsonify({"success": True, "transaction_id": transaction.id})
        
    except Exception as e:
        db.session.rollback()
        print(f"[Offline Sync - Intake] Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

def handle_offline_distribution(hub_id, payload, client_id):
    """Handle offline distribution (stock out) operation"""
    try:
        item_sku = payload.get("item_sku")
        quantity = payload.get("quantity")
        beneficiary_name = payload.get("beneficiary_name")
        beneficiary_parish = payload.get("beneficiary_parish")
        notes = payload.get("notes", "")
        
        # Validate item exists
        item = Item.query.filter_by(sku=item_sku).first()
        if not item:
            return jsonify({"success": False, "error": f"Item {item_sku} not found"}), 404
        
        # Validate hub exists
        hub = Depot.query.get(hub_id)
        if not hub:
            return jsonify({"success": False, "error": f"Hub {hub_id} not found"}), 404
        
        # Check stock availability
        stock_map = get_stock_by_location()
        current_stock = stock_map.get((item_sku, hub_id), 0)
        
        if current_stock < quantity:
            return jsonify({
                "success": False, 
                "error": f"Insufficient stock. Available: {current_stock}, Requested: {quantity}"
            }), 400
        
        # Create or get beneficiary
        beneficiary = None
        if beneficiary_name:
            beneficiary = Beneficiary.query.filter_by(
                name=beneficiary_name,
                parish=beneficiary_parish
            ).first()
            if not beneficiary:
                beneficiary = Beneficiary(
                    name=beneficiary_name,
                    parish=beneficiary_parish
                )
                db.session.add(beneficiary)
                db.session.flush()
        
        # Create transaction
        transaction = Transaction(
            item_sku=item_sku,
            ttype="OUT",
            qty=quantity,
            location_id=hub_id,
            beneficiary_id=beneficiary.id if beneficiary else None,
            notes=f"[Offline Sync - {client_id}] {notes}",
            created_by=current_user.username,
            created_at=datetime.utcnow()
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        return jsonify({"success": True, "transaction_id": transaction.id})
        
    except Exception as e:
        db.session.rollback()
        print(f"[Offline Sync - Distribution] Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

def handle_offline_needs_list(hub_id, payload, client_id):
    """Handle offline needs list creation"""
    try:
        # Only allow Agency and Sub hubs to create needs lists offline
        hub = Depot.query.get(hub_id)
        if not hub:
            return jsonify({"success": False, "error": f"Hub {hub_id} not found"}), 404
        
        if hub.hub_type not in ['AGENCY', 'SUB']:
            return jsonify({
                "success": False, 
                "error": "Only Agency and Sub hubs can create needs lists"
            }), 403
        
        # Create needs list as Draft (will need online approval anyway)
        needs_list = NeedsList(
            agency_hub_id=hub_id,
            status='Draft',
            created_by_id=current_user.id,
            created_at=datetime.utcnow(),
            notes=f"[Offline Sync - {client_id}] {payload.get('notes', '')}"
        )
        
        db.session.add(needs_list)
        db.session.flush()
        
        # Add line items
        line_items = payload.get("line_items", [])
        for item_data in line_items:
            line_item = NeedsListLineItem(
                needs_list_id=needs_list.id,
                item_sku=item_data.get("item_sku"),
                quantity_requested=item_data.get("quantity"),
                priority=item_data.get("priority", "MEDIUM"),
                notes=item_data.get("notes", "")
            )
            db.session.add(line_item)
        
        db.session.commit()
        
        return jsonify({"success": True, "needs_list_id": needs_list.id})
        
    except Exception as e:
        db.session.rollback()
        print(f"[Offline Sync - Needs List] Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/offline")
def offline_page():
    """Fallback page shown when application is offline"""
    return render_template("offline.html")

# ---------- Error Handlers ----------

@app.errorhandler(403)
def forbidden(error):
    """Handle 403 Forbidden errors with user-friendly page"""
    return render_template("403.html"), 403

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_seed_data()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
