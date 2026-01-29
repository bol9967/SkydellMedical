# Manual View Installation

The view for the Team Leader checkbox is temporarily disabled from automatic loading to avoid validation errors during module installation.

## After Module Installation

After the module is successfully installed, you can manually load the view by:

1. **Via Odoo UI (Developer Mode)**:
   - Go to Settings → Technical → User Interface → Views
   - Click "Create"
   - Or import the view XML file

2. **Via Odoo Shell**:
```python
from odoo import api, SUPERUSER_ID
from odoo.tools import convert_file
import os

env = api.Environment(cr, SUPERUSER_ID, {})
module_path = '/path/to/ox_sales_team_hierarchy'
view_file = os.path.join(module_path, 'views', 'res_users_views.xml')

with open(view_file, 'rb') as f:
    convert_file(env.cr, 'ox_sales_team_hierarchy', f, {}, 'init', False, 'data')
```

3. **Or simply uncomment the line in __manifest__.py**:
   - Edit `__manifest__.py`
   - Uncomment: `'views/res_users_views.xml',`
   - Upgrade the module

## Alternative: Use Group Directly

You can also assign users to the "Team Leader" group directly without using the checkbox:
- Settings → Users & Companies → Groups
- Find "Team Leader" group
- Add users to it

The checkbox is just a convenience feature - the group assignment works the same way.
