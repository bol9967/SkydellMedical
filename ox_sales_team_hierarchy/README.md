# Sales Team Hierarchy Access

This module extends Odoo's access control to allow sales team leaders to view records (sales orders, CRM leads, invoices, etc.) belonging to their team members.

## Features

- **Team Leader Access**: Sales team leaders can see all records (sales orders, CRM leads, invoices) created by members of their teams
- **Personal Access Maintained**: Regular salespersons still only see their own records (unless they have additional permissions)
- **Automatic Detection**: The system automatically detects team leaders based on the `user_id` field on sales teams

## How It Works

1. When a user is set as a team leader (via the `user_id` field on `crm.team`), the system computes which users are members of their teams
2. Record rules are extended to allow access to records where:
   - The record's `user_id` matches the current user (personal records)
   - The record has no `user_id` assigned
   - The record's `user_id` is a member of a team where the current user is the leader

## Models Affected

- **Sale Orders** (`sale.order`)
- **Sale Order Lines** (`sale.order.line`)
- **Sale Order Reports** (`sale.report`)
- **CRM Leads** (`crm.lead`)
- **CRM Activity Reports** (`crm.activity.report`)
- **Account Invoices** (`account.move`)
- **Account Invoice Lines** (`account.move.line`)
- **Account Invoice Reports** (`account.invoice.report`)

## Installation

1. Copy this module to your Odoo addons directory
2. Update the apps list in Odoo
3. Install the module "Sales Team Hierarchy Access"

## Configuration

No configuration needed. The module works automatically once installed.

## Technical Details

- Adds a computed Many2many field `team_member_user_ids` on `res.users` that contains all users who are members of teams where the current user is the leader
- Extends existing record rules for salespersons to include team member records
- Uses Odoo's standard record rule mechanism, so it integrates seamlessly with existing security

## Requirements

- Odoo 18.0
- `sales_team` module
- `sale` module
- `crm` module
- `account` module
