#!/bin/bash

echo "📚 Starting documentation and scripts cleanup..."

# Create docs folder
echo "📁 Creating docs folder..."
mkdir -p docs

# Move markdown documentation files
echo "📄 Moving markdown documentation..."
mv ALGORITHM_RANDOMIZATION_UPDATE.md docs/ 2>/dev/null
mv BULK_STAFFING_IMPLEMENTATION.md docs/ 2>/dev/null
mv BULK_STAFFING_UPDATE_FIX.md docs/ 2>/dev/null
mv CSV_SKILL_DECLARATIONS_FEATURE.md docs/ 2>/dev/null
mv FACILITATOR_DASHBOARD_ACCESS.md docs/ 2>/dev/null
mv FEATURE_COMPLETE_SUMMARY.md docs/ 2>/dev/null
mv HIERARCHICAL_ROLE_SYSTEM.md docs/ 2>/dev/null
mv INJECT_SKILLS_README.md docs/ 2>/dev/null
mv MULTI_FACILITATOR_FIX_SUMMARY.md docs/ 2>/dev/null
mv MULTI_FACILITATOR_UI_IMPLEMENTATION.md docs/ 2>/dev/null
mv NO_INTEREST_CONSTRAINT_VERIFICATION.md docs/ 2>/dev/null
mv SCHEDULE_REPORT_README.md docs/ 2>/dev/null
mv UC_DASHBOARD_ACCESS.md docs/ 2>/dev/null
mv UNIT_CREATION_FLOW_VERIFICATION.md docs/ 2>/dev/null
mv VERIFICATION_SUMMARY.md docs/ 2>/dev/null
mv EMAIL_SETUP.md docs/ 2>/dev/null

# Create scripts folder
echo "🔧 Creating scripts folder..."
mkdir -p scripts

# Move utility scripts
echo "📜 Moving utility scripts..."
mv add_admin.py scripts/ 2>/dev/null
mv add_admin_cli.py scripts/ 2>/dev/null
mv add_admin_user.py scripts/ 2>/dev/null
mv add_facilitator.py scripts/ 2>/dev/null
mv add_today_sessions.py scripts/ 2>/dev/null
mv add_uc.py scripts/ 2>/dev/null
mv manage_roles.py scripts/ 2>/dev/null
mv reset_db.py scripts/ 2>/dev/null
mv cleanup_repo.sh scripts/ 2>/dev/null

# Delete outdated files
echo "🗑️  Removing outdated files..."
rm QUICKSTART_SKILLS.txt 2>/dev/null

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "📋 Summary:"
echo "  - Documentation → docs/"
echo "  - Utility scripts → scripts/"
echo "  - Outdated files deleted"
echo ""
echo "📂 Your root directory now has:"
echo "  - Core app files (.py files that run the app)"
echo "  - README.md & LICENSE"
echo "  - Folders: templates/, static/, migrations/, csv/, archive/, docs/, scripts/"
echo ""
echo "🔍 Check the changes with: git status"
echo "💾 Commit with: git add . && git commit -m 'Organize documentation and utility scripts'"
