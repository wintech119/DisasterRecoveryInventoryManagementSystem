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

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(200), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # WAREHOUSE_STAFF, FIELD_PERSONNEL, LOGISTICS_OFFICER, LOGISTICS_MANAGER, EXECUTIVE, ADMIN, AUDITOR
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    assigned_location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=True)  # For warehouse staff
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    assigned_location = db.relationship("Depot")
    
    def set_password(self, password):
        """Hash and set the user's password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password against hash"""
        return check_password_hash(self.password_hash, password)
    
    def get_id(self):
        """Required by Flask-Login"""
        return str(self.id)

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
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    agency_hub = db.relationship("Depot", foreign_keys=[agency_hub_id])
    main_hub = db.relationship("Depot", foreign_keys=[main_hub_id])
    event = db.relationship("DisasterEvent")
    dispatched_by_user = db.relationship("User", foreign_keys=[dispatched_by_id])
    received_by_user = db.relationship("User", foreign_keys=[received_by_id])
    items = db.relationship("NeedsListItem", back_populates="needs_list", cascade="all, delete-orphan")
    fulfilments = db.relationship("NeedsListFulfilment", back_populates="needs_list", cascade="all, delete-orphan")

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

# ---------- Flask-Login Configuration ----------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "warning"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------- Role Constants ----------
ROLE_WAREHOUSE_STAFF = "WAREHOUSE_STAFF"
ROLE_FIELD_PERSONNEL = "FIELD_PERSONNEL"
ROLE_LOGISTICS_OFFICER = "LOGISTICS_OFFICER"
ROLE_LOGISTICS_MANAGER = "LOGISTICS_MANAGER"
ROLE_EXECUTIVE = "EXECUTIVE"
ROLE_ADMIN = "ADMIN"
ROLE_AUDITOR = "AUDITOR"

ALL_ROLES = [
    ROLE_WAREHOUSE_STAFF,
    ROLE_FIELD_PERSONNEL,
    ROLE_LOGISTICS_OFFICER,
    ROLE_LOGISTICS_MANAGER,
    ROLE_EXECUTIVE,
    ROLE_ADMIN,
    ROLE_AUDITOR
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
    """Decorator to restrict access to specific roles"""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("login"))
            if current_user.role not in allowed_roles:
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
        item_fulfillment_pct = int((item_dispatched / item_requested * 100)) if item_requested > 0 else 0
        item_shortfall = max(item_requested - item_dispatched, 0)
        
        items_data.append({
            'item_name': item_entry.item.name,
            'sku': item_entry.item_sku,
            'unit': item_entry.item.unit,
            'requested_qty': item_requested,
            'dispatched_qty': item_dispatched,
            'fulfillment_pct': item_fulfillment_pct,
            'shortfall': item_shortfall,
            'source_hubs': source_hubs,
            'justification': item_entry.justification,
            'has_shortfall': item_shortfall > 0
        })
    
    # Calculate overall metrics
    fulfillment_rate = int((total_dispatched_qty / total_requested_qty * 100)) if total_requested_qty > 0 else 0
    shortfall_qty = max(total_requested_qty - total_dispatched_qty, 0)
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
        dispatcher_name = needs_list.dispatched_by_user.full_name if needs_list.dispatched_by_user else 'System'
        timeline.append({
            'milestone': 'Dispatched',
            'label': 'Items Dispatched',
            'timestamp': needs_list.dispatched_at,
            'actor': dispatcher_name,
            'notes': needs_list.dispatch_notes,
            'icon': 'bi-truck'
        })
    
    if needs_list.received_at:
        receiver_name = needs_list.received_by_user.full_name if needs_list.received_by_user else 'System'
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
            'can_download_pdf': current_user.role in [ROLE_ADMIN] or (
                current_user.assigned_location_id and 
                current_user.assigned_location_id == needs_list.agency_hub_id
            ),
            'total_received': total_dispatched_qty,
            'dispatch_sources': list(set([hub['hub_name'] for item in items_data for hub in item['source_hubs']])),
            'confirmed_by': needs_list.received_by_user.full_name if needs_list.received_by_user else None,
            'confirmed_at': needs_list.received_at
        },
        'officer': {
            'approved_qty': total_dispatched_qty,  # In this workflow, what was allocated was what was approved
            'has_discrepancies': shortfall_qty > 0,
            'shortfall_items': [item for item in items_data if item['has_shortfall']],
            'dispatch_details': {
                'dispatcher': needs_list.dispatched_by_user.full_name if needs_list.dispatched_by_user else None,
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
            'fulfillment_rate': fulfillment_rate,
            'shortfall_qty': shortfall_qty,
            'fulfillment_class': fulfillment_class,
            'dispatch_date': needs_list.dispatched_at,
            'receipt_date': needs_list.received_at,
            'confirmed_by': needs_list.received_by_user.full_name if needs_list.received_by_user else None
        },
        'items': items_data,
        'timeline': timeline,
        'roles': roles
    }

