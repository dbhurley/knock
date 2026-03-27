# Knock Deployment Guide

## Initial Server Setup

### 1. Provision DigitalOcean Droplet

- Create an Ubuntu 24.04 droplet (recommended: 4GB RAM, 2 vCPUs minimum)
- Enable monitoring and backups during creation
- Add your SSH key during setup

### 2. Server Configuration

SSH into the droplet and run the initial setup:

```bash
# Create the deploy user
adduser deploy
usermod -aG docker deploy

# Install Docker and Docker Compose
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin

# Clone the repository
mkdir -p /opt/knock
chown deploy:deploy /opt/knock
su - deploy
git clone git@github.com:<your-org>/knock.git /opt/knock
cd /opt/knock

# Copy and configure environment
cp .env.example .env
# Edit .env with production values (database credentials, API keys, etc.)

# Start services
docker compose up -d

# Run initial migrations
docker compose exec -T app npm run db:migrate
```

### 3. Configure Nginx and SSL

```bash
apt install -y nginx certbot python3-certbot-nginx

# Set up Nginx config for askknock.com (reverse proxy to port 3000)
# Then obtain SSL certificate:
certbot --nginx -d askknock.com -d api.askknock.com
```

## GitHub Secrets

Configure the following secrets in your GitHub repository settings
(Settings > Secrets and variables > Actions):

| Secret           | Description                                    |
|------------------|------------------------------------------------|
| `DROPLET_IP`     | Public IPv4 address of the DigitalOcean droplet |
| `DEPLOY_SSH_KEY` | Private SSH key for the `deploy` user           |

### Generating the Deploy Key

```bash
# On your local machine
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/knock_deploy

# Copy the public key to the server
ssh-copy-id -i ~/.ssh/knock_deploy.pub deploy@<DROPLET_IP>

# Add the private key contents as the DEPLOY_SSH_KEY secret in GitHub
cat ~/.ssh/knock_deploy
```

## How the Deploy Pipeline Works

The production deploy pipeline (`.github/workflows/deploy.yml`) runs
automatically on every push to the `main` branch:

1. **Test job** -- Checks out the code, installs dependencies, runs the test
   suite and linter against `services/api`.
2. **Deploy job** (runs only if tests pass) -- SSHs into the production droplet
   and executes:
   - `git pull origin main` -- pulls the latest code
   - `docker compose build` -- rebuilds container images
   - `docker compose up -d` -- restarts services with zero-downtime rolling
     updates
   - `npm run db:migrate` -- applies any pending database migrations
   - Health check via `curl` to `/health` -- verifies the API is responding
3. On success, the workflow completes. On failure at any step, the pipeline
   stops and GitHub sends a notification.

### PR Checks

Pull requests targeting `main` trigger `.github/workflows/test.yml`, which
runs typecheck, lint, and tests for every service. PRs cannot be merged until
all checks pass.

### Scheduled Data Sync

`.github/workflows/data-sync.yml` runs every Sunday at 3:00 AM UTC to rebuild
the Redis cache. It can also be triggered manually from the Actions tab.

## Manual Deploy

If you need to deploy without going through CI:

```bash
ssh deploy@<DROPLET_IP>
cd /opt/knock
git pull origin main
docker compose build
docker compose up -d
docker compose exec -T app npm run db:migrate
curl -f http://localhost:3000/health
```

## Rollback

### Quick Rollback (revert to previous commit)

```bash
ssh deploy@<DROPLET_IP>
cd /opt/knock
git log --oneline -5            # identify the commit to roll back to
git checkout <commit-hash>
docker compose build
docker compose up -d
curl -f http://localhost:3000/health
```

### Full Rollback (revert commit on main)

```bash
# On your local machine
git revert <bad-commit-hash>
git push origin main
# The CI pipeline will deploy the reverted state automatically
```

## Backup and Restore

### Automated Backups

A cron job on the server runs daily at 2:00 AM UTC:

```
0 2 * * * deploy /opt/knock/scripts/backup-postgres.sh
```

This dumps the PostgreSQL database and uploads it to DigitalOcean Spaces.

### Manual Backup

```bash
ssh deploy@<DROPLET_IP>
cd /opt/knock
bash scripts/backup-postgres.sh
```

### Restore from Backup

```bash
ssh deploy@<DROPLET_IP>
cd /opt/knock

# Stop the application
docker compose stop app

# Restore the database
docker compose exec -T db psql -U knock knock_db < /path/to/backup.sql

# Restart services
docker compose up -d

# Verify
curl -f http://localhost:3000/health
```

### Redis Cache Rebuild

If the Redis cache becomes stale or corrupted, rebuild it:

```bash
ssh deploy@<DROPLET_IP>
cd /opt/knock
bash scripts/rebuild-redis-cache.sh
```

This can also be triggered via the GitHub Actions "Weekly Data Sync" workflow.
