"""
Database Migration Script: Update NeedsList Status from 'Fulfilled' to 'Completed'

This script updates any existing NeedsList records with status='Fulfilled' to status='Completed'
to align with the official workflow statuses.

Usage:
    python migrate_fulfilled_to_completed.py
"""
from app import app, db, NeedsList

def migrate_fulfilled_to_completed():
    """Update all NeedsList records from 'Fulfilled' to 'Completed' status"""
    with app.app_context():
        # Find all needs lists with 'Fulfilled' status
        fulfilled_lists = NeedsList.query.filter_by(status='Fulfilled').all()
        
        if not fulfilled_lists:
            print("✓ No records found with 'Fulfilled' status. Database is up to date.")
            return
        
        print(f"Found {len(fulfilled_lists)} needs lists with 'Fulfilled' status.")
        print("Updating to 'Completed' status...")
        
        # Update each record
        for needs_list in fulfilled_lists:
            old_status = needs_list.status
            needs_list.status = 'Completed'
            print(f"  - {needs_list.list_number}: {old_status} → Completed")
        
        # Commit changes
        db.session.commit()
        print(f"✓ Successfully updated {len(fulfilled_lists)} records to 'Completed' status.")

if __name__ == '__main__':
    migrate_fulfilled_to_completed()
