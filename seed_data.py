#!/usr/bin/env python3
"""
DRIMS Test Data Seeding Script
Populates the database with realistic demo data for testing and demonstrations
"""

from app import app, db, User, Depot, DisasterEvent, Item, Donor, Beneficiary, Distributor, Transaction, TransferRequest, generate_sku
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
from sqlalchemy import text, inspect
import random

def migrate_schema():
    """Apply schema migrations for hub hierarchy"""
    print("\nChecking and applying schema migrations...")
    
    with app.app_context():
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('location')]
        
        # Check if hub_type column exists
        if 'hub_type' not in columns:
            print("  Adding hub_type column...")
            db.session.execute(text("ALTER TABLE location ADD COLUMN hub_type VARCHAR(10) DEFAULT 'MAIN' NOT NULL"))
            db.session.commit()
            print("  ✓ hub_type column added")
        else:
            print("  ✓ hub_type column already exists")
        
        # Check if parent_location_id column exists
        if 'parent_location_id' not in columns:
            print("  Adding parent_location_id column...")
            db.session.execute(text("ALTER TABLE location ADD COLUMN parent_location_id INTEGER REFERENCES location(id)"))
            db.session.commit()
            print("  ✓ parent_location_id column added")
        else:
            print("  ✓ parent_location_id column already exists")
        
        # Check if transfer_request table exists - use SQLAlchemy create_all for database-agnostic table creation
        if not inspector.has_table('transfer_request'):
            print("  Creating transfer_request table...")
            # Use SQLAlchemy's create_all which handles SQLite vs PostgreSQL differences
            db.create_all()
            db.session.commit()
            print("  ✓ transfer_request table created")
        else:
            print("  ✓ transfer_request table already exists")
        
        # Backfill existing locations with MAIN hub type if they don't have one set
        result = db.session.execute(text("SELECT COUNT(*) FROM location WHERE hub_type IS NULL OR hub_type = ''"))
        null_count = result.scalar()
        if null_count > 0:
            print(f"  Backfilling {null_count} locations with MAIN hub type...")
            db.session.execute(text("UPDATE location SET hub_type = 'MAIN' WHERE hub_type IS NULL OR hub_type = ''"))
            db.session.commit()
            print(f"  ✓ Backfilled {null_count} locations")
        
        # Smoke test: verify TransferRequest table supports inserts with auto-incrementing ID
        try:
            # Try to create a test TransferRequest object to ensure auto-increment works
            test_depot = db.session.query(Depot).first()
            test_item = db.session.query(Item).first()
            if test_depot and test_item:
                test_request = TransferRequest(
                    from_location_id=test_depot.id,
                    to_location_id=test_depot.id,
                    item_sku=test_item.sku,
                    quantity=1,
                    notes="Migration smoke test"
                )
                db.session.add(test_request)
                db.session.flush()  # This will trigger ID auto-increment
                db.session.rollback()  # Rollback to not pollute data
                print(f"  ✓ TransferRequest table smoke test passed (auto-increment verified)")
            else:
                # If no test data, just count rows
                test_count = db.session.query(TransferRequest).count()
                print(f"  ✓ TransferRequest table smoke test passed ({test_count} existing requests)")
        except Exception as e:
            print(f"  ✗ TransferRequest table smoke test failed: {e}")
            db.session.rollback()
            raise
        
        print("✓ Schema migrations complete")

def clear_data():
    """Clear existing data (optional)"""
    print("Clearing existing data...")
    with app.app_context():
        Transaction.query.delete()
        Item.query.delete()
        Distributor.query.delete()
        Beneficiary.query.delete()
        Donor.query.delete()
        DisasterEvent.query.delete()
        Depot.query.delete()
        User.query.delete()
        db.session.commit()
    print("✓ Data cleared")

