#!/bin/bash
# Run diagnostics on server
# Usage: ./run_diagnostics.sh

echo "Running Odoo diagnostics for ox_sale_dropship_postpaid module..."
echo "Database: erp"
echo ""

# Run Odoo shell with diagnostics script
odoo-bin shell -d erp --no-http < diagnose_server_issue.py

echo ""
echo "Diagnostics complete. Check output above."

