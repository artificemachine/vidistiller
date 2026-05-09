# Production VM Deployment Guide

## Target Environment
- **Host:** `vidistiller` (SSH alias) — Proxmox VM 900 on `node03-antares`
- **IP Address:** `10.255.181.20`
- **Type:** Proxmox VM (cloud-init Ubuntu 24.04 template)
- **Application:** Vidistiller — YouTube to Documentation engine

> **History:** prod was previously hosted in an LXC at `10.255.181.10` and was
> migrated to this VM. See `deploy/ansible/migrate-db.yml` for the DB migration
> playbook used during the cut-over. The `vidistiller-lxc` host alias still
> resolves but is no longer the deploy target.

The canonical provisioning flow is `deploy/terraform/vidistiller.tf` (clones the
Ubuntu 24.04 cloud-init template) followed by the `deploy/ansible` roles. This
document is the manual fallback — useful for understanding the stack or
recovering by hand.

---

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [VM Provisioning](#vm-provisioning)
3. [System Dependencies](#system-dependencies)
4. [Application Deployment](#application-deployment)
5. [Service Configuration](#service-configuration)
6. [Network Configuration](#network-configuration)
7. [Health Checks & Monitoring](#health-checks--monitoring)
8. [Troubleshooting](#troubleshooting)
9. [Maintenance & Updates](#maintenance--updates)

---

## Prerequisites

### On the Proxmox host
- An Ubuntu 24.04 cloud-init template (referenced by `template_vm_id` in `deploy/terraform/vidistiller.tf`)
- Sufficient resources allocated to the VM:
  - **CPU:** Minimum 4 cores (8+ recommended for video processing)
  - **RAM:** Minimum 8 GB (16 GB+ recommended)
  - **Disk:** Minimum 50 GB (100 GB+ recommended for video storage)
  - **Network:** Bridge network on the lab subnet

### Required software versions
- Ubuntu 24.04 LTS (cloud-init image)
- Docker 24.0+
- Docker Compose 2.20+
- Git 2.0+
- Python 3.12+ (for backend)
- Node.js 20+ (for frontend)

---

## VM Provisioning

### Preferred: Terraform

```bash
cd deploy/terraform
terraform init
terraform apply
```

See `deploy/terraform/vidistiller.tf` for variables (`vm_id`, `vm_cores`,
`vm_memory`, `vm_disk_size`, `vm_storage`).

### Manual: Proxmox CLI

```bash
# Clone the Ubuntu 24.04 cloud-init template (replace <TPL_ID> and <VMID>)
qm clone <TPL_ID> <VMID> --name vidistiller-prod --full

# Resize disk and set resources
qm resize <VMID> scsi0 +50G
qm set <VMID> --cores 8 --memory 16384 --net0 virtio,bridge=vmbr0

# Configure cloud-init (user, ssh key, static IP)
qm set <VMID> --ciuser sysadmin --sshkeys ~/.ssh/authorized_keys
qm set <VMID> --ipconfig0 ip=10.255.181.20/24,gw=<YOUR_GATEWAY_IP>

# Start
qm start <VMID>
```

### Initial VM configuration

```bash
ssh sysadmin@10.255.181.20

# Update system
sudo apt update && sudo apt upgrade -y

# Set timezone
sudo timedatectl set-timezone America/New_York  # or your timezone

# Set hostname
sudo hostnamectl set-hostname vidistiller-prod
```

---

## System Dependencies

### 1. Install Docker & Docker Compose

```bash
# Remove old Docker versions
apt remove docker docker-engine docker.io containerd runc 2>/dev/null || true

# Install prerequisites
apt install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    software-properties-common

# Add Docker GPG key
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify installation
docker --version
docker compose version

# Add appuser to docker group
usermod -aG docker appuser

# Enable Docker service
systemctl enable docker
systemctl start docker
```

### 2. Install Additional Dependencies

```bash
# Install Python 3.12
apt install -y python3.12 python3.12-venv python3-pip

# Install Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

# Install FFmpeg (for video processing)
apt install -y ffmpeg

# Install Git
apt install -y git

# Install system utilities
apt install -y \
    htop \
    net-tools \
    vim \
    curl \
    wget \
    unzip \
    postgresql-client \
    redis-tools

# Verify installations
python3.12 --version
node --version
npm --version
ffmpeg -version
git --version
```

### 3. Install Ollama (for LLM processing)

```bash
# Download and install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
systemctl enable ollama
systemctl start ollama

# Pull Mistral 7B model (this will download ~4GB)
ollama pull mistral

# Verify Ollama is running
curl http://localhost:11434/api/tags
```

---

## Application Deployment

### 1. Clone Repository

```bash
# Switch to appuser
su - appuser

# Create application directory
mkdir -p /home/appuser/apps
cd /home/appuser/apps

# Clone repository
git clone https://github.com/artificemachine/vidistiller.git
cd vidistiller

# Check current branch
git branch
# If not on 'backend' branch, switch to it
git checkout backend
```

### 2. Environment Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env file with production values
vim .env
```

**Required `.env` Configuration:**

```bash
# Database Configuration
DB_USER=tutorial_user
DB_PASSWORD=<STRONG_PASSWORD_HERE>  # Generate with: openssl rand -base64 32
DB_NAME=tutorial_db
DB_PORT=5432
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@postgres:5432/${DB_NAME}

# Redis Configuration
REDIS_PORT=6379
REDIS_URL=redis://redis:6379/0

# Ollama Configuration (host.docker.internal resolves to the VM host)
OLLAMA_PORT=11434
OLLAMA_BASE_URL=http://host.docker.internal:11434

# API Configuration
API_PORT=8000
API_HOST=0.0.0.0
FRONTEND_PORT=3000

# Security - CRITICAL: Generate a strong JWT secret
# Generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET_KEY=<YOUR_STRONG_SECRET_HERE>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS Configuration - Update with your domain
CORS_ORIGINS=http://<OLLAMA_IP>:3000,http://localhost:3000

# Environment
ENVIRONMENT=production
LOG_LEVEL=INFO

# pgAdmin Configuration (optional for production)
PGADMIN_EMAIL=admin@yourdomain.com
PGADMIN_PASSWORD=<STRONG_PASSWORD_HERE>
PGADMIN_PORT=5050

# Application Settings
MAX_WORKERS=4
```

### 3. Generate Secure Secrets

```bash
# Generate JWT secret key (32+ characters with complexity)
python3 -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(32))"

# Generate database password
openssl rand -base64 32

# Generate pgAdmin password
openssl rand -base64 24
```

**Update your `.env` file with these generated values.**

### 4. Docker network configuration

To let containers reach services running directly on the VM host, add a
`host-gateway` mapping:

```bash
# Edit docker-compose.yml to add host.docker.internal mapping
vim docker-compose.yml
```

Add this to the `api` service:

```yaml
api:
  # ... existing configuration ...
  extra_hosts:
    - "host.docker.internal:host-gateway"  # Required for Ollama access from container
```

Also add to `celery_worker` service:

```yaml
celery_worker:
  # ... existing configuration ...
  extra_hosts:
    - "host.docker.internal:host-gateway"
```

### 5. Build and Start Services

```bash
# Build Docker images (this may take 10-15 minutes)
docker compose build

# Start all services
docker compose up -d

# Monitor startup logs
docker compose logs -f

# Wait for health checks (should take ~60 seconds)
sleep 60

# Check service status
docker compose ps
```

Expected output:
```
NAME                    STATUS          PORTS
tutorial_api            Up (healthy)    0.0.0.0:8000->8000/tcp
tutorial_celery_worker  Up
tutorial_postgres       Up (healthy)    0.0.0.0:5432->5432/tcp
tutorial_redis          Up (healthy)    0.0.0.0:6379->6379/tcp
tutorial_web            Up              0.0.0.0:3000->3000/tcp
tutorial_pgadmin        Up              0.0.0.0:5050->80/tcp
```

### 6. Run Database Migrations

```bash
# Run Alembic migrations inside the API container
docker compose exec api alembic upgrade head

# Verify tables were created
docker compose exec postgres psql -U tutorial_user -d tutorial_db -c "\dt"
```

Expected tables:
```
               List of relations
 Schema |         Name          | Type  |     Owner
--------+-----------------------+-------+----------------
 public | alembic_version       | table | tutorial_user
 public | documents             | table | tutorial_user
 public | processing_jobs       | table | tutorial_user
 public | snapshots             | table | tutorial_user
 public | transcript_segments   | table | tutorial_user
 public | transcripts           | table | tutorial_user
 public | users                 | table | tutorial_user
 public | videos                | table | tutorial_user
```

---

## Service Configuration

### 1. Systemd Service for Auto-Start

Create a systemd service to automatically start the application on boot:

```bash
# Create systemd service file (as root)
sudo vim /etc/systemd/system/vidistiller.service
```

**Service file content:**

```ini
[Unit]
Description=YouTube Tutorial to Doc Converter
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/appuser/apps/vidistiller
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
User=appuser
Group=appuser

[Install]
WantedBy=multi-user.target
```

**Enable and start service:**

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable vidistiller.service

# Start service
sudo systemctl start vidistiller.service

# Check status
sudo systemctl status vidistiller.service
```

### 2. Nginx Reverse Proxy (Optional but Recommended)

Install Nginx to handle SSL/TLS and provide a reverse proxy:

```bash
# Install Nginx
sudo apt install -y nginx

# Create Nginx configuration
sudo vim /etc/nginx/sites-available/vidistiller
```

**Nginx configuration:**

```nginx
# Frontend
server {
    listen 80;
    server_name <OLLAMA_IP>;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# API
server {
    listen 8080;
    server_name <OLLAMA_IP>;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Increase timeout for long-running requests
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
```

**Enable Nginx configuration:**

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/vidistiller \
            /etc/nginx/sites-enabled/

# Remove default site
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx

# Enable Nginx
sudo systemctl enable nginx
```

---

## Network Configuration

### 1. Firewall Configuration (UFW)

```bash
# Enable UFW
sudo ufw enable

# Allow SSH (important!)
sudo ufw allow 22/tcp

# Allow HTTP and HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow API (if not using Nginx proxy)
sudo ufw allow 8000/tcp

# Allow frontend (if not using Nginx proxy)
sudo ufw allow 3000/tcp

# Check status
sudo ufw status
```

### 2. Port Mapping Summary

| Service | Internal Port | External Port | Access |
|---------|--------------|---------------|---------|
| Frontend | 3000 | 80 (via Nginx) | Public |
| API | 8000 | 8080 (via Nginx) | Public |
| PostgreSQL | 5432 | - | Internal only |
| Redis | 6379 | - | Internal only |
| Ollama | 11434 | - | Internal only |
| pgAdmin | 5050 | 5050 | Admin only |

---

## Health Checks & Monitoring

### 1. Application Health Checks

```bash
# Check all service health
docker compose ps

# API health check
curl http://localhost:8000/health

# Check API docs
curl http://localhost:8000/docs

# Frontend health check
curl http://localhost:3000

# Database connection test
docker compose exec postgres pg_isready -U tutorial_user

# Redis connection test
docker compose exec redis redis-cli ping

# Ollama health check
curl http://localhost:11434/api/tags
```

### 2. Log Monitoring

```bash
# View all logs
docker compose logs -f

# View specific service logs
docker compose logs -f api
docker compose logs -f celery_worker
docker compose logs -f postgres

# View last 100 lines
docker compose logs --tail=100 api

# Save logs to file
docker compose logs > /var/log/vidistiller.log
```

### 3. Resource Monitoring

```bash
# Monitor container resource usage
docker stats

# Check disk usage
df -h
docker system df

# Check memory usage
free -h

# Check CPU usage
htop
```

### 4. Automated Health Check Script

Create a health check script:

```bash
vim /home/appuser/apps/vidistiller/scripts/health-check-production.sh
```

```bash
#!/bin/bash
# Production Health Check Script

echo "=== YouTube Tutorial Converter Health Check ==="
echo "Timestamp: $(date)"
echo ""

# Check Docker
echo "1. Docker Status:"
if systemctl is-active --quiet docker; then
    echo "   ✓ Docker is running"
else
    echo "   ✗ Docker is NOT running"
    exit 1
fi

# Check containers
echo "2. Container Status:"
cd /home/appuser/apps/vidistiller
CONTAINERS=$(docker compose ps --services --filter "status=running" | wc -l)
echo "   Running containers: $CONTAINERS/6"

# Check API health
echo "3. API Health:"
if curl -sf http://localhost:8000/health > /dev/null; then
    echo "   ✓ API is healthy"
else
    echo "   ✗ API is NOT responding"
fi

# Check Frontend
echo "4. Frontend Health:"
if curl -sf http://localhost:3000 > /dev/null; then
    echo "   ✓ Frontend is accessible"
else
    echo "   ✗ Frontend is NOT responding"
fi

# Check Database
echo "5. Database Health:"
if docker compose exec -T postgres pg_isready -U tutorial_user > /dev/null 2>&1; then
    echo "   ✓ PostgreSQL is ready"
else
    echo "   ✗ PostgreSQL is NOT ready"
fi

# Check Redis
echo "6. Redis Health:"
if docker compose exec -T redis redis-cli ping > /dev/null 2>&1; then
    echo "   ✓ Redis is responding"
else
    echo "   ✗ Redis is NOT responding"
fi

# Check Ollama
echo "7. Ollama Health:"
if curl -sf http://localhost:11434/api/tags > /dev/null; then
    echo "   ✓ Ollama is running"
else
    echo "   ✗ Ollama is NOT responding"
fi

# Disk usage
echo "8. Disk Usage:"
df -h / | tail -1 | awk '{print "   " $5 " used (" $3 " / " $2 ")"}'

# Memory usage
echo "9. Memory Usage:"
free -h | grep Mem | awk '{print "   " $3 " / " $2 " (" int($3/$2*100) "% used)"}'

echo ""
echo "=== Health Check Complete ==="
```

Make executable and set up cron:

```bash
chmod +x /home/appuser/apps/vidistiller/scripts/health-check-production.sh

# Add to crontab (runs every 5 minutes)
crontab -e

# Add this line:
*/5 * * * * /home/appuser/apps/vidistiller/scripts/health-check-production.sh >> /var/log/health-check.log 2>&1
```

---

## Troubleshooting

### Common Issues and Solutions

#### 1. Docker "Cannot connect to Docker daemon"

```bash
# Check Docker service
sudo systemctl status docker

# Restart Docker
sudo systemctl restart docker

# Check if user is in docker group
groups appuser

# Add user to docker group
sudo usermod -aG docker appuser

# Log out and back in for group changes to take effect
```

#### 2. Ollama not accessible from containers

```bash
# Check Ollama status
systemctl status ollama

# Restart Ollama
sudo systemctl restart ollama

# Verify Ollama port
sudo netstat -tulpn | grep 11434

# Test from host
curl http://localhost:11434/api/tags

# Test from container
docker compose exec api curl http://host.docker.internal:11434/api/tags
```

#### 3. Database connection errors

```bash
# Check PostgreSQL logs
docker compose logs postgres

# Check database is accepting connections
docker compose exec postgres pg_isready -U tutorial_user

# Connect to database
docker compose exec postgres psql -U tutorial_user -d tutorial_db

# Check DATABASE_URL in .env matches docker-compose.yml
```

#### 4. Frontend can't connect to API

```bash
# Check CORS_ORIGINS in .env includes frontend URL
# Check API is accessible
curl http://localhost:8000/health

# Check frontend environment
docker compose exec web env | grep NEXT_PUBLIC_API_URL

# Should be: NEXT_PUBLIC_API_URL=http://<OLLAMA_IP>:8000/api
```

#### 5. Celery worker not processing jobs

```bash
# Check Celery worker logs
docker compose logs celery_worker

# Check Redis connection
docker compose exec celery_worker redis-cli -h redis ping

# Restart worker
docker compose restart celery_worker
```

#### 6. Out of disk space

```bash
# Check disk usage
df -h

# Clean up Docker
docker system prune -a --volumes

# Clean up old images
docker image prune -a

# Check Docker volumes
docker volume ls
docker volume prune
```

#### 7. Container keeps restarting

```bash
# Check container logs
docker compose logs <service_name>

# Check resource limits
docker stats

# Check health check failures
docker inspect <container_name> | grep -A 10 Health
```

---

## Maintenance & Updates

### 1. Application Updates

```bash
# Pull latest code
cd /home/appuser/apps/vidistiller
git pull origin main

# Rebuild containers
docker compose build

# Stop services
docker compose down

# Start with new images
docker compose up -d

# Run migrations
docker compose exec api alembic upgrade head
```

### 2. Database Backups

Create automated backup script:

```bash
vim /home/appuser/scripts/backup-database.sh
```

```bash
#!/bin/bash
# Database Backup Script

BACKUP_DIR="/home/appuser/backups/postgres"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/tutorial_db_$TIMESTAMP.sql"

mkdir -p $BACKUP_DIR

# Backup database
docker compose exec -T postgres pg_dump -U tutorial_user tutorial_db > $BACKUP_FILE

# Compress backup
gzip $BACKUP_FILE

# Keep only last 7 days of backups
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete

echo "Backup completed: ${BACKUP_FILE}.gz"
```

Make executable and schedule:

```bash
chmod +x /home/appuser/scripts/backup-database.sh

# Add to crontab (daily at 2 AM)
crontab -e

# Add:
0 2 * * * /home/appuser/scripts/backup-database.sh >> /var/log/database-backup.log 2>&1
```

### 3. Log Rotation

```bash
# Create logrotate configuration
sudo vim /etc/logrotate.d/vidistiller
```

```
/var/log/vidistiller.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 appuser appuser
    sharedscripts
}

/var/log/health-check.log {
    weekly
    rotate 4
    compress
    delaycompress
    notifempty
    create 0640 appuser appuser
}

/var/log/database-backup.log {
    monthly
    rotate 12
    compress
    delaycompress
    notifempty
    create 0640 appuser appuser
}
```

### 4. Security Updates

```bash
# Update system packages monthly
sudo apt update && sudo apt upgrade -y

# Update Docker
sudo apt install docker-ce docker-ce-cli containerd.io

# Update Docker Compose
sudo apt install docker-compose-plugin

# Restart services
docker compose down && docker compose up -d
```

---

## Deployment Checklist

Use this checklist when deploying:

- [ ] VM provisioned (terraform apply, or `qm clone` from cloud-init template)
- [ ] System updated (`apt update && apt upgrade`)
- [ ] Docker and Docker Compose installed
- [ ] Ollama installed and Mistral model pulled
- [ ] Repository cloned on 'main' branch
- [ ] `.env` file created with strong secrets
- [ ] JWT_SECRET_KEY generated (32+ characters)
- [ ] Database password generated
- [ ] CORS_ORIGINS updated with correct domain/IP
- [ ] docker-compose.yml updated with extra_hosts for Ollama
- [ ] Docker containers built (`docker compose build`)
- [ ] Services started (`docker compose up -d`)
- [ ] Database migrations run (`alembic upgrade head`)
- [ ] Health checks passing (all services "Up (healthy)")
- [ ] API accessible at http://<OLLAMA_IP>:8000/docs
- [ ] Frontend accessible at http://<OLLAMA_IP>:3000
- [ ] Ollama accessible from containers
- [ ] Systemd service created and enabled
- [ ] Firewall configured (UFW)
- [ ] Nginx reverse proxy configured (optional)
- [ ] Health check cron job configured
- [ ] Database backup cron job configured
- [ ] Log rotation configured

---

## Quick Reference Commands

```bash
# Start application
cd /home/appuser/apps/vidistiller
docker compose up -d

# Stop application
docker compose down

# View logs
docker compose logs -f

# Restart a service
docker compose restart <service_name>

# Check status
docker compose ps

# Run migrations
docker compose exec api alembic upgrade head

# Access database
docker compose exec postgres psql -U tutorial_user -d tutorial_db

# Access Redis CLI
docker compose exec redis redis-cli

# Health check
curl http://localhost:8000/health

# Clean up resources
docker system prune -a
```

---

## Support & Documentation

- **Application Docs:** `/docs` directory in repository
- **API Documentation:** http://<OLLAMA_IP>:8000/docs (Swagger UI)
- **Alternative API Docs:** http://<OLLAMA_IP>:8000/redoc
- **Repository:** https://github.com/artificemachine/vidistiller
- **Docker Docs:** https://docs.docker.com
- **FastAPI Docs:** https://fastapi.tiangolo.com
- **Next.js Docs:** https://nextjs.org/docs

---

**Deployment Guide Version:** 2.0
**Last Updated:** 2026-05-09 (renamed from LXC_DEPLOYMENT.md after prod migrated to a VM)
**Target host:** `vidistiller` (Proxmox VM 900 at 10.255.181.20)
