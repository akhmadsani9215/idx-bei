"""Factual SBOM + declared-license inventory (Cluster 14).

Reads installed package metadata only (Python runtime closure of ``idx-bei`` and
frontend production dependencies). Declared licenses are NOT legal review;
anything copyleft / unknown is flagged ``REVIEW_REQUIRED``.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from importlib import metadata
from typing import Any

from idx.core.utils import DATA_DIR

REPO_ROOT = os.path.abspath(os.path.join(DATA_DIR, ".."))
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
ROOT_PACKAGE = "idx-bei"

PERMISSIVE = (
    "MIT",
    "BSD",
    "APACHE",
    "ISC",
    "PSF",
    "PYTHON SOFTWARE FOUNDATION",
    "0BSD",
    "UNLICENSE",
    "ZLIB",
    "CC0",
    "HPND",
    "PUBLIC DOMAIN",
)
COPYLEFT = ("GPL", "LGPL", "AGPL", "MPL", "EPL", "CDDL", "EUPL", "SSPL", "CC-BY-SA")

_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared_license(dist: metadata.Distribution) -> str:
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr.strip()
    classifiers = [
        c.split("::")[-1].strip()
        for c in md.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    lic = (md.get("License") or "").strip()
    if classifiers:
        return "; ".join(sorted(set(classifiers)))
    if lic and len(lic) < 120 and "\n" not in lic:
        return lic
    return "UNKNOWN"


def classify_license(declared: str) -> str:
    up = declared.upper()
    if up in ("", "UNKNOWN"):
        return "REVIEW_REQUIRED"
    if any(tag in up for tag in COPYLEFT):
        return "REVIEW_REQUIRED"
    if any(tag in up for tag in PERMISSIVE):
        return "PERMISSIVE_DECLARED"
    return "REVIEW_REQUIRED"


def python_runtime_closure(root: str = ROOT_PACKAGE) -> list[dict[str, Any]]:
    """Transitive ``Requires-Dist`` closure (no extras) of the installed root package."""
    installed = {
        _norm(d.metadata["Name"]): d for d in metadata.distributions() if d.metadata["Name"]
    }
    seen: dict[str, dict[str, Any]] = {}
    stack = [_norm(root)]
    while stack:
        name = stack.pop()
        dist = installed.get(name)
        if dist is None or name in seen:
            continue
        declared = _declared_license(dist)
        seen[name] = {
            "ecosystem": "pypi",
            "name": dist.metadata["Name"],
            "version": dist.version,
            "declared_license": declared,
            "license_review": classify_license(declared),
            "purl": f"pkg:pypi/{name}@{dist.version}",
        }
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            m = _REQ_NAME.match(req)
            if m:
                stack.append(_norm(m.group(1)))
    seen.pop(_norm(root), None)
    return sorted(seen.values(), key=lambda r: r["name"].lower())


def frontend_dependencies(frontend_dir: str = FRONTEND_DIR) -> list[dict[str, Any]]:
    """Direct production ``dependencies`` from package.json with installed metadata."""
    pkg_path = os.path.join(frontend_dir, "package.json")
    if not os.path.exists(pkg_path):
        return []
    with open(pkg_path, encoding="utf-8") as fh:
        deps = json.load(fh).get("dependencies") or {}
    out = []
    for name, spec in sorted(deps.items()):
        meta_path = os.path.join(frontend_dir, "node_modules", *name.split("/"), "package.json")
        version, declared = None, "NOT_INSTALLED"
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
            version = meta.get("version")
            lic = meta.get("license")
            declared = (
                lic
                if isinstance(lic, str)
                else (lic or {}).get("type", "UNKNOWN")
                if lic
                else "UNKNOWN"
            )
        out.append(
            {
                "ecosystem": "npm",
                "name": name,
                "version": version,
                "requested": spec,
                "declared_license": declared,
                "license_review": classify_license(declared) if version else "REVIEW_REQUIRED",
                "purl": f"pkg:npm/{name}@{version}" if version else None,
            }
        )
    return out


def build_sbom() -> dict[str, Any]:
    components = python_runtime_closure() + frontend_dependencies()
    try:
        root_version = metadata.version(ROOT_PACKAGE)
    except metadata.PackageNotFoundError:
        root_version = None
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {
                "type": "application",
                "name": ROOT_PACKAGE,
                "version": root_version,
                "licenses": [{"license": {"id": "MIT"}}],
            },
            "properties": [
                {
                    "name": "ritelinsight:scope",
                    "value": "python runtime closure + frontend prod deps",
                },
                {"name": "ritelinsight:legal_status", "value": "NOT_LEGALLY_REVIEWED"},
            ],
        },
        "components": [
            {
                "type": "library",
                "name": c["name"],
                "version": c["version"],
                "purl": c["purl"],
                "licenses": [{"license": {"name": c["declared_license"]}}],
                "properties": [
                    {"name": "ritelinsight:ecosystem", "value": c["ecosystem"]},
                    {"name": "ritelinsight:license_review", "value": c["license_review"]},
                ],
            }
            for c in components
        ],
    }


def license_inventory_markdown(sbom: dict[str, Any]) -> str:
    rows = []
    review = []
    for c in sbom["components"]:
        props = {p["name"]: p["value"] for p in c["properties"]}
        lic = c["licenses"][0]["license"]["name"]
        flag = props["ritelinsight:license_review"]
        rows.append(
            f"| {props['ritelinsight:ecosystem']} | {c['name']} | {c['version'] or '—'} | {lic} | {flag} |"
        )
        if flag != "PERMISSIVE_DECLARED":
            review.append(f"- {c['name']} {c['version'] or ''}: {lic}")
    return "\n".join(
        [
            "# Dependency License Inventory (declared metadata)",
            "",
            f"Generated: {sbom['metadata']['timestamp']} by `uv run idx sbom`.",
            "",
            "Status: **NOT_LEGALLY_REVIEWED** — declared package metadata only; not a NOTICE file "
            "and not legal advice. Data-source rights are tracked separately in "
            "`docs/COMMERCIAL_READINESS.md`.",
            "",
            f"Components: {len(sbom['components'])} · review required: {len(review)}",
            "",
            "## Review required (copyleft / unknown / not installed)",
            "",
            *(review or ["- none"]),
            "",
            "## All components",
            "",
            "| Ecosystem | Package | Version | Declared license | Review |",
            "|---|---|---|---|---|",
            *rows,
            "",
        ]
    )
