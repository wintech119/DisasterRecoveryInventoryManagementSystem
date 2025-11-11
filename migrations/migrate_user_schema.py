"""
User Schema Migration Script

This script migrates the DRIMS user management system to the new normalized schema.
It performs the following operations:
1. Creates new tables: role, user_role, user_hub
2. Seeds the roles table with standard roles
3. Migrates existing user data to the new structure
4. Splits full_name into first_name and last_name
5. Migrates role strings to role relationships
6. Migrates assigned_location to user_hubs relationships

Run this script ONCE after deploying the new models.
"""

from app import app, db, User, Role, UserRole, UserHub
from datetime import datetime


def split_full_name(full_name):
    """Split full_name into first_name and last_name"""
    if not full_name:
        return "Unknown", "User"
    
    parts = full_name.strip().split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def seed_roles():
    """Create standard roles in the roles table"""
    print("Seeding roles...")
    
    roles_data = [
        {
            'code': 'ADMIN',
            'name': 'Administrator',
            'description': 'Full system access and user management'
        },
        {
            'code': 'LOGISTICS_MANAGER',
            'name': 'Logistics Manager',
            'description': 'Manages logistics operations, approves needs lists and transfers'
        },
        {
            'code': 'LOGISTICS_OFFICER',
            'name': 'Logistics Officer',
            'description': 'Handles logistics coordination and fulfillment planning'
        },
        {
            'code': 'WAREHOUSE_SUPERVISOR',
            'name': 'Warehouse Supervisor',
            'description': 'Supervises warehouse operations at Sub-Hub level'
        },
        {
            'code': 'WAREHOUSE_OFFICER',
            'name': 'Warehouse Officer',
            'description': 'Manages warehouse dispatch and inventory at Sub-Hub level'
        },
        {
            'code': 'WAREHOUSE_STAFF',
            'name': 'Warehouse Staff',
            'description': 'General warehouse operations and stock management'
        },
        {
            'code': 'FIELD_PERSONNEL',
            'name': 'Field Personnel',
            'description': 'Agency hub field staff managing requests and distributions'
        },
        {
            'code': 'EXECUTIVE',
            'name': 'Executive',
            'description': 'Executive oversight and reporting access'
        },
        {
            'code': 'AUDITOR',
            'name': 'Auditor',
            'description': 'Audit and compliance review access'
        }
    ]
    
    created_count = 0
    for role_data in roles_data:
        existing = Role.query.filter_by(code=role_data['code']).first()
        if not existing:
            role = Role(**role_data)
            db.session.add(role)
            created_count += 1
            print(f"  Created role: {role_data['code']}")
        else:
            print(f"  Role already exists: {role_data['code']}")
    
    db.session.commit()
    print(f"Roles seeded: {created_count} new, {len(roles_data) - created_count} existing\n")


def migrate_user_data():
    """Migrate existing user data to new schema"""
    print("Migrating user data...")
    
    users = User.query.all()
    total_users = len(users)
    migrated_count = 0
    
    # Get all roles for mapping
    role_map = {r.code: r for r in Role.query.all()}
    
    for user in users:
        print(f"  Migrating user: {user.email}")
        
        # 1. Split full_name into first_name and last_name
        if user.full_name and not user.first_name:
            first, last = split_full_name(user.full_name)
            user.first_name = first
            user.last_name = last
            print(f"    Split name: '{user.full_name}' → '{first}' + '{last}'")
        
        # 2. Migrate legacy role to user_roles table
        if user.role and not user.user_roles:
            role_obj = role_map.get(user.role)
            if role_obj:
                user_role = UserRole(
                    user_id=user.id,
                    role_id=role_obj.id,
                    assigned_at=user.created_at or datetime.utcnow()
                )
                db.session.add(user_role)
                print(f"    Assigned role: {user.role}")
            else:
                print(f"    WARNING: Unknown role '{user.role}' - skipping")
        
        # 3. Migrate assigned_location to user_hubs table
        if user.assigned_location_id and not user.user_hubs:
            user_hub = UserHub(
                user_id=user.id,
                hub_id=user.assigned_location_id,
                assigned_at=user.created_at or datetime.utcnow()
            )
            db.session.add(user_hub)
            print(f"    Assigned hub: {user.assigned_location_id}")
        
        # 4. Set default timezone and language if not set
        if not user.timezone:
            user.timezone = 'America/Jamaica'
        if not user.language:
            user.language = 'en'
        
        migrated_count += 1
    
    db.session.commit()
    print(f"\nUser data migrated: {migrated_count}/{total_users} users\n")


def verify_migration():
    """Verify the migration was successful"""
    print("Verifying migration...")
    
    # Check roles
    role_count = Role.query.count()
    print(f"  Roles in database: {role_count}")
    
    # Check user_roles
    user_role_count = UserRole.query.count()
    print(f"  User-role assignments: {user_role_count}")
    
    # Check user_hubs
    user_hub_count = UserHub.query.count()
    print(f"  User-hub assignments: {user_hub_count}")
    
    # Check users with first_name
    users_with_names = User.query.filter(User.first_name.isnot(None)).count()
    total_users = User.query.count()
    print(f"  Users with first_name: {users_with_names}/{total_users}")
    
    # Sample user check
    print("\nSample user check:")
    sample_user = User.query.first()
    if sample_user:
        print(f"  Email: {sample_user.email}")
        print(f"  Display Name: {sample_user.display_name}")
        print(f"  First Name: {sample_user.first_name}")
        print(f"  Last Name: {sample_user.last_name}")
        print(f"  Roles: {sample_user.roles}")
        print(f"  Hubs: {[h.name for h in sample_user.hubs]}")
    
    print("\n✅ Migration verification complete!\n")


def add_new_columns():
    """Add new columns to existing user table"""
    print("Adding new columns to user table...")
    
    # SQL statements to add new columns
    alter_statements = [
        # Name fields
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS first_name VARCHAR(100)",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS last_name VARCHAR(100)",
        
        # Profile fields
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS organization VARCHAR(200)",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS job_title VARCHAR(200)",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS phone VARCHAR(50)",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS timezone VARCHAR(50) DEFAULT 'America/Jamaica'",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en'",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS notification_preferences TEXT",
        
        # Audit fields
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS created_by_id INTEGER",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS updated_by_id INTEGER",
        
        # Make legacy fields nullable for gradual migration
        "ALTER TABLE \"user\" ALTER COLUMN full_name DROP NOT NULL",
        "ALTER TABLE \"user\" ALTER COLUMN role DROP NOT NULL",
    ]
    
    for statement in alter_statements:
        try:
            db.session.execute(db.text(statement))
            print(f"  ✓ {statement.split('ADD COLUMN IF NOT EXISTS')[-1].split()[0] if 'ADD COLUMN' in statement else 'Modified constraint'}")
        except Exception as e:
            print(f"  ⚠ Error: {e}")
    
    db.session.commit()
    print("Columns added.\n")


def main():
    """Run the migration"""
    print("=" * 60)
    print("DRIMS User Schema Migration")
    print("=" * 60)
    print()
    
    with app.app_context():
        # Create new tables (role, user_role, user_hub)
        print("Creating new tables...")
        db.create_all()
        print("Tables created.\n")
        
        # Add new columns to existing user table
        add_new_columns()
        
        # Seed roles
        seed_roles()
        
        # Migrate users
        migrate_user_data()
        
        # Verify
        verify_migration()
        
        print("=" * 60)
        print("Migration complete!")
        print("=" * 60)


if __name__ == '__main__':
    main()
