variable "location" {
  description = "The Azure region to deploy resources into"
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Name of the central platform resource group"
  type        = string
  default     = "rg-platform-apps"
}

variable "environment_name" {
  description = "Name of the Container Apps Environment"
  type        = string
  default     = "cae-platform-apps"
}

variable "acr_name" {
  description = "Globally unique name for the Azure Container Registry (alphanumeric only)"
  type        = string
  default     = "crplatformapps"
}

variable "storage_account_name" {
  description = "Globally unique name for the Azure Storage Account (lowercase alphanumeric only, max 24 chars)"
  type        = string
  default     = "stplatformdata01"
}

variable "log_analytics_name" {
  description = "Name of the Log Analytics workspace"
  type        = string
  default     = "law-platform-apps"
}

variable "key_vault_name" {
  description = "Globally unique name for Azure Key Vault"
  type        = string
  default     = "kv-platform-apps01"
}

variable "tags" {
  description = "Resource tags applied to all platform components"
  type        = map(string)
  default = {
    Environment = "Production"
    ManagedBy   = "Terraform"
    Platform    = "AzureContainerApps"
  }
}