def seed_users():
    """Create demo users with different roles"""
    print("\nSeeding users...")
    
    with app.app_context():
        existing_count = User.query.count()
        if existing_count > 0:
            print(f"  Skipping - {existing_count} users already exist")
            return
    
    users = [
        User(
            email="admin@gov.jm",
            full_name="System Administrator",
            password_hash=generate_password_hash("admin123"),
            role="ADMIN"
        ),
        User(
            email="logistics.manager@gov.jm",
            full_name="Jane Thompson",
            password_hash=generate_password_hash("logmanager123"),
            role="LOGISTICS_MANAGER"
        ),
        User(
            email="logistics.officer@gov.jm",
            full_name="Mark Davis",
            password_hash=generate_password_hash("logofficer123"),
            role="LOGISTICS_OFFICER"
        ),
        User(
            email="warehouse@gov.jm",
            full_name="Michael Brown",
            password_hash=generate_password_hash("warehouse123"),
            role="WAREHOUSE_STAFF",
            assigned_location_id=None  # Will be set after locations are created
        ),
        User(
            email="field@gov.jm",
            full_name="Sarah Williams",
            password_hash=generate_password_hash("field123"),
            role="FIELD_PERSONNEL"
        ),
        User(
            email="executive@gov.jm",
            full_name="Dr. Robert Chen",
            password_hash=generate_password_hash("exec123"),
            role="EXECUTIVE"
        ),
        User(
            email="auditor@gov.jm",
            full_name="Patricia Davis",
            password_hash=generate_password_hash("audit123"),
            role="AUDITOR"
        ),
        User(
            email="distributor@gov.jm",
            full_name="Carlos Martinez",
            password_hash=generate_password_hash("distributor123"),
            role="DISTRIBUTOR"
        ),
    ]
    
    with app.app_context():
        for user in users:
            db.session.add(user)
        db.session.commit()
    print(f"✓ Created {len(users)} users")

def seed_locations():
    """Create demo locations with three-tier hub hierarchy"""
    print("\nSeeding locations (hub hierarchy)...")
    
    with app.app_context():
        existing_count = Depot.query.count()
        if existing_count > 0:
            print(f"  Skipping - {existing_count} locations already exist")
            return
    
    with app.app_context():
        # Create MAIN hub first
        main_hub = Depot(name="Pimento JDF", hub_type="MAIN", parent_location_id=None)
        db.session.add(main_hub)
        db.session.commit()
        
        # Create SUB hubs under MAIN
        sub_hubs = [
            Depot(name="Trelawny", hub_type="SUB", parent_location_id=main_hub.id),
            Depot(name="Haining", hub_type="SUB", parent_location_id=main_hub.id),
        ]
        for hub in sub_hubs:
            db.session.add(hub)
        db.session.commit()
        
        # Create AGENCY hubs under MAIN
        agency_hubs = [
            Depot(name="Montego Bay", hub_type="AGENCY", parent_location_id=main_hub.id),
            Depot(name="Pimento", hub_type="AGENCY", parent_location_id=main_hub.id),
        ]
        for hub in agency_hubs:
            db.session.add(hub)
        db.session.commit()
        
        all_hubs = [main_hub] + sub_hubs + agency_hubs
        
        # Update warehouse staff user with location (assign to MAIN hub)
        warehouse_user = User.query.filter_by(email="warehouse@gov.jm").first()
        if warehouse_user:
            warehouse_user.assigned_location_id = main_hub.id
            db.session.commit()
    
    print(f"✓ Created {len(all_hubs)} locations in hub hierarchy:")
    print(f"  - 1 MAIN hub: Pimento JDF")
    print(f"  - 2 SUB hubs: Trelawny, Haining")
    print(f"  - 2 AGENCY hubs: Montego Bay, Pimento")

