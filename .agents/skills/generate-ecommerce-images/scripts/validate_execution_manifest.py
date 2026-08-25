#!/usr/bin/env python3
"""Mechanically validate ecommerce image execution manifests.

This script validates records and file binding only. It does not inspect or edit
image pixels, and a passing result never replaces visual QA.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


REQUIRED_JOB_FIELDS = {
    "job_id",
    "sku",
    "slot",
    "role",
    "prompt_hash",
    "expected_filename",
    "returned_path",
    "final_path",
    "status",
    "planned",
    "observed",
}

REQUIRED_OBSERVED_FIELDS = {
    "role",
    "framework_topology",
    "p_t_e_relationship",
    "alignment_axis",
    "camera",
    "text_exact",
    "unplanned_text",
    "component_count",
    "component_types",
    "evidence_binding",
    "fingerprint",
    "status",
}

REQUIRED_PROMPT_FIELDS = {
    "FRAMEWORK_ID",
    "P_REGION",
    "T_REGION",
    "E_REGION",
    "ALIGNMENT_AXIS",
    "READING_PATH",
    "CAMERA",
    "TEXT_ROLES",
    "ALLOWED_TEXT_EXACT",
    "DISCLOSURE",
    "EXCEPTION_CODE",
    "EVIDENCE_BINDING",
    "COMPONENT",
    "FONT_HIERARCHY",
    "COLOR_RATIO",
    "NEGATIVE_CONSTRAINTS",
}

HERO_ROLES = {"marketing_hero", "amazon_main", "tiktok_clean_main"}
FUNCTION_ROLES = {"functional_scene", "function_use_scene"}
DIMENSION_ROLES = {"dimension", "dimensions", "size_chart"}


def _nonempty(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def validate_manifest(data: Any, base_dir: Path, check_files: bool = True) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        return ["manifest must be an object with a jobs array"]

    jobs = data["jobs"]
    seen_job_ids: set[str] = set()
    seen_final_paths: set[str] = set()

    for index, job in enumerate(jobs):
        prefix = f"jobs[{index}]"
        if not isinstance(job, dict):
            errors.append(f"{prefix} must be an object")
            continue

        missing = sorted(REQUIRED_JOB_FIELDS - job.keys())
        if missing:
            errors.append(f"{prefix} missing fields: {', '.join(missing)}")
            continue

        for field in REQUIRED_JOB_FIELDS - {"planned", "observed"}:
            if not _nonempty(job.get(field)):
                errors.append(f"{prefix}.{field} must be non-empty")

        job_id = str(job.get("job_id", ""))
        if job_id in seen_job_ids:
            errors.append(f"{prefix}.job_id is duplicated: {job_id}")
        seen_job_ids.add(job_id)

        final_path_raw = str(job.get("final_path", ""))
        final_path = Path(final_path_raw)
        if not final_path.is_absolute():
            final_path = base_dir / final_path
        normalized = str(final_path.resolve(strict=False)).casefold()
        if normalized in seen_final_paths:
            errors.append(f"{prefix}.final_path is duplicated: {final_path_raw}")
        seen_final_paths.add(normalized)

        if Path(final_path_raw).name != str(job.get("expected_filename", "")):
            errors.append(
                f"{prefix} expected_filename does not match final_path basename"
            )
        if check_files and final_path_raw and not final_path.is_file():
            errors.append(f"{prefix}.final_path does not exist: {final_path}")

        planned = job.get("planned")
        observed = job.get("observed")
        if not isinstance(planned, dict):
            errors.append(f"{prefix}.planned must be an object")
            continue
        if not isinstance(observed, dict):
            errors.append(f"{prefix}.observed must be an object")
            continue

        prompt_fields = planned.get("prompt_fields")
        if not isinstance(prompt_fields, dict):
            errors.append(f"{prefix}.planned.prompt_fields must be an object")
        else:
            missing_prompt = sorted(REQUIRED_PROMPT_FIELDS - prompt_fields.keys())
            if missing_prompt:
                errors.append(
                    f"{prefix}.planned.prompt_fields missing: {', '.join(missing_prompt)}"
                )
            for field in REQUIRED_PROMPT_FIELDS & prompt_fields.keys():
                if not _nonempty(prompt_fields.get(field)):
                    errors.append(f"{prefix}.planned.prompt_fields.{field} must be non-empty")

        missing_observed = sorted(REQUIRED_OBSERVED_FIELDS - observed.keys())
        if missing_observed:
            errors.append(
                f"{prefix}.observed missing fields: {', '.join(missing_observed)}"
            )
            continue

        if str(job.get("role")) != str(observed.get("role")):
            errors.append(f"{prefix} role does not match observed.role")
        if observed.get("status") != "pass" or job.get("status") != "pass":
            errors.append(f"{prefix} is not marked pass after observed QA")
        if observed.get("unplanned_text") not in ([], "NONE", None):
            errors.append(f"{prefix} contains unplanned observed text")

        component_count = observed.get("component_count")
        if not isinstance(component_count, int) or component_count < 0:
            errors.append(f"{prefix}.observed.component_count must be >= 0 integer")
            component_count = -1

        planned_component = str(planned.get("component", "")).upper()
        role = str(job.get("role", ""))
        if planned_component == "NONE" and component_count != 0:
            errors.append(f"{prefix} planned NONE but observed components are present")
        if role in HERO_ROLES and component_count != 0:
            errors.append(f"{prefix} hero/main image must have zero observed components")

        allowed_text = planned.get("allowed_text_exact")
        if not _nonempty(allowed_text):
            errors.append(f"{prefix}.planned.allowed_text_exact must be recorded")

        if role in FUNCTION_ROLES:
            function_tuple = observed.get("function_tuple")
            if not isinstance(function_tuple, dict):
                errors.append(f"{prefix}.observed.function_tuple must be an object")
            else:
                visible = function_tuple.get("visible", [])
                required = {"action", "contact_or_placement"}
                if not isinstance(visible, list) or len(set(visible)) < 3:
                    errors.append(f"{prefix} functional tuple has fewer than 3 visible parts")
                if not required.issubset(set(visible) if isinstance(visible, list) else set()):
                    errors.append(f"{prefix} functional tuple lacks action/contact evidence")
                if function_tuple.get("text_binding") != "pass":
                    errors.append(f"{prefix} functional text binding is not pass")

        if role in DIMENSION_ROLES:
            mappings = observed.get("dimension_mapping")
            if not isinstance(mappings, list) or not mappings:
                errors.append(f"{prefix}.observed.dimension_mapping must be a non-empty list")
            elif any(not isinstance(item, dict) or item.get("status") != "pass" for item in mappings):
                errors.append(f"{prefix} has a failed dimension semantic mapping")

        if not _nonempty(planned.get("fingerprint")):
            errors.append(f"{prefix}.planned.fingerprint must be recorded")
        if not _nonempty(observed.get("fingerprint")):
            errors.append(f"{prefix}.observed.fingerprint must be recorded")

    if data.get("planned_fingerprint_status") != "pass":
        errors.append("planned_fingerprint_status must be pass")
    if data.get("observed_fingerprint_status") != "pass":
        errors.append("observed_fingerprint_status must be pass")
    if data.get("contact_sheet_reviewed") is not True:
        errors.append("contact_sheet_reviewed must be true")
    return errors


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        image_path = Path(tmp) / "sku01_02_marketing_hero.png"
        image_path.touch()
        job = {
            "job_id": "sku01-02-a1",
            "sku": "sku01",
            "slot": 2,
            "role": "marketing_hero",
            "prompt_hash": "abc123",
            "expected_filename": image_path.name,
            "returned_path": str(image_path),
            "final_path": str(image_path),
            "status": "pass",
            "planned": {
                "component": "NONE",
                "allowed_text_exact": ["MODULAR ORGANIZER"],
                "fingerprint": "A|left|wide|scene",
                "prompt_fields": {
                    "FRAMEWORK_ID": "H01",
                    "P_REGION": "left 55%",
                    "T_REGION": "right 45%",
                    "E_REGION": "MERGED_WITH_P",
                    "ALIGNMENT_AXIS": "left",
                    "READING_PATH": "P → E → T",
                    "CAMERA": "eye-level wide",
                    "TEXT_ROLES": ["MODULAR ORGANIZER"],
                    "ALLOWED_TEXT_EXACT": ["MODULAR ORGANIZER"],
                    "DISCLOSURE": "NONE",
                    "EXCEPTION_CODE": "NONE",
                    "EVIDENCE_BINDING": "headline → product",
                    "COMPONENT": "NONE",
                    "FONT_HIERARCHY": "hero 144 px",
                    "COLOR_RATIO": "70/20/10",
                    "NEGATIVE_CONSTRAINTS": "no cards",
                },
            },
            "observed": {
                "role": "marketing_hero",
                "framework_topology": "P-left T-right E-merged",
                "p_t_e_relationship": "asymmetric",
                "alignment_axis": "left",
                "camera": "eye-level wide",
                "text_exact": ["MODULAR ORGANIZER"],
                "unplanned_text": [],
                "component_count": 0,
                "component_types": [],
                "evidence_binding": "pass",
                "fingerprint": "A|left|wide|scene",
                "status": "pass",
            },
        }
        manifest = {
            "jobs": [job],
            "planned_fingerprint_status": "pass",
            "observed_fingerprint_status": "pass",
            "contact_sheet_reviewed": True,
        }
        if validate_manifest(manifest, Path(tmp)):
            print("self-test failed: valid fixture was rejected", file=sys.stderr)
            return 1

        broken = json.loads(json.dumps(manifest))
        broken["jobs"][0]["observed"]["component_count"] = 1
        if not validate_manifest(broken, Path(tmp)):
            print("self-test failed: invalid fixture was accepted", file=sys.stderr)
            return 1

    print("self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", nargs="?", help="path to execution manifest JSON")
    parser.add_argument("--no-file-check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.manifest:
        parser.error("manifest is required unless --self-test is used")

    manifest_path = Path(args.manifest).resolve()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read manifest: {exc}", file=sys.stderr)
        return 2

    errors = validate_manifest(data, manifest_path.parent, not args.no_file_check)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("execution manifest passed mechanical validation; visual QA is still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
