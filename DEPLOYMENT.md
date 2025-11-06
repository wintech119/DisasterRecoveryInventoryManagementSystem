# GOJ Relief Inventory System - Deployment Guide

## Overview
This guide covers deploying the GOJ Relief Inventory System on Red Hat Enterprise Linux (RHEL) or compatible systems.

## System Requirements

### RHEL 8/9 Requirements
- Python 3.11 or higher
- PostgreSQL 13 or higher
- Nginx (recommended for production)
- 2GB RAM minimum (4GB recommended)
- 20GB disk space

## Deployment Steps

### 1. Install System Dependencies

```bash
# Install Python and development tools
sudo dnf install python3.11 python3.11-pip python3.11-devel gcc

# Install PostgreSQL
sudo dnf install postgresql-server postgresql-contrib

# Install Nginx
sudo dnf install nginx

# Install additional dependencies
sudo dnf install git
```

### 2. Set Up PostgreSQL

```bash
# Initialize PostgreSQL
sudo postgresql-setup --initdb

# Start and enable PostgreSQL
sudo systemctl enable postgresql
sudo systemctl start postgresql

# Create database and user
sudo -u postgres psql << EOF
CREATE DATABASE relief_inventory;
CREATE USER relief_user WITH PASSWORD 'CHANGE_THIS_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE relief_inventory TO relief_user;
\q
EOF
```

### 3. Deploy Application

```bash
# Create application directory
sudo mkdir -p /opt/goj-relief
cd /opt/goj-relief

# Clone repository (adjust URL to your Git server)
sudo git clone https://github.com/yourusername/goj-relief-inventory.git .

# Create application user
sudo useradd -r -s /bin/false relief-app

# Set ownership
sudo chown -R relief-app:relief-app /opt/goj-relief

# Switch to application user
sudo -u relief-app bash

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn psycopg2-binary
```

### 4. Configure Environment

```bash
# Create .env file (as relief-app user)
cat > .env << 'EOF'
SECRET_KEY=GENERATE_RANDOM_KEY_HERE
DATABASE_URL=postgresql://relief_user:CHANGE_THIS_PASSWORD@localhost/relief_inventory
FLASK_ENV=production
EOF

# Generate a secure secret key
python3 -c 'import secrets; print("SECRET_KEY=" + secrets.token_hex(32))' >> .env.tmp
# Manually copy the SECRET_KEY from .env.tmp to .env

# Set proper permissions
chmod 600 .env
```

### 5. Initialize Database

```bash
# Still as relief-app user with venv activated
export $(cat .env | xargs)

# Initialize database tables
python -c "from app import app, db; app.app_context().push(); db.create_all()"

# Create initial admin user
flask create-admin
```

### 6. Create Systemd Service

Exit back to root user, then create service file:

```bash
# Create service file
sudo nano /etc/systemd/system/relief-inventory.service
```

Add the following content:

```ini
[Unit]
Description=GOJ Relief Inventory System
After=network.target postgresql.service

[Service]
Type=notify
User=relief-app
Group=relief-app
WorkingDirectory=/opt/goj-relief
Environment="PATH=/opt/goj-relief/venv/bin"
EnvironmentFile=/opt/goj-relief/.env
ExecStart=/opt/goj-relief/venv/bin/gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 4 \
    --timeout 120 \
    --access-logfile /var/log/relief-inventory/access.log \
    --error-logfile /var/log/relief-inventory/error.log \
    app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Create log directory:

```bash
sudo mkdir -p /var/log/relief-inventory
sudo chown relief-app:relief-app /var/log/relief-inventory
```

Enable and start service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable relief-inventory
sudo systemctl start relief-inventory
sudo systemctl status relief-inventory
```

### 7. Configure Nginx Reverse Proxy

```bash
sudo nano /etc/nginx/conf.d/relief-inventory.conf
```

Add the following:

```nginx
server {
    listen 80;
    server_name relief.gov.jm;  # Change to your domain

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /opt/goj-relief/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
}
```

Enable and restart Nginx:

```bash
sudo systemctl enable nginx
sudo systemctl restart nginx
```

### 8. Configure Firewall

```bash
# Allow HTTP and HTTPS
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### 9. Set Up SSL/TLS (Recommended)

Install certbot for Let's Encrypt:

```bash
sudo dnf install certbot python3-certbot-nginx
sudo certbot --nginx -d relief.gov.jm
```

## Post-Deployment

### Create Additional Users

```bash
# SSH into server
cd /opt/goj-relief
sudo -u relief-app bash
source venv/bin/activate
export $(cat .env | xargs)

# Create users
flask create-user
```

### Monitoring

```bash
# Check application logs
sudo journalctl -u relief-inventory -f

# Check Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Check application-specific logs
sudo tail -f /var/log/relief-inventory/access.log
sudo tail -f /var/log/relief-inventory/error.log
```

### Backup Strategy

Create backup script `/opt/backup-relief.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/relief-inventory"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup database
sudo -u postgres pg_dump relief_inventory | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Backup uploaded files (if any)
tar -czf $BACKUP_DIR/files_$DATE.tar.gz /opt/goj-relief/static/uploads 2>/dev/null

# Keep only last 30 days of backups
find $BACKUP_DIR -type f -mtime +30 -delete

echo "Backup completed: $DATE"
```

Make executable and add to cron:

```bash
sudo chmod +x /opt/backup-relief.sh
sudo crontab -e
# Add: 0 2 * * * /opt/backup-relief.sh
```

### Updates and Maintenance

```bash
# Pull latest changes
cd /opt/goj-relief
sudo -u relief-app git pull origin main

# Activate venv and update dependencies
sudo -u relief-app bash
source venv/bin/activate
pip install -r requirements.txt

# Restart service
exit
sudo systemctl restart relief-inventory
```

## Security Checklist

- [ ] Change default PostgreSQL password
- [ ] Generate strong SECRET_KEY
- [ ] Enable firewall (firewalld)
- [ ] Install and configure SELinux
- [ ] Set up SSL/TLS certificates
- [ ] Configure regular backups
- [ ] Enable log rotation
- [ ] Keep system updated (`sudo dnf update`)
- [ ] Restrict SSH access
- [ ] Monitor application logs

## Troubleshooting

### Service won't start
```bash
sudo journalctl -u relief-inventory -n 50
```

### Database connection issues
```bash
sudo -u postgres psql
\l  # List databases
\du # List users
```

### Permission issues
```bash
sudo chown -R relief-app:relief-app /opt/goj-relief
sudo chmod 600 /opt/goj-relief/.env
```

## Support

For issues or questions, contact your system administrator or refer to the project documentation.
