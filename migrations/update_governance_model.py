"""
Migration: Update Users to New Governance Model
Updates user data to align with the new governance model, Hub types, and Agency Hub logic.
"""

import sys
sys.path.insert(0, '.')

from app import app, db, User, Role, UserRole, Depot

# New governance model roles
NEW_ROLES = [
    {
        'code': 'ADMIN',
        'name': 'System Administrator',
        'description': 'Full system access and user management'
    },
    {
        'code': 'LOGISTICS_MANAGER',
        'name': 'Logistics Manager',
        'description': 'Manages logistics operations, has final approval rights for needs lists and transfers'
    },
    {
        'code': 'LOGISTICS_OFFICER',
        'name': 'Logistics Officer',
        'description': 'Handles logistics coordination and fulfillment planning, prepares but does not approve'
    },
    {
        'code': 'MAIN_HUB_USER',
        'name': 'Main Hub User',
        'description': 'Operations at government-owned Main Hub facilities'
    },
    {
        'code': 'SUB_HUB_USER',
        'name': 'Sub-Hub User',
        'description': 'Operations at government-owned Sub-Hub facilities'
    },
    {
        'code': 'AGENCY_HUB_USER',
        'name': 'Agency Hub User',
        'description': 'Independent Agency Hubs (e.g., Food for the Poor, Red Cross) with private inventory'
    },
    {
        'code': 'AUDITOR',
        'name': 'Auditor / M&E Officer',
        'description': 'Read-only audit and compliance review access'
    },
    {
        'code': 'INVENTORY_CLERK',
        'name': 'Inventory Clerk',
        'description': 'Inventory management and stock tracking (optional for future use)'
    }
]

# Updated user data aligned with new governance model
UPDATED_USERS = [
    {
        'id': 1,
        'email': 'admin@gov.jm',
        'first_name': 'System',
        'last_name': 'Administrator',
        'role': 'ADMIN',
        'location_name': None,
        'organization': 'Government of Jamaica',
        'job_title': 'Administrator',
        'phone': None
    },
    {
        'id': 2,
        'email': 'manager@gov.jm',
        'first_name': 'Maria',
        'last_name': 'Johnson',
        'role': 'LOGISTICS_MANAGER',
        'location_name': 'Trelawny',
        'organization': 'Ministry of Local Government / ODPEM',
        'job_title': 'National Logistics Manager',
        'phone': None
    },
    {
        'id': 3,
        'email': 'warehouse@gov.jm',
        'first_name': 'John',
        'last_name': 'Brown',
        'role': 'MAIN_HUB_USER',
        'location_name': 'Pimento JDF',
        'organization': 'Government of Jamaica',
        'job_title': 'Main Hub Operations Officer',
        'phone': None
    },
    {
        'id': 4,
        'email': 'executive@gov.jm',
        'first_name': 'Dr. Sarah',
        'last_name': 'Williams',
        'role': 'AUDITOR',
        'location_name': None,
        'organization': 'Ministry of Local Government',
        'job_title': 'Executive Auditor',
        'phone': None
    },
    {
        'id': 5,
        'email': 'field@gov.jm',
        'first_name': 'Michael',
        'last_name': 'Davis',
        'role': 'SUB_HUB_USER',
        'location_name': 'Montego Bay',
        'organization': 'Government of Jamaica',
        'job_title': 'Sub-Hub Field Operator',
        'phone': None
    },
    {
        'id': 7,
        'email': 'distributor@gov.jm',
        'first_name': 'Sarah',
        'last_name': 'Williams',
        'role': 'AGENCY_HUB_USER',
        'location_name': 'Food for the Poor',
        'organization': 'Food for the Poor Jamaica',
        'job_title': 'Agency Warehouse Staff',
        'phone': None
    },
    {
        'id': 8,
        'email': 'logistics.manager@gov.jm',
        'first_name': 'Jane',
        'last_name': 'Thompson',
        'role': 'LOGISTICS_MANAGER',
        'location_name': 'Pimento JDF',
        'organization': 'Ministry of Local Government / ODPEM',
        'job_title': 'Logistics Division Head',
        'phone': None
    },
    {
        'id': 9,
        'email': 'logistics.officer@gov.jm',
        'first_name': 'Mark',
        'last_name': 'Davis',
        'role': 'LOGISTICS_OFFICER',
        'location_name': 'Haining',
        'organization': 'ODPEM',
        'job_title': 'National Logistics Officer',
        'phone': None
    },
    {
        'id': 10,
        'email': 'redcross@gov.jm',
        'first_name': 'James',
        'last_name': 'Brown',
        'role': 'AGENCY_HUB_USER',
        'location_name': 'Red Cross',
        'organization': 'Jamaica Red Cross',
        'job_title': 'Agency Logistics Coordinator',
        'phone': None
    },
    {
        'id': 11,
        'email': 'rick.james@gov.jm',
        'first_name': 'Rick',
        'last_name': 'James',
        'role': 'SUB_HUB_USER',
        'location_name': 'Montego Bay',
        'organization': 'ODPEM',
        'job_title': 'Warehouse Supervisor',
        'phone': None
    }
]


