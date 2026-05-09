# =============================================================================
# DEPRECATED — variables for the old LXC-based deployment.
#
# Prod migrated from LXC to a Proxmox VM. The active provisioning lives in
# `deploy/terraform/vidistiller.tf` (clones an Ubuntu 24.04 cloud-init template
# into VM 900). This file is kept only so historical tfvars don't break;
# nothing references it.
# =============================================================================

# -----------------------------------------------------------------------------
# Proxmox Connection Settings
# -----------------------------------------------------------------------------
variable "proxmox_api_url" {
  description = "Proxmox API URL (e.g., https://192.168.1.100:8006/api2/json)"
  type        = string
}

variable "proxmox_api_token_id" {
  description = "Proxmox API token ID (e.g., root@pam!terraform)"
  type        = string
}

variable "proxmox_api_token_secret" {
  description = "Proxmox API token secret"
  type        = string
  sensitive   = true
}

variable "proxmox_tls_insecure" {
  description = "Skip TLS verification (set true for self-signed certs)"
  type        = bool
  default     = true
}

variable "proxmox_node" {
  description = "Proxmox node name to create container on"
  type        = string
  default     = "node01"
}

# -----------------------------------------------------------------------------
# Container Settings
# -----------------------------------------------------------------------------
variable "container_id" {
  description = "Container ID (CTID). Set to 0 for auto-assignment."
  type        = number
  default     = 0
}

variable "container_hostname" {
  description = "Hostname for the container"
  type        = string
  default     = "docker-host"
}

variable "container_template" {
  description = "LXC template to use (storage:template)"
  type        = string
  default     = "local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst"
}

variable "container_password" {
  description = "Root password for the container"
  type        = string
  sensitive   = true
}

variable "container_unprivileged" {
  description = "Create unprivileged container (more secure)"
  type        = bool
  default     = true
}

variable "container_tags" {
  description = "Tags for the container (comma-separated)"
  type        = string
  default     = "docker,terraform"
}

# -----------------------------------------------------------------------------
# Resource Allocation
# -----------------------------------------------------------------------------
variable "cpu_cores" {
  description = "Number of CPU cores"
  type        = number
  default     = 4
}

variable "memory_mb" {
  description = "Memory in MB"
  type        = number
  default     = 8192
}

variable "swap_mb" {
  description = "Swap in MB"
  type        = number
  default     = 2048
}

variable "disk_size" {
  description = "Root disk size (e.g., 50G)"
  type        = string
  default     = "50G"
}

variable "storage_name" {
  description = "Proxmox storage name for the container"
  type        = string
  default     = "local-lvm"
}

# -----------------------------------------------------------------------------
# Network Settings
# -----------------------------------------------------------------------------
variable "network_bridge" {
  description = "Network bridge to use"
  type        = string
  default     = "vmbr0"
}

variable "network_ip" {
  description = "IP address with CIDR (e.g., 192.168.1.100/24) or 'dhcp'"
  type        = string
  default     = "dhcp"
}

variable "network_gateway" {
  description = "Gateway IP (required if using static IP)"
  type        = string
  default     = ""
}

variable "dns_servers" {
  description = "DNS servers (space-separated). Leave empty to use host settings."
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# Additional Options
# -----------------------------------------------------------------------------
variable "start_on_boot" {
  description = "Start container when Proxmox boots"
  type        = bool
  default     = true
}

variable "ssh_public_key" {
  description = "SSH public key for root user (optional)"
  type        = string
  default     = ""
}

variable "auto_install_docker" {
  description = "Automatically install Docker after container creation"
  type        = bool
  default     = true
}
