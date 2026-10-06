#!/usr/bin/env bash
# ==============================================================================
# Azure Container Apps Platform — GitHub Actions Workload Identity Setup
# Configures zero-secret OIDC federated credentials between GitHub Actions
# and Microsoft Entra ID (Azure AD), eliminating long-lived credentials.
# ==============================================================================

set -euo pipefail

APP_NAME="${1:-github-actions-aca-deployer}"
GITHUB_REPO="${2:-ssaurabh61/azure-container-apps-platform}"
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-platform-apps}"

echo "=============================================================================="
echo "🛡️  Configuring Azure OIDC Workload Identity for GitHub Actions"
echo "   GitHub Repo:    ${GITHUB_REPO}"
echo "   Entra App Name: ${APP_NAME}"
echo "   Subscription:   ${SUBSCRIPTION_ID}"
echo "   Tenant:         ${TENANT_ID}"
echo "=============================================================================="

# 1. Create Entra ID App Registration
echo "1️⃣  Creating App Registration..."
APP_ID=$(az ad app create --display-name "${APP_NAME}" --query appId -o tsv)

# 2. Create Service Principal
echo "2️⃣  Creating Service Principal..."
SP_ID=$(az ad sp create --id "${APP_ID}" --query id -o tsv)

# 3. Assign Contributor Role on Resource Group
echo "3️⃣  Assigning Contributor role to RG: ${RESOURCE_GROUP}..."
az role assignment create \
    --role "Contributor" \
    --assignee-object-id "${SP_ID}" \
    --assignee-principal-type "ServicePrincipal" \
    --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}"

# 4. Assign AcrPush Role on Subscription/Registry
echo "4️⃣  Assigning AcrPush role..."
az role assignment create \
    --role "AcrPush" \
    --assignee-object-id "${SP_ID}" \
    --assignee-principal-type "ServicePrincipal" \
    --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}"

# 5. Create Federated Identity Credential for main branch
echo "5️⃣  Creating Federated Credential for branch 'main'..."
az ad app federated-credential create \
    --id "${APP_ID}" \
    --parameters '{
        "name": "github-main-branch",
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:'"${GITHUB_REPO}"':ref:refs/heads/main",
        "description": "Deploy to Azure Container Apps from main branch",
        "audiences": ["api://AzureADTokenExchange"]
    }'

# 6. Create Federated Identity Credential for pull requests
echo "6️⃣  Creating Federated Credential for pull requests..."
az ad app federated-credential create \
    --id "${APP_ID}" \
    --parameters '{
        "name": "github-pr-validation",
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:'"${GITHUB_REPO}"':pull_request",
        "description": "PR validation for Azure Container Apps",
        "audiences": ["api://AzureADTokenExchange"]
    }'

echo ""
echo "=============================================================================="
echo "✅ Workload Identity Configured Successfully!"
echo "   Add these secrets in GitHub Settings -> Secrets and variables -> Actions:"
echo "   AZURE_CLIENT_ID:       ${APP_ID}"
echo "   AZURE_TENANT_ID:       ${TENANT_ID}"
echo "   AZURE_SUBSCRIPTION_ID: ${SUBSCRIPTION_ID}"
echo "=============================================================================="
