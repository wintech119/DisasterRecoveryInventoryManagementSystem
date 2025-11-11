"""
Role Check Refactoring Script

This script refactors direct role checks to use the new has_role() and has_any_role() helper methods.

Patterns to replace:
1. user.role == ROLE_X → user.has_role(ROLE_X)
2. user.role != ROLE_X → not user.has_role(ROLE_X)
3. user.role in [ROLE_X, ROLE_Y] → user.has_any_role(ROLE_X, ROLE_Y)
4. user.role not in [ROLE_X, ROLE_Y] → not user.has_any_role(ROLE_X, ROLE_Y)
5. current_user.role == ROLE_X → current_user.has_role(ROLE_X)
6. current_user.role in [ROLE_X, ROLE_Y] → current_user.has_any_role(ROLE_X, ROLE_Y)
"""

import re
import sys


def extract_roles_from_list(roles_list_str):
    """Extract individual role constants from a list string like '[ROLE_X, ROLE_Y]'"""
    # Remove brackets and split by comma
    roles_str = roles_list_str.strip('[]')
    roles = [r.strip() for r in roles_str.split(',')]
    return roles


def refactor_role_checks(content):
    """Refactor role checks in the content"""
    
    changes_made = []
    
    # Pattern 1: user.role == 'ROLE_X' or user.role == ROLE_X
    # Replace with user.has_role(ROLE_X)
    pattern1 = r'(\w+)\.role\s*==\s*(["\']?ROLE_\w+["\']?)'
    def replace1(match):
        user_var = match.group(1)
        role = match.group(2).strip('\'"')
        changes_made.append(f"{match.group(0)} → {user_var}.has_role({role})")
        return f"{user_var}.has_role({role})"
    content = re.sub(pattern1, replace1, content)
    
    # Pattern 2: user.role != ROLE_X
    # Replace with not user.has_role(ROLE_X)
    pattern2 = r'(\w+)\.role\s*!=\s*(["\']?ROLE_\w+["\']?)'
    def replace2(match):
        user_var = match.group(1)
        role = match.group(2).strip('\'"')
        changes_made.append(f"{match.group(0)} → not {user_var}.has_role({role})")
        return f"not {user_var}.has_role({role})"
    content = re.sub(pattern2, replace2, content)
    
    # Pattern 3: user.role in [ROLE_X, ROLE_Y, ...]
    # Replace with user.has_any_role(ROLE_X, ROLE_Y, ...)
    pattern3 = r'(\w+)\.role\s+in\s+\[([^\]]+)\]'
    def replace3(match):
        user_var = match.group(1)
        roles_list = match.group(2)
        roles = extract_roles_from_list('[' + roles_list + ']')
        roles_str = ', '.join(roles)
        changes_made.append(f"{match.group(0)} → {user_var}.has_any_role({roles_str})")
        return f"{user_var}.has_any_role({roles_str})"
    content = re.sub(pattern3, replace3, content)
    
    # Pattern 4: user.role not in [ROLE_X, ROLE_Y, ...]
    # Replace with not user.has_any_role(ROLE_X, ROLE_Y, ...)
    pattern4 = r'(\w+)\.role\s+not\s+in\s+\[([^\]]+)\]'
    def replace4(match):
        user_var = match.group(1)
        roles_list = match.group(2)
        roles = extract_roles_from_list('[' + roles_list + ']')
        roles_str = ', '.join(roles)
        changes_made.append(f"{match.group(0)} → not {user_var}.has_any_role({roles_str})")
        return f"not {user_var}.has_any_role({roles_str})"
    content = re.sub(pattern4, replace4, content)
    
    return content, changes_made


def main():
    """Main refactoring function"""
    
    print("=" * 70)
    print("DRIMS Role Check Refactoring Script")
    print("=" * 70)
    print()
    
    # Read the file
    file_path = "app.py"
    print(f"Reading {file_path}...")
    with open(file_path, 'r') as f:
        original_content = f.read()
    
    # Perform refactoring
    print("Refactoring role checks...")
    refactored_content, changes = refactor_role_checks(original_content)
    
    # Show summary
    print(f"\nTotal changes made: {len(changes)}")
    print()
    
    # Show first 20 changes as preview
    if changes:
        print("Sample changes (first 20):")
        print("-" * 70)
        for i, change in enumerate(changes[:20], 1):
            print(f"{i}. {change}")
        
        if len(changes) > 20:
            print(f"... and {len(changes) - 20} more changes")
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
