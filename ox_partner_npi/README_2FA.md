# Two-Factor Authentication (2FA) in Odoo 18

## Overview

Odoo 18 includes native **Two-Factor Authentication (TOTP)** support through the `auth_totp` module. However, **2FA is NOT available during the signup process** - it is configured **after** the user account is created.

## How 2FA Works in Odoo 18

### During Signup
- **2FA is NOT required or available during signup**
- Users can sign up normally with email, password, and NPI validation
- After successful signup, users are automatically logged in

### After Signup (Post-Account Creation)
1. **User logs in** with their email and password
2. **If 2FA is enabled** for the user:
   - After successful password authentication, user is redirected to `/web/login/totp`
   - User must enter a 6-digit code from their authenticator app (Google Authenticator, Authy, etc.)
   - Once verified, user gains access to the system

### Enabling 2FA
- Users can enable 2FA from their user profile settings after logging in
- Go to: **Settings → Users & Companies → Users → [Your User] → Two-factor authentication**
- Click "Enable Two-Factor Authentication"
- Scan QR code with authenticator app
- Enter verification code to complete setup

## Integration with NPI Signup

The NPI validation module (`ox_partner_npi`) works independently of 2FA:

1. **Signup Process:**
   - User enters: Name, Email, Password, **NPI Number**
   - NPI is validated via CMS NPI Registry API
   - If NPI is invalid → Error message displayed, signup blocked
   - If NPI is valid → Account created, user logged in

2. **After Signup:**
   - User can optionally enable 2FA from their profile
   - 2FA adds an extra security layer for future logins
   - NPI validation is only required during signup, not for subsequent logins

## Module Dependencies

- `auth_signup` - Handles user signup/registration
- `auth_totp` - Provides 2FA functionality (auto-installed in Odoo 18)
- `ox_partner_npi` - Adds NPI validation to signup process

## Security Flow

```
Signup:
  Email + Password + NPI → Validate NPI → Create Account → Login

Login (with 2FA enabled):
  Email + Password → Validate → 2FA Code → Access Granted

Login (without 2FA):
  Email + Password → Access Granted
```

## Notes

- 2FA is **optional** - users can choose to enable it after signup
- 2FA can be enabled/disabled from user profile settings
- Trusted devices can be configured to skip 2FA for 90 days
- NPI validation is **mandatory** during signup (as per client requirements)
- NPI validation does not interfere with 2FA functionality
