"""Every dataset's and every tool's labels, mapped onto one shared set of types.

PERSON names; EMAIL; PHONE (and fax); ADDRESS (street, city, postcode; for TAB its LOC
class, which also holds countries and regions); ID (national, account, card and other
numbers and codes); DATE (dates, dates of birth, date-times); USERNAME; OTHER for the rest.
"""
TYPES = ("PERSON", "EMAIL", "PHONE", "ADDRESS", "ID", "DATE", "USERNAME", "OTHER")


def _invert(groups):
    return {label: kind for kind, labels in groups.items() for label in labels}


class _Map(dict):
    """A label map whose unknown labels fall to OTHER (and are remembered, to report)."""
    def __missing__(self, label):
        self.unknown.add(label)
        return "OTHER"

    def __init__(self, groups):
        super().__init__(_invert(groups))
        self.unknown = set()


# --- datasets -----------------------------------------------------------------
NEMOTRON = _Map({
    "PERSON": ["first_name", "last_name"],
    "EMAIL": ["email"],
    "PHONE": ["phone_number", "fax_number"],
    "ADDRESS": ["street_address", "city", "postcode"],
    "ID": ["account_number", "customer_id", "medical_record_number", "biometric_identifier",
           "health_plan_beneficiary_number", "employee_id", "bank_routing_number", "ssn",
           "credit_debit_card", "swift_bic", "certificate_license_number",
           "vehicle_identifier", "license_plate", "tax_id", "unique_id", "device_identifier",
           "cvv", "pin", "national_id"],
    "DATE": ["date", "date_of_birth", "date_time"],
    "USERNAME": ["user_name"],
    "OTHER": ["company_name", "url", "occupation", "time", "state", "country", "county",
              "coordinate", "employment_status", "education_level", "age", "race_ethnicity",
              "gender", "language", "password", "religious_belief", "political_view",
              "blood_type", "http_cookie", "api_key", "mac_address", "ipv4", "ipv6",
              "sexuality"],
})

TAB = _Map({
    "PERSON": ["PERSON"], "ID": ["CODE"], "ADDRESS": ["LOC"], "DATE": ["DATETIME"],
    "OTHER": ["ORG", "DEM", "QUANTITY", "MISC"],
})

PIITRACE = _Map({
    "PERSON": ["private_person"], "EMAIL": ["private_email"], "PHONE": ["private_phone"],
    "ADDRESS": ["private_address"], "ID": ["account_number", "other_pii"],
    "DATE": ["private_date"], "OTHER": ["private_url", "secret"],
})

CHAT = _Map({
    "PERSON": ["PERSON"], "EMAIL": ["EMAIL"], "PHONE": ["PHONE"], "ID": ["ID_NUMBER"],
    "OTHER": ["API_KEY", "IP_ADDRESS"],
})

# --- tools --------------------------------------------------------------------
HUSH = _Map({
    "PERSON": ["PERSON", "STUDENT", "STAFF", "CLINICIAN", "SAID"],
    "EMAIL": ["EMAIL"],
    "PHONE": ["PHONE"],
    "ADDRESS": ["ADDRESS", "HOMEADDR", "POSTCODE", "PLACE"],
    "ID": ["UPN", "ULN", "NINO", "NHSNUM", "IBAN", "SORTCODE", "LICENCE", "CARD", "ACCOUNTNO",
           "PASSPORT", "NUMBER", "MRN", "BIC", "CODE"],
    "DATE": ["DATE", "DOB"],
    "USERNAME": ["USERNAME", "HANDLE"],
    "OTHER": ["SECRET", "IP", "URL", "TOKEN"],
})

PRESIDIO = _Map({
    "PERSON": ["PERSON"],
    "EMAIL": ["EMAIL_ADDRESS"],
    "PHONE": ["PHONE_NUMBER"],
    "ADDRESS": ["LOCATION"],
    "DATE": ["DATE_TIME"],
    "OTHER": ["URL", "IP_ADDRESS", "NRP", "CRYPTO", "MAC_ADDRESS"],
    # every other Presidio recogniser is a national, financial or licence number: ID
})
PRESIDIO_DEFAULT = "ID"

# The labels GLiNER is asked for (30, its trained maximum), and their shared type.
GLINER = _Map({
    "PERSON": ["name", "first name", "last name"],
    "EMAIL": ["email address"],
    "PHONE": ["phone number", "fax number"],
    "ADDRESS": ["location address", "location street", "location city", "location zip",
                "location state", "location country"],
    "DATE": ["dob", "date"],
    "ID": ["account number", "bank account", "credit card", "cvv", "ssn", "passport number",
           "driver license", "customer id", "employee id", "healthcare number",
           "routing number", "vehicle id"],
    "USERNAME": ["username"],
    "OTHER": ["password", "ip address", "url"],
})

# A short list, one plain label per shared type, to check how much the long list costs.
GLINER_SHORT = _Map({
    "PERSON": ["name"], "EMAIL": ["email"], "PHONE": ["phone number"], "ADDRESS": ["address"],
    "DATE": ["date"], "ID": ["account number", "id number"], "USERNAME": ["username"],
    "OTHER": ["url", "password"],
})


def tool_type(tool, label):
    if tool.startswith("hush"):
        # hush 0.2.0 gives a known person with a role the kind PERSON_<ROLE>
        return HUSH["PERSON" if label.startswith("PERSON_") else label]
    if tool == "presidio":
        return PRESIDIO.get(label, PRESIDIO_DEFAULT)
    if tool == "gliner":
        return GLINER[label]
    if tool == "gliner-short":
        return GLINER_SHORT[label]
    raise ValueError(tool)