def update_governance_model():
    """Update roles and users to align with new governance model."""
    
    with app.app_context():
        print("=" * 60)
        print("GOVERNANCE MODEL UPDATE MIGRATION")
        print("=" * 60)
        
        # Step 1: Update Role table with new governance roles
        print("\n[1/4] Updating Role table with new governance model...")
        
        role_mapping = {}
        for role_data in NEW_ROLES:
            role = Role.query.filter_by(code=role_data['code']).first()
            if role:
                # Update existing role
                role.name = role_data['name']
                role.description = role_data['description']
                print(f"  ✓ Updated role: {role_data['name']}")
            else:
                # Create new role
                role = Role(
                    code=role_data['code'],
                    name=role_data['name'],
                    description=role_data['description']
                )
                db.session.add(role)
                print(f"  + Created role: {role_data['name']}")
            
            role_mapping[role_data['code']] = role
        
        db.session.flush()
        
        # Step 2: Get location mapping
        print("\n[2/4] Building location mapping...")
        locations = Depot.query.all()
        location_mapping = {loc.name: loc for loc in locations}
        print(f"  ✓ Found {len(locations)} locations")
        
        # Step 3: Update users with new data
        print("\n[3/4] Updating user records...")
        
        for user_data in UPDATED_USERS:
            user = User.query.get(user_data['id'])
            if not user:
                print(f"  ✗ User ID {user_data['id']} not found - skipping")
                continue
            
            # Update basic info
            user.first_name = user_data['first_name']
            user.last_name = user_data['last_name']
            user.organization = user_data['organization']
            user.job_title = user_data['job_title']
            user.phone = user_data['phone']
            
            # Update legacy full_name for backwards compatibility
            user.full_name = f"{user_data['first_name']} {user_data['last_name']}"
            
            # Update legacy role field for backwards compatibility
            user.role = user_data['role']
            
            # Update location
            if user_data['location_name']:
                location = location_mapping.get(user_data['location_name'])
                if location:
                    user.assigned_location_id = location.id
                else:
                    print(f"  ⚠ Location '{user_data['location_name']}' not found for user {user.email}")
                    user.assigned_location_id = None
            else:
                user.assigned_location_id = None
            
            print(f"  ✓ Updated {user.email}: {user_data['first_name']} {user_data['last_name']} ({user_data['role']})")
        
        db.session.flush()
        
        # Step 4: Update UserRole mappings
        print("\n[4/4] Updating UserRole mappings...")
        
        for user_data in UPDATED_USERS:
            user = User.query.get(user_data['id'])
            if not user:
                continue
            
            # Clear existing role assignments
            UserRole.query.filter_by(user_id=user.id).delete()
            
            # Add new role assignment
            role = role_mapping.get(user_data['role'])
            if role:
                user_role = UserRole(user_id=user.id, role_id=role.id)
                db.session.add(user_role)
                print(f"  ✓ Assigned {user.email} → {user_data['role']}")
        
        # Commit all changes
        db.session.commit()
        
        print("\n" + "=" * 60)
        print("MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)
        
        # Verification
        print("\n[VERIFICATION] Updated user summary:")
        print("-" * 60)
        users = User.query.order_by(User.id).all()
        for user in users:
            location = user.assigned_location.name if user.assigned_location else "None"
            hub_type = user.assigned_location.hub_type if user.assigned_location else "N/A"
            print(f"  {user.id:2d}. {user.display_name:25s} | {user.role:20s} | {location:15s} ({hub_type})")
        
        print("\n[VERIFICATION] Role summary:")
        print("-" * 60)
        roles = Role.query.all()
        for role in roles:
            user_count = UserRole.query.filter_by(role_id=role.id).count()
            print(f"  {role.name:20s}: {user_count} user(s)")
        
        print("\n✅ All users updated to align with new governance model!")


if __name__ == '__main__':
    update_governance_model()
