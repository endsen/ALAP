"""Validate offline schemas, examples, and the generated OpenAPI specification."""

import json
from pathlib import Path

import yaml
from openapi_spec_validator import validate

from alap.contracts import ContractCatalog

ROOT = Path(__file__).resolve().parent


def main():
    catalog = ContractCatalog(ROOT)
    for name in catalog.schemas:
        fixture = json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8"))
        catalog.validate(name, fixture)
    validate(yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8")))
    print(f"PASS: {len(catalog.schemas)} schemas/examples and full OpenAPI specification")


if __name__ == "__main__":
    main()
