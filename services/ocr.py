"""
OCR service -- extracts the structured fields from KYC documents.

In production: AWS Textract via the S3-native API.

With USE_REAL_OCR=False: returns the deterministic mock data seeded from the document filename, so the same file always gives the same "extracted" values -- makes testing predictable.

Return format:
{
    "name":         str | None,
    "dob":          str | None,  # YYYY-MM-DD
    "id_number":    str | None,  # raw, before masking
    "income":       float | None,  # salary slip only
    "confidence":   int,  # 0-100
    "error":        str | None,  # set if OCR failed
"""
import logging, random
from pathlib import Path
from config import settings

logger = logging.getLogger(__name__)

# Sample names for mock OCR
_MOCK_NAMES = [
    "Rahul Sharma", "Priya Patel", "Amit Kumar", "Sunita Verma", "Rajesh Singh", "Anita Gupta",
]


class OCRService:

    async def extract(
            self,
            file_content: bytes,
            document_type: str,
            file_name: str,
    ) -> dict:
        """
        Main entry point. Dispatches to real or mock OCR.
        """
        if settings.USE_REAL_OCR:
            return await self._real_ocr(file_content, document_type)
        return self._mock_ocr(document_type, file_name)

    async def _real_ocr(self, file_content: bytes, document_type: str) -> dict:
        """
        Production path -- calls AWS Textract.
        Requires USE_REAL_OCR=True and valid AWS credentials.
        """
        import boto3
        try:
            textract = boto3.client(
                "textract",
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            response = textract.detect_document_text(
                Document={"Bytes": file_content}
            )
            # Extracting all text blocks
            full_text = " ".join(
                block["Text"]
                for block in response.get("Blocks", [])
                if block["BlockType"] == "LINE"
            )
            # Parse structured fields from raw text
            return self._parse_fields(full_text, document_type)
        except Exception as exc:
            logger.error(f"Textract failed: {exc}")
            return {"name": None, "dob": None, "id_number": None, "income": None, "confidence": 0, "error": str(exc)}

    def _mock_ocr(self, document_type: str, file_name: str) -> dict:
        """
        Deterministic mock -- same file_name always produces same output. Simulates realistic OCR results per document type.
        """
        seed = sum(ord(c) for c in file_name)
        rng = random.Random(seed)

        confidence = rng.randint(72, 98)

        # Simulating Occasional Unreadable Document (5% chance)
        if rng.random() < 0.05:
            return {
                "name": None, "dob": None, "id_number": None, "income": None, "confidence": 20,
                "error": "Document too blurry or rotated for OCR extraction",
            }

        name = rng.choice(_MOCK_NAMES)

        # Generating a plausible DOB
        year = rng.randint(1970, 2000)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        dob = f"{year}-{month:02d}-{day:02d}"

        if document_type == "aadhaar":
            digits = "".join(str(rng.randint(0, 9)) for _ in range(12))
            id_num = f"{digits[:4]} {digits[4:8]} {digits[8:]}"
        elif document_type == "pan":
            letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            id_num = (
                    "".join(rng.choice(letters) for _ in range(5)) + "".join(
                str(rng.randint(0, 9)) for _ in range(4)) + rng.choice(letters)
            )
        elif document_type == "salary_slip":
            income = float(rng.randint(25, 200) * 1000)
            return {
                "name": name, "dob": dob, "id_number": None, "income": income, "confidence": confidence, "error": None,
            }
        else:
            id_num = "".join(str(rng.randint(0, 9)) for _ in range(10))

        return {
            "name": name, "dob": dob, "id_number": id_num, "income": None, "confidence": confidence, "error": None,
        }

    def _parse_fields(self, text: str, document_type: str) -> dict:
        """
        Parses raw OCR text into structured fields. This is a simplified parser -- production would use regex patterns tuned per document layout.
        """
        import re

        result = {
            "name": None, "dob": None, "id_number": None, "income": None, "confidence": 85, "error": None,
        }

        # Name: looking for patterns like "Name: RAHUL SHARMA"
        name_match = re.search(r"(?:Name|नाम)\s*[:\s]+([A-Z][A-Za-z\s]+)", text)
        if name_match:
            result["name"] = name_match.group(1).strip()

        # DOB: look for DD/MM/YYYY or YYYY-MM-DD
        dob_match = re.search(r"(\d{2})[/\-](\d{2})[/\-](\d{4})", text)
        if dob_match:
            d, m, y = dob_match.groups()
            result["dob"] = f"{y}-{m}-{d}"

        # Aadhaar: 12 digits in groups of 4
        if document_type == "aadhaar":
            aadhaar_match = re.search(r"(\d{4}\s\d{4}\s\d{4})", text)
            if aadhaar_match:
                result["id_number"] = aadhaar_match.group(1)

        # PAN: 5 letters + 4 digits + 1 letter
        if document_type == "pan":
            pan_match = re.search(r"([A-Z]{5}[0-9]{4}[A-Z])", text)
            if pan_match:
                result["id_number"] = pan_match.group(1)

        return result

