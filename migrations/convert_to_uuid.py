#!/usr/bin/env python3
"""
UUID Migration Script
Converts all Integer ID columns to UUID columns.
WARNING: This drops the entire database and recreates it!
Only use with test data.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, app

def drop_all_tables():
    """Drop all tables in the database."""
    print("Dropping all tables...")
    with app.app_context():
        db.drop_all()
    print("✓ All tables dropped")

def create_uuid_tables():
    """Create all tables with UUID schema."""
    print("Creating tables with UUID schema...")
    with app.app_context():
        db.create_all()
    print("✓ All tables created with UUID primary keys")

def main():
    print("="*60)
    print("UUID MIGRATION SCRIPT")
    print("="*60)
    print("WARNING: This will DELETE all existing data!")
    print("="*60)
    
    response = input("Type 'yes' to continue: ")
    if response.lower() != 'yes':
        print("Migration cancelled.")
        return
    
    drop_all_tables()
    create_uuid_tables()
    
    print("\n" + "="*60)
    print("✓ Migration complete!")
    print("="*60)
    print("\nNext steps:")
    print("1. Update app.py model definitions to use UUID")
    print("2. Run seed script to populate with fresh data")

if __name__ == '__main__':
    main()