# ---------- Needs List Permission Helpers ----------

def can_view_needs_list(user, needs_list):
    """
    Check if user can view a specific needs list.
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # ADMIN has full access
    if user.role == ROLE_ADMIN:
        return (True, None)
    
    # Logistics Officers and Managers have global visibility
    if user.role in [ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER]:
        return (True, None)
    
    # Hub-based users: check if they own this needs list
    if user.assigned_location_id:
        user_depot = Depot.query.get(user.assigned_location_id)
        if user_depot and user_depot.id == needs_list.agency_hub_id:
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
    if user.role == ROLE_ADMIN:
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
    if user.role == ROLE_ADMIN:
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
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Must be in correct status
    if needs_list.status not in ['Submitted', 'Fulfilment Prepared', 'Awaiting Approval']:
        return (False, "Only submitted or prepared needs lists can be edited.")
    
    # Only ADMIN, Logistics Officers, and Logistics Managers can prepare
    if user.role not in [ROLE_ADMIN, ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER]:
        return (False, "Only logistics staff can prepare fulfilments.")
    
    # Logistics Officers cannot edit once submitted for approval
    if user.role == ROLE_LOGISTICS_OFFICER and needs_list.status == 'Awaiting Approval':
        return (False, "Cannot edit fulfilment after submitting for approval. Please contact a Logistics Manager.")
    
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
    if user.role not in [ROLE_ADMIN, ROLE_LOGISTICS_MANAGER]:
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
    if user.role not in [ROLE_ADMIN, ROLE_LOGISTICS_MANAGER]:
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
    if user.role == ROLE_ADMIN:
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

def can_dispatch_needs_list(user, needs_list):
    """
    Check if user can dispatch an approved needs list.
    Only Logistics Officers and Managers can dispatch after approval.
    
    Returns:
        tuple: (allowed: bool, error_message: str or None)
    """
    # Must be in Approved status (post-approval, ready for dispatch)
    if needs_list.status != 'Approved':
        return (False, "Only approved needs lists can be dispatched.")
    
    # Only ADMIN, Logistics Officers, and Logistics Managers can dispatch
    if user.role not in [ROLE_ADMIN, ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER]:
        return (False, "Only Logistics Officers and Managers can dispatch items.")
    
    return (True, None)

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
    if user.role == ROLE_ADMIN:
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
    from datetime import datetime, timedelta
    
    # Block Agency hub users from accessing dashboard
    if current_user.assigned_location and current_user.assigned_location.hub_type == 'AGENCY':
        flash("This page is not available for Agency hub users.", "warning")
        return redirect(url_for("needs_lists"))
    
    # KPIs - Inventory
    total_items = Item.query.count()
    # Exclude AGENCY hubs from overall inventory displays
    locations = Depot.query.filter(Depot.hub_type != 'AGENCY').order_by(Depot.name.asc()).all()
    
    # KPIs - Operations
    total_donors = Donor.query.count()
    total_beneficiaries = Beneficiary.query.count()
    active_events = DisasterEvent.query.filter_by(status="Active").count()
    total_events = DisasterEvent.query.count()
    
    # Transaction volumes
    total_intakes = Transaction.query.filter_by(ttype="IN").count()
    total_distributions = Transaction.query.filter_by(ttype="OUT").count()
    
    # Recent activity (last 30 days)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    recent_intakes = Transaction.query.filter(
        Transaction.ttype == "IN",
        Transaction.created_at >= thirty_days_ago
    ).count()
    recent_distributions = Transaction.query.filter(
        Transaction.ttype == "OUT",
        Transaction.created_at >= thirty_days_ago
    ).count()
    
    # Stock by location
    stock_by_location = {}
    for loc in locations:
        stock_total = db.session.query(
            func.sum(case((Transaction.ttype == "IN", Transaction.qty), else_=-Transaction.qty))
        ).filter(Transaction.location_id == loc.id).scalar()
        stock_by_location[loc.id] = stock_total or 0
    
    total_in_stock = sum(stock_by_location.values())
    
    # Low stock items (by location)
    low = []
    stock_map = get_stock_by_location()
    items = Item.query.all()
    
    for item in items:
        for loc in locations:
            stock = stock_map.get((item.sku, loc.id), 0)
            if item.min_qty and stock < item.min_qty and stock >= 0:
                low.append((item, loc, stock))
    
    low.sort(key=lambda x: x[2])  # Sort by stock level
    
    # Provide sliced and full data for low stock (for mobile responsiveness)
    PREVIEW_LIMIT = 5
    low_stock_preview = low[:PREVIEW_LIMIT]
    low_stock_full = low

    # Inventory by category
    stock_by_category = {}
    for item in items:
        category = item.category or "Uncategorized"
        total_stock = sum(stock_map.get((item.sku, loc.id), 0) for loc in locations)
        if category not in stock_by_category:
            stock_by_category[category] = {"items": [], "total_units": 0}
        stock_by_category[category]["items"].append({
            "name": item.name,
            "stock": total_stock,
            "unit": item.unit
        })
        stock_by_category[category]["total_units"] += total_stock
    
    # Sort categories by name
    sorted_categories = sorted(stock_by_category.items())
    stock_by_category_preview = sorted_categories[:PREVIEW_LIMIT]
    stock_by_category_full = sorted_categories
    
    # Provide sliced data for locations (for mobile responsiveness)
    locations_preview = locations[:PREVIEW_LIMIT]
    locations_full = locations
    
    # Activity by event - get all events first
    event_stats_all = db.session.query(
        DisasterEvent.name,
        DisasterEvent.event_type,
        func.sum(case((Transaction.ttype == "IN", Transaction.qty), else_=0)).label("total_intake"),
        func.sum(case((Transaction.ttype == "OUT", Transaction.qty), else_=0)).label("total_distribution")
    ).join(Transaction, DisasterEvent.id == Transaction.event_id, isouter=False)\
     .group_by(DisasterEvent.id, DisasterEvent.name, DisasterEvent.event_type)\
     .order_by(DisasterEvent.id.desc())\
     .all()
    
    event_stats_preview = event_stats_all[:PREVIEW_LIMIT]
    event_stats_full = event_stats_all
    
    # Expiring items (from transactions with expiry dates within next 30 days)
    from datetime import date, timedelta
    today = date.today()
    thirty_days = today + timedelta(days=30)
    expiring_transactions_query = Transaction.query.filter(
        Transaction.ttype == "IN",
        Transaction.expiry_date.isnot(None),
        Transaction.expiry_date <= thirty_days,
        Transaction.expiry_date >= today
    ).order_by(Transaction.expiry_date.asc()).all()
    
    # Calculate days remaining for each expiring batch
    expiring_items_all = []
    for tx in expiring_transactions_query:
        days_remaining = (tx.expiry_date - today).days
        expiring_items_all.append({
            'item': tx.item,
            'transaction': tx,
            'days_remaining': days_remaining,
            'urgency': 'critical' if days_remaining <= 7 else 'warning' if days_remaining <= 14 else 'normal'
        })
    
    expiring_items_preview = expiring_items_all[:PREVIEW_LIMIT]
    expiring_items_full = expiring_items_all
    
    # Recent transactions
    recent_all = Transaction.query.order_by(Transaction.created_at.desc()).limit(50).all()
    recent_preview = recent_all[:PREVIEW_LIMIT]
    recent_full = recent_all
    
    # Pending needs lists (for logistics staff and admins)
    pending_needs_lists = []
    if current_user.role in [ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER]:
        pending_needs_lists = DistributionPackage.query.filter_by(status="Draft")\
                                                       .order_by(DistributionPackage.created_at.asc()).all()
    
    # Hubs by type (for chart)
    hubs_by_type = {}
    all_hubs = Depot.query.all()
    for hub in all_hubs:
        hub_type = hub.hub_type or "Other"
        hubs_by_type[hub_type] = hubs_by_type.get(hub_type, 0) + 1
    
    # Category data for chart (top 5)
    category_labels = []
    category_data = []
    for category, stats in sorted_categories[:5]:
        category_labels.append(category if len(category) <= 15 else category[:12] + "...")
        category_data.append(stats['total_units'])
    
    # Needs Lists stats
    # TODO: Create centralized NeedsListStatus enum to prevent status string inconsistencies
    needs_lists_draft = NeedsList.query.filter_by(status='Draft').count()
    needs_lists_submitted = NeedsList.query.filter_by(status='Submitted').count()
    needs_lists_awaiting = NeedsList.query.filter(
        NeedsList.status.in_(['Awaiting Approval', 'Fulfilment Prepared'])
    ).count()
    needs_lists_completed = NeedsList.query.filter_by(status='Completed').count()
    
    needs_lists_stats = {
        'pending': needs_lists_submitted + needs_lists_awaiting,
        'in_progress': needs_lists_awaiting,
        'completed': needs_lists_completed
    }
    
    needs_lists_chart_data = {
        'Draft': needs_lists_draft,
        'Submitted': needs_lists_submitted,
        'In Progress': needs_lists_awaiting,
        'Completed': needs_lists_completed
    }
    
    # Total distributors (this was being queried but not used)
    total_distributors = Depot.query.filter_by(hub_type='AGENCY').count()
    
    # Fulfillment progress over last 7 days
    fulfillment_labels = []
    fulfillment_data = []
    for i in range(6, -1, -1):  # Last 7 days in chronological order
        day = today - timedelta(days=i)
        day_start = datetime.combine(day, datetime.min.time())
        day_end = datetime.combine(day, datetime.max.time())
        
        # Count needs lists completed on this day
        completed_count = NeedsList.query.filter(
            NeedsList.status == 'Completed',
            NeedsList.fulfilled_at >= day_start,
            NeedsList.fulfilled_at <= day_end
        ).count()
        
        fulfillment_labels.append(day.strftime("%b %d"))
        fulfillment_data.append(completed_count)
    
    return render_template("dashboard.html",
                           total_items=total_items,
                           total_in_stock=total_in_stock,
                           low_stock_preview=low_stock_preview,
                           low_stock_full=low_stock_full,
                           recent_preview=recent_preview,
                           recent_full=recent_full,
                           locations_preview=locations_preview,
                           locations_full=locations_full,
                           stock_by_location=stock_by_location,
                           stock_by_category_preview=stock_by_category_preview,
                           stock_by_category_full=stock_by_category_full,
                           total_donors=total_donors,
                           total_beneficiaries=total_beneficiaries,
                           active_events=active_events,
                           total_events=total_events,
                           total_intakes=total_intakes,
                           total_distributions=total_distributions,
                           recent_intakes=recent_intakes,
                           recent_distributions=recent_distributions,
                           event_stats_preview=event_stats_preview,
                           event_stats_full=event_stats_full,
                           expiring_items_preview=expiring_items_preview,
                           expiring_items_full=expiring_items_full,
                           pending_needs_lists=pending_needs_lists,
                           total_distributors=total_distributors,
                           hubs_by_type=hubs_by_type,
                           category_labels=category_labels,
                           category_data=category_data,
                           needs_lists_stats=needs_lists_stats,
                           needs_lists_chart_data=needs_lists_chart_data,
                           fulfillment_labels=fulfillment_labels,
                           fulfillment_data=fulfillment_data)

@app.route("/items")
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF, ROLE_AUDITOR, ROLE_EXECUTIVE)
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
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF)
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
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF)
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
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF)
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
                         created_by=current_user.full_name)
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

@app.route("/distribute", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF, ROLE_FIELD_PERSONNEL)
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
                         created_by=current_user.full_name)
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
    
    # AGENCY hub users should only see transactions for their own hub
    if current_user.assigned_location_id:
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
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF)
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
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF)
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
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF)
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
            created_by=current_user.full_name,
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
        record_package_status_change(package, None, "Draft", current_user.full_name, "Package created")
        
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
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF)
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
                    created_by=current_user.full_name
                )
                db.session.add(out_transaction)
                
                in_note = f"Stock transfer from {from_depot.name}. {notes}" if notes else f"Stock transfer from {from_depot.name}"
                in_transaction = Transaction(
                    item_sku=item_sku,
                    ttype="IN",
                    qty=quantity,
                    location_id=to_depot_id,
                    notes=in_note,
                    created_by=current_user.full_name
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
        created_by=current_user.full_name
    )
    db.session.add(out_transaction)
    
    in_note = f"Approved transfer from {from_depot.name}. {transfer_request.notes}" if transfer_request.notes else f"Approved transfer from {from_depot.name}"
    in_transaction = Transaction(
        item_sku=transfer_request.item_sku,
        ttype="IN",
        qty=transfer_request.quantity,
        location_id=transfer_request.to_location_id,
        notes=in_note,
        created_by=current_user.full_name
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
    
    # Role-based views for Logistics Officers and Managers
    if current_user.role == ROLE_LOGISTICS_OFFICER:
        # Logistics Officer view: All submitted needs lists awaiting fulfilment preparation
        submitted_lists = NeedsList.query.filter_by(status='Submitted').order_by(NeedsList.submitted_at.desc()).all()
        prepared_lists = NeedsList.query.filter(NeedsList.status.in_(['Fulfilment Prepared', 'Awaiting Approval'])).filter_by(prepared_by=current_user.full_name).order_by(NeedsList.prepared_at.desc()).all()
        return render_template("logistics_officer_needs_lists.html", submitted_lists=submitted_lists, prepared_lists=prepared_lists)
    
    elif current_user.role == ROLE_LOGISTICS_MANAGER:
        # Logistics Manager view: Can do EVERYTHING - prepare AND approve
        submitted_lists = NeedsList.query.filter_by(status='Submitted').order_by(NeedsList.submitted_at.desc()).all()
        awaiting_approval = NeedsList.query.filter(NeedsList.status.in_(['Fulfilment Prepared', 'Awaiting Approval'])).order_by(NeedsList.prepared_at.desc()).all()
        approved_lists = NeedsList.query.filter(NeedsList.status.in_(['Approved', 'Dispatched', 'Received', 'Completed'])).order_by(NeedsList.approved_at.desc()).limit(20).all()
        rejected_lists = NeedsList.query.filter_by(status='Rejected').order_by(NeedsList.updated_at.desc()).limit(20).all()
        return render_template("logistics_manager_needs_lists.html", submitted_lists=submitted_lists, awaiting_approval=awaiting_approval, approved_lists=approved_lists, rejected_lists=rejected_lists)
    
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
            created_by=current_user.full_name
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
    if current_user.role in [ROLE_ADMIN, ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER]:
        stock_map = get_stock_by_location()
    
    # Prepare completed context for enhanced Completed view
    completed_context = None
    if needs_list.status == 'Completed':
        completed_context = prepare_completed_context(needs_list, current_user)
    
    return render_template("needs_list_details.html", 
                         needs_list=needs_list, 
                         user_depot=user_depot, 
                         stock_map=stock_map, 
                         main_hubs=main_hubs,
                         completed_context=completed_context)

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
            "submitted_by": current_user.full_name,
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
            "submitted_by": current_user.full_name,
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
            "submitted_by": current_user.full_name,
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
    
    if request.method == "POST":
        fulfilment_notes = request.form.get("fulfilment_notes", "").strip() or None
        
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
                                fulfilment = NeedsListFulfilment(
                                    needs_list_id=needs_list.id,
                                    item_sku=sku,
                                    source_hub_id=int(depot_id),
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
        
        # Check if user is a Logistics Manager - they can directly approve
        is_manager = current_user.role == ROLE_LOGISTICS_MANAGER
        
        if is_manager:
            # Logistics Managers: Directly approve (stock transfers will happen during dispatch)
            needs_list.status = 'Approved'
            needs_list.prepared_by = current_user.full_name
            needs_list.prepared_at = datetime.utcnow()
            needs_list.approved_by = current_user.full_name
            needs_list.approved_at = datetime.utcnow()
            needs_list.fulfilment_notes = fulfilment_notes
            db.session.commit()
            
            flash(f"Needs list {needs_list.list_number} approved successfully. Ready for dispatch.", "success")
        else:
            # Logistics Officers: Submit for manager approval
            needs_list.status = 'Awaiting Approval'
            needs_list.prepared_by = current_user.full_name
            needs_list.prepared_at = datetime.utcnow()
            needs_list.fulfilment_notes = fulfilment_notes
            db.session.commit()
            
            # Notify Logistics Managers about approval needed
            create_notifications_for_role(
                role=ROLE_LOGISTICS_MANAGER,
                title="Approval Needed",
                message=f"Needs list {needs_list.list_number} from {needs_list.agency_hub.name} is ready for your approval.",
                notification_type="approval_needed",
                link_url=f"/logistics/needs-lists",
                payload_data={
                    "needs_list_number": needs_list.list_number,
                    "agency_hub": needs_list.agency_hub.name,
                    "prepared_by": current_user.full_name,
                    "prepared_by_id": current_user.id
                },
                needs_list_id=needs_list.id
            )
            
            flash(f"Fulfilment for {needs_list.list_number} prepared and submitted for manager approval.", "success")
        
        return redirect(url_for("needs_list_details", list_id=list_id))
    
    # GET request: Show fulfilment preparation form
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
                         existing_allocations=existing_allocations)

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
    needs_list.approved_by = current_user.full_name
    needs_list.approved_at = datetime.utcnow()
    needs_list.approval_notes = approval_notes
    db.session.commit()
    
    # Create notification for agency hub users
    create_notification_for_agency_hub(
        needs_list=needs_list,
        title="Needs List Approved",
        message=f"Your needs list {needs_list.list_number} has been approved by {current_user.full_name} and is ready for dispatch.",
        notification_type="approved",
        triggered_by_user=current_user
    )
    
    # Notify Logistics Officers about approved items ready for dispatch
    create_notifications_for_role(
        role=ROLE_LOGISTICS_OFFICER,
        title="Items Approved - Ready for Dispatch",
        message=f"Needs list {needs_list.list_number} for {needs_list.agency_hub.name} has been approved and is ready for dispatch.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "approved_by": current_user.full_name,
            "approved_by_id": current_user.id
        },
        needs_list_id=needs_list.id
    )
    
    # Notify Warehouse Staff about approved items to prepare for dispatch
    create_notifications_for_role(
        role=ROLE_WAREHOUSE_STAFF,
        title="Items Approved - Prepare for Dispatch",
        message=f"Needs list {needs_list.list_number} for {needs_list.agency_hub.name} has been approved. Prepare items for dispatch.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "approved_by": current_user.full_name,
            "approved_by_id": current_user.id
        },
        needs_list_id=needs_list.id
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
    needs_list.approved_by = current_user.full_name
    needs_list.approved_at = datetime.utcnow()
    needs_list.approval_notes = approval_notes
    needs_list.prepared_by = None
    needs_list.prepared_at = None
    needs_list.fulfilment_notes = None
    db.session.commit()
    
    flash(f"Fulfilment for {needs_list.list_number} rejected. Needs list returned to submitted status.", "warning")
    return redirect(url_for("needs_list_details", list_id=list_id))

@app.route("/needs-lists/<int:list_id>/dispatch", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_OFFICER, ROLE_LOGISTICS_MANAGER)
def needs_list_dispatch(list_id):
    """Dispatch approved needs list - Creates stock transactions and updates status to Dispatched"""
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
            created_by=current_user.full_name,
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
            created_by=current_user.full_name,
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
        needs_list.approved_by = current_user.full_name
        needs_list.approved_at = datetime.utcnow()
    
    db.session.commit()
    
    # Create notification for agency hub users
    create_notification_for_agency_hub(
        needs_list=needs_list,
        title="Items Dispatched",
        message=f"Items for needs list {needs_list.list_number} have been dispatched by {current_user.full_name}. Please confirm receipt when items arrive.",
        notification_type="dispatched",
        triggered_by_user=current_user
    )
    
    # Notify Warehouse Staff about dispatch completion
    create_notifications_for_role(
        role=ROLE_WAREHOUSE_STAFF,
        title="Dispatch Completed",
        message=f"Needs list {needs_list.list_number} to {needs_list.agency_hub.name} has been dispatched.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "dispatched_by": current_user.full_name,
            "dispatched_by_id": current_user.id
        },
        needs_list_id=needs_list.id
    )
    
    # Notify Field Personnel about items dispatched for potential distribution support
    create_notifications_for_role(
        role=ROLE_FIELD_PERSONNEL,
        title="Items Dispatched to Agency",
        message=f"Items for needs list {needs_list.list_number} dispatched to {needs_list.agency_hub.name}. Be ready to assist with distribution if needed.",
        notification_type="task_assigned",
        link_url=f"/needs-lists/{needs_list.id}",
        payload_data={
            "needs_list_number": needs_list.list_number,
            "agency_hub": needs_list.agency_hub.name,
            "dispatched_by": current_user.full_name,
            "dispatched_by_id": current_user.id,
            "event_type": "distribution_support"
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
        message=f"Receipt has been confirmed for needs list {needs_list.list_number} by {current_user.full_name}. Request is now completed.",
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
            "received_by": current_user.full_name,
            "received_by_id": current_user.id,
            "completed_at": datetime.utcnow().isoformat()
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
            "received_by": current_user.full_name,
            "received_by_id": current_user.id
        },
        needs_list_id=needs_list.id
    )
    
    # Notify Executives about completed deliveries for high-level oversight
    create_notifications_for_role(
        role=ROLE_EXECUTIVE,
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
        record_package_status_change(package, "Draft", "Draft", current_user.full_name, 
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
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF)
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
    
    record_package_status_change(package, old_status, "Under Review", current_user.full_name, 
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
    package.approved_by = current_user.full_name
    package.approved_at = datetime.utcnow()
    package.updated_at = datetime.utcnow()
    
    record_package_status_change(package, old_status, "Approved", current_user.full_name, approval_notes)
    
    db.session.commit()
    
    flash(f"Package {package.package_number} approved.", "success")
    return redirect(url_for("package_details", package_id=package_id))

@app.route("/packages/<int:package_id>/dispatch", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF)
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
                    created_by=current_user.full_name
                )
                db.session.add(transaction)
    
    old_status = package.status
    package.status = "Dispatched"
    package.dispatched_by = current_user.full_name
    package.dispatched_at = datetime.utcnow()
    package.updated_at = datetime.utcnow()
    
    record_package_status_change(package, old_status, "Dispatched", current_user.full_name, dispatch_notes)
    
    db.session.commit()
    
    flash(f"Package {package.package_number} dispatched successfully. Inventory updated.", "success")
    return redirect(url_for("package_details", package_id=package_id))

@app.route("/packages/<int:package_id>/deliver", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER, ROLE_WAREHOUSE_STAFF)
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
    
    record_package_status_change(package, old_status, "Delivered", current_user.full_name, delivery_notes)
    
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
        
        from datetime import datetime as dt
        start_date = dt.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = dt.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
        
        event = DisasterEvent(name=name, event_type=event_type, start_date=start_date, 
                            end_date=end_date, description=description, status=status)
        db.session.add(event)
        db.session.commit()
        flash(f"Disaster event '{name}' created successfully.", "success")
        return redirect(url_for("disaster_events"))
    return render_template("disaster_event_form.html", event=None)

@app.route("/disaster-events/<int:event_id>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_LOGISTICS_MANAGER, ROLE_LOGISTICS_OFFICER)
def disaster_event_edit(event_id):
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
        
        from datetime import datetime as dt
        start_date = dt.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = dt.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
        
        event.name = name
        event.event_type = event_type
        event.start_date = start_date
        event.end_date = end_date
        event.description = description
        event.status = status
        db.session.commit()
        flash(f"Disaster event updated successfully.", "success")
        return redirect(url_for("disaster_events"))
    return render_template("disaster_event_form.html", event=event)

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
        full_name = request.form["full_name"].strip()
        role = request.form["role"]
        password = request.form["password"]
        password_confirm = request.form["password_confirm"]
        assigned_location_id = request.form.get("assigned_location_id") or None
        
        if not email or not full_name or not role or not password:
            flash("All fields except location are required.", "danger")
            return redirect(url_for("user_new"))
        
        if password != password_confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("user_new"))
        
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return redirect(url_for("user_new"))
        
        if role not in ALL_ROLES:
            flash("Invalid role selected.", "danger")
            return redirect(url_for("user_new"))
        
        existing = User.query.filter_by(email=email).first()
        if existing:
            flash(f"User with email '{email}' already exists.", "warning")
            return redirect(url_for("user_new"))
        
        user = User(
            email=email,
            full_name=full_name,
            role=role,
            is_active=True,
            assigned_location_id=int(assigned_location_id) if assigned_location_id else None
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash(f"User '{full_name}' created successfully.", "success")
        return redirect(url_for("users"))
    
    locations = Depot.query.order_by(Depot.name.asc()).all()
    return render_template("user_form.html", user=None, all_roles=ALL_ROLES, locations=locations)

@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def user_edit(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        full_name = request.form["full_name"].strip()
        role = request.form["role"]
        is_active = request.form.get("is_active") == "on"
        assigned_location_id = request.form.get("assigned_location_id") or None
        password = request.form.get("password", "").strip()
        password_confirm = request.form.get("password_confirm", "").strip()
        
        if not email or not full_name or not role:
            flash("Email, full name, and role are required.", "danger")
            return redirect(url_for("user_edit", user_id=user_id))
        
        if role not in ALL_ROLES:
            flash("Invalid role selected.", "danger")
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
        user.full_name = full_name
        user.role = role
        user.is_active = is_active
        user.assigned_location_id = int(assigned_location_id) if assigned_location_id else None
        
        db.session.commit()
        flash(f"User '{full_name}' updated successfully.", "success")
        return redirect(url_for("users"))
    
    locations = Depot.query.order_by(Depot.name.asc()).all()
    return render_template("user_form.html", user=user, all_roles=ALL_ROLES, locations=locations)

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
            "created_at": notif.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            "created_at_iso": notif.created_at.isoformat(),
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
            "triggered_by": triggered_by_user.full_name if triggered_by_user else "System",
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
