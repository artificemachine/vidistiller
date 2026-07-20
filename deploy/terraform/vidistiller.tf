# Provision vidistiller-prod on your-proxmox-node
# Provider: bpg/proxmox ~> 0.74 (same as your existing cluster)
# Clone from Ubuntu 24.04 cloud-init template (VM 9001 on your-proxmox-node)
# IP: 10.0.181.20 (deprecated LXC at 10.0.181.10 lives on the same subnet)

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.74"
    }
  }
}

# --- Provider ---

provider "proxmox" {
  endpoint  = var.proxmox_api_url
  api_token = format("%s=%s", var.proxmox_token_id, var.proxmox_token_secret)
  # TLS verified via /etc/hosts: 10.0.100.33 proxmox-node.example.com
  insecure = false

  ssh {
    agent    = true
    username = "root"
  }
}

# --- Variables ---

variable "proxmox_api_url" {
  description = "Proxmox API endpoint"
  type        = string
  default     = "https://proxmox-node.example.com:8006"
}

variable "proxmox_token_id" {
  description = "Proxmox API token ID"
  type        = string
}

variable "proxmox_token_secret" {
  description = "Proxmox API token secret"
  type        = string
  sensitive   = true
}

variable "target_node" {
  description = "Proxmox node name"
  type        = string
  default     = "your-proxmox-node"
}

variable "template_vm_id" {
  description = "VM ID of Ubuntu 24.04 cloud-init template"
  type        = number
  default     = 9001
}

variable "vm_id" {
  description = "VM ID for vidistiller-prod"
  type        = number
  default     = 900
}

variable "vm_cores" {
  type    = number
  default = 4
}

variable "vm_memory" {
  description = "RAM in MB"
  type        = number
  default     = 8192
}

variable "vm_disk_size" {
  description = "OS disk in GB (includes Docker volumes for videos/snapshots)"
  type        = number
  default     = 80
}

variable "vm_storage" {
  description = "Proxmox storage pool"
  type        = string
  default     = "nvme00-proxmox"
}

variable "vm_bridge" {
  # 10.0.181.x lives on this bridge on proxmox-node.
  # Verify with: pvesh get /nodes/your-proxmox-node/network on the Proxmox host.
  # your other node uses vmbr10 for 10.0.77.x; 10.0.181.x may be vmbr0 or another bridge.
  description = "Proxmox bridge for the 10.0.181.x subnet"
  type        = string
  default     = "vmbr0"
}

variable "vm_ip" {
  description = "Static IP for vidistiller-prod"
  type        = string
  default     = "10.0.181.20"
}

variable "vm_prefix" {
  type    = number
  default = 16
}

variable "gateway" {
  type    = string
  default = "10.0.10.1"
}

variable "ssh_public_key" {
  description = "SSH public key for VM access (paste output of: cat ~/.ssh/id_ed25519.pub)"
  type        = string
  default     = ""
}

# --- VM Resource ---

resource "proxmox_virtual_environment_vm" "vidistiller_prod" {
  vm_id     = var.vm_id
  name      = "vidistiller-prod"
  node_name = var.target_node

  clone {
    vm_id     = var.template_vm_id
    full      = true
    node_name = var.target_node
  }

  cpu {
    cores   = var.vm_cores
    sockets = 1
    type    = "host"
  }

  memory {
    dedicated = var.vm_memory
  }

  disk {
    datastore_id = var.vm_storage
    interface    = "scsi0"
    size         = var.vm_disk_size
  }

  network_device {
    model  = "virtio"
    bridge = var.vm_bridge
  }

  serial_device {}

  # Disable QEMU guest agent polling during Terraform state refresh.
  # qemu-guest-agent is installed by Ansible; Terraform does not manage it.
  agent {
    enabled = false
  }

  initialization {
    ip_config {
      ipv4 {
        address = "${var.vm_ip}/${var.vm_prefix}"
        gateway = var.gateway
      }
    }
    dns {
      servers = [var.gateway]
    }
    user_account {
      keys = var.ssh_public_key != "" ? [var.ssh_public_key] : []
    }
  }

  on_boot = true
  startup {
    order = 2
  }

  tags = ["vidistiller", "prod", "docker"]

  lifecycle {
    ignore_changes = [
      network_device,
      clone,
      disk,
      initialization,
      agent,
    ]
  }
}

# --- Outputs ---

output "vm_id" {
  value = proxmox_virtual_environment_vm.vidistiller_prod.vm_id
}

output "vm_ip" {
  value = var.vm_ip
}

output "vm_name" {
  value = proxmox_virtual_environment_vm.vidistiller_prod.name
}
