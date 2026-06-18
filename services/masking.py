"""
Data masking utilities -- applied before storing extracted PII.

Rules (RBI Digital Lending Guidelines + DPDP Act):
    -- Aadhaar: Store only the last 4 digits. Full number must NEVER be persisted.
    -- PAN: Store in masked display form (ABCXX1234X) -> full value kept for bureau use.
    -- Bank Account: Store only the 4 digits.
    -- Income: Store as a range bucket, not the exact figure.
    -- Name: Store as-is (needed for matching, not a secret).
    -- DOB: Store as-is (needed for age verification).
"""


def mask_aadhaar(aadhaar: str) -> str:
    """
    '1234 5678 9012' -> 'XXXX XXXX 9012'
    Only the last 4 digits are stored -- UIDAI mandate.
    """
    digits = aadhaar.replace(" ", "").replace("-", "")
    if len(digits) < 4:
        return "XXXX XXXX XXXX"
    last4 = digits[-4:]
    return f"XXXX XXXX {last4}"


def mask_pan(pan: str) -> str:
    """
    'ABCDE1234F' -> 'ABCXX1234X'
    Middle 2 letters and last letter are masked in display.
    Full value remains available for credit bureau queries.
    """
    pan = pan.upper().strip()
    if len(pan) != 10:
        return pan
    return pan[:3] + "XX" + pan[5:9] + "X"


def mask_bank_account(account: str) -> str:
    """
    '9876543210001234' -> 'XXXXXXXXXXXX1234'
    """
    digits = account.replace(" ", "")
    if len(digits) < 4:
        return "XXXX"
    return "X" * (len(digits) - 4) + digits[-4:]


def income_to_bucket(income: float) -> str:
    """
    Converts the exact income to a range bucket for compliant storage. Exact income figures are not stored -- only the bucket.
    """
    if income < 25_000:
        return "LT_25K"
    elif income < 50_000:
        return "25K_50K"
    elif income < 100_000:
        return "50K_100K"
    elif income < 200_000:
        return "100K_2L"
    else:
        return "GT_2L"

