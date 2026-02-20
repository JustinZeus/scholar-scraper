from __future__ import annotations

import re
from urllib.parse import unquote

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    match = DOI_RE.search(unquote(value))
    if not match:
        return None
    return match.group(0).rstrip(" .;,)").lower()


def first_doi_from_texts(*values: str | None) -> str | None:
    for value in values:
        doi = normalize_doi(value)
        if doi:
            return doi
    return None