def seed_disaster_events():
    """Create demo disaster events"""
    print("\nSeeding disaster events...")
    
    with app.app_context():
        existing_count = DisasterEvent.query.count()
        if existing_count > 0:
            print(f"  Skipping - {existing_count} disaster events already exist")
            return
    
    events = [
        DisasterEvent(
            name="Hurricane Beryl 2024",
            event_type="hurricane",
            start_date=datetime(2024, 7, 1).date(),
            end_date=datetime(2024, 7, 10).date(),
            status="Closed",
            description="Major hurricane that impacted Jamaica in July 2024"
        ),
        DisasterEvent(
            name="Tropical Storm Milton",
            event_type="tropical_storm",
            start_date=datetime(2024, 10, 15).date(),
            end_date=datetime(2024, 10, 18).date(),
            status="Closed",
            description="Tropical storm with heavy rainfall"
        ),
        DisasterEvent(
            name="Hurricane Season 2025",
            event_type="hurricane",
            start_date=datetime(2025, 6, 1).date(),
            end_date=None,
            status="Active",
            description="Ongoing hurricane season preparedness and response"
        ),
        DisasterEvent(
            name="Flooding - St. Catherine",
            event_type="flood",
            start_date=datetime(2025, 10, 20).date(),
            end_date=None,
            status="Active",
            description="Flash flooding affecting St. Catherine parish"
        ),
    ]
    
    with app.app_context():
        for event in events:
            db.session.add(event)
        db.session.commit()
    print(f"✓ Created {len(events)} disaster events")

def seed_items():
    """Create demo inventory items"""
    print("\nSeeding items...")
    
    with app.app_context():
        existing_count = Item.query.count()
        if existing_count > 0:
            print(f"  Skipping - {existing_count} items already exist")
            return
    
    items_data = [
        # Food Items
        ("Rice - 25kg Bag", "Food", "bag", 50, "Store in a cool, dry place", 180),
        ("Canned Beans", "Food", "tin", 100, "Store in a cool, dry place", 730),
        ("Bottled Water - 500ml", "Water", "bottle", 200, "Keep away from direct sunlight", 365),
        ("Canned Tuna", "Food", "tin", 75, "Store in a cool, dry place", 1095),
        ("Pasta - 1kg Pack", "Food", "pack", 60, "Store in a cool, dry place", 365),
        ("Cooking Oil - 1L", "Food", "bottle", 40, "Keep away from direct sunlight", 180),
        ("Sugar - 2kg Bag", "Food", "bag", 50, "Keep sealed to prevent contamination", 730),
        
        # Hygiene Items
        ("Soap Bars", "Hygiene", "pcs", 150, "Store in a cool, dry place", None),
        ("Toothpaste", "Hygiene", "tube", 100, "Store in a cool, dry place", 730),
        ("Sanitizer - 250ml", "Hygiene", "bottle", 80, "Keep sealed to prevent contamination", 730),
        ("Toilet Paper - 4 Roll Pack", "Hygiene", "pack", 120, "Protect items from moisture", 730),
        ("Feminine Hygiene Products", "Hygiene", "pack", 60, "Store in a cool, dry place", 1095),
        
        # Medical Supplies
        ("First Aid Kit", "Medical", "kit", 30, "Keep in original packaging", 1095),
        ("Bandages - Assorted", "Medical", "box", 50, "Keep sealed to prevent contamination", 1460),
        ("Pain Relief Medicine", "Medical", "box", 40, "Store in a cool, dry place", 730),
        ("Antiseptic Solution", "Medical", "bottle", 35, "Keep away from direct sunlight", 365),
        ("Gauze Pads", "Medical", "pack", 60, "Keep sealed to prevent contamination", 1095),
        
        # Shelter Items
        ("Emergency Blankets", "Shelter", "pcs", 100, "Store in pest-free area", None),
        ("Tarpaulin - Large", "Shelter", "pcs", 25, "Protect items from moisture", None),
        ("Sleeping Mats", "Shelter", "pcs", 40, "Store off the floor (use pallets or shelves)", None),
        ("Mosquito Nets", "Shelter", "pcs", 50, "Keep in original packaging", None),
        
        # Baby Supplies
        ("Baby Formula - 400g", "Baby Care", "tin", 30, "Store in a cool, dry place", 365),
        ("Diapers - Infant Size", "Baby Care", "pack", 40, "Protect items from moisture", 730),
        ("Baby Wipes", "Baby Care", "pack", 50, "Keep sealed to prevent contamination", 730),
    ]
    
    with app.app_context():
        for name, category, unit, min_qty, storage, expiry_days in items_data:
            expiry_date = None
            if expiry_days:
                expiry_date = datetime.now().date() + timedelta(days=expiry_days)
            
            item = Item(
                sku=generate_sku(),  # Generate unique SKU
                name=name,
                category=category,
                unit=unit,
                min_qty=min_qty,
                storage_requirements=storage,
                expiry_date=expiry_date,
                description=f"Emergency relief supply: {name}"
            )
            db.session.add(item)
        db.session.commit()
    print(f"✓ Created {len(items_data)} items")

