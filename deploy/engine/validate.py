#!/usr/bin/env python3
"""
Azure Container Apps Platform — Manifest & Schema Validator
Validates declarative app.yaml contracts and container readiness offline
without requiring active Azure cloud credentials.
"""

import sys
import argparse
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[ERROR] PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


VALID_CATEGORIES = {"Engineering", "Operations", "Product", "Security", "Analytics", "Utilities", "Management"}
VALID_AUTH_PROVIDERS = {"entra-id", "none", "oauth2"}


def validate_app_directory(app_dir: Path) -> list:
    """Validates an application directory and its app.yaml specification."""
    errors = []
    
    if not app_dir.is_dir():
        return [f"Directory does not exist: {app_dir}"]

    manifest_path = app_dir / "app.yaml"
    if not manifest_path.exists():
        return [f"Missing required manifest 'app.yaml' in {app_dir}"]

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
    except Exception as e:
        return [f"Failed to parse YAML in {manifest_path}: {e}"]

    if not isinstance(manifest, dict):
        return [f"Manifest in {manifest_path} must be a YAML dictionary"]

    # 1. App Metadata Validation
    app_meta = manifest.get("app")
    if not app_meta or not isinstance(app_meta, dict):
        errors.append("Missing required top-level section: 'app'")
    else:
        name = app_meta.get("name")
        if not name:
            errors.append("Field 'app.name' is required")
        elif not name.replace("-", "").isalnum() or not name.islower():
            errors.append(f"Invalid 'app.name' '{name}': must be lowercase alphanumeric with hyphens")

        if not app_meta.get("title"):
            errors.append("Field 'app.title' is required")
        
        category = app_meta.get("category", "Operations")
        if category not in VALID_CATEGORIES:
            errors.append(f"Invalid 'app.category' '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}")

    # 2. Routing Validation
    routing = manifest.get("routing", {})
    if not isinstance(routing, dict):
        errors.append("Section 'routing' must be a dictionary")
    else:
        target_port = routing.get("targetPort", 80)
        if not isinstance(target_port, int) or target_port < 1 or target_port > 65535:
            errors.append(f"Invalid 'routing.targetPort': {target_port}. Must be an integer between 1 and 65535")
        
        subdomain = routing.get("subdomain")
        custom_domain = routing.get("customDomain")
        if not subdomain and not custom_domain:
            errors.append("Either 'routing.subdomain' or 'routing.customDomain' must be defined")

    # 3. Resources Validation
    resources = manifest.get("resources", {})
    if resources:
        cpu = resources.get("cpu", 0.25)
        if cpu not in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 4.0]:
            errors.append(f"Invalid 'resources.cpu' {cpu}. Valid ACA CPU values: 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 4.0")
        
        min_rep = resources.get("minReplicas", 0)
        max_rep = resources.get("maxReplicas", 1)
        if min_rep < 0 or max_rep < 1 or min_rep > max_rep:
            errors.append(f"Invalid replica configuration: minReplicas={min_rep}, maxReplicas={max_rep}")

    # 4. Storage Validation
    storage = manifest.get("storage", {})
    if storage and storage.get("enabled"):
        quota = storage.get("quotaGb", 5)
        if not isinstance(quota, int) or quota < 1 or quota > 1000:
            errors.append(f"Invalid 'storage.quotaGb': {quota}. Must be between 1 and 1000 GB")
        mount_path = storage.get("mountPath", "/data")
        if not mount_path.startswith("/"):
            errors.append(f"Invalid 'storage.mountPath': {mount_path}. Must be an absolute path (e.g., /data)")

    # 5. Auth Validation
    auth = manifest.get("auth", {})
    if auth:
        provider = auth.get("provider", "entra-id")
        if provider not in VALID_AUTH_PROVIDERS:
            errors.append(f"Invalid 'auth.provider' '{provider}'. Must be one of: {', '.join(sorted(VALID_AUTH_PROVIDERS))}")
        if provider == "entra-id" and auth.get("enabled", True):
            allowed_groups = auth.get("allowedGroups", [])
            if not isinstance(allowed_groups, list):
                errors.append("'auth.allowedGroups' must be a list of group names")

    # 6. Container Source Validation
    source = manifest.get("source", {})
    source_type = source.get("type", "local")
    if source_type == "local":
        dockerfile = app_dir / source.get("dockerfile", "Dockerfile")
        if not dockerfile.exists():
            errors.append(f"Dockerfile not found at expected path: {dockerfile}")
    elif source_type in ("image", "external-image"):
        if not source.get("image"):
            errors.append("Field 'source.image' is required when source type is 'image'")
    elif source_type == "external-git":
        if not source.get("repository") and not source.get("url"):
            errors.append("Field 'source.url' or 'source.repository' is required for external-git source type")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate ACA micro-app specifications")
    parser.add_argument("--app", help="Path to specific app directory (e.g. apps/team-planner)")
    parser.add_argument("--all", action="store_true", help="Validate all apps in apps/ and templates/")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent.parent

    apps_to_check = []
    if args.app:
        apps_to_check.append(Path(args.app))
    elif args.all or not args.app:
        # Check all apps in apps/ and templates/
        for p in (repo_root / "apps").glob("*/"):
            if p.is_dir() and (p / "app.yaml").exists():
                apps_to_check.append(p)
        for p in (repo_root / "templates").glob("*/"):
            if p.is_dir() and (p / "app.yaml").exists():
                apps_to_check.append(p)

    if not apps_to_check:
        print("[WARN] No micro-app manifests found to validate.")
        sys.exit(0)

    total_errors = 0
    print(f"🔍 Validating {len(apps_to_check)} micro-app specification(s)...\n")

    for app_dir in apps_to_check:
        errors = validate_app_directory(app_dir)
        if errors:
            print(f"❌ FAILED: {app_dir.name}")
            for err in errors:
                print(f"   - {err}")
            total_errors += len(errors)
        else:
            print(f"✅ PASSED: {app_dir.name} (app.yaml contract valid)")

    print("-" * 60)
    if total_errors > 0:
        print(f"💥 Validation failed with {total_errors} error(s).")
        sys.exit(1)
    else:
        print("🎉 All micro-app manifests conform to platform contract specification!")
        sys.exit(0)


if __name__ == "__main__":
    main()
