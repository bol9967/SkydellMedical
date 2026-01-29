# Sales Team Hierarchy Module

## Overview

This module extends Odoo's native 3-tier access control system to add a **4th tier: Team Leader Access**.

## Access Control Hierarchy

```
1. Administrator (group_sale_manager)
   └── Bypasses all record rules → Sees everything

2. All Documents (group_sale_salesman_all_leads)
   └── Rule: [(1,'=',1)] → Sees everything

3. Team Leader Access (group_team_leader) ← NEW 4TH TIER
   └── Rule: Own records + Team member records
   └── If no team members → Falls back to "Own Documents Only"

4. Own Documents Only (group_sale_salesman)
   └── Rule: ['|',('user_id','=',user.id),('user_id','=',False)]
```

## How It Works

### Team Leader Access (4th Tier)

**When user has Team Leader group but NOT "All Documents":**

1. **With Team Members:**
   - Sees own records (where `user_id = current user`)
   - Sees team member records (where `user_id` is in team member list)
   - Does NOT see unassigned records (`user_id = False`) unless they are own records

2. **No Team Members:**
   - Falls back to "Own Documents Only" behavior
   - Sees only own records + unassigned records

3. **Has "All Documents":**
   - Team Leader logic is skipped
   - Sees everything (native "All Documents" rule applies)

## Implementation Details

### Hybrid Approach (Native-Style)

- **XML Record Rules:** Define the structure and make rules visible in UI
- **Python Overrides:** Extend domains dynamically based on team membership

### Key Files

- `security/security_groups.xml` - Defines Team Leader group
- `security/ir_rules.xml` - Defines base record rules (extended in Python)
- `models/sale_order.py` - Extends `_search()` and `read()` for sales orders
- `models/crm_lead.py` - Extends `_search()` and `read()` for CRM leads
- `models/res_users.py` - Computed field for team member IDs

### Why Python Overrides?

Team membership changes dynamically when:
- Teams are created/modified
- Team members are added/removed
- Users are assigned/unassigned

XML record rules can't compute this dynamically, so Python overrides extend the base domain.

## Installation

1. Copy module to `addons` directory
2. Update apps list
3. Install "Sales Team Hierarchy" module
4. Assign "User: Team Leader Access" group to users
5. Set users as team leaders in Sales > Configuration > Sales Teams

## Usage

1. Go to Sales > Configuration > Sales Teams
2. Create or edit a team
3. Set the "Team Leader" field to the user who should see team member records
4. Add team members in the "Team Members" tab
5. The team leader will now see:
   - Their own sales orders and CRM leads
   - Sales orders and CRM leads of all active team members

## Technical Notes

- Uses SQL queries to avoid recursion when reading `user_id` field
- Maintains compatibility with Odoo 18's `Query` object handling
- Respects native record rules (multi-company, etc.)
- Falls back gracefully when no team members exist
