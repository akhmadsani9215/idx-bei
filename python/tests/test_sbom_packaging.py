"""Cluster 14 — runtime dependency declaration + factual SBOM."""

from __future__ import annotations

import os
import re
import tomllib

from idx.sbom import REPO_ROOT, build_sbom, classify_license, license_inventory_markdown


def _declared_runtime() -> set[str]:
    with open(os.path.join(REPO_ROOT, "python", "pyproject.toml"), "rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]
    return {re.split(r"[<>=!~ ;\[]", d, maxsplit=1)[0].lower() for d in deps}


def test_core_imports_are_declared_runtime_dependencies():
    declared = _declared_runtime()
    for pkg in ("pandas", "numpy", "pyarrow", "duckdb", "fastapi", "uvicorn"):
        assert pkg in declared, pkg
    assert "yfinance" not in declared  # opt-in extra only


def test_license_classification():
    assert classify_license("MIT") == "PERMISSIVE_DECLARED"
    assert classify_license("BSD-3-Clause") == "PERMISSIVE_DECLARED"
    assert classify_license("MPL-2.0 AND MIT") == "REVIEW_REQUIRED"
    assert classify_license("GNU General Public License v3 (GPLv3)") == "REVIEW_REQUIRED"
    assert classify_license("UNKNOWN") == "REVIEW_REQUIRED"


def test_sbom_is_cyclonedx_and_marks_legal_status():
    sbom = build_sbom()
    assert sbom["bomFormat"] == "CycloneDX"
    props = {p["name"]: p["value"] for p in sbom["metadata"]["properties"]}
    assert props["ritelinsight:legal_status"] == "NOT_LEGALLY_REVIEWED"
    names = {c["name"].lower() for c in sbom["components"]}
    assert {"pandas", "numpy", "fastapi"} <= names
    md = license_inventory_markdown(sbom)
    assert "NOT_LEGALLY_REVIEWED" in md
