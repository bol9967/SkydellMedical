# How the Sales Team Hierarchy Access Module Works

## Overview
This module allows sales team leaders to view records (sales orders, CRM leads, etc.) created by their team members, while maintaining the existing security rules for regular salespersons.

## Architecture

### 1. **Team Leader Detection**
The module identifies team leaders by checking the `user_id` field on `crm.team` records:
- When a user is set as a team leader (`crm.team.user_id = user.id`)
- The system automatically tracks which users are members of that team

### 2. **Component Breakdown**

#### A. **res.users Model Extension** (`models/res_users.py`)
- **Purpose**: Computes and stores team member relationships
- **Fields**:
  - `team_member_user_ids`: Computed Many2many field (not stored) - contains all users who are members of teams where this user is the leader
  - `team_member_user_ids_list`: Stored Char field - comma-separated list of team member user IDs (for potential future use)

**How it works:**
```python
1. When accessed, searches for all teams where user_id = current user
2. Gets all active members from those teams
3. Stores their user IDs in the computed field
```

#### B. **Team Change Tracking** (`models/crm_team.py` & `models/crm_team_member.py`)
- **Purpose**: Automatically updates team member relationships when teams change
- **Triggers**:
  - When a team leader is assigned/changed
  - When team members are added/removed/activated/deactivated
  - When a team is created

**How it works:**
```python
1. Monitors write/create/unlink operations on crm.team and crm.team.member
2. When changes occur, triggers recomputation of team_member_user_ids
3. Ensures data stays synchronized
```

#### C. **Search Extension** (`models/sale_order.py` & `models/crm_lead.py`)
- **Purpose**: Extends search results to include team member records
- **Method**: Overrides `_search()` method (Odoo 18 standard pattern)

## Step-by-Step Flow

### Scenario: Team Leader Views Sales Orders

```
1. User Action
   └─> Team Leader (John) opens Sales Orders menu
       └─> Odoo calls sale.order._search()

2. Standard Search (with Record Rules)
   └─> super()._search() is called
       └─> Odoo applies standard record rules:
           - Personal rule: user_id = John.id OR user_id = False
           └─> Returns: John's own orders + unassigned orders

3. Team Leader Check
   └─> Module checks:
       ├─> Is user in 'sales_team.group_sale_salesman'? ✓
       ├─> Is user NOT in 'sales_team.group_sale_salesman_all_leads'? ✓
       └─> Is user a team leader? (searches crm.team where user_id = John.id)
           └─> Found: Team A (John is leader)

4. Get Team Members
   └─> Gets all active members from Team A
       └─> member_user_ids = [Alice.id, Bob.id, Charlie.id]

5. Extended Search
   └─> Searches for orders where:
       ├─> Same domain filters (customer, date, etc.)
       └─> user_id IN [Alice.id, Bob.id, Charlie.id]
       └─> Uses sudo() to bypass record rules for this specific search

6. Combine Results
   └─> Original results (John's orders) 
       UNION 
       Team member results (Alice's, Bob's, Charlie's orders)
   └─> Returns combined recordset

7. Apply Pagination/Ordering
   └─> Applies offset, limit, and order parameters
   └─> Returns final results to user
```

## Key Features

### ✅ What Works
1. **Automatic Detection**: No manual configuration needed - automatically detects team leaders
2. **Real-time Updates**: When team members change, access is updated immediately
3. **Security Maintained**: Only applies to salespersons, not managers (who already see all)
4. **Non-intrusive**: Doesn't break existing functionality - extends it

### ⚠️ Current Implementation Details
1. **Uses `sudo()`**: The module uses `sudo().search()` to bypass record rules when searching for team member records
   - **Why**: Standard record rules would filter out team member records
   - **Security Note**: This is a controlled bypass - only searches records where `user_id IN team_member_ids`
   - **Future Improvement**: Could be refined to use more granular permissions

2. **Domain Filtering**: Removes `user_id` conditions from the search domain before searching team member records
   - This ensures we get all team member records matching other filters (customer, date, etc.)

## Example Use Cases

### Use Case 1: Team Leader Reviews Team Performance
```
Scenario: Sarah (Team Leader) wants to see all sales orders from her team this month

1. Sarah opens Sales > Orders
2. Filters by: This Month
3. Module automatically includes:
   - Sarah's own orders
   - Orders from Team Members: Tom, Jerry, Mike
4. Sarah sees complete team performance
```

### Use Case 2: Team Member Added to Team
```
Scenario: New member "Alice" is added to Team B (led by Bob)

1. Admin adds Alice to Team B
2. crm_team_member.create() is triggered
3. Module detects change
4. Recomputes Bob's team_member_user_ids
5. Bob can now see Alice's records immediately
```

### Use Case 3: Regular Salesperson (Not Leader)
```
Scenario: Regular salesperson "Charlie" (not a team leader) views orders

1. Charlie opens Sales > Orders
2. Module checks: Is Charlie a team leader? NO
3. Standard search only (no extension)
4. Charlie sees only his own orders (standard Odoo behavior)
```

## Models Affected

Currently implemented:
- ✅ `sale.order` - Sales Orders
- ✅ `crm.lead` - CRM Leads/Opportunities

Can be extended to:
- `sale.order.line` - Sales Order Lines
- `sale.report` - Sales Reports
- `account.move` - Invoices
- `account.move.line` - Invoice Lines
- `crm.activity.report` - Activity Reports

## Technical Details

### Why Override `_search()`?
- **Odoo 18 Standard**: This is the recommended way to extend search behavior
- **Record Rules Limitation**: Can't use computed fields in XML record rules (they're evaluated during module installation)
- **Flexibility**: Python code can dynamically compute team members at runtime

### Why Not Use Record Rules?
- Record rules are evaluated during XML parsing
- Computed fields aren't available at that time
- Would require stored fields, which adds complexity
- `_search()` override is more flexible and maintainable

## Performance Considerations

1. **Caching**: Team member relationships are computed on-demand
2. **Query Optimization**: Uses efficient Odoo ORM methods (`mapped()`, `filtered()`)
3. **Minimal Overhead**: Only adds extra search when user is a team leader
4. **Future**: Could cache team member IDs in stored field for better performance

## Security Model

```
User Types:
├── Sales Manager (group_sale_salesman_all_leads)
│   └─> Sees ALL records (unchanged - Odoo default)
│
├── Team Leader (group_sale_salesman + is team leader)
│   └─> Sees own records + team member records
│
└── Regular Salesperson (group_sale_salesman, not leader)
    └─> Sees only own records (unchanged - Odoo default)
```

## Installation & Setup

1. **No Configuration Required**: Works automatically after installation
2. **Team Setup**: Just assign team leaders via `crm.team.user_id` field
3. **Team Members**: Add members via `crm.team.member` records
4. **Automatic**: All relationships are computed automatically

## Troubleshooting

### Team Leader Can't See Member Records
- Check: Is user actually set as team leader? (`crm.team.user_id`)
- Check: Are team members active? (`crm.team.member.active = True`)
- Check: Does user have `sales_team.group_sale_salesman` group?
- Check: Does user NOT have `sales_team.group_sale_salesman_all_leads` group?

### Performance Issues
- Large teams: Consider caching team member IDs
- Many searches: Monitor query performance
- Solution: Could add stored computed field for faster lookups
