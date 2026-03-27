# Knock

Executive search for private and independent schools.

## Quick Start

```bash
cp .env.example .env
# Fill in your environment variables
docker compose up -d
```

## Architecture

- **PostgreSQL 16** — Primary database (~34K schools, candidates, searches)
- **Redis 7** — Cache layer for sub-millisecond Janet queries
- **OpenClaw** — AI agent platform (Janet, the office manager)
- **Telegram Bot** — Primary interface for Janet
- **Caddy** — Reverse proxy with automatic HTTPS
- **Meilisearch** — Full-text search engine

## Domains

| URL | Purpose |
|---|---|
| askknock.com | Public site |
| janet.askknock.com | OpenClaw Gateway |
| api.askknock.com | REST API |

## Documentation

See [PRD.md](./PRD.md) for the complete project specification.
