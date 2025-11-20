#!/bin/bash

echo "🧹 Starting repository cleanup..."

# Create archive subdirectories
echo "📁 Creating archive folders..."
mkdir -p archive/tests
mkdir -p archive/sample_data
mkdir -p archive/debug
mkdir -p archive/old_scripts

# Move test files
echo "🧪 Moving test files..."
mv test_bulk_staffing.py archive/tests/ 2>/dev/null
mv test_clear_csv_sessions.py archive/tests/ 2>/dev/null
mv test_csv_with_skill_declarations.py archive/tests/ 2>/dev/null
mv test_edit_unit.py archive/tests/ 2>/dev/null
mv test_email_system.py archive/tests/ 2>/dev/null
mv test_multi_facilitator_display.py archive/tests/ 2>/dev/null
mv test_no_interest_constraint.py archive/tests/ 2>/dev/null
mv test_no_interest_integration.py archive/tests/ 2>/dev/null
mv test_role_hierarchy.py archive/tests/ 2>/dev/null
mv test_role_hierarchy_integration.py archive/tests/ 2>/dev/null
mv test_skill_declarations_csv.py archive/tests/ 2>/dev/null
mv test_swap_request_model.py archive/tests/ 2>/dev/null
mv test_swaps_api.py archive/tests/ 2>/dev/null
mv test_unavailability_integration.py archive/tests/ 2>/dev/null
mv simple_algorithm_test.py archive/tests/ 2>/dev/null
mv algorithm_tester.py archive/tests/ 2>/dev/null
mv algorithm_comparison.py archive/tests/ 2>/dev/null
mv run_algorithm_demo_fixed.py archive/tests/ 2>/dev/null

# Move sample data scripts
echo "📊 Moving sample data scripts..."
mv add_sample_facilitators.py archive/sample_data/ 2>/dev/null
mv add_sample_sessions.py archive/sample_data/ 2>/dev/null
mv add_test_facilitators.py archive/sample_data/ 2>/dev/null
mv add_multi_facilitator_test_data.py archive/sample_data/ 2>/dev/null
mv create_sample_facilitators.py archive/sample_data/ 2>/dev/null
mv create_unavailability_test_data.py archive/sample_data/ 2>/dev/null
mv sample_attendance_data.py archive/sample_data/ 2>/dev/null
mv init_sample_data.py archive/sample_data/ 2>/dev/null

# Move debug files
echo "🐛 Moving debug files..."
mv debug_aws.py archive/debug/ 2>/dev/null
mv check_modules.py archive/debug/ 2>/dev/null
mv session_check.py archive/debug/ 2>/dev/null

# Move old/unused scripts
echo "📦 Moving old scripts..."
mv swapSession.py archive/old_scripts/ 2>/dev/null
mv migrate_availability.py archive/old_scripts/ 2>/dev/null
mv update_facilitator_names.py archive/old_scripts/ 2>/dev/null
mv create_modules.py archive/old_scripts/ 2>/dev/null
mv create_facilitators_from_csv.py archive/old_scripts/ 2>/dev/null
mv inject_facilitator_skills.py archive/old_scripts/ 2>/dev/null

# Move algorithm extras
echo "🔧 Moving algorithm extras..."
mv algorithm_requirements.txt archive/ 2>/dev/null

# Move test directory if it exists
if [ -d "test" ]; then
    echo "📂 Moving test directory..."
    mv test archive/test_dir 2>/dev/null
fi

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "📋 Summary:"
echo "  - Test files → archive/tests/"
echo "  - Sample data → archive/sample_data/"
echo "  - Debug files → archive/debug/"
echo "  - Old scripts → archive/old_scripts/"
echo ""
echo "🔍 Check the changes with: git status"
echo "💾 Commit with: git add . && git commit -m 'Clean up repository: organize files into archive'"
