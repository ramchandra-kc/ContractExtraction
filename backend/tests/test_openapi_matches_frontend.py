"""frontend/openapi.json is the contract the frontend's types are generated from; it must match the live API.

After changing the API: ``cd frontend && npm run gen:api`` (writes openapi.json and src/api/schema.d.ts).
"""

from __future__ import annotations

import json
from pathlib import Path

from contract_extraction.cli import openapi_json

FRONTEND_OPENAPI = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def test_frontend_openapi_is_current():
    assert FRONTEND_OPENAPI.is_file(), "frontend/openapi.json is missing; run `npm run gen:api` in frontend/"
    assert json.loads(FRONTEND_OPENAPI.read_text(encoding="utf-8")) == json.loads(openapi_json()), (
        "frontend/openapi.json is out of date; run `npm run gen:api` in frontend/"
    )
