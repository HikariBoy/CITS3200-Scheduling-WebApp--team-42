#!/usr/bin/env python3
"""
Pre-Merge Safety Checker
Analyzes your branch for potentially breaking database changes
Run this before merging to main!

Usage: python check_safe_to_merge.py
"""

import os
import sys
import re
import subprocess

def run_command(cmd):
    """Run shell command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {e}"

def get_current_branch():
    """Get current git branch name"""
    return run_command("git branch --show-current")

def get_changed_files():
    """Get list of files changed compared to main"""
    # Get files changed between current branch and main
    output = run_command("git diff --name-only main...HEAD")
    return output.split('\n') if output else []

def check_models_changes():
    """Check if models.py has changes and analyze them"""
    diff = run_command("git diff main...HEAD models.py")
    
    if not diff:
        return None, []
    
    warnings = []
    
    # Check for removed columns (lines starting with -)
    removed_lines = [line for line in diff.split('\n') if line.startswith('-') and 'db.Column' in line]
    if removed_lines:
        warnings.append({
            'severity': 'HIGH',
            'type': 'REMOVED_COLUMN',
            'message': 'Detected removed database columns - this will break production!',
            'details': removed_lines[:3]  # Show first 3
        })
    
    # Check for nullable=False on new columns
    added_lines = [line for line in diff.split('\n') if line.startswith('+') and 'db.Column' in line]
    for line in added_lines:
        if 'nullable=False' in line and 'default=' not in line:
            warnings.append({
                'severity': 'MEDIUM',
                'type': 'NON_NULLABLE_COLUMN',
                'message': 'New column without default value and nullable=False',
                'details': [line.strip()]
            })
    
    # Check for removed tables (class definitions)
    removed_classes = [line for line in diff.split('\n') if line.startswith('-class ') and '(db.Model)' in line]
    if removed_classes:
        warnings.append({
            'severity': 'HIGH',
            'type': 'REMOVED_TABLE',
            'message': 'Detected removed database tables - this will break production!',
            'details': removed_classes
        })
    
    return diff, warnings

def check_migration_files():
    """Check if migration files exist for model changes"""
    # Check if migrations/versions has new files
    new_migrations = run_command("git diff --name-only main...HEAD migrations/versions/")
    return new_migrations.split('\n') if new_migrations else []

def print_report(branch, changed_files, models_diff, warnings, migrations):
    """Print safety report"""
    print("=" * 70)
    print("🔍 PRE-MERGE SAFETY CHECK")
    print("=" * 70)
    print(f"\n📌 Current Branch: {branch}")
    print(f"📌 Comparing to: main")
    print(f"\n📝 Files Changed: {len(changed_files)}")
    
    if 'models.py' in changed_files:
        print("\n⚠️  DATABASE SCHEMA CHANGES DETECTED")
        print("-" * 70)
        
        if warnings:
            print(f"\n🚨 FOUND {len(warnings)} POTENTIAL ISSUE(S):\n")
            for i, warning in enumerate(warnings, 1):
                severity_emoji = "🔴" if warning['severity'] == 'HIGH' else "🟡"
                print(f"{severity_emoji} Issue #{i}: {warning['message']}")
                print(f"   Type: {warning['type']}")
                print(f"   Severity: {warning['severity']}")
                if warning['details']:
                    print(f"   Details:")
                    for detail in warning['details']:
                        print(f"      {detail}")
                print()
        else:
            print("\n✅ No obvious breaking changes detected in models.py")
        
        # Check for migrations
        print("\n📦 Migration Files:")
        if migrations:
            print(f"   ✅ Found {len(migrations)} new migration(s):")
            for mig in migrations:
                print(f"      - {mig}")
        else:
            print("   ⚠️  No migration files found!")
            print("   💡 Run: flask db migrate -m 'description'")
    else:
        print("\n✅ No database schema changes detected")
    
    # Overall recommendation
    print("\n" + "=" * 70)
    print("📋 RECOMMENDATION:")
    print("=" * 70)
    
    if not warnings and (migrations or 'models.py' not in changed_files):
        print("✅ SAFE TO MERGE")
        print("\nYour changes appear safe for production!")
        if 'models.py' in changed_files:
            print("\n⚠️  Before deploying to AWS:")
            print("   1. Backup production database")
            print("   2. Run: flask db upgrade")
            print("   3. Test the application")
    elif not warnings and 'models.py' in changed_files and not migrations:
        print("⚠️  NEEDS MIGRATION")
        print("\nYou have model changes but no migration files.")
        print("\n📝 Next steps:")
        print("   1. Run: flask db migrate -m 'description of changes'")
        print("   2. Review the migration file")
        print("   3. Test migration locally")
        print("   4. Run this check again")
    else:
        print("🚨 POTENTIALLY UNSAFE - REVIEW REQUIRED")
        print("\nYour changes may break production!")
        print("\n📝 Next steps:")
        print("   1. Review the warnings above")
        print("   2. Consider 2-phase deployment (see DATABASE_SAFETY_GUIDE.md)")
        print("   3. Test on production database copy")
        print("   4. Have a rollback plan ready")
    
    print("\n" + "=" * 70)
    print("📚 For more info: Read DATABASE_SAFETY_GUIDE.md")
    print("=" * 70)

def main():
    """Main function"""
    print("\n🔍 Analyzing your changes...\n")
    
    # Get current branch
    branch = get_current_branch()
    if branch == 'main':
        print("⚠️  You're already on main branch!")
        print("Switch to your feature branch first.")
        return
    
    # Get changed files
    changed_files = get_changed_files()
    
    # Check models.py
    models_diff, warnings = check_models_changes()
    
    # Check migrations
    migrations = check_migration_files()
    
    # Print report
    print_report(branch, changed_files, models_diff, warnings, migrations)

if __name__ == "__main__":
    main()
