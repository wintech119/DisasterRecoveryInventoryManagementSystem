"""
Database Migration: Add Concurrency Control Lock Columns to NeedsList

This script adds the locked_by_id and locked_at columns to the needs_list table
to support the concurrency control mechanism for fulfilment editing.

Run this script once to migrate your database:
    python add_lock_columns_migration.py
"""

from app import app, db
from sqlalchemy import text

def migrate():
    """Add lock columns to needs_list table"""
    with app.app_context():
        try:
            # Check if columns already exist
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('needs_list')]
            
            if 'locked_by_id' in columns and 'locked_at' in columns:
                print("✓ Lock columns already exist. No migration needed.")
                return
            
            print("Adding lock columns to needs_list table...")
            
            # Add locked_by_id column (FK to user.id)
            if 'locked_by_id' not in columns:
                db.session.execute(text("""
                    ALTER TABLE needs_list 
                    ADD COLUMN locked_by_id INTEGER REFERENCES "user"(id) ON DELETE SET NULL
                """))
                print("✓ Added locked_by_id column")
            
            # Add locked_at column
            if 'locked_at' not in columns:
                db.session.execute(text("""
                    ALTER TABLE needs_list 
                    ADD COLUMN locked_at TIMESTAMP
                """))
                print("✓ Added locked_at column")
            
            # Create index on locked_by_id for better query performance
            try:
                db.session.execute(text("""
                    CREATE INDEX idx_needs_list_locked_by_id 
                    ON needs_list(locked_by_id)
                """))
                print("✓ Created index on locked_by_id")
            except Exception as e:
                # Index might already exist
                print(f"  (Index creation skipped: {str(e)})")
            
            # Commit the changes
            db.session.commit()
            print("\n✅ Migration completed successfully!")
            print("   The needs_list table now has lock columns for concurrency control.")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Migration failed: {str(e)}")
            print("   Please check your database connection and try again.")
            raise

if __name__ == "__main__":
    print("=" * 70)
    print("Needs List Concurrency Control - Database Migration")
    print("=" * 70)
    print()
    migrate()
    print()
    print("=" * 70)
