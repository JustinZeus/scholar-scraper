from __future__ import annotations

import re

EXPORT_SCHEMA_VERSION = 1
MAX_IMPORT_SCHOLARS = 10_000
MAX_IMPORT_PUBLICATIONS = 100_000
WORD_RE = re.compile(r"[a-z0-9]+")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
