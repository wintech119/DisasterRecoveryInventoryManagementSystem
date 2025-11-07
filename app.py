import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
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

class Item(db.Model):
    sku = db.Column(db.String(64), primary_key=True)
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

class Distributor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    contact = db.Column(db.String(200), nullable=True)
    organization = db.Column(db.String(200), nullable=True)
    parish = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(500), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # Link to distributor login account
    
    user = db.relationship("User", backref="distributor_profile")

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
    distributor_id = db.Column(db.Integer, db.ForeignKey("distributor.id"), nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey("disaster_event.id"), nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)  # Expiry date for this batch of items
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(200), nullable=True)  # User who created the transaction (for audit)

    item = db.relationship("Item")
    location = db.relationship("Depot")
    donor = db.relationship("Donor")
    beneficiary = db.relationship("Beneficiary")
    distributor = db.relationship("Distributor")
    event = db.relationship("DisasterEvent")

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(200), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # WAREHOUSE_STAFF, FIELD_PERSONNEL, INVENTORY_MANAGER, EXECUTIVE, ADMIN, AUDITOR, DISTRIBUTOR
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

class DistributionPackage(db.Model):
    """Distribution packages created from distributor needs lists"""
    id = db.Column(db.Integer, primary_key=True)
    package_number = db.Column(db.String(64), unique=True, nullable=False, index=True)  # e.g., PKG-000001
    distributor_id = db.Column(db.Integer, db.ForeignKey("distributor.id"), nullable=False)
    assigned_location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=True)  # Warehouse/outpost
    event_id = db.Column(db.Integer, db.ForeignKey("disaster_event.id"), nullable=True)
    status = db.Column(db.String(50), nullable=False, default="Draft")  # Draft, Under Review, Approved, Dispatched, Delivered
    is_partial = db.Column(db.Boolean, default=False, nullable=False)  # True if stock insufficient for full fulfillment
    distributor_accepted_partial = db.Column(db.Boolean, nullable=True)  # None=pending, True=accepted, False=rejected
    distributor_response_at = db.Column(db.DateTime, nullable=True)
    distributor_response_notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.String(200), nullable=False)
    approved_by = db.Column(db.String(200), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    dispatched_by = db.Column(db.String(200), nullable=True)
    dispatched_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    distributor = db.relationship("Distributor")
    assigned_location = db.relationship("Depot")
    event = db.relationship("DisasterEvent")
    items = db.relationship("PackageItem", back_populates="package", cascade="all, delete-orphan")
    status_history = db.relationship("PackageStatusHistory", back_populates="package", cascade="all, delete-orphan")
    notifications = db.relationship("DistributorNotification", back_populates="package", cascade="all, delete-orphan")

class PackageItem(db.Model):
    """Items in a distribution package"""
    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(db.Integer, db.ForeignKey("distribution_package.id"), nullable=False)
    item_sku = db.Column(db.String(64), db.ForeignKey("item.sku"), nullable=False)
    requested_qty = db.Column(db.Integer, nullable=False)  # Quantity requested by distributor
    allocated_qty = db.Column(db.Integer, nullable=False, default=0)  # Actual quantity allocated (may be less if stock insufficient)
    
    package = db.relationship("DistributionPackage", back_populates="items")
    item = db.relationship("Item")

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

class DistributorNotification(db.Model):
    """In-app notifications for distributors (partial fulfillment alerts)"""
    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(db.Integer, db.ForeignKey("distribution_package.id"), nullable=False)
    distributor_id = db.Column(db.Integer, db.ForeignKey("distributor.id"), nullable=False)
    notification_type = db.Column(db.String(50), nullable=False)  # partial_fulfillment, status_update, etc.
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    package = db.relationship("DistributionPackage", back_populates="notifications")
    distributor = db.relationship("Distributor")

# ---------- Flask-Login Configuration ----------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "warning"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------- Context Processor ----------
@app.context_processor
def inject_notification_count():
    """Inject unread notification count for distributors into all templates"""
    unread_count = 0
    if current_user.is_authenticated and current_user.role == "DISTRIBUTOR":
        distributor = Distributor.query.filter_by(user_id=current_user.id).first()
        if distributor:
            unread_count = DistributorNotification.query.filter_by(
                distributor_id=distributor.id,
                is_read=False
            ).count()
    return dict(unread_notification_count=unread_count)

# ---------- Role Constants ----------
ROLE_WAREHOUSE_STAFF = "WAREHOUSE_STAFF"
ROLE_FIELD_PERSONNEL = "FIELD_PERSONNEL"
ROLE_INVENTORY_MANAGER = "INVENTORY_MANAGER"
ROLE_EXECUTIVE = "EXECUTIVE"
ROLE_ADMIN = "ADMIN"
ROLE_AUDITOR = "AUDITOR"

ALL_ROLES = [
    ROLE_WAREHOUSE_STAFF,
    ROLE_FIELD_PERSONNEL,
    ROLE_INVENTORY_MANAGER,
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
    locations = Depot.query.all()
    
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

def assign_nearest_warehouse(distributor):
    """
    Assign package to nearest warehouse based on distributor's location.
    Uses GPS coordinates if available, otherwise falls back to parish matching.
    
    Returns:
        Depot object or None
    """
    locations = Depot.query.all()
    if not locations:
        return None
    
    # Method 1: Use GPS coordinates if both distributor and locations have them
    # (Future enhancement: add latitude/longitude to Depot model for precise matching)
    # For now, we'll use parish-based matching
    
    # Method 2: Parish matching (if distributor has parish field)
    if distributor.parish:
        distributor_parish_lower = distributor.parish.lower()
        for location in locations:
            location_name_lower = location.name.lower()
            # Match if location name contains distributor's parish
            if distributor_parish_lower in location_name_lower:
                return location
    
    # Method 3: Legacy organization-based matching (fallback)
    distributor_org = (distributor.organization or "").lower()
    for location in locations:
        location_name_lower = location.name.lower()
        if any(parish in location_name_lower for parish in ["kingston", "st. andrew"] if parish in distributor_org):
            return location
        if "st. catherine" in distributor_org and "st. catherine" in location_name_lower:
            return location
        if "st. james" in distributor_org and "st. james" in location_name_lower:
            return location
        if "clarendon" in distributor_org and "clarendon" in location_name_lower:
            return location
    
    # Fallback: return first available location
    return locations[0]

def create_package_notification(package, notification_type, message):
    """
    Create an in-app notification for the distributor.
    
    Args:
        package: DistributionPackage object
        notification_type: str (e.g., 'partial_fulfillment', 'status_update')
        message: str - notification message
    """
    notification = DistributorNotification(
        package_id=package.id,
        distributor_id=package.distributor_id,
        notification_type=notification_type,
        message=message
    )
    db.session.add(notification)
    db.session.commit()
    return notification

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
    
    # KPIs - Inventory
    total_items = Item.query.count()
    locations = Depot.query.order_by(Depot.name.asc()).all()
    
    # KPIs - Operations
    total_donors = Donor.query.count()
    total_beneficiaries = Beneficiary.query.count()
    total_distributors = Distributor.query.count()
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
    
    # Pending needs lists (for inventory managers and admins)
    pending_needs_lists = []
    if current_user.role in [ROLE_ADMIN, ROLE_INVENTORY_MANAGER]:
        pending_needs_lists = DistributionPackage.query.filter_by(status="Draft")\
                                                       .order_by(DistributionPackage.created_at.asc()).all()
    
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
                           total_distributors=total_distributors,
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
                           pending_needs_lists=pending_needs_lists)

@app.route("/items")
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF, ROLE_AUDITOR, ROLE_EXECUTIVE)
def items():
    q = request.args.get("q", "").strip()
    cat = request.args.get("category", "").strip()
    
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
    locations = Depot.query.order_by(Depot.name.asc()).all()
    
    return render_template("items.html", items=all_items, q=q, cat=cat, 
                          locations=locations, stock_map=stock_map)