def seed_donors():
    """Create demo donors"""
    print("\nSeeding donors...")
    
    with app.app_context():
        existing_count = Donor.query.count()
        if existing_count > 0:
            print(f"  Skipping - {existing_count} donors already exist")
            return
    
    donors = [
        Donor(name="Caribbean Disaster Emergency Management Agency (CDEMA)", contact="cdema@cdema.org"),
        Donor(name="Red Cross Jamaica", contact="redcross@jamaica.org"),
        Donor(name="United Nations World Food Programme", contact="wfp@un.org"),
        Donor(name="UNICEF Jamaica", contact="jamaica@unicef.org"),
        Donor(name="USAID Caribbean", contact="usaid@caribbean.gov"),
        Donor(name="Jamaica National Foundation", contact="info@jnf.org.jm"),
        Donor(name="Private Donor - Marcus Chen", contact="m.chen@email.com"),
        Donor(name="Digicel Foundation", contact="foundation@digicelgroup.com"),
    ]
    
    with app.app_context():
        for donor in donors:
            db.session.add(donor)
        db.session.commit()
    print(f"✓ Created {len(donors)} donors")

def seed_beneficiaries():
    """Create demo beneficiaries"""
    print("\nSeeding beneficiaries...")
    
    with app.app_context():
        existing_count = Beneficiary.query.count()
        if existing_count > 0:
            print(f"  Skipping - {existing_count} beneficiaries already exist")
            return
    
    beneficiaries = [
        Beneficiary(name="Johnson Family (4 members)", contact="876-555-0101", parish="Kingston"),
        Beneficiary(name="Williams Community Group", contact="876-555-0102", parish="St. Catherine"),
        Beneficiary(name="Brown Elderly Care Center", contact="876-555-0103", parish="St. James"),
        Beneficiary(name="St. Andrew Evacuation Shelter", contact="876-555-0104", parish="St. Andrew"),
        Beneficiary(name="Port Antonio Community", contact="876-555-0105", parish="Portland"),
        Beneficiary(name="Thompson Single Mother (3 children)", contact="876-555-0106", parish="Clarendon"),
        Beneficiary(name="Manchester Relief Recipients", contact="876-555-0107", parish="Manchester"),
        Beneficiary(name="Davis Displaced Family", contact="876-555-0108", parish="St. Catherine"),
    ]
    
    with app.app_context():
        for beneficiary in beneficiaries:
            db.session.add(beneficiary)
        db.session.commit()
    print(f"✓ Created {len(beneficiaries)} beneficiaries")

def seed_distributors():
    """Create demo distributors"""
    print("\nSeeding distributors...")
    
    with app.app_context():
        existing_count = Distributor.query.count()
        if existing_count > 0:
            print(f"  Skipping - {existing_count} distributors already exist")
            return
    
    distributors = [
        Distributor(name="Sarah Williams", contact="field@gov.jm", organization="Government Relief Operations"),
        Distributor(name="Michael Brown", contact="warehouse@gov.jm", organization="Central Warehouse"),
        Distributor(name="Jamaica Defence Force - Relief Unit", contact="jdf-relief@mod.gov.jm", organization="JDF"),
        Distributor(name="Parish Council Relief Team", contact="parish-relief@gov.jm", organization="Parish Council"),
        Distributor(name="Red Cross Field Team Alpha", contact="team-alpha@redcross.jm", organization="Red Cross Jamaica"),
        Distributor(name="Community Volunteer Network", contact="volunteers@community.jm", organization="Volunteer Network"),
    ]
    
    with app.app_context():
        for distributor in distributors:
            db.session.add(distributor)
        db.session.commit()
    print(f"✓ Created {len(distributors)} distributors")

