# Declarative Application Specification (app.yaml)

This document outlines the standard schema specification for `app.yaml`, the declarative contract consumed by the Azure Container Apps Platform GitOps Reconciler.

---

## 1. Specification Overview

Every micro-app directory inside `apps/` or `templates/` must contain an `app.yaml` file defining its operational contract. Developers declare *what* their application needs; the platform reconciler handles *how* it is provisioned on Azure.

```yaml
version: "1.0"

app:
  name: "string"               # Unique lowercase slug (e.g., leave-planner)
  title: "string"              # Human-readable title
  description: "string"        # Short functional description
  category: "string"           # Classification: Engineering | Operations | Platform | Security | Utilities
  icon: "string"               # Emoji or icon identifier
  tags: [string]               # Searchable keywords

routing:
  subdomain: "string"          # Ingress subdomain (e.g., planner -> planner.internal.example.com)
  customDomain: "string"       # Optional explicit FQDN override
  targetPort: integer          # HTTP listening port inside the container (default: 8080)

resources:
  cpu: number                  # Allocations: 0.25 | 0.5 | 0.75 | 1.0 | 2.0 (default: 0.25)
  memory: "string"             # Allocations: 0.5Gi | 1.0Gi | 2.0Gi (default: 0.5Gi)
  minReplicas: integer         # 0 (scale-to-zero) or >= 1 (default: 1)
  maxReplicas: integer         # Max scale ceiling (default: 2)

storage:
  enabled: boolean             # Mount dedicated Azure File Share (default: false)
  type: "sqlite-azure-file"     # Volume backing type
  mountPath: "string"          # Container mount path (default: /data)
  quotaGb: integer             # Storage share quota in GB (default: 5)

auth:
  provider: "string"           # entra-id | none (default: entra-id)
  enabled: boolean             # Enable EasyAuth SSO enforcement (default: true)
  allowedGroups: [string]      # List of Microsoft Entra ID Security Groups permitted to access

env:
  - name: "string"             # Plaintext environment variable name
    value: "string"            # Environment variable value

secrets:
  - name: "string"             # Secret reference name inside ACA
    keyVault: "string"         # Azure Key Vault name to read from
    secretName: "string"       # Secret name inside Key Vault
    envVar: "string"           # Target environment variable injected into container

source:
  type: "string"               # local | image | external-git (default: local)
  image: "string"              # Required if type is 'image' (e.g., myregistry.azurecr.io/app:v1)
```

---

## 2. Schema Breakdown

### 2.1 `app` (Required)
Defines metadata utilized by the central discovery portal and operational dashboards:
- `name`: Lowercase alphanumeric with hyphens. Used to name cloud resources (`<name>`, `<name>-data`, `<name>-auth`).
- `category`: Must match one of the recognized platform categories: `Engineering`, `Operations`, `Platform`, `Security`, `Management`, `Utilities`, `Analytics`.

### 2.2 `routing` (Required)
Controls Envoy ingress routing, DNS record generation, and TLS termination:
- `subdomain`: Generates the canonical URL: `https://<subdomain>.<DNS_ZONE>`.
- `targetPort`: The container port to which Envoy forwards decrypted traffic. Default: `8080` for web applications, `80` for Nginx proxies.

### 2.3 `resources` (Optional)
Configures compute allocations on the Azure Container Apps Consumption profile:
- Valid CPU & Memory combinations must adhere to Azure Container Apps rules:
  - `0.25 vCPU` with `0.5Gi` memory
  - `0.50 vCPU` with `1.0Gi` memory
  - `1.00 vCPU` with `2.0Gi` memory
  - `2.00 vCPU` with `4.0Gi` memory
- `minReplicas: 0`: Configures the container to scale down to zero replicas during inactivity, reducing compute costs to $0.00 while maintaining ingress availability.

### 2.4 `storage` (Optional)
Provisions persistent storage backed by Azure Files (SMB 3.0):
- Automatically provisions a dedicated Azure File Share (`<name>-data`).
- Links the share into the Container Apps Environment.
- Mounts the share into the container at `mountPath` (default: `/data`).

### 2.5 `auth` (Optional)
Governs Zero-Trust identity enforcement via Microsoft Entra ID EasyAuth:
- `provider: "entra-id"`: Automatically provisions an App Registration and Service Principal via Microsoft Graph API.
- `allowedGroups`: Enforces role assignments on the Enterprise Application. Unauthenticated users or users outside these groups receive an HTTP 403 or are redirected to corporate login.
- `provider: "none"`: Disables EasyAuth for public endpoints or apps handling authentication internally.

---

## 3. Manifest Lifecycle & Reconciliation Stages

```
   [Developer PR]
         │
         ▼
 1. Schema Validation    ───► validate.py checks YAML syntax, categories, and resource limits
         │
         ▼
 2. Dry-Run Planning     ───► reconcile.py --dry-run prints plan without cloud mutation
         │
   [Merge to main]
         │
         ▼
 3. Storage Mount        ───► Provision Azure File Share & register in ACA Environment
         │
         ▼
 4. Container Build      ───► ACR cloud build from local Dockerfile context
         │
         ▼
 5. Workload Deploy      ───► Idempotently create/update Container App with secrets & volumes
         │
         ▼
 6. DNS & Managed TLS    ───► Configure CNAME, TXT verification, and bind DigiCert TLS
         │
         ▼
 7. Identity & SSO       ───► Graph API creates App Reg, assigns groups, activates EasyAuth
         │
         ▼
 8. Catalog Sync         ───► Auto-registers app into central discovery portal (apps.json)
```
