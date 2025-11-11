"""
Display Name Refactoring Script

This script refactors full_name references to use the new display_name property.

Patterns to replace:
1. user.full_name → user.display_name
2. current_user.full_name → current_user.display_name
3. Some_user_object.full_name → Some_user_object.display_name

Special cases to preserve:
- Database column references in queries (e.g., User.full_name in filters)
- Form field names
- Template variable names that are already strings
"""

import re


def refactor_display_name(content):
    """Refactor full_name references to display_name"""
    
    changes_made = []
    
    # First, protect the display_name property definition by temporarily replacing it
    display_name_property_pattern = r'(@property\s+def display_name\(self\):.*?return self\.email)'
    display_name_match = re.search(display_name_property_pattern, content, re.DOTALL)
    protected_section = None
    
    if display_name_match:
        protected_section = display_name_match.group(0)
        content = content.replace(protected_section, '<<<PROTECTED_DISPLAY_NAME_PROPERTY>>>')
    
    # Pattern: object.full_name (but not in quotes or as a string literal)
    # This will match: user.full_name, current_user.full_name, needs_list.dispatched_by_user.full_name
    # But won't match: "full_name" or 'full_name' in strings
    
    # Find all patterns like: word_chars.full_name or word_chars.word_chars.full_name
    pattern = r'(\w+(?:\.\w+)*)\.full_name\b'
    
    def should_replace(match):
        """Check if this match should be replaced"""
        full_match = match.group(0)
        prefix = match.group(1)
        
        # Don't replace if it's a class reference like User.full_name in queries
        if prefix in ['User', 'user', 'Beneficiary', 'Donor']:
            # Could be a class reference in filter_by or similar
            # We'll check the context - if followed by parentheses or used in filter context
            return False
        
        # Replace all instance references
        return True
    
    def replace_match(match):
        if should_replace(match):
            prefix = match.group(1)
            new_ref = f"{prefix}.display_name"
            changes_made.append(f"{match.group(0)} → {new_ref}")
            return new_ref
        return match.group(0)
    
    content = re.sub(pattern, replace_match, content)
    
    # Restore the protected section
    if protected_section:
        content = content.replace('<<<PROTECTED_DISPLAY_NAME_PROPERTY>>>', protected_section)
    
    return content, changes_made


def main():
    """Main refactoring function"""
    
    print("=" * 70)
    print("DRIMS Display Name Refactoring Script")
    print("=" * 70)
    print()
    
    # Read the file
    file_path = "app.py"
    print(f"Reading {file_path}...")
    with open(file_path, 'r') as f:
        original_content = f.read()
    
    # Perform refactoring
    print("Refactoring full_name to display_name...")
    refactored_content, changes = refactor_display_name(original_content)
    
    # Show summary
    print(f"\nTotal changes made: {len(changes)}")
    print()
    
    # Show first 30 changes as preview
    if changes:
        print("Sample changes (first 30):")
        print("-" * 70)
        for i, change in enumerate(changes[:30], 1):
            print(f"{i}. {change}")
        
        if len(changes) > 30:
            print(f"... and {len(changes) - 30} more changes")
        print()
    
    # Ask for confirmation
    response = input("Apply these changes to app.py? (yes/no): ")
    
    if response.lower() in ['yes', 'y']:
        # Write the refactored content
        with open(file_path, 'w') as f:
            f.write(refactored_content)
        print(f"\n✅ Successfully refactored {file_path}")
        print(f"   Total replacements: {len(changes)}")
    else:
        print("\n❌ Refactoring cancelled. No changes were made.")
    
    print()
    print("=" * 70)


if __name__ == '__main__':
    main()
