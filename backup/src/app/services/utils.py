import re
import unicodedata
from uuid import uuid4


def make_slug(value: str, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    slug = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-_")
    if not slug:
        slug = f"item-{uuid4().hex[:10]}"
    return slug[:max_length].rstrip("-_")
