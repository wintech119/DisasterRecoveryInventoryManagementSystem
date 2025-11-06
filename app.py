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
class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)  # e.g., Parish depot / shelter

class Item(db.Model):
    sku = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    category = db.Column(db.String(120), nullable=True, index=True)       # e.g., Food, Water, Hygiene, Medical
    unit = db.Column(db.String(32), nullable=False, default="unit")        # Unit of measure: e.g., pcs, kg, L, boxes
    min_qty = db.Column(db.Integer, nullable=False, default=0)             # threshold for "low stock"
    description = db.Column(db.Text, nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)                        # Expiry date for perishable items
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
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(200), nullable=True)  # User who created the transaction (for audit)

    item = db.relationship("Item")
    location = db.relationship("Location")
    donor = db.relationship("Donor")
    beneficiary = db.relationship("Beneficiary")
    distributor = db.relationship("Distributor")
    event = db.relationship("DisasterEvent")

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(200), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # WAREHOUSE_STAFF, FIELD_PERSONNEL, INVENTORY_MANAGER, EXECUTIVE, ADMIN, AUDITOR
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    assigned_location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=True)  # For warehouse staff
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    assigned_location = db.relationship("Location")
    
    def set_password(self, password):
        """Hash and set the user's password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password against hash"""
        return check_password_hash(self.password_hash, password)
    
    def get_id(self):
        """Required by Flask-Login"""
        return str(self.id)

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
    if Location.query.count() == 0:
        for name in ["Kingston & St. Andrew Depot", "St. Catherine Depot", "St. James Depot", "Clarendon Depot"]:
            db.session.add(Location(name=name))
    # Seed categories via a sample item (not necessary, categories are free text)
    db.session.commit()

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
    locations = Location.query.order_by(Location.name.asc()).all()
    
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
            stock_by_category[category] = {"items": 0, "total_units": 0}
        stock_by_category[category]["items"] += 1
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
    
    # Expiring items (within next 30 days)
    from datetime import date, timedelta
    today = date.today()
    thirty_days = today + timedelta(days=30)
    expiring_items_query = Item.query.filter(
        Item.expiry_date.isnot(None),
        Item.expiry_date <= thirty_days,
        Item.expiry_date >= today
    ).order_by(Item.expiry_date.asc()).all()
    
    # Calculate days remaining for each expiring item
    expiring_items_all = []
    for item in expiring_items_query:
        days_remaining = (item.expiry_date - today).days
        expiring_items_all.append({
            'item': item,
            'days_remaining': days_remaining,
            'urgency': 'critical' if days_remaining <= 7 else 'warning' if days_remaining <= 14 else 'normal'
        })
    
    expiring_items_preview = expiring_items_all[:PREVIEW_LIMIT]
    expiring_items_full = expiring_items_all
    
    # Recent transactions
    recent_all = Transaction.query.order_by(Transaction.created_at.desc()).limit(50).all()
    recent_preview = recent_all[:PREVIEW_LIMIT]
    recent_full = recent_all
    
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
                           expiring_items_full=expiring_items_full)

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
    locations = Location.query.order_by(Location.name.asc()).all()
    
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
        
        # Parse expiry date
        expiry_date = None
        expiry_str = request.form.get("expiry_date", "").strip()
        if expiry_str:
            try:
                expiry_date = dt.strptime(expiry_str, "%Y-%m-%d").date()
            except:
                pass

        # Duplicate suggestion by normalized name+category+unit
        norm = normalize_name(name)
        existing = Item.query.filter(func.lower(Item.name) == norm, Item.category == category, Item.unit == unit).first()
        if existing:
            flash(f"Possible duplicate found: '{existing.name}' in category '{existing.category or '—'}' (unit: {existing.unit}). Consider editing that item instead.", "warning")
            return redirect(url_for("item_edit", item_sku=existing.sku))

        # Generate SKU
        sku = generate_sku()
        item = Item(sku=sku, name=name, category=category, unit=unit, min_qty=min_qty, 
                   description=description, expiry_date=expiry_date, storage_requirements=storage_requirements)
        
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
        
        # Parse expiry date
        expiry_str = request.form.get("expiry_date", "").strip()
        if expiry_str:
            try:
                item.expiry_date = dt.strptime(expiry_str, "%Y-%m-%d").date()
            except:
                item.expiry_date = None
        else:
            item.expiry_date = None
        
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
    locations = Location.query.order_by(Location.name.asc()).all()
    events = DisasterEvent.query.filter_by(status="Active").order_by(DisasterEvent.start_date.desc()).all()
    if request.method == "POST":
        item_sku = request.form["item_sku"]
        qty = int(request.form["qty"])
        location_id = int(request.form["location_id"]) if request.form.get("location_id") else None
        
        # Location is required for inventory tracking
        if not location_id:
            flash("Please select a location for intake.", "danger")
            return redirect(url_for("intake"))
        
        donor_name = request.form.get("donor_name", "").strip() or None
        event_id = int(request.form["event_id"]) if request.form.get("event_id") else None
        
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

        tx = Transaction(item_sku=item_sku, ttype="IN", qty=qty, location_id=location_id,
                         donor_id=donor.id if donor else None, event_id=event_id, notes=notes,
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
    locations = Location.query.order_by(Location.name.asc()).all()
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
                loc_name = Location.query.get(location_id).name
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
    rows = Transaction.query.order_by(Transaction.created_at.desc()).limit(500).all()
    return render_template("transactions.html", rows=rows)

@app.route("/reports/stock")
@login_required
def report_stock():
    locations = Location.query.order_by(Location.name.asc()).all()
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

@app.route("/locations")
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
def locations():
    locs = Location.query.order_by(Location.name.asc()).all()
    # Get stock counts per location
    stock_by_loc = {}
    for loc in locs:
        stock_rows = db.session.query(
            func.sum(case((Transaction.ttype == "IN", Transaction.qty), else_=-Transaction.qty))
        ).filter(Transaction.location_id == loc.id).scalar()
        stock_by_loc[loc.id] = stock_rows or 0
    return render_template("locations.html", locations=locs, stock_by_loc=stock_by_loc)

@app.route("/locations/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
def location_new():
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Location name is required.", "danger")
            return redirect(url_for("location_new"))
        
        # Check for duplicates
        existing = Location.query.filter_by(name=name).first()
        if existing:
            flash(f"Location '{name}' already exists.", "warning")
            return redirect(url_for("locations"))
        
        location = Location(name=name)
        db.session.add(location)
        db.session.commit()
        flash(f"Location '{name}' created successfully.", "success")
        return redirect(url_for("locations"))
    return render_template("location_form.html", location=None)

@app.route("/locations/<int:location_id>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER)
def location_edit(location_id):
    location = Location.query.get_or_404(location_id)
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Location name is required.", "danger")
            return redirect(url_for("location_edit", location_id=location_id))
        
        # Check for duplicates (excluding current location)
        existing = Location.query.filter(Location.name == name, Location.id != location_id).first()
        if existing:
            flash(f"Location '{name}' already exists.", "warning")
            return redirect(url_for("location_edit", location_id=location_id))
        
        location.name = name
        db.session.commit()
        flash(f"Location updated successfully.", "success")
        return redirect(url_for("locations"))
    return render_template("location_form.html", location=location)

@app.route("/locations/<int:location_id>/inventory")
@role_required(ROLE_ADMIN, ROLE_INVENTORY_MANAGER, ROLE_WAREHOUSE_STAFF)
def location_inventory(location_id):
    location = Location.query.get_or_404(location_id)
    
    # Get all items with stock at this location
    stock_expr = func.sum(
        case((Transaction.ttype == "IN", Transaction.qty), else_=-Transaction.qty)
    ).label("stock")
    
    rows = db.session.query(Item, stock_expr).join(
        Transaction, Item.sku == Transaction.item_sku
    ).filter(
        Transaction.location_id == location_id
    ).group_by(Item.sku).order_by(Item.category.asc(), Item.name.asc()).all()
    
    return render_template("location_inventory.html", location=location, rows=rows)

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
        
        distributor = Distributor(name=name, contact=contact, organization=organization)
        db.session.add(distributor)
        db.session.commit()
        flash(f"Distributor '{name}' created successfully.", "success")
        return redirect(url_for("distributors"))
    return render_template("distributor_form.html", distributor=None)

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
        db.session.commit()
        flash(f"Distributor updated successfully.", "success")
        return redirect(url_for("distributors"))
    return render_template("distributor_form.html", distributor=distributor)

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
        locations = Location.query.all()
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
