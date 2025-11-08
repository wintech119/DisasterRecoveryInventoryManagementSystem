#!/usr/bin/env python3
"""
Migration: Add status and operational_timestamp columns to location table
"""
from app import app, db
from datetime import datetime

def migrate():
    with app.app_context():
        print("Starting migration: Add status and operational_timestamp to location table...")
        
        # Add status column (default to 'Active' for all existing hubs)
        try:
            db.session.execute(db.text("""
                ALTER TABLE location 
                ADD COLUMN IF NOT EXISTS status VARCHAR(10) DEFAULT 'Active' NOT NULL
            """))
            print("✓ Added status column")
        except Exception as e:
            print(f"Note: status column may already exist - {e}")
        
        # Add operational_timestamp column
        try:
            db.session.execute(db.text("""
                ALTER TABLE location 
                ADD COLUMN IF NOT EXISTS operational_timestamp TIMESTAMP
            """))
            print("✓ Added operational_timestamp column")
        except Exception as e:
            print(f"Note: operational_timestamp column may already exist - {e}")
        
        # Set operational_timestamp to current time for all existing Active hubs
        try:
            db.session.execute(db.text("""
                UPDATE location 
                SET operational_timestamp = :now 
                WHERE status = 'Active' AND operational_timestamp IS NULL
            """), {"now": datetime.utcnow()})
            print("✓ Set operational_timestamp for existing Active hubs")
        except Exception as e:
            print(f"Note: Could not update timestamps - {e}")
        
        db.session.commit()
        print("✓ Migration completed successfully!")
        
        # Verify the changes
        result = db.session.execute(db.text("SELECT id, name, status, operational_timestamp FROM location LIMIT 5"))
        print("\nSample data after migration:")
        for row in result:
            print(f"  ID: {row[0]}, Name: {row[1]}, Status: {row[2]}, Timestamp: {row[3]}")

if __name__ == "__main__":
    migrate()