@app.route("/items/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
def item_new():
    if request.method == "POST":
        from datetime import datetime as dt
        name = request.form["name"].strip()
        category = request.form.get("category", "").strip() or None
        unit = request.form.get("unit", "unit").strip() or "unit"
        min_qty = int(request.form.get("min_qty", "0") or 0)
        description = request.form.get("description", "").strip() or None
        storage_requirements = request.form.get("storage_requirements", "").strip() or None

        # Duplicate suggestion by normalized name+category+unit
        norm = normalize_name(name)
        existing = Item.query.filter(func.lower(Item.name) == norm, Item.category == category, Item.unit == unit).first()
        if existing:
            flash(f"Possible duplicate found: '{existing.name}' in category '{existing.category or '—'}' (unit: {existing.unit}). Consider editing that item instead.", "warning")
            return redirect(url_for("item_edit", item_sku=existing.sku))

        # Generate SKU
        sku = generate_sku()
        item = Item(sku=sku, name=name, category=category, unit=unit, min_qty=min_qty, 
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
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
def item_edit(item_sku):
    from datetime import datetime as dt
    item = Item.query.get_or_404(item_sku)
    if request.method == "POST":
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
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
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

@app.route("/distribute", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF, ROLE_FIELD_PERSONNEL)
def distribute():
    items = Item.query.order_by(Item.name.asc()).all()
    locations = Depot.query.order_by(Depot.name.asc()).all()
    distributors = Distributor.query.order_by(Distributor.name.asc()).all()
    events = DisasterEvent.query.filter_by(status="Active").order_by(DisasterEvent.start_date.desc()).all()
    if request.method == "POST":
        item_sku = request.form["item_sku"]
        qty = int(request.form["qty"])
        location_id = int(request.form["location_id"]) if request.form.get("location_id") else None
        beneficiary_name = request.form.get("beneficiary_name", "").strip() or None
        parish = request.form.get("parish", "").strip() or None
        distributor_id = int(request.form["distributor_id"]) if request.form.get("distributor_id") else None
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
                         distributor_id=distributor_id, event_id=event_id, notes=notes,
                         created_by=current_user.full_name)
        db.session.add(tx)
        db.session.commit()
        flash("Distribution recorded.", "success")
        return redirect(url_for("dashboard"))
    return render_template("distribute.html", items=items, locations=locations, distributors=distributors, events=events)

@app.route("/transactions")
@login_required
def transactions():
    # Get sorting parameters from query string
    sort_by = request.args.get("sort_by", "created_at")
    order = request.args.get("order", "desc")
    
    # Build the query
    query = Transaction.query
    
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
    locations = Depot.query.order_by(Depot.name.asc()).all()
    items = Item.query.order_by(Item.category.asc(), Item.name.asc()).all()
    stock_map = get_stock_by_location()
    
    return render_template("report_stock.html", items=items, locations=locations, stock_map=stock_map)

@app.route("/export/items.csv")
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
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
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
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
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
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
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
def depot_new():
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Depot name is required.", "danger")
            return redirect(url_for("depot_new"))
        
        # Check for duplicates
        existing = Depot.query.filter_by(name=name).first()
        if existing:
            flash(f"Depot '{name}' already exists.", "warning")
            return redirect(url_for("depots"))
        
        location = Depot(name=name)
        db.session.add(location)
        db.session.commit()
        flash(f"Depot '{name}' created successfully.", "success")
        return redirect(url_for("depots"))
    return render_template("depot_form.html", location=None)

@app.route("/locations/<int:location_id>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
def depot_edit(location_id):
    location = Depot.query.get_or_404(location_id)
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Depot name is required.", "danger")
            return redirect(url_for("depot_edit", location_id=location_id))
        
        # Check for duplicates (excluding current location)
        existing = Depot.query.filter(Depot.name == name, Depot.id != location_id).first()
        if existing:
            flash(f"Depot '{name}' already exists.", "warning")
            return redirect(url_for("depot_edit", location_id=location_id))
        
        location.name = name
        db.session.commit()
        flash(f"Depot updated successfully.", "success")
        return redirect(url_for("depots"))
    return render_template("depot_form.html", location=location)

@app.route("/locations/<int:location_id>/inventory")
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
def depot_inventory(location_id):
    location = Depot.query.get_or_404(location_id)
    
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

@app.route("/distributors")
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
def distributors():
    distrs = Distributor.query.order_by(Distributor.name.asc()).all()
    # Get distribution count per distributor
    dist_count = {}
    for d in distrs:
        count = Transaction.query.filter_by(distributor_id=d.id, ttype="OUT").count()
        dist_count[d.id] = count
    return render_template("distributors.html", distributors=distrs, dist_count=dist_count)

@app.route("/distributors/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
def distributor_new():
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Distributor name is required.", "danger")
            return redirect(url_for("distributor_new"))
        
        contact = request.form.get("contact", "").strip() or None
        organization = request.form.get("organization", "").strip() or None
        parish = request.form.get("parish", "").strip() or None
        address = request.form.get("address", "").strip() or None
        
        # Handle GPS coordinates
        latitude = None
        longitude = None
        if request.form.get("latitude"):
            try:
                latitude = float(request.form.get("latitude"))
            except ValueError:
                flash("Invalid latitude value.", "warning")
        if request.form.get("longitude"):
            try:
                longitude = float(request.form.get("longitude"))
            except ValueError:
                flash("Invalid longitude value.", "warning")
        
        distributor = Distributor(
            name=name, 
            contact=contact, 
            organization=organization,
            parish=parish,
            address=address,
            latitude=latitude,
            longitude=longitude
        )
        db.session.add(distributor)
        db.session.commit()
        flash(f"Distributor '{name}' created successfully.", "success")
        return redirect(url_for("distributors"))
    
    # Get list of Jamaican parishes for dropdown
    parishes = [
        "Kingston", "St. Andrew", "St. Thomas", "Portland", "St. Mary",
        "St. Ann", "Trelawny", "St. James", "Hanover", "Westmoreland",
        "St. Elizabeth", "Manchester", "Clarendon", "St. Catherine"
    ]
    return render_template("distributor_form.html", distributor=None, parishes=parishes)

@app.route("/distributors/<int:distributor_id>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
def distributor_edit(distributor_id):
    distributor = Distributor.query.get_or_404(distributor_id)
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Distributor name is required.", "danger")
            return redirect(url_for("distributor_edit", distributor_id=distributor_id))
        
        distributor.name = name
        distributor.contact = request.form.get("contact", "").strip() or None
        distributor.organization = request.form.get("organization", "").strip() or None
        distributor.parish = request.form.get("parish", "").strip() or None
        distributor.address = request.form.get("address", "").strip() or None
        
        # Handle GPS coordinates
        if request.form.get("latitude"):
            try:
                distributor.latitude = float(request.form.get("latitude"))
            except ValueError:
                flash("Invalid latitude value.", "warning")
                distributor.latitude = None
        else:
            distributor.latitude = None
            
        if request.form.get("longitude"):
            try:
                distributor.longitude = float(request.form.get("longitude"))
            except ValueError:
                flash("Invalid longitude value.", "warning")
                distributor.longitude = None
        else:
            distributor.longitude = None
        
        db.session.commit()
        flash(f"Distributor updated successfully.", "success")
        return redirect(url_for("distributors"))
    
    # Get list of Jamaican parishes for dropdown
    parishes = [
        "Kingston", "St. Andrew", "St. Thomas", "Portland", "St. Mary",
        "St. Ann", "Trelawny", "St. James", "Hanover", "Westmoreland",
        "St. Elizabeth", "Manchester", "Clarendon", "St. Catherine"
    ]
    return render_template("distributor_form.html", distributor=distributor, parishes=parishes)

# ---------- Distribution Package Routes ----------

@app.route("/packages")
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
def packages():
    """List all distribution packages with filters"""
    status_filter = request.args.get("status")
    distributor_filter = request.args.get("distributor_id")
    
    query = DistributionPackage.query
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    if distributor_filter:
        query = query.filter_by(distributor_id=int(distributor_filter))
    
    packages_list = query.order_by(DistributionPackage.created_at.desc()).all()
    distributors = Distributor.query.order_by(Distributor.name).all()
    
    # Define status options for filter
    status_options = ["Draft", "Under Review", "Approved", "Dispatched", "Delivered"]
    
    return render_template("packages.html", 
                         packages=packages_list, 
                         distributors=distributors,
                         status_filter=status_filter,
                         distributor_filter=distributor_filter,
                         status_options=status_options)

@app.route("/packages/create", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
def package_create():
    """Create a new distribution package from needs list"""
    if request.method == "POST":
        distributor_id = request.form.get("distributor_id")
        event_id = request.form.get("event_id") or None
        notes = request.form.get("notes", "").strip() or None
        
        if not distributor_id:
            flash("Distributor is required.", "danger")
            return redirect(url_for("package_create"))
        
        # Parse items from form (dynamic fields: item_sku_N, item_qty_N)
        items_requested = []
        item_index = 0
        while True:
            sku_key = f"item_sku_{item_index}"
            qty_key = f"item_qty_{item_index}"
            
            if sku_key not in request.form:
                break
            
            sku = request.form[sku_key].strip()
            qty_str = request.form[qty_key].strip()
            
            if sku and qty_str:
                try:
                    qty = int(qty_str)
                    if qty > 0:
                        items_requested.append((sku, qty))
                except ValueError:
                    pass
            
            item_index += 1
        
        if not items_requested:
            flash("At least one item with quantity is required.", "danger")
            return redirect(url_for("package_create"))
        
        # Check stock availability
        availability_result = check_stock_availability(items_requested)
        
        # Create package
        package = DistributionPackage(
            package_number=generate_package_number(),
            distributor_id=int(distributor_id),
            event_id=int(event_id) if event_id else None,
            status="Draft",
            is_partial=availability_result['is_partial'],
            created_by=current_user.full_name,
            notes=notes
        )
        db.session.add(package)
        db.session.flush()  # Get package.id
        
        # Add package items
        for item_data in availability_result['items']:
            package_item = PackageItem(
                package_id=package.id,
                item_sku=item_data['sku'],
                requested_qty=item_data['requested_qty'],
                allocated_qty=item_data['allocated_qty']
            )
            db.session.add(package_item)
        
        # Record initial status
        record_package_status_change(package, None, "Draft", current_user.full_name, "Package created")
        
        db.session.commit()
        
        flash(f"Package {package.package_number} created successfully.", "success")
        return redirect(url_for("package_details", package_id=package.id))
    
    # GET request
    distributors = Distributor.query.order_by(Distributor.name).all()
    events = DisasterEvent.query.filter_by(status="Active").order_by(DisasterEvent.start_date.desc()).all()
    items = Item.query.order_by(Item.name).all()
    
    return render_template("package_form.html", 
                         distributors=distributors, 
                         events=events,
                         items=items)

@app.route("/packages/<int:package_id>")
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
def package_details(package_id):
    """View package details with full audit trail"""
    package = DistributionPackage.query.get_or_404(package_id)
    
    # Get stock availability for display
    stock_map = get_stock_by_location()
    locations = Depot.query.all()
    
    # Calculate current stock for each item
    for pkg_item in package.items:
        pkg_item.current_stock = sum(stock_map.get((pkg_item.item_sku, loc.id), 0) for loc in locations)
    
    return render_template("package_details.html", package=package)

@app.route("/packages/<int:package_id>/submit_review", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
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
    
    # If package is partial, create notification for distributor
    if package.is_partial:
        message = f"Package {package.package_number} has partial fulfillment. Some items are not available in requested quantities. Please review and accept or reject."
        create_package_notification(package, "partial_fulfillment", message)
    
    db.session.commit()
    
    flash(f"Package {package.package_number} submitted for review.", "success")
    return redirect(url_for("package_details", package_id=package_id))

@app.route("/packages/<int:package_id>/approve", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
def package_approve(package_id):
    """Approve package (Under Review → Approved)"""
    package = DistributionPackage.query.get_or_404(package_id)
    
    if package.status != "Under Review":
        flash("Only packages under review can be approved.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    # Check if partial and distributor hasn't accepted
    if package.is_partial and package.distributor_accepted_partial is None:
        flash("Waiting for distributor to accept partial fulfillment.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    if package.is_partial and package.distributor_accepted_partial is False:
        flash("Distributor rejected partial fulfillment. Package requires revision.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    approval_notes = request.form.get("approval_notes", "").strip() or None
    
    old_status = package.status
    package.status = "Approved"
    package.approved_by = current_user.full_name
    package.approved_at = datetime.utcnow()
    package.updated_at = datetime.utcnow()
    
    # Auto-assign to nearest warehouse
    assigned_location = assign_nearest_warehouse(package.distributor)
    if assigned_location:
        package.assigned_location_id = assigned_location.id
    
    record_package_status_change(package, old_status, "Approved", current_user.full_name, approval_notes)
    
    # Create status update notification
    message = f"Package {package.package_number} has been approved and assigned to {assigned_location.name if assigned_location else 'warehouse'}."
    create_package_notification(package, "status_update", message)
    
    db.session.commit()
    
    flash(f"Package {package.package_number} approved and assigned to {assigned_location.name if assigned_location else 'warehouse'}.", "success")
    return redirect(url_for("package_details", package_id=package_id))

@app.route("/packages/<int:package_id>/dispatch", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
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
    
    # Generate OUT transactions for each item
    for pkg_item in package.items:
        if pkg_item.allocated_qty > 0:
            transaction = Transaction(
                item_sku=pkg_item.item_sku,
                ttype="OUT",
                qty=pkg_item.allocated_qty,
                location_id=package.assigned_location_id,
                distributor_id=package.distributor_id,
                event_id=package.event_id,
                notes=f"Dispatched via package {package.package_number}",
                created_by=current_user.full_name
            )
            db.session.add(transaction)
    
    old_status = package.status
    package.status = "Dispatched"
    package.dispatched_by = current_user.full_name
    package.dispatched_at = datetime.utcnow()
    package.updated_at = datetime.utcnow()
    
    record_package_status_change(package, old_status, "Dispatched", current_user.full_name, dispatch_notes)
    
    # Create dispatch notification
    message = f"Package {package.package_number} has been dispatched from {package.assigned_location.name}."
    create_package_notification(package, "status_update", message)
    
    db.session.commit()
    
    flash(f"Package {package.package_number} dispatched successfully. Inventory updated.", "success")
    return redirect(url_for("package_details", package_id=package_id))

@app.route("/packages/<int:package_id>/deliver", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
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
    
    # Create delivery confirmation notification
    message = f"Package {package.package_number} has been marked as delivered."
    create_package_notification(package, "status_update", message)
    
    db.session.commit()
    
    flash(f"Package {package.package_number} marked as delivered.", "success")
    return redirect(url_for("package_details", package_id=package_id))

@app.route("/packages/<int:package_id>/distributor_response", methods=["POST"])
@login_required
def package_distributor_response(package_id):
    """Distributor accepts or rejects partial fulfillment"""
    package = DistributionPackage.query.get_or_404(package_id)
    
    # Verify user has access to this distributor's packages
    # For now, allow any logged-in user (in future, add distributor-user linking)
    
    if package.status != "Under Review":
        flash("Package is not awaiting distributor response.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    if not package.is_partial:
        flash("This package has full fulfillment, no response needed.", "warning")
        return redirect(url_for("package_details", package_id=package_id))
    
    response = request.form.get("response")  # 'accept' or 'reject'
    response_notes = request.form.get("response_notes", "").strip() or None
    
    if response == "accept":
        package.distributor_accepted_partial = True
        flash_message = "You have accepted the partial fulfillment. Package will proceed to approval."
        flash_type = "success"
    elif response == "reject":
        package.distributor_accepted_partial = False
        flash_message = "You have requested revision. Inventory manager will be notified."
        flash_type = "info"
    else:
        flash("Invalid response.", "danger")
        return redirect(url_for("package_details", package_id=package_id))
    
    package.distributor_response_at = datetime.utcnow()
    package.distributor_response_notes = response_notes
    package.updated_at = datetime.utcnow()
    
    # Mark notification as read
    for notification in package.notifications:
        if notification.notification_type == "partial_fulfillment" and not notification.is_read:
            notification.is_read = True
    
    # Create response record in audit trail
    response_text = "Accepted partial fulfillment" if response == "accept" else "Rejected partial fulfillment - requested revision"
    record_package_status_change(package, package.status, package.status, 
                                package.distributor.name, 
                                f"{response_text}. {response_notes or ''}")
    
    db.session.commit()
    
    flash(flash_message, flash_type)
    return redirect(url_for("package_details", package_id=package_id))

# ---------- Distributor Self-Service Routes ----------

@app.route("/my-needs-lists")
@role_required("DISTRIBUTOR")
def distributor_needs_lists():
    """Distributor view of their own needs lists (packages)"""
    # Find distributor profile linked to current user
    distributor = Distributor.query.filter_by(user_id=current_user.id).first()
    
    if not distributor:
        flash("No distributor profile is linked to your account. Please contact administrator.", "warning")
        return redirect(url_for("dashboard"))
    
    # Get packages for this distributor
    packages = DistributionPackage.query.filter_by(distributor_id=distributor.id)\
                                        .order_by(DistributionPackage.created_at.desc()).all()
    
    # Get all notifications (unread and read)
    all_notifications = DistributorNotification.query.filter_by(
        distributor_id=distributor.id
    ).order_by(DistributorNotification.created_at.desc()).all()
    
    # Separate unread notifications
    unread_notifications = [n for n in all_notifications if not n.is_read]
    
    return render_template("distributor_needs_lists.html", 
                         packages=packages, 
                         distributor=distributor,
                         notifications=all_notifications,
                         unread_notifications=unread_notifications)

@app.route("/my-needs-lists/create", methods=["GET", "POST"])
@role_required("DISTRIBUTOR")
def distributor_create_needs_list():
    """Distributor creates their own needs list"""
    # Find distributor profile linked to current user
    distributor = Distributor.query.filter_by(user_id=current_user.id).first()
    
    if not distributor:
        flash("No distributor profile is linked to your account. Please contact administrator.", "danger")
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        event_id = request.form.get("event_id") or None
        notes = request.form.get("notes", "").strip() or None
        
        # Parse items from form (dynamic fields: item_sku_N, item_qty_N)
        items_requested = []
        item_index = 0
        while True:
            sku_key = f"item_sku_{item_index}"
            qty_key = f"item_qty_{item_index}"
            
            if sku_key not in request.form:
                break
            
            sku = request.form[sku_key].strip()
            qty_str = request.form[qty_key].strip()
            
            if sku and qty_str:
                try:
                    qty = int(qty_str)
                    if qty > 0:
                        items_requested.append((sku, qty))
                except ValueError:
                    pass
            
            item_index += 1
        
        if not items_requested:
            flash("At least one item with quantity is required.", "danger")
            return redirect(url_for("distributor_create_needs_list"))
        
        # Create package in Draft state
        package = DistributionPackage(
            package_number=generate_package_number(),
            distributor_id=distributor.id,
            event_id=int(event_id) if event_id else None,
            status="Draft",
            is_partial=False,  # Will be checked when submitted for review
            created_by=f"{current_user.full_name} (Distributor)"
        )
        db.session.add(package)
        db.session.flush()  # Get package ID
        
        # Add package items
        for sku, qty in items_requested:
            package_item = PackageItem(
                package_id=package.id,
                item_sku=sku,
                requested_qty=qty,
                allocated_qty=qty  # Initially same as requested, will be adjusted during review
            )
            db.session.add(package_item)
        
        # Record initial status in audit trail
        record_package_status_change(package, None, "Draft", current_user.full_name, 
                                    f"Needs list created by distributor. {notes or ''}")
        
        db.session.commit()
        
        flash(f"Needs list {package.package_number} created successfully! It will be reviewed by inventory managers.", "success")
        return redirect(url_for("distributor_needs_lists"))
    
    # GET request - show form
    items = Item.query.order_by(Item.category.asc(), Item.name.asc()).all()
    events = DisasterEvent.query.filter_by(status="Active").order_by(DisasterEvent.start_date.desc()).all()
    
    return render_template("distributor_needs_list_form.html", 
                         items=items, 
                         events=events,
                         distributor=distributor)

@app.route("/notifications/mark-read/<int:notification_id>", methods=["POST"])
@role_required("DISTRIBUTOR")
def mark_notification_read(notification_id):
    """Mark a notification as read"""
    notification = DistributorNotification.query.get_or_404(notification_id)
    
    # Verify the notification belongs to the current user's distributor
    distributor = Distributor.query.filter_by(user_id=current_user.id).first()
    if not distributor or notification.distributor_id != distributor.id:
        flash("Unauthorized access to notification.", "danger")
        return redirect(url_for("dashboard"))
    
    notification.is_read = True
    db.session.commit()
    
    flash("Notification marked as read.", "success")
    return redirect(request.referrer or url_for("distributor_needs_lists"))

@app.route("/notifications/mark-all-read", methods=["POST"])
@role_required("DISTRIBUTOR")
def mark_all_notifications_read():
    """Mark all notifications as read for current distributor"""
    distributor = Distributor.query.filter_by(user_id=current_user.id).first()
    
    if not distributor:
        flash("No distributor profile found.", "danger")
        return redirect(url_for("dashboard"))
    
    DistributorNotification.query.filter_by(
        distributor_id=distributor.id,
        is_read=False
    ).update({"is_read": True})
    db.session.commit()
    
    flash("All notifications marked as read.", "success")
    return redirect(url_for("distributor_needs_lists"))

@app.route("/disaster-events")
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
def disaster_events():
    events = DisasterEvent.query.order_by(DisasterEvent.start_date.desc()).all()
    # Get transaction counts per event
    event_txn_count = {}
    for ev in events:
        count = Transaction.query.filter_by(event_id=ev.id).count()
        event_txn_count[ev.id] = count
    return render_template("disaster_events.html", events=events, event_txn_count=event_txn_count)

@app.route("/disaster-events/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
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
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
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
    print("3. Inventory Manager")
    print("4. Executive Management")
    print("5. System Administrator")
    print("6. Auditor")
    
    role_choice = input("\nSelect role (1-6): ").strip()
    role_map = {
        "1": ROLE_WAREHOUSE_STAFF,
        "2": ROLE_FIELD_PERSONNEL,
        "3": ROLE_INVENTORY_MANAGER,
        "4": ROLE_EXECUTIVE,
        "5": ROLE_ADMIN,
        "6": ROLE_AUDITOR
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

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_seed_data()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