def seed_transactions():
    """Create demo transactions (both intake and distribution)"""
    print("\nSeeding transactions...")
    
    with app.app_context():
        existing_count = Transaction.query.count()
        if existing_count > 10:  # Allow some transactions to exist
            print(f"  Skipping - {existing_count} transactions already exist")
            return
        

        items = Item.query.all()
        locations = Depot.query.all()
        donors = Donor.query.all()
        beneficiaries = Beneficiary.query.all()
        distributors = Distributor.query.all()
        events = DisasterEvent.query.all()
        admin_user = User.query.filter_by(role="ADMIN").first()
        
        transaction_count = 0
        
        # Create intake transactions (donations received)
        for _ in range(40):
            item = random.choice(items)
            location = random.choice(locations)
            donor = random.choice(donors)
            event = random.choice([e for e in events if e.status == "Active"])
            
            quantity = random.randint(50, 500)
            days_ago = random.randint(1, 60)
            trans_date = datetime.now() - timedelta(days=days_ago)
            
            transaction = Transaction(
                item_sku=item.sku,
                location_id=location.id,
                ttype="IN",
                qty=quantity,
                donor_id=donor.id,
                event_id=event.id,
                notes=f"Donation received from {donor.name}",
                created_by=admin_user.full_name if admin_user else "System",
                created_at=trans_date  # Set historical timestamp
            )
            db.session.add(transaction)
            transaction_count += 1
        
        # Create distribution transactions
        for _ in range(30):
            item = random.choice(items)
            location = random.choice(locations)
            beneficiary = random.choice(beneficiaries)
            distributor = random.choice(distributors)
            event = random.choice([e for e in events if e.status == "Active"])
            
            quantity = random.randint(10, 100)
            days_ago = random.randint(1, 45)
            trans_date = datetime.now() - timedelta(days=days_ago)
            
            transaction = Transaction(
                item_sku=item.sku,
                location_id=location.id,
                ttype="OUT",
                qty=quantity,
                beneficiary_id=beneficiary.id,
                distributor_id=distributor.id,
                event_id=event.id,
                notes=f"Distributed to {beneficiary.name} by {distributor.name}",
                created_by=admin_user.full_name if admin_user else "System",
                created_at=trans_date  # Set historical timestamp
            )
            db.session.add(transaction)
            transaction_count += 1
        
        db.session.commit()
    print(f"✓ Created {transaction_count} transactions")

def main():
    """Main seeding function"""
    print("=" * 60)
    print("DRIMS Test Data Seeding Script")
    print("=" * 60)
    
    # Apply schema migrations first
    migrate_schema()
    
    # Uncomment to clear existing data first
    # clear_data()
    
    seed_users()
    seed_locations()
    seed_disaster_events()
    seed_items()
    seed_donors()
    seed_beneficiaries()
    seed_distributors()
    seed_transactions()
    
    print("\n" + "=" * 60)
    print("✓ Demo data seeding complete!")
    print("=" * 60)
    print("\nDemo Login Credentials:")
    print("-" * 60)
    print("Administrator:       admin@gov.jm / admin123")
    print("Logistics Manager:   logistics.manager@gov.jm / logmanager123")
    print("Logistics Officer:   logistics.officer@gov.jm / logofficer123")
    print("Warehouse Staff:     warehouse@gov.jm / warehouse123")
    print("Field Personnel:     field@gov.jm / field123")
    print("Executive:           executive@gov.jm / exec123")
    print("Auditor:             auditor@gov.jm / audit123")
    print("Distributor:         distributor@gov.jm / distributor123")
    print("=" * 60)

if __name__ == "__main__":
    main()
