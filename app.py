import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, case
import pandas as pd
import secrets

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
    unit = db.Column(db.String(32), nullable=False, default="unit")        # e.g., pcs, kg, L
    min_qty = db.Column(db.Integer, nullable=False, default=0)             # threshold for "low stock"
    description = db.Column(db.Text, nullable=True)

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

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_sku = db.Column(db.String(64), db.ForeignKey("item.sku"), nullable=False)
    ttype = db.Column(db.String(8), nullable=False)  # "IN" or "OUT"
    qty = db.Column(db.Integer, nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donor.id"), nullable=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiary.id"), nullable=True)
    distributor_id = db.Column(db.Integer, db.ForeignKey("distributor.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship("Item")
    location = db.relationship("Location")
    donor = db.relationship("Donor")
    beneficiary = db.relationship("Beneficiary")
    distributor = db.relationship("Distributor")

# ---------- Utility ----------
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

# ---------- Routes ----------
@app.route("/")
def dashboard():
    # KPIs
    total_items = Item.query.count()
    locations = Location.query.order_by(Location.name.asc()).all()
    
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

    # Recent transactions
    recent = Transaction.query.order_by(Transaction.created_at.desc()).limit(10).all()
    return render_template("dashboard.html",
                           total_items=total_items,
                           total_in_stock=total_in_stock,
                           low_stock=low,
                           recent=recent,
                           locations=locations,
                           stock_by_location=stock_by_location)

@app.route("/items")
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
def item_new():
    if request.method == "POST":
        name = request.form["name"].strip()
        category = request.form.get("category", "").strip() or None
        unit = request.form.get("unit", "unit").strip() or "unit"
        min_qty = int(request.form.get("min_qty", "0") or 0)
        description = request.form.get("description", "").strip() or None

        # Duplicate suggestion by normalized name+category+unit
        norm = normalize_name(name)
        existing = Item.query.filter(func.lower(Item.name) == norm, Item.category == category, Item.unit == unit).first()
        if existing:
            flash(f"Possible duplicate found: '{existing.name}' in category '{existing.category or '—'}' (unit: {existing.unit}). Consider editing that item instead.", "warning")
            return redirect(url_for("item_edit", item_sku=existing.sku))

        # Generate SKU
        sku = generate_sku()
        item = Item(sku=sku, name=name, category=category, unit=unit, min_qty=min_qty, description=description)
        db.session.add(item)
        db.session.commit()
        flash(f"Item created with SKU: {sku}", "success")
        return redirect(url_for("items"))
    return render_template("item_form.html", item=None)

@app.route("/items/<item_sku>/edit", methods=["GET", "POST"])
def item_edit(item_sku):
    item = Item.query.get_or_404(item_sku)
    if request.method == "POST":
        item.name = request.form["name"].strip()
        item.category = request.form.get("category", "").strip() or None
        item.unit = request.form.get("unit", "unit").strip() or "unit"
        item.min_qty = int(request.form.get("min_qty", "0") or 0)
        item.description = request.form.get("description", "").strip() or None
        db.session.commit()
        flash("Item updated.", "success")
        return redirect(url_for("items"))
    return render_template("item_form.html", item=item)

@app.route("/intake", methods=["GET", "POST"])
def intake():
    items = Item.query.order_by(Item.name.asc()).all()
    locations = Location.query.order_by(Location.name.asc()).all()
    if request.method == "POST":
        item_sku = request.form["item_sku"]
        qty = int(request.form["qty"])
        location_id = int(request.form["location_id"]) if request.form.get("location_id") else None
        
        # Location is required for inventory tracking
        if not location_id:
            flash("Please select a location for intake.", "danger")
            return redirect(url_for("intake"))
        
        donor_name = request.form.get("donor_name", "").strip() or None
        donor = None
        if donor_name:
            donor = Donor.query.filter_by(name=donor_name).first()
            if not donor:
                donor = Donor(name=donor_name)
                db.session.add(donor)
                db.session.flush()
        notes = request.form.get("notes", "").strip() or None

        tx = Transaction(item_sku=item_sku, ttype="IN", qty=qty, location_id=location_id,
                         donor_id=donor.id if donor else None, notes=notes)
        db.session.add(tx)
        db.session.commit()
        flash("Intake recorded.", "success")
        return redirect(url_for("dashboard"))
    return render_template("intake.html", items=items, locations=locations)

@app.route("/distribute", methods=["GET", "POST"])
def distribute():
    items = Item.query.order_by(Item.name.asc()).all()
    locations = Location.query.order_by(Location.name.asc()).all()
    distributors = Distributor.query.order_by(Distributor.name.asc()).all()
    if request.method == "POST":
        item_sku = request.form["item_sku"]
        qty = int(request.form["qty"])
        location_id = int(request.form["location_id"]) if request.form.get("location_id") else None
        beneficiary_name = request.form.get("beneficiary_name", "").strip() or None
        parish = request.form.get("parish", "").strip() or None
        distributor_id = int(request.form["distributor_id"]) if request.form.get("distributor_id") else None
        
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
                         distributor_id=distributor_id, notes=notes)
        db.session.add(tx)
        db.session.commit()
        flash("Distribution recorded.", "success")
        return redirect(url_for("dashboard"))
    return render_template("distribute.html", items=items, locations=locations, distributors=distributors)

@app.route("/transactions")
def transactions():
    rows = Transaction.query.order_by(Transaction.created_at.desc()).limit(500).all()
    return render_template("transactions.html", rows=rows)

@app.route("/reports/stock")
def report_stock():
    locations = Location.query.order_by(Location.name.asc()).all()
    items = Item.query.order_by(Item.category.asc(), Item.name.asc()).all()
    stock_map = get_stock_by_location()
    
    return render_template("report_stock.html", items=items, locations=locations, stock_map=stock_map)

@app.route("/export/items.csv")
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
def distributors():
    distrs = Distributor.query.order_by(Distributor.name.asc()).all()
    # Get distribution count per distributor
    dist_count = {}
    for d in distrs:
        count = Transaction.query.filter_by(distributor_id=d.id, ttype="OUT").count()
        dist_count[d.id] = count
    return render_template("distributors.html", distributors=distrs, dist_count=dist_count)

@app.route("/distributors/new", methods=["GET", "POST"])
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

# ---------- CLI for DB ----------
@app.cli.command("init-db")
def init_db():
    db.create_all()
    ensure_seed_data()
    print("Database initialized.")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_seed_data()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
