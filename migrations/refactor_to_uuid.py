#!/usr/bin/env python3
"""
Refactors app.py to use UUID instead of Integer for all ID columns.
"""

import re

def convert_models_to_uuid(filename='app.py'):
    with open(filename, 'r') as f:
        content = f.read()
    
    # Track all changes
    changes = []
    
    # Pattern 1: Simple ID columns (id = db.Column(db.Integer, primary_key=True))
    pattern1 = r'(\s+)id = db\.Column\(db\.Integer, primary_key=True\)'
    replacement1 = r'\1id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)'
    content, count1 = re.subn(pattern1, replacement1, content)
    if count1 > 0:
        changes.append(f"Converted {count1} simple ID columns to UUID")
    
    # Pattern 2: Foreign key references with db.Integer
    pattern2 = r'= db\.Column\(db\.Integer, db\.ForeignKey\('
    replacement2 = r'= db.Column(UUID(as_uuid=True), db.ForeignKey('
    content, count2 = re.subn(pattern2, replacement2, content)
    if count2 > 0:
        changes.append(f"Converted {count2} Integer foreign keys to UUID")
    
    # Pattern 3: Standalone Integer foreign keys (without db.ForeignKey on same line)
    # This handles cases like: parent_location_id = db.Column(db.Integer, db.ForeignKey(...))
    # Already handled by pattern2
    
    # Write back
    with open(filename, 'w') as f:
        f.write(content)
    
    return changes

if __name__ == '__main__':
    print("Refactoring app.py to use UUID...")
    changes = convert_models_to_uuid()
    
    for change in changes:
        print(f"✓ {change}")
    
    print("\nDone! Review the changes in app.py")
