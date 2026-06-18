"""
Cross-validation service.

Compares OCR-extracted fields against the applicant's declared data (passed in by the caller). Mismatches generate a flag reason.
"""

import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Thresholds -- tunable per document type and risk appetite
NAME_SIMILARITY_THRESHOLD = 0.75  # 75% string similarity for name match
DOB_EXACT_MATCH_REQUIRED = True
INCOME_TOLERANCE_PERCENT = 20  # extracted income within +-20% of declared


class CrossValidator:

    def validate(self, document_type: str, ocr_result: dict, declared_name: str, declared_dob: str, declared_income: float | None = None) -> tuple[bool, str | None]:
        """
        Returns (is_valid: bool, flag_reason: str | None).
        is_valid=True means the document passes all the checks.
        """
        flags = []

        extracted_name = ocr_result.get("name")
        extracted_dob = ocr_result.get("dob")
        extracted_income = ocr_result.get("income")
        confidence = ocr_result.get("confidence", 0)
        error = ocr_result.get("error")

        # 1. OCR failed completely
        if error and not extracted_name:
            return False, f"OCR extraction failed: {error}"

        # 2. Low confidence -- can't trust the extraction
        if confidence < 60:
            return False, (
                f"OCR confidence {confidence}% is too low to auto-verify. "
                "Please re-upload a clearer image."
            )

        # 3.Name match
        if extracted_name and declared_name:
            similarity = SequenceMatcher(
                None,
                extracted_name.lower().strip(),
                declared_name.lower().strip(),
            ).ratio()
            if similarity < NAME_SIMILARITY_THRESHOLD:
                flags.append(
                    f"Name mismatch: document shows '{extracted_name}', "
                    f"application declared '{declared_name}' "
                    f"(similarity: {similarity:.0%})."
                )
                logger.warning(
                    f"Name mismatch for doc_type={document_type}: "
                    f"ocr='{extracted_name}' declared='{declared_name}' "
                    f"similarity={similarity:.2f}"
                )

        # 4. Date of birth match
        if DOB_EXACT_MATCH_REQUIRED and extracted_dob and declared_dob:
            if extracted_dob.strip() != declared_dob.strip():
                flags.append(
                    f"Date of birth mismatch: document shows '{extracted_dob}', "
                    f"application declared '{declared_dob}'."
                )

        # 5. Income validation (salary slip only)
        if document_type == "salary_slip" and extracted_income and declared_income:
            lower = declared_income * (1 - INCOME_TOLERANCE_PERCENT / 100)
            upper = declared_income * (1 + INCOME_TOLERANCE_PERCENT / 100)
            if not (lower <= extracted_income <= upper):
                flags.append(
                    f"Income mismatch: salary slip shows Rs. {extracted_income:,.0f}, "
                    f"application declared Rs. {declared_income:,.0f} "
                    f"(tolerance +-{INCOME_TOLERANCE_PERCENT}%)."
                )

        if flags:
            return False, " | ".join(flags)

        return True, None

