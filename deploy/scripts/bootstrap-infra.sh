#!/usr/bin/env bash
# ==============================================================================
# Azure Container Apps Platform — Infrastructure Bootstrap Script
# Provisions core platform prerequisites:
#   1. Resource Group
#   2. Azure Log Analytics Workspace (observability sink)
#   3. Azure Container Apps Environment (shared runtime with Envoy ingress)
#   4. Azure Container Registry (ACR) with Admin enabled for build caching
#   5. Azure Storage Account (standard LRS for persistent Azure Files shares)
#   6. Azure Key Vault (central secret store)
# ==============================================================================

set -euo pipefail

# Configuration Defaults (override via environment variables)
LOCATION="${AZURE_REGION:-eastus}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-platform-apps}"
ENVIRONMENT_NAME="${AZURE_CONTAINER_APP_ENV:-cae-platform-apps}"
ACR_NAME="${AZURE_ACR_NAME:-crplatformapps$RANDOM}"
STORAGE_ACCOUNT="${AZURE_STORAGE_ACCOUNT:-stplatformdata$RANDOM}"
LOG_ANALYTICS="${AZURE_LOG_ANALYTICS:-law-platform-apps}"
KEYVAULT_NAME="${AZURE_KEYVAULT_NAME:-kv-platform-$RANDOM}"

echo "=============================================================================="
echo "🚀 Bootstrapping Azure Container Apps Enterprise Platform Foundation"
echo "   Location:        ${LOCATION}"
echo "   Resource Group:  ${RESOURCE_GROUP}"
echo "   ACA Environment: ${ENVIRONMENT_NAME}"
echo "   ACR Registry:    ${ACR_NAME}"
echo "   Storage Account: ${STORAGE_ACCOUNT}"
echo "=============================================================================="

# 1. Register required Azure resource providers
echo "📦 Ensuring Azure Resource Providers are registered..."
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait
az provider register --namespace Microsoft.ContainerRegistry --wait

# 2. Resource Group
echo "🏗️  Creating Resource Group: ${RESOURCE_GROUP}..."
az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" --output table

# 3. Log Analytics Workspace
echo "📊 Creating Log Analytics Workspace: ${LOG_ANALYTICS}..."
az monitor log-analytics workspace create \
    --resource-group "${RESOURCE_GROUP}" \
    --workspace-name "${LOG_ANALYTICS}" \
    --location "${LOCATION}" \
    --output table

LOG_ANALYTICS_CUSTOMER_ID=$(az monitor log-analytics workspace show \
    --resource-group "${RESOURCE_GROUP}" \
    --workspace-name "${LOG_ANALYTICS}" \
    --query customerId -o tsv)

LOG_ANALYTICS_KEY=$(az monitor log-analytics workspace get-shared-keys \
    --resource-group "${RESOURCE_GROUP}" \
    --workspace-name "${LOG_ANALYTICS}" \
    --query primarySharedKey -o tsv)

# 4. Azure Container Apps Environment
echo "☁️  Creating Azure Container Apps Environment: ${ENVIRONMENT_NAME}..."
az containerapp env create \
    --name "${ENVIRONMENT_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --logs-workspace-id "${LOG_ANALYTICS_CUSTOMER_ID}" \
    --logs-workspace-key "${LOG_ANALYTICS_KEY}" \
    --output table

# 5. Azure Container Registry
echo "🐳 Creating Azure Container Registry: ${ACR_NAME}..."
az acr create \
    --name "${ACR_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --sku Basic \
    --admin-enabled true \
    --location "${LOCATION}" \
    --output table

# 6. Azure Storage Account (for persistent Azure Files shares)
echo "💾 Creating Storage Account: ${STORAGE_ACCOUNT}..."
az storage account create \
    --name "${STORAGE_ACCOUNT}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --output table

# 7. Azure Key Vault
echo "🔐 Creating Key Vault: ${KEYVAULT_NAME}..."
az keyvault create \
    --name "${KEYVAULT_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --enable-rbac-authorization false \
    --output table

# Summary
ACA_DEFAULT_DOMAIN=$(az containerapp env show -n "${ENVIRONMENT_NAME}" -g "${RESOURCE_GROUP}" --query properties.defaultDomain -o tsv)
ACA_STATIC_IP=$(az containerapp env show -n "${ENVIRONMENT_NAME}" -g "${RESOURCE_GROUP}" --query properties.staticIp -o tsv)

echo ""
echo "=============================================================================="
echo "✅ Bootstrap Complete! Platform Details:"
echo "   Default Domain: https://${ACA_DEFAULT_DOMAIN}"
echo "   Static Outbound IP: ${ACA_STATIC_IP}"
echo "   Save these in deploy/config/platform.env to begin deploying apps!"
echo "=============================================================================="
