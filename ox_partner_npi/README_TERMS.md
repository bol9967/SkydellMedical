# Terms & Conditions with Digital Signature - Implementation Guide

## Overview

This implementation adds a **legally binding, HIPAA-compliant Terms & Conditions acceptance** system to the signup process with a complete audit trail.

## Features

### ✅ Clickwrap Method
- Scrollable Terms & Conditions window
- "Accept" button remains **disabled** until user scrolls to bottom
- Visual feedback when scroll requirement is met

### ✅ Digital Signature
- Full name input field (typed signature)
- Required before acceptance
- Stored in audit trail

### ✅ Complete Audit Trail
Stores the following metadata:
- **Timestamp (UTC)** - Exact date/time of acceptance
- **IP Address** - User's IP address at time of acceptance
- **Terms Version ID** - Exact version of Terms accepted
- **Digital Signature** - Full name typed by user
- **User Agent** - Browser and device information
- **Acceptance Method** - How terms were accepted (signup/manual/update)

## Signup Flow

### Step 1: Standard Signup Form
1. User enters: Name, Email, Password, **NPI Number**
2. NPI is validated via CMS API
3. If valid → Proceed to Step 2

### Step 2: Terms & Conditions Page
1. User sees scrollable Terms & Conditions
2. Must scroll to bottom (button disabled until then)
3. Must type full name in Digital Signature field
4. Click "Accept Terms & Conditions"
5. Account created with full audit trail

## Database Models

### `terms.conditions`
Stores Terms & Conditions versions:
- **name**: Title
- **version**: Version number (e.g., "1.0", "2.0")
- **content**: HTML content of Terms
- **active**: Whether this version is active
- **is_current**: The current version users must accept
- **effective_date**: When this version became effective

### `terms.acceptance`
Stores acceptance audit trail:
- **terms_id**: Which Terms version was accepted
- **terms_version**: Version number (for quick reference)
- **partner_id**: Who accepted
- **user_id**: Associated user
- **acceptance_date**: Timestamp (UTC)
- **ip_address**: IP address
- **digital_signature**: Typed full name
- **user_agent**: Browser/device info
- **acceptance_method**: How it was accepted

## Admin Interface

### Managing Terms & Conditions
1. Go to: **Settings → Terms & Conditions → Terms Versions**
2. Create new Terms version
3. Set as "Current Version" (only one can be current)
4. View all acceptances with full audit trail

### Viewing Acceptances
1. Go to: **Settings → Terms & Conditions → Acceptances**
2. See all acceptances with:
   - User/Partner information
   - Acceptance date/time
   - Digital signature
   - IP address
   - Terms version accepted

## Technical Implementation

### Two-Step Signup Process

**Step 1 Controller** (`_signup_with_values`):
- Validates NPI
- Stores signup data in session
- Redirects to Terms page if Terms exist

**Step 2 Controller** (`web_signup_terms`):
- Displays Terms & Conditions
- Validates scroll and signature
- Creates acceptance record
- Completes signup

### JavaScript Features

**`terms_acceptance.js`**:
- Detects when user scrolls to bottom
- Enables/disables Accept button based on:
  - Scroll position (must be at bottom)
  - Signature field (must have value)
- Form validation before submission
- Visual feedback for user

### Security Features

- **CSRF Protection**: All forms use CSRF tokens
- **Session-based**: Signup data stored in session (not exposed in URL)
- **IP Tracking**: Captures IP address automatically
- **UTC Timestamps**: All dates stored in UTC for consistency
- **Immutable Records**: Acceptance records are read-only after creation

## HIPAA Compliance

This implementation provides:
- ✅ **Audit Trail**: Complete record of who accepted what and when
- ✅ **Digital Signature**: Legal proof of acceptance
- ✅ **Version Control**: Track which version each user accepted
- ✅ **Timestamp**: Precise time of acceptance (UTC)
- ✅ **IP Address**: Location data for compliance
- ✅ **User Agent**: Device/browser information

## Usage

### Setting Up Terms & Conditions

1. **Create Terms Version**:
   ```
   Settings → Terms & Conditions → Terms Versions → Create
   ```

2. **Enter Details**:
   - Title: "Terms & Conditions - Version 1.0"
   - Version: "1.0"
   - Effective Date: Today's date
   - Content: Your Terms & Conditions (HTML supported)

3. **Set as Current**:
   - Click "Set as Current Version" button
   - This makes it the version new users must accept

4. **Activate**:
   - Ensure "Active" checkbox is checked

### Testing the Flow

1. Go to `/web/signup`
2. Fill in signup form with valid NPI
3. Submit form
4. You'll be redirected to Terms & Conditions page
5. Scroll to bottom (button enables)
6. Type your full name
7. Click "Accept Terms & Conditions"
8. Account is created with full audit trail

## Files Created/Modified

### Models
- `models/terms_conditions.py` - Terms and Acceptance models

### Controllers
- `controllers/main.py` - Updated signup flow with T&C step

### Views
- `views/signup_terms_templates.xml` - T&C acceptance page
- `views/terms_conditions_views.xml` - Admin views for managing Terms

### JavaScript
- `static/src/js/terms_acceptance.js` - Scroll detection and validation

### Security
- `security/ir.model.access.csv` - Access rights

### Data
- `data/terms_conditions_demo.xml` - Demo Terms (optional)

## Best Practices

1. **Version Management**: Always create new versions instead of editing existing ones
2. **Effective Dates**: Set effective dates when creating new versions
3. **Content Review**: Use HTML editor for rich formatting
4. **Testing**: Test scroll detection on different screen sizes
5. **Audit Review**: Regularly review acceptance records for compliance

## Legal Considerations

- ✅ **Clickwrap**: Users must scroll to bottom (proves they saw content)
- ✅ **Digital Signature**: Typed name serves as legal signature
- ✅ **Audit Trail**: Complete record for legal defense
- ✅ **Version Control**: Track which version each user accepted
- ✅ **Timestamp**: Precise time for legal purposes

This implementation provides a robust, legally defensible Terms & Conditions acceptance system that meets HIPAA compliance requirements.
