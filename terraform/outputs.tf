output "resource_group_name" {
  description = "The name of the provisioned resource group"
  value       = azurerm_resource_group.platform.name
}

output "container_app_environment_id" {
  description = "The ID of the Azure Container Apps Environment"
  value       = azurerm_container_app_environment.cae.id
}

output "container_app_environment_default_domain" {
  description = "Default DNS suffix for apps deployed in the environment"
  value       = azurerm_container_app_environment.cae.default_domain
}

output "container_app_environment_static_ip" {
  description = "Static egress IP address of the Container Apps Environment"
  value       = azurerm_container_app_environment.cae.static_ip_address
}

output "acr_login_server" {
  description = "Login server endpoint for Azure Container Registry"
  value       = azurerm_container_registry.acr.login_server
}

output "storage_account_name" {
  description = "Name of the storage account used for Azure Files mounts"
  value       = azurerm_storage_account.storage.name
}

output "key_vault_uri" {
  description = "URI of the provisioned Azure Key Vault"
  value       = azurerm_key_vault.kv.vault_uri
}
