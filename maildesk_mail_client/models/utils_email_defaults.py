# Copyright (C) 2025 Metzler IT GmbH
# License Odoo Proprietary License v1.0 (OPL-1)
# You may use this file only in accordance with the license terms.
# For more information, visit: https://www.odoo.com/documentation/18.0/legal/licenses/licenses.html#odoo-proprietary-license


import re

GENERIC_LOCALPART = {
    "info","contact","sales","hello","support","office","service",
    "kundenservice","verkauf","mail","team","admin",
}
FREE_MAIL = {
    "gmail.com","googlemail.com","outlook.com","hotmail.com","yahoo.com",
    "icloud.com","me.com","aol.com","gmx.de","web.de","t-online.de",
}
TLD_COUNTRY_MAP = {
    "de": ("de_DE","Europe/Berlin","Germany"),
    "at": ("de_AT","Europe/Vienna","Austria"),
    "ch": ("de_CH","Europe/Zurich","Switzerland"),
    "fr": ("fr_FR","Europe/Paris","France"),
    "it": ("it_IT","Europe/Rome","Italy"),
    "es": ("es_ES","Europe/Madrid","Spain"),
    "pt": ("pt_PT","Europe/Lisbon","Portugal"),
    "nl": ("nl_NL","Europe/Amsterdam","Netherlands"),
    "be": ("nl_BE","Europe/Brussels","Belgium"),
    "uk": ("en_GB","Europe/London","United Kingdom"),
    "co.uk": ("en_GB","Europe/London","United Kingdom"),
    "us": ("en_US","America/New_York","United States"),
}

def _domain(email: str) -> str:
    m = re.match(r"^[^@]+@([^@]+\.[^@]+)$", (email or "").lower().strip())
    return m.group(1) if m else ""

def _local(email: str) -> str:
    m = re.match(r"^([^@]+)@[^@]+\.[^@]+$", (email or "").lower().strip())
    return m.group(1) if m else ""

def _core(domain: str) -> str:
    parts = [p for p in (domain or "").split(".") if p]
    return parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")

def _tld_key(domain: str) -> str:
    d = (domain or "").lower()
    if d.endswith(".co.uk"):
        return "co.uk"
    return (d.split(".")[-1] if d else "")

def _guess_company(domain: str) -> str:
    if not domain or domain in FREE_MAIL:
        return ""
    return _core(domain).replace("-", " ").replace("_", " ").title()

def defaults_from_email(email: str, display_name: str = "") -> dict:
    email = (email or "").strip().lower()
    domain = _domain(email)
    local = _local(email)

    lang, tz, country = TLD_COUNTRY_MAP.get(_tld_key(domain), ("en_US", "UTC", ""))

    if display_name:
        name = display_name.strip()
    elif local and local not in GENERIC_LOCALPART:
        name = local.replace(".", " ").replace("-", " ").replace("_", " ").title()
    else:
        name = _guess_company(domain) or (email or "New Contact")

    website = ("" if (not domain or domain in FREE_MAIL) else f"https://{domain}")

    return {
        "name": name,
        "website": website,
        "lang": lang,
        "tz": tz,
        "x_email_domain": domain,
        "x_email_localpart": local,
        "x_company_guess": _guess_company(domain),
        "x_country_name_guess": country,
    }
