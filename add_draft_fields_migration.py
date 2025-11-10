"""
Database Migration: Add Draft Tracking Fields to NeedsList

This script adds the draft_saved_by and draft_saved_at columns to the needs_list table
to support draft-save functionality for fulfilment preparation.

Run this script once to migrate your database:
    python add_draft_fields_migration.py
"""

from app import app, db
from sqlalchemy import text

def migrate():
    """Add draft tracking fields to needs_list table"""
    with app.app_context():
        try:
            # Check if columns already exist
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('needs_list')]
            
            if 'draft_saved_by' in columns and 'draft_saved_at' in columns:
                print("✓ Draft tracking fields already exist. No migration needed.")
                return
            
            print("Adding draft tracking fields to needs_list table...")
            
            # Add draft_saved_by column
            if 'draft_saved_by' not in columns:
                db.session.execute(text("""
                    ALTER TABLE needs_list 
                    ADD COLUMN draft_saved_by VARCHAR(200)
                """))
                print("✓ Added draft_saved_by column")
            
            # Add draft_saved_at column
            if 'draft_saved_at' not in columns:
                db.session.execute(text("""
                    ALTER TABLE needs_list 
                    ADD COLUMN draft_saved_at TIMESTAMP
                """))
                print("✓ Added draft_saved_at column")
            
            # Commit the changes
            db.session.commit()
            print("\n✅ Migration completed successfully!")
            print("   The needs_list table now has draft tracking fields.")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Migration failed: {str(e)}")
            print("   Please check your database connection and try again.")
            raise

if __name__ == "__main__":
    print("=" * 70)
    print("Needs List Draft Tracking - Database Migration")
    print("=" * 70)
    print()
    migrate()
    print()
    print("=" * 70)
