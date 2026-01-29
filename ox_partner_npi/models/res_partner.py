# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import ValidationError
import requests
import json
import logging

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    npi_number = fields.Char(string="NPI #", copy=False)
    
    def _compute_has_internal_user(self):
        """Compute if partner has any internal users (share=False)"""
        for partner in self:
            partner.has_internal_user = bool(partner.user_ids.filtered(lambda u: not u.share))
    
    has_internal_user = fields.Boolean(string="Has Internal User", compute='_compute_has_internal_user', store=False)
    npi_enumeration_type = fields.Char(string="NPI Type", readonly=True, help="Type 1: Individual, Type 2: Organization")
    
    # Basic Provider Information
    npi_provider_name = fields.Char(string="Provider Name", readonly=True)
    npi_first_name = fields.Char(string="First Name", readonly=True)
    npi_middle_name = fields.Char(string="Middle Name", readonly=True)
    npi_last_name = fields.Char(string="Last Name", readonly=True)
    npi_name_prefix = fields.Char(string="Name Prefix", readonly=True, help="e.g., Dr., Mr., Mrs.")
    npi_name_suffix = fields.Char(string="Name Suffix", readonly=True, help="e.g., Jr., III, MD")
    npi_credential = fields.Char(string="Credential", readonly=True, help="e.g., MD, DO, RN")
    npi_gender = fields.Char(string="NPI Gender", readonly=True, help="Gender from NPI Registry")
    npi_sole_proprietor = fields.Char(string="Sole Proprietor", readonly=True)
    
    # Organization Information
    npi_organization_name = fields.Char(string="Organization Name", readonly=True)
    npi_organizational_subpart = fields.Char(string="Organizational Subpart", readonly=True, help="YES or NO")
    npi_authorized_official_first_name = fields.Char(string="Auth Official First Name", readonly=True)
    npi_authorized_official_last_name = fields.Char(string="Auth Official Last Name", readonly=True)
    npi_authorized_official_middle_name = fields.Char(string="Auth Official Middle Name", readonly=True)
    npi_authorized_official_title = fields.Char(string="Auth Official Title", readonly=True)
    npi_authorized_official_telephone = fields.Char(string="Auth Official Telephone", readonly=True)
    
    # Dates
    npi_enumeration_date = fields.Date(string="Enumeration Date", readonly=True)
    npi_certification_date = fields.Date(string="Certification Date", readonly=True)
    npi_created_date = fields.Date(string="Created Date", readonly=True, help="Date from created_epoch")
    npi_created_epoch = fields.Char(string="Created Epoch", readonly=True, help="Epoch timestamp in milliseconds")
    npi_last_updated = fields.Datetime(string="NPI Data Last Updated", readonly=True)
    npi_last_updated_date = fields.Date(string="NPI Last Updated Date", readonly=True, help="Date from last_updated field in API")
    npi_last_updated_epoch = fields.Char(string="Last Updated Epoch", readonly=True, help="Epoch timestamp in milliseconds")
    npi_deactivation_date = fields.Date(string="Deactivation Date", readonly=True)
    npi_reactivation_date = fields.Date(string="Reactivation Date", readonly=True)
    npi_replacement_npi = fields.Char(string="Replacement NPI", readonly=True)
    npi_status = fields.Char(string="NPI Status", readonly=True, help="A=Active, I=Inactive, D=Deactivated, T=Terminated")
    
    # Addresses
    npi_primary_practice_location = fields.Text(string="Primary Practice Location", readonly=True)
    npi_mailing_address = fields.Text(string="Mailing Address", readonly=True)
    npi_location_telephone = fields.Char(string="Location Telephone", readonly=True)
    npi_location_fax = fields.Char(string="Location Fax", readonly=True)
    npi_mailing_telephone = fields.Char(string="Mailing Telephone", readonly=True)
    npi_mailing_fax = fields.Char(string="Mailing Fax", readonly=True)
    
    # Taxonomies
    npi_taxonomies = fields.Text(string="Taxonomies", readonly=True)
    npi_primary_taxonomy = fields.Char(string="Primary Taxonomy", readonly=True)
    npi_primary_taxonomy_code = fields.Char(string="Primary Taxonomy Code", readonly=True)
    npi_primary_taxonomy_license = fields.Char(string="Primary Taxonomy License", readonly=True)
    
    # Other Data
    npi_identifiers = fields.Text(string="Other Identifiers", readonly=True)
    npi_endpoints = fields.Text(string="Endpoints", readonly=True)
    npi_other_names = fields.Text(string="Other Names", readonly=True)
    npi_practice_locations = fields.Text(string="Practice Locations", readonly=True, help="Additional practice locations beyond primary")
    npi_lookup_data = fields.Text(string="NPI Lookup Data (JSON)", readonly=True)

    # Note: We use Python constraint instead of SQL constraint to handle:
    # 1. Multiple NULL/empty values (NPI is optional)
    # 2. Better error messages
    # 3. Avoids database constraint errors on existing duplicate data
    # SQL UNIQUE constraint would fail if there are existing duplicates or empty strings

    @api.constrains('npi_number')
    def _check_npi_unique(self):
        """Check that NPI number is unique across all partners"""
        for partner in self:
            if partner.npi_number:
                # Check for duplicates excluding current record
                duplicate = self.env['res.partner'].search([
                    ('npi_number', '=', partner.npi_number),
                    ('id', '!=', partner.id)
                ], limit=1)
                if duplicate:
                    raise ValidationError(f"NPI Number {partner.npi_number} is already assigned to partner: {duplicate.name}")

    def action_lookup_npi(self):
        """Lookup NPI data from CMS API and update partner"""
        self.ensure_one()
        if not self.npi_number:
            raise ValidationError("Please enter an NPI number first.")
        
        # Validate NPI format (10 digits)
        npi = self.npi_number.strip()
        if not npi.isdigit() or len(npi) != 10:
            raise ValidationError("NPI number must be exactly 10 digits.")
        
        # Call NPI API
        try:
            api_url = f"https://npiregistry.cms.hhs.gov/api/?version=2.1&number={npi}"
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('result_count', 0) == 0:
                raise ValidationError(f"No NPI data found for number: {npi}")
            
            # Extract first result
            result = data.get('results', [{}])[0]
            
            # Extract all NPI data using helper method
            npi_data = self._extract_npi_data(result)
            
            self.write(npi_data)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': f'NPI data retrieved successfully for {npi}',
                    'type': 'success',
                    'sticky': False,
                }
            }
            
        except requests.exceptions.RequestException as e:
            _logger.error(f"Error fetching NPI data: {e}")
            raise ValidationError(f"Error fetching NPI data: {str(e)}")
        except Exception as e:
            _logger.error(f"Error processing NPI data: {e}")
            raise ValidationError(f"Error processing NPI data: {str(e)}")

    def _extract_npi_data(self, result):
        """Extract all NPI data from API result into dictionary for partner update"""
        from datetime import datetime
        
        npi_data = {
            'npi_enumeration_type': result.get('enumeration_type'),
            'npi_last_updated': fields.Datetime.now(),  # When we last updated the data in Odoo
            'npi_lookup_data': json.dumps(result, indent=2),
        }
        
        # Extract dates from basic section
        basic = result.get('basic', {})
        for date_field, npi_field in [
            ('enumeration_date', 'npi_enumeration_date'),
            ('certification_date', 'npi_certification_date'),
            ('last_updated', 'npi_last_updated_date'),
            ('deactivation_date', 'npi_deactivation_date'),
            ('reactivation_date', 'npi_reactivation_date'),
        ]:
            date_value = basic.get(date_field) if date_field in ['enumeration_date', 'certification_date', 'last_updated'] else result.get(date_field)
            if date_value:
                try:
                    date_val = datetime.strptime(date_value, '%Y-%m-%d').date()
                    npi_data[npi_field] = date_val
                except:
                    pass
        
        # Extract created_epoch (convert to date and store epoch)
        if result.get('created_epoch'):
            npi_data['npi_created_epoch'] = str(result.get('created_epoch'))  # Store epoch as string
            try:
                # Epoch is in milliseconds, convert to seconds then to date
                epoch_ms = int(result.get('created_epoch'))
                epoch_seconds = epoch_ms / 1000
                created_date = datetime.fromtimestamp(epoch_seconds).date()
                npi_data['npi_created_date'] = created_date
            except (ValueError, TypeError, OSError) as e:
                _logger.warning("Error converting created_epoch to date: %s", str(e))
        
        # Extract last_updated_epoch
        if result.get('last_updated_epoch'):
            npi_data['npi_last_updated_epoch'] = str(result.get('last_updated_epoch'))
        
        # Extract status from basic section
        if basic.get('status'):
            npi_data['npi_status'] = basic.get('status')
        
        if result.get('replacement_npi'):
            npi_data['npi_replacement_npi'] = result.get('replacement_npi')
        
        # Extract basic provider information (basic already defined above)
        if result.get('enumeration_type') == 'NPI-1':  # Individual
            # API uses 'sex' field, not 'gender'
            sex = basic.get('sex', '')
            # Map sex to gender: F = Female, M = Male
            gender_map = {'F': 'Female', 'M': 'Male'}
            npi_gender = gender_map.get(sex, sex) if sex else ''
            
            npi_data.update({
                'npi_first_name': basic.get('first_name', ''),
                'npi_middle_name': basic.get('middle_name', ''),
                'npi_last_name': basic.get('last_name', ''),
                'npi_name_prefix': basic.get('name_prefix', ''),
                'npi_name_suffix': basic.get('name_suffix', ''),
                'npi_credential': basic.get('credential', ''),
                'npi_gender': npi_gender,  # Use mapped gender from sex field
                'npi_sole_proprietor': basic.get('sole_proprietor', ''),
                'npi_provider_name': f"{basic.get('first_name', '')} {basic.get('last_name', '')}".strip(),
            })
        else:  # Organization (NPI-2)
            npi_data.update({
                'npi_organization_name': basic.get('organization_name', ''),
                'npi_provider_name': basic.get('organization_name', ''),
                'npi_organizational_subpart': basic.get('organizational_subpart', ''),
            })
            # Extract authorized official - fields are directly in basic section, not nested
            npi_data.update({
                'npi_authorized_official_first_name': basic.get('authorized_official_first_name', ''),
                'npi_authorized_official_last_name': basic.get('authorized_official_last_name', ''),
                'npi_authorized_official_middle_name': basic.get('authorized_official_middle_name', ''),
                'npi_authorized_official_title': basic.get('authorized_official_title_or_position', ''),
                'npi_authorized_official_telephone': basic.get('authorized_official_telephone_number', ''),
            })
        
        # Extract addresses with telephone and fax
        addresses = result.get('addresses', [])
        for addr in addresses:
            if addr.get('address_purpose') == 'LOCATION':
                npi_data['npi_primary_practice_location'] = self._format_address(addr)
                npi_data['npi_location_telephone'] = addr.get('telephone_number', '')
                npi_data['npi_location_fax'] = addr.get('fax_number', '')
            elif addr.get('address_purpose') == 'MAILING':
                npi_data['npi_mailing_address'] = self._format_address(addr)
                npi_data['npi_mailing_telephone'] = addr.get('telephone_number', '')
                npi_data['npi_mailing_fax'] = addr.get('fax_number', '')
        
        # Extract taxonomies with detailed information (including taxonomy_group)
        taxonomies = result.get('taxonomies', [])
        if taxonomies:
            tax_list = []
            for tax in taxonomies:
                desc = tax.get('desc', '')
                code = tax.get('code', '')
                license_num = tax.get('license', '')
                state = tax.get('state', '')
                primary = tax.get('primary', False)
                taxonomy_group = tax.get('taxonomy_group', '')
                
                tax_info = f"{desc}"
                if code:
                    tax_info += f" (Code: {code})"
                if license_num:
                    tax_info += f" - License: {license_num}"
                if state:
                    tax_info += f" - State: {state}"
                if taxonomy_group:
                    tax_info += f" - Group: {taxonomy_group}"
                if primary:
                    tax_info += " (Primary)"
                    npi_data['npi_primary_taxonomy'] = desc
                    npi_data['npi_primary_taxonomy_code'] = code
                    npi_data['npi_primary_taxonomy_license'] = license_num
                
                tax_list.append(tax_info)
            npi_data['npi_taxonomies'] = '\n'.join(tax_list) if tax_list else ''
        
        # Extract identifiers with improved formatting
        identifiers = result.get('identifiers', [])
        if identifiers:
            id_list = []
            for identifier in identifiers:
                id_value = identifier.get('identifier', '')
                id_desc = identifier.get('desc', '')
                id_code = identifier.get('code', '')
                id_state = identifier.get('state', '')
                id_issuer = identifier.get('issuer', '')
                
                # Format: "MEDICAID (Code: 05) - Identifier: 248903 - State: SC"
                id_info = id_desc if id_desc else f"Code: {id_code}"
                if id_code and id_desc:
                    id_info = f"{id_desc} (Code: {id_code})"
                if id_value:
                    id_info += f" - Identifier: {id_value}"
                if id_state:
                    id_info += f" - State: {id_state}"
                if id_issuer:
                    id_info += f" - Issuer: {id_issuer}"
                
                id_list.append(id_info)
            npi_data['npi_identifiers'] = '\n'.join(id_list) if id_list else ''
        
        # Extract endpoints
        endpoints = result.get('endpoints', [])
        if endpoints:
            endpoint_list = []
            for endpoint in endpoints:
                endpoint_type = endpoint.get('endpoint_type', '')
                endpoint_addr = endpoint.get('endpoint', '')
                endpoint_desc = endpoint.get('endpoint_description', '')
                endpoint_use = endpoint.get('use', '')
                
                endpoint_info = f"{endpoint_type}"
                if endpoint_desc:
                    endpoint_info += f": {endpoint_desc}"
                if endpoint_addr:
                    endpoint_info += f" - {endpoint_addr}"
                if endpoint_use:
                    endpoint_info += f" ({endpoint_use})"
                
                endpoint_list.append(endpoint_info)
            npi_data['npi_endpoints'] = '\n'.join(endpoint_list)
        
        # Extract other names
        other_names = result.get('other_names', [])
        if other_names:
            name_list = []
            for other_name in other_names:
                name_type = other_name.get('desc', '')
                first_name = other_name.get('first_name', '')
                last_name = other_name.get('last_name', '')
                middle_name = other_name.get('middle_name', '')
                
                name_info = f"{name_type}: {first_name} {middle_name} {last_name}".strip()
                name_list.append(name_info)
            npi_data['npi_other_names'] = '\n'.join(name_list) if name_list else ''
        
        # Extract practiceLocations (additional practice locations beyond primary)
        practice_locations = result.get('practiceLocations', [])
        if practice_locations:
            practice_list = []
            for practice in practice_locations:
                if isinstance(practice, dict):
                    practice_addr = self._format_address(practice)
                    practice_list.append(practice_addr)
                else:
                    practice_list.append(str(practice))
            npi_data['npi_practice_locations'] = '\n'.join(practice_list) if practice_list else ''
        
        return npi_data

    def _format_address(self, addr):
        """Format address dictionary into readable string"""
        parts = []
        if addr.get('address_1'):
            parts.append(addr['address_1'])
        if addr.get('address_2'):
            parts.append(addr['address_2'])
        city = addr.get('city', '')
        state = addr.get('state', '')
        postal = addr.get('postal_code', '')
        if city or state or postal:
            city_state = ', '.join(filter(None, [city, state, postal]))
            parts.append(city_state)
        # API returns 3-character ISO country codes (e.g., 'USA', 'CAN', 'GBR')
        # Only append country if it's not USA
        country_code = addr.get('country_code', '')
        if country_code and country_code not in ('US', 'USA'):
            parts.append(addr.get('country_name', country_code))
        return '\n'.join(parts)

    def validate_npi(self, npi_number, signup_name=None, partner_id=None):
        """Validate NPI number via API. Returns (is_valid, message, data, error_field)
        
        Args:
            npi_number: The NPI number to validate
            signup_name: Optional name from signup form to validate against NPI data
            partner_id: Optional partner ID to exclude from uniqueness check (for invitations where partner already has NPI)
        
        Returns:
            tuple: (is_valid: bool, message: str, data: dict, error_field: str or None)
        """
        _logger.info("Validating NPI number: %s, Partner ID: %s", npi_number, partner_id)
        
        if not npi_number:
            _logger.warning("NPI validation failed: NPI number is required")
            return False, "NPI number is required.", None, 'npi_number'
        
        npi = npi_number.strip()
        if not npi.isdigit() or len(npi) != 10:
            _logger.warning("NPI validation failed: Invalid format - %s (length: %s)", npi, len(npi))
            return False, "NPI number must be exactly 10 digits.", None, 'npi_number'
        
        # Check if NPI already exists on another partner (exclude current partner if provided)
        domain = [('npi_number', '=', npi)]
        if partner_id:
            domain.append(('id', '!=', partner_id))
        existing = self.env['res.partner'].search(domain, limit=1)
        if existing:
            _logger.warning("NPI validation failed: Already exists - Partner: %s (ID: %s)", existing.name, existing.id)
            return False, f"NPI number {npi} is already registered to another partner.", None, 'npi_number'
        
        # Call NPI API
        try:
            api_url = f"https://npiregistry.cms.hhs.gov/api/?version=2.1&number={npi}"
            _logger.info("Calling NPI API: %s", api_url)
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            _logger.info("NPI API response - Result count: %s", data.get('result_count', 0))
            
            if data.get('result_count', 0) == 0:
                _logger.warning("NPI validation failed: No results found for NPI: %s", npi)
                return False, f"No valid NPI found for number: {npi}. Please provide a valid NPI number.", None, 'npi_number'
            
            result = data.get('results', [{}])[0]
            basic = result.get('basic', {})
            enumeration_type = result.get('enumeration_type', '')
            
            _logger.info("NPI data - Enumeration type: %s, Basic keys: %s", 
                        enumeration_type, list(basic.keys()))
            
            # Check status - must be "A" (Active)
            status = basic.get('status', '').upper()
            if status != 'A':
                _logger.warning("NPI validation failed: Status is not Active - Status: %s, NPI: %s", status, npi)
                status_desc = {
                    'I': 'Inactive',
                    'D': 'Deactivated',
                    'T': 'Terminated'
                }.get(status, f'Unknown ({status})')
                return False, f"NPI number {npi} is not active. Current status: {status_desc}. Only active NPI numbers can be used for registration.", None, 'npi_number'
            
            # Validate name match if signup_name is provided
            if signup_name:
                if enumeration_type == 'NPI-1':  # Individual
                    # Extract name from NPI data for individuals
                    first_name = basic.get('first_name', '').strip().upper()
                    middle_name = basic.get('middle_name', '').strip().upper()
                    last_name = basic.get('last_name', '').strip().upper()
                    
                    if not first_name or not last_name:
                        _logger.warning("NPI validation failed: Missing name data - First: '%s', Last: '%s'", 
                                      first_name, last_name)
                        return False, f"NPI number {npi} does not have complete name information in the registry. Please contact support.", None, 'npi_number'
                    
                    # Build NPI full name (without middle name for comparison)
                    npi_full_name = f"{first_name} {last_name}".strip()
                    npi_full_name_with_middle = f"{first_name} {middle_name} {last_name}".strip() if middle_name else npi_full_name
                    
                    # Normalize signup name for comparison (remove extra spaces, convert to uppercase)
                    signup_name_normalized = ' '.join(signup_name.strip().upper().split())
                    
                    _logger.info("Individual name validation - Signup name (original): '%s', Normalized: '%s'", 
                                signup_name, signup_name_normalized)
                    
                    # Build comparison names (also normalize)
                    # first_name, last_name are already uppercase from extraction
                    npi_full_name_normalized = ' '.join(npi_full_name.split())
                    npi_full_name_with_middle_normalized = ' '.join(npi_full_name_with_middle.split()) if middle_name else npi_full_name_normalized
                    
                    _logger.info("NPI name - Full: '%s', With middle: '%s'", 
                                npi_full_name_normalized, npi_full_name_with_middle_normalized if middle_name else 'N/A')
                    
                    # Check if signup name matches NPI name (with or without middle name)
                    # Allow flexible matching: "FIRST LAST", "FIRST MIDDLE LAST", or "FIRST ... LAST"
                    name_parts_signup = signup_name_normalized.split()
                    name_parts_npi = npi_full_name_normalized.split()
                    
                    # Check exact matches first
                    exact_match = (
                        signup_name_normalized == npi_full_name_normalized or
                        signup_name_normalized == npi_full_name_with_middle_normalized
                    )
                    
                    # Check if first and last name match (allowing middle name variations)
                    first_last_match = (
                        len(name_parts_signup) >= 2 and
                        len(name_parts_npi) >= 2 and
                        name_parts_signup[0] == name_parts_npi[0] and  # First name matches
                        name_parts_signup[-1] == name_parts_npi[-1]    # Last name matches
                    )
                    
                    name_matches = exact_match or first_last_match
                    
                    _logger.info("Individual name match result - Exact: %s, First+Last: %s, Final: %s", 
                                exact_match, first_last_match, name_matches)
                    
                    if not name_matches:
                        _logger.warning("NPI validation failed: Name mismatch - Signup: '%s', NPI: '%s %s'", 
                                      signup_name, first_name, last_name)
                        return False, f"The name '{signup_name}' does not match the NPI registry name '{first_name} {last_name}'. Please enter the exact name as registered with NPI.", None, 'name'
                    
                    _logger.info("Name validation successful - Signup: %s, NPI: %s %s", 
                               signup_name, first_name, last_name)
                    
                elif enumeration_type == 'NPI-2':  # Organization
                    # For organizations, validate against organization_name OR authorized official name
                    organization_name = basic.get('organization_name', '').strip().upper()
                    auth_official_first = basic.get('authorized_official_first_name', '').strip().upper()
                    auth_official_last = basic.get('authorized_official_last_name', '').strip().upper()
                    auth_official_name = f"{auth_official_first} {auth_official_last}".strip() if (auth_official_first and auth_official_last) else ''
                    
                    if not organization_name and not auth_official_name:
                        _logger.warning("NPI validation failed: Missing organization and authorized official name")
                        return False, f"NPI number {npi} is registered as an organization but does not have name information. Please contact support.", None, 'npi_number'
                    
                    # Normalize signup name for comparison (case-insensitive)
                    signup_name_normalized = ' '.join(signup_name.strip().upper().split())
                    
                    _logger.info("Organization name validation - Signup name (original): '%s', Normalized: '%s'", 
                                signup_name, signup_name_normalized)
                    
                    # Check against organization name
                    org_name_matches = False
                    if organization_name:
                        # organization_name is already uppercase from extraction, just normalize spacing
                        organization_name_normalized = ' '.join(organization_name.split())
                        _logger.info("Organization name - Original: '%s', Normalized: '%s'", 
                                    organization_name, organization_name_normalized)
                        
                        org_name_matches = (
                            signup_name_normalized == organization_name_normalized or
                            organization_name_normalized.startswith(signup_name_normalized) or
                            signup_name_normalized.startswith(organization_name_normalized)
                        )
                        _logger.info("Organization name match result: %s", org_name_matches)
                    
                    # Check against authorized official name (first + last)
                    auth_official_matches = False
                    if auth_official_name:
                        # auth_official_name is already uppercase from extraction, just normalize spacing
                        auth_official_name_normalized = ' '.join(auth_official_name.split())
                        # Allow flexible matching for authorized official (with or without middle name)
                        auth_official_parts = auth_official_name_normalized.split()
                        signup_parts = signup_name_normalized.split()
                        
                        _logger.info("Authorized official name matching - Signup normalized: '%s', NPI normalized: '%s'", 
                                    signup_name_normalized, auth_official_name_normalized)
                        _logger.info("Name parts - Signup: %s, NPI: %s", signup_parts, auth_official_parts)
                        
                        # Exact match check
                        exact_match = signup_name_normalized == auth_official_name_normalized
                        
                        # First and last name match (allowing middle name variations)
                        first_last_match = (
                            len(signup_parts) >= 2 and len(auth_official_parts) >= 2 and
                            signup_parts[0] == auth_official_parts[0] and  # First name matches
                            signup_parts[-1] == auth_official_parts[-1]    # Last name matches
                        )
                        
                        auth_official_matches = exact_match or first_last_match
                        
                        _logger.info("Authorized official match result - Exact: %s, First+Last: %s, Final: %s", 
                                    exact_match, first_last_match, auth_official_matches)
                    
                    name_matches = org_name_matches or auth_official_matches
                    
                    if not name_matches:
                        # Build error message with available names
                        available_names = []
                        if organization_name:
                            available_names.append(f"organization name '{organization_name}'")
                        if auth_official_name:
                            available_names.append(f"authorized official name '{auth_official_name}'")
                        
                        names_str = ' or '.join(available_names)
                        _logger.warning("NPI validation failed: Organization/Authorized official name mismatch - Signup: '%s', Available: %s", 
                                      signup_name, names_str)
                        return False, f"The name '{signup_name}' does not match the {names_str} in the NPI registry. Please enter the exact name as registered with NPI.", None, 'name'
                    
                    matched_name = organization_name if org_name_matches else auth_official_name
                    _logger.info("Organization/Authorized official name validation successful - Signup: %s, Matched: %s", 
                               signup_name, matched_name)
                    
                else:
                    _logger.warning("NPI validation failed: Unknown enumeration type - %s", enumeration_type)
                    return False, f"NPI number {npi} has an unknown type. Please contact support.", None, 'npi_number'
            
            _logger.info("NPI validation successful: %s", npi)
            return True, "NPI number is valid.", result, None
            
        except requests.exceptions.RequestException as e:
            _logger.error("Error validating NPI (RequestException): %s", str(e), exc_info=True)
            return False, f"Error validating NPI: Unable to connect to NPI registry. Please try again later.", None, 'npi_number'
        except Exception as e:
            _logger.error("Error validating NPI (Exception): %s", str(e), exc_info=True)
            return False, f"Error validating NPI: {str(e)}", None, 'npi_number'
