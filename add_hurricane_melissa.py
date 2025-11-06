#!/usr/bin/env python3
"""
Add Hurricane Melissa disaster event to DRIMS database
"""

from app import app, db, DisasterEvent
from datetime import date

def add_hurricane_melissa():
    """Add Hurricane Melissa event to the database"""
    with app.app_context():
        # Check if Hurricane Melissa already exists
        existing = DisasterEvent.query.filter_by(name="Hurricane Melissa").first()
        
        if existing:
            print("✓ Hurricane Melissa already exists in the database")
            print(f"  Event ID: {existing.id}")
            print(f"  Start Date: {existing.start_date}")
            print(f"  Status: {existing.status}")
            return
        
        # Create Hurricane Melissa event
        hurricane_melissa = DisasterEvent(
            name="Hurricane Melissa",
            event_type="Hurricane",
            start_date=date(2025, 10, 28),
            end_date=None,  # Still active/ongoing
            description="Category 4 hurricane affecting Jamaica with high winds and heavy rainfall. Emergency relief operations in progress.",
            status="Active"
        )
        
        db.session.add(hurricane_melissa)
        db.session.commit()
        
        print("✓ Hurricane Melissa added successfully!")
        print(f"  Event ID: {hurricane_melissa.id}")
        print(f"  Name: {hurricane_melissa.name}")
        print(f"  Type: {hurricane_melissa.event_type}")
        print(f"  Start Date: {hurricane_melissa.start_date}")
        print(f"  Status: {hurricane_melissa.status}")

if __name__ == "__main__":
    print("=" * 60)
    print("Adding Hurricane Melissa to DRIMS")
    print("=" * 60)
    add_hurricane_melissa()
    print("=" * 60)
