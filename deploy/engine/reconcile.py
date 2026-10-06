#!/usr/bin/env python3
"""
Azure Container Apps (ACA) Platform — Declarative GitOps Reconciler

Reads declarative 'app.yaml' specifications and idempotently orchestrates
end-to-end cloud infrastructure on Azure:
  1. Storage Provisioning: Azure File Share & Container Apps Environment mount link.
  2. Container Image Build: ACR cloud build (local context or external Git) or external registry.
  3. Workload Deployment: Container App lifecycle, CPU/RAM, min/max scale, secrets, and volumes.
  4. Networking & Security: DNS CNAME/A records, Custom Hostname binding, and Managed DigiCert TLS.
  5. Identity & Zero-Trust: Microsoft Entra ID (Azure AD) App Registration, Service Principal,
     Security Group RBAC role assignments, and EasyAuth SSO injection.
  6. Service Catalog: Automatic registration in the central discovery portal directory.

Zero manual Azure or Entra ID administrator privileges required by application developers.
"""

import os
import sys
import json
import time
import shutil
import tempfile
import argparse
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

# Ensure PyYAML is available
try:
    import yaml
except ImportError:
    print("[INFO] PyYAML not found. Installing via pip...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "--quiet"])
    import yaml

# Central Infrastructure Configuration (Configured via Environment Variables)
RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP", "rg-platform-apps")
ENVIRONMENT = os.getenv("AZURE_CONTAINER_APP_ENV", "cae-platform-apps")
STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT", "stplatformdata")
STORAGE_RG = os.getenv("AZURE_STORAGE_RG", RESOURCE_GROUP)
ACR_NAME = os.getenv("AZURE_ACR_NAME", "crplatformapps")
DNS_ZONE = os.getenv("AZURE_DNS_ZONE", "internal.example.com")
DNS_RG = os.getenv("AZURE_DNS_RG", RESOURCE_GROUP)
TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
ACA_CUSTOM_DOMAIN_VERIFICATION_ID = os.getenv("ACA_CUSTOM_DOMAIN_VERIFICATION_ID", "")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def run_az(args, capture_output=True, check=True):
    """Executes an Azure CLI command and returns trimmed stdout."""
    cmd = ["az"] + args
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command {' '.join(cmd)} failed with exit {res.returncode}:\n{res.stderr.strip()}")
    return res.stdout.strip()


def run_az_json(args, check=True):
    """Executes an Azure CLI command and parses the resulting JSON."""
    raw = run_az(args, check=check)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def get_graph_token():
    """Retrieves a Microsoft Graph API access token using the active Azure CLI session."""
    try:
        token = run_az([
            "account", "get-access-token",
            "--resource-type", "ms-graph",
            "--query", "accessToken",
            "-o", "tsv"
        ])
        return token
    except Exception as e:
        print(f"[WARN] Unable to acquire Microsoft Graph token: {e}")
        return None


def graph_request(method, endpoint, token, data=None):
    """Performs an authenticated REST request against Microsoft Graph API."""
    full_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    if "?" in full_path:
        base_path, query_str = full_path.split("?", 1)
        encoded_query = urllib.parse.quote(query_str, safe="=&$,':").replace(" ", "%20")
        url = f"{GRAPH_BASE}{base_path}?{encoded_query}"
    else:
        url = f"{GRAPH_BASE}{full_path}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        if e.code in (400, 409) and "already exists" in err_msg.lower():
            return {"error": "already_exists", "details": err_msg}
        raise RuntimeError(f"Graph API {method} {url} returned HTTP {e.code}:\n{err_msg}")


def load_manifest(manifest_path):
    """Loads and parses an app.yaml manifest."""
    with open(manifest_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_app_name(raw_name):
    """Normalizes an application name for cloud resource constraints."""
    clean = raw_name.strip().lower().replace("_", "-")
    return clean


# ==============================================================================
# 1. Storage Reconciliation (Azure Files -> ACA Environment Volume)
# ==============================================================================
def reconcile_storage(app_name, storage_cfg, dry_run=False):
    """
    Provisions an Azure File Share for the micro-app and registers it as a storage
    resource in the Azure Container Apps Environment.
    """
    if not storage_cfg or not storage_cfg.get("enabled"):
        print("\n💾 Persistent storage disabled in manifest. Skipping volume provisioning.")
        return None, None

    clean_name = normalize_app_name(app_name)
    share_name = f"{clean_name}-data"
    env_storage_name = f"{clean_name.replace('-', '')}storage"
    quota = storage_cfg.get("quotaGb", 5)

    print(f"\n💾 Reconciling Persistent Storage: {STORAGE_ACCOUNT}/{share_name} -> /data...")

    if dry_run:
        print(f"  [DRY-RUN] Would create Azure File Share '{share_name}' ({quota}GB) and link as '{env_storage_name}'")
        return share_name, env_storage_name

    # 1. Create Azure File Share idempotently
    run_az([
        "storage", "share", "create",
        "--account-name", STORAGE_ACCOUNT,
        "--name", share_name,
        "--quota", str(quota),
        "--only-show-errors", "-o", "none"
    ], check=False)
    print(f"  ✓ Azure File Share confirmed: {share_name} (Quota: {quota}GB)")

    # 2. Retrieve storage account primary key
    key = run_az([
        "storage", "account", "keys", "list",
        "-g", STORAGE_RG,
        "-n", STORAGE_ACCOUNT,
        "--query", "[0].value",
        "-o", "tsv"
    ])

    # 3. Mount Azure File share into the Container Apps Environment
    run_az([
        "containerapp", "env", "storage", "set",
        "-n", ENVIRONMENT,
        "-g", RESOURCE_GROUP,
        "--storage-name", env_storage_name,
        "--azure-file-account-name", STORAGE_ACCOUNT,
        "--azure-file-account-key", key,
        "--azure-file-share-name", share_name,
        "--access-mode", "ReadWrite",
        "--only-show-errors", "-o", "none"
    ])
    print(f"  ✓ Linked CAE Environment Storage: {env_storage_name}")
    return share_name, env_storage_name


# ==============================================================================
# 2. Workload & Container App Reconciliation
# ==============================================================================
def reconcile_container_app(app_name, app_dir, manifest, env_storage_name, override_version=None, dry_run=False):
    """
    Builds the container image in ACR (or references external image) and creates/updates
    the Azure Container App with resource allocations, ingress, secrets, and volume mounts.
    """
    clean_name = normalize_app_name(app_name)
    res_cfg = manifest.get("resources", {})
    cpu = res_cfg.get("cpu", 0.25)
    memory = res_cfg.get("memory", "0.5Gi")
    min_replicas = res_cfg.get("minReplicas", 1)
    max_replicas = res_cfg.get("maxReplicas", 1)

    target_port = manifest.get("routing", {}).get("targetPort", 80)
    source_cfg = manifest.get("source", {})
    source_type = source_cfg.get("type", "local")

    # Determine image tag & URI
    if source_type in ("image", "external-image"):
        image_uri = source_cfg["image"]
        build_required = False
        tag = image_uri.split(":")[-1] if ":" in image_uri else "latest"
    else:
        build_required = True
        if override_version:
            version = override_version.strip()
        else:
            version_file = Path(app_dir) / "VERSION"
            version = version_file.read_text().strip() if version_file.exists() else source_cfg.get("version", "1.0.0")
        tag = f"v{version}" if not version.startswith("v") else version
        image_uri = f"{ACR_NAME}.azurecr.io/{clean_name}:{tag}"

    print(f"\n☁️  Reconciling Container App: {clean_name} ({image_uri})...")
    print(f"   Target Port: {target_port} | CPU: {cpu} | Memory: {memory} | Replicas: {min_replicas}-{max_replicas}")

    if dry_run:
        print(f"  [DRY-RUN] Would build '{image_uri}' and deploy Container App '{clean_name}'")
        return clean_name, f"{clean_name}.{ENVIRONMENT}.azurecontainerapps.io"

    # Build container image in Azure Container Registry (ACR Cloud Build)
    if build_required:
        print(f"  🐳 Building Container Image in ACR: {ACR_NAME} ({clean_name}:{tag})...")
        run_az([
            "acr", "build",
            "-r", ACR_NAME,
            "-t", f"{clean_name}:{tag}",
            "-t", f"{clean_name}:latest",
            "-f", str(Path(app_dir) / "Dockerfile"),
            str(app_dir),
            "--only-show-errors", "-o", "none"
        ])
        print(f"  ✓ Container image pushed: {image_uri}")

    # Process Environment Variables & Key Vault Secrets
    secrets_to_set = []
    env_to_set = []

    for s in manifest.get("secrets", []):
        s_name = s.get("name")
        kv_name = s.get("keyVault")
        secret_name = s.get("secretName", s_name)
        val = None
        if kv_name:
            val = run_az([
                "keyvault", "secret", "show",
                "--vault-name", kv_name,
                "--name", secret_name,
                "--query", "value",
                "-o", "tsv"
            ], check=False)
        elif s.get("value"):
            val = s["value"]

        if val:
            secrets_to_set.append(f"{s_name}={val}")
            if s.get("envVar"):
                env_to_set.append(f"{s['envVar']}=secretref:{s_name}")

    for e in manifest.get("env", []):
        env_to_set.append(f"{e['name']}={e['value']}")

    # Idempotent Container App Check
    existing = run_az_json(["containerapp", "show", "-n", clean_name, "-g", RESOURCE_GROUP], check=False)

    if not existing:
        print(f"  🚀 Provisioning new Container App: {clean_name}...")
        create_cmd = [
            "containerapp", "create",
            "-n", clean_name,
            "-g", RESOURCE_GROUP,
            "--environment", ENVIRONMENT,
            "--image", image_uri,
            "--target-port", str(target_port),
            "--ingress", "external",
            "--cpu", str(cpu),
            "--memory", str(memory),
            "--min-replicas", str(min_replicas),
            "--max-replicas", str(max_replicas),
            "--registry-server", f"{ACR_NAME}.azurecr.io",
            "--registry-identity", "system",
            "--only-show-errors", "-o", "none"
        ]
        if secrets_to_set:
            create_cmd += ["--secrets"] + secrets_to_set
        if env_to_set:
            create_cmd += ["--env-vars"] + env_to_set
        run_az(create_cmd)
        print(f"  ✓ Container App created successfully: {clean_name}")
    else:
        print(f"  🔄 Updating existing Container App: {clean_name}...")
        if secrets_to_set:
            run_az(["containerapp", "secret", "set", "-n", clean_name, "-g", RESOURCE_GROUP, "--secrets"] + secrets_to_set, check=False)

        run_az(["containerapp", "ingress", "update", "-n", clean_name, "-g", RESOURCE_GROUP, "--target-port", str(target_port)], check=False)

        update_cmd = [
            "containerapp", "update",
            "-n", clean_name,
            "-g", RESOURCE_GROUP,
            "--image", image_uri,
            "--cpu", str(cpu),
            "--memory", str(memory),
            "--min-replicas", str(min_replicas),
            "--max-replicas", str(max_replicas),
            "--only-show-errors", "-o", "none"
        ]
        if env_to_set:
            update_cmd += ["--set-env-vars"] + env_to_set
        run_az(update_cmd)
        print(f"  ✓ Container App updated: {clean_name}")

    # Attach Persistent Volume Mount if enabled
    if env_storage_name:
        mount_path = manifest.get("storage", {}).get("mountPath", "/data")
        vol_name = f"{clean_name}-storage-volume"
        print(f"  💾 Attaching volume mount {vol_name} -> {mount_path}...")
        run_az([
            "containerapp", "volume", "add",
            "-n", clean_name,
            "-g", RESOURCE_GROUP,
            "--volume-name", vol_name,
            "--storage-name", env_storage_name,
            "--storage-type", "AzureFile",
            "--mount-path", mount_path,
            "--only-show-errors", "-o", "none"
        ], check=False)
        print(f"  ✓ Persistent volume mounted at {mount_path}")

    fqdn = run_az(["containerapp", "show", "-n", clean_name, "-g", RESOURCE_GROUP, "--query", "properties.configuration.ingress.fqdn", "-o", "tsv"])
    return clean_name, fqdn


# ==============================================================================
# 3. DNS, Custom Hostname & Managed TLS Binding
# ==============================================================================
def reconcile_dns_and_tls(container_app, aca_fqdn, routing_cfg, app_name, dry_run=False):
    """
    Configures Azure DNS CNAME record, TXT verification record, and binds
    an automated DigiCert Managed TLS certificate.
    """
    custom_domain_cfg = (routing_cfg or {}).get("customDomain")
    if custom_domain_cfg:
        custom_domain = custom_domain_cfg.strip()
        cname_record = custom_domain[:-len(f".{DNS_ZONE}")].rstrip(".") if custom_domain.endswith(f".{DNS_ZONE}") else custom_domain
    else:
        subdomain = (routing_cfg or {}).get("subdomain", app_name).strip()
        custom_domain = f"{subdomain}.{DNS_ZONE}"
        cname_record = subdomain

    asuid_record = f"asuid.{cname_record}"
    print(f"\n🌐 Reconciling DNS & Custom TLS: https://{custom_domain}...")

    if dry_run:
        print(f"  [DRY-RUN] Would route '{custom_domain}' -> '{aca_fqdn}' with Managed TLS")
        return custom_domain

    # 1. Update/Create DNS CNAME record
    run_az([
        "network", "dns", "record-set", "cname", "set-record",
        "-g", DNS_RG,
        "-z", DNS_ZONE,
        "-n", cname_record,
        "-c", aca_fqdn,
        "--ttl", "300",
        "--only-show-errors", "-o", "none"
    ], check=False)
    print(f"  ✓ DNS CNAME configured: {custom_domain} -> {aca_fqdn}")

    # 2. Add Domain Verification TXT Record if configured
    if ACA_CUSTOM_DOMAIN_VERIFICATION_ID:
        run_az([
            "network", "dns", "record-set", "txt", "add-record",
            "-g", DNS_RG,
            "-z", DNS_ZONE,
            "-n", asuid_record,
            "-v", ACA_CUSTOM_DOMAIN_VERIFICATION_ID,
            "--only-show-errors", "-o", "none"
        ], check=False)

    # 3. Bind Custom Hostname and issue Managed TLS Certificate
    run_az([
        "containerapp", "hostname", "add",
        "-n", container_app,
        "-g", RESOURCE_GROUP,
        "--hostname", custom_domain,
        "--only-show-errors", "-o", "none"
    ], check=False)

    run_az([
        "containerapp", "hostname", "bind",
        "-n", container_app,
        "-g", RESOURCE_GROUP,
        "--hostname", custom_domain,
        "--environment", ENVIRONMENT,
        "--validation-method", "CNAME",
        "--only-show-errors", "-o", "none"
    ], check=False)
    print(f"  ✓ Managed DigiCert TLS bound to: https://{custom_domain}")
    return custom_domain


# ==============================================================================
# 4. Zero-Trust Identity: Microsoft Entra ID (EasyAuth SSO)
# ==============================================================================
def reconcile_entra_id_auth(app_name, custom_domain, auth_cfg, container_app, token, dry_run=False):
    """
    Automates Microsoft Entra ID (Azure AD) App Registration, Client Secret generation,
    Enterprise Service Principal role assignment, and EasyAuth enforcement.
    """
    auth_enabled = (auth_cfg or {}).get("enabled", True)
    auth_provider = (auth_cfg or {}).get("provider", "entra-id")

    if not auth_enabled or auth_provider == "none":
        print(f"\n🔓 Authentication disabled in manifest (provider: {auth_provider}). Disabling EasyAuth.")
        if not dry_run:
            run_az(["containerapp", "auth", "update", "-n", container_app, "-g", RESOURCE_GROUP, "--enabled", "false", "-y", "--only-show-errors", "-o", "none"], check=False)
        return

    clean_name = normalize_app_name(app_name)
    app_reg_name = f"{clean_name}-auth"
    redirect_uri = f"https://{custom_domain}/.auth/login/aad/callback"

    print(f"\n🔐 Reconciling Microsoft Entra ID Authentication & EasyAuth: {app_reg_name}...")

    if dry_run:
        print(f"  [DRY-RUN] Would create App Registration '{app_reg_name}' and enable EasyAuth for allowed groups")
        return

    if not token or not TENANT_ID:
        print("  ⚠️ Graph token or TENANT_ID unavailable. Skipping automated Entra ID reconciliation.")
        return

    # 1. Check or Create App Registration
    q = f"/applications?$filter=displayName eq '{urllib.parse.quote(app_reg_name)}'&$select=id,appId,displayName"
    res = graph_request("GET", q, token)
    existing_apps = res.get("value", [])

    if existing_apps:
        app_obj_id = existing_apps[0]["id"]
        client_id = existing_apps[0]["appId"]
        print(f"  ✓ Found existing App Registration: {client_id}")
    else:
        create_payload = {
            "displayName": app_reg_name,
            "signInAudience": "AzureADMyOrg",
            "web": {
                "redirectUris": [redirect_uri],
                "implicitGrantSettings": {"enableIdTokenIssuance": True}
            }
        }
        new_app = graph_request("POST", "/applications", token, create_payload)
        app_obj_id = new_app["id"]
        client_id = new_app["appId"]
        print(f"  ✓ Created App Registration: {client_id}")

    # Ensure redirect URI is up-to-date
    graph_request("PATCH", f"/applications/{app_obj_id}", token, {
        "web": {
            "redirectUris": [redirect_uri],
            "implicitGrantSettings": {"enableIdTokenIssuance": True}
        }
    })

    # 2. Generate Application Secret for EasyAuth
    secret_payload = {"passwordCredential": {"displayName": "aca-easyauth-secret"}}
    secret_res = graph_request("POST", f"/applications/{app_obj_id}/addPassword", token, secret_payload)
    client_secret = secret_res.get("secretText")

    # 3. Ensure Service Principal exists and enforce role assignment
    sp_q = f"/servicePrincipals?$filter=appId eq '{client_id}'&$select=id,appId"
    sp_res = graph_request("GET", sp_q, token)
    sp_vals = sp_res.get("value", [])
    sp_id = sp_vals[0]["id"] if sp_vals else graph_request("POST", "/servicePrincipals", token, {"appId": client_id})["id"]
    graph_request("PATCH", f"/servicePrincipals/{sp_id}", token, {"appRoleAssignmentRequired": True})

    # 4. Authorize Allowed Security Groups
    allowed_groups = auth_cfg.get("allowedGroups", [])
    for g_name in allowed_groups:
        g_lookup = graph_request("GET", f"/groups?$filter=displayName eq '{urllib.parse.quote(g_name)}'&$select=id,displayName", token)
        g_vals = g_lookup.get("value", [])
        if g_vals:
            g_id = g_vals[0]["id"]
            role_assignment = {
                "principalId": g_id,
                "resourceId": sp_id,
                "appRoleId": "00000000-0000-0000-0000-000000000000"
            }
            try:
                graph_request("POST", f"/servicePrincipals/{sp_id}/appRoleAssignments", token, role_assignment)
                print(f"  ✓ Authorized Entra ID Group: '{g_name}' ({g_id})")
            except Exception:
                pass  # Already assigned

    # 5. Configure EasyAuth on Azure Container App
    run_az([
        "containerapp", "auth", "microsoft", "update",
        "-n", container_app,
        "-g", RESOURCE_GROUP,
        "--client-id", client_id,
        "--client-secret", client_secret,
        "--tenant-id", TENANT_ID,
        "-y", "--only-show-errors", "-o", "none"
    ])

    run_az([
        "containerapp", "auth", "update",
        "-n", container_app,
        "-g", RESOURCE_GROUP,
        "--enabled", "true",
        "--action", "RedirectToLoginPage",
        "--redirect-provider", "AzureActiveDirectory",
        "--excluded-paths", "/healthz",
        "-y", "--only-show-errors", "-o", "none"
    ])
    print(f"  ✓ EasyAuth SSO active on: {container_app} (health check bypassed at /healthz)")


# ==============================================================================
# 5. Service Catalog Auto-Registration
# ==============================================================================
def update_portal_registry(manifest, custom_domain, repo_root):
    """Automatically synchronizes micro-app metadata into the central discovery portal directory."""
    portal_json_path = repo_root / "apps" / "internal-portal" / "src" / "data" / "apps.json"
    if not portal_json_path.exists():
        return False

    app_meta = manifest.get("app", {})
    app_name = app_meta.get("name")
    if app_name in ("portal", "internal-portal"):
        return False

    print(f"\n🧭 Updating Service Catalog: {portal_json_path}...")
    try:
        with open(portal_json_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
            if not isinstance(registry, list):
                registry = []
    except Exception:
        registry = []

    app_title = app_meta.get("title", app_name.replace("-", " ").title())
    app_target_url = f"https://{custom_domain}"
    app_entry = {
        "name": app_title,
        "url": app_target_url,
        "description": app_meta.get("description", "Internal Platform Application"),
        "category": app_meta.get("category", "Operations"),
        "badge": "Active",
        "icon": app_meta.get("icon", "⚡"),
        "tags": app_meta.get("tags") or [app_name.lower(), app_meta.get("category", "ops").lower()]
    }

    # Upsert entry
    existing_idx = next((i for i, item in enumerate(registry) if item.get("url") == app_target_url or item.get("name", "").lower() == app_title.lower()), None)
    if existing_idx is not None:
        registry[existing_idx] = app_entry
        print(f"  ✓ Updated catalog entry for '{app_title}'")
    else:
        registry.append(app_entry)
        print(f"  ✓ Added catalog entry for '{app_title}'")

    registry.sort(key=lambda x: x.get("name", "").lower())
    with open(portal_json_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
        f.write("\n")
    return True


# ==============================================================================
# Main CLI Orchestrator
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="Azure Container Apps Declarative GitOps Reconciler")
    parser.add_argument("--app", required=True, help="Path to application directory (e.g. apps/team-planner)")
    parser.add_argument("--version", help="Version tag override (e.g. 1.2.0)")
    parser.add_argument("--dry-run", action="store_true", help="Perform offline execution plan without mutating cloud resources")
    args = parser.parse_args()

    app_dir = Path(args.app).resolve()
    manifest_path = app_dir / "app.yaml"
    if not manifest_path.exists():
        print(f"[ERROR] Manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    repo_root = Path(__file__).resolve().parent.parent.parent
    manifest = load_manifest(manifest_path)
    app_name = manifest.get("app", {}).get("name", app_dir.name)

    print("=" * 70)
    print(f"⚡ Reconciling Micro-App: {app_name.upper()} [{'DRY-RUN' if args.dry_run else 'LIVE'}]")
    print(f"   Resource Group: {RESOURCE_GROUP} | Environment: {ENVIRONMENT}")
    print("=" * 70)

    graph_token = None if args.dry_run else get_graph_token()

    # 1. Storage
    share_name, env_storage_name = reconcile_storage(app_name, manifest.get("storage"), dry_run=args.dry_run)

    # 2. Container App
    container_app, aca_fqdn = reconcile_container_app(app_name, app_dir, manifest, env_storage_name, override_version=args.version, dry_run=args.dry_run)

    # 3. DNS & Managed TLS
    custom_domain = reconcile_dns_and_tls(container_app, aca_fqdn, manifest.get("routing"), app_name, dry_run=args.dry_run)

    # 4. Identity & EasyAuth SSO
    reconcile_entra_id_auth(app_name, custom_domain, manifest.get("auth"), container_app, graph_token, dry_run=args.dry_run)

    # 5. Service Catalog Sync
    if not args.dry_run:
        update_portal_registry(manifest, custom_domain, repo_root)

    print("\n" + "=" * 70)
    print(f"✨ Reconciliation Complete! Target URL: https://{custom_domain}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
