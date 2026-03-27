# Dockerfile for Knock OpenClaw Agent (Janet)
#
# This builds the OpenClaw service container with Janet's configuration,
# prompts, skills, workflows, and tools.
#
# Base image reference: update to the actual OpenClaw image once available.

FROM node:22-alpine AS base

WORKDIR /app

# Install dependencies for OpenClaw runtime
RUN apk add --no-cache curl ca-certificates

# ---------------------------------------------------------------------------
# Build stage: compile TypeScript tools
# ---------------------------------------------------------------------------
FROM base AS builder

COPY package*.json ./
RUN npm ci --production=false 2>/dev/null || true

COPY tools/ ./tools/

# Compile TypeScript tools if tsconfig exists
RUN if [ -f tsconfig.json ]; then npx tsc; else echo "No tsconfig, skipping TS build"; fi

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
FROM base AS runtime

# Create non-root user
RUN addgroup -g 1001 openclaw && \
    adduser -u 1001 -G openclaw -s /bin/sh -D openclaw

# Copy OpenClaw configuration
COPY config.yaml ./config.yaml

# Copy prompts
COPY prompts/ ./prompts/

# Copy skills
COPY skills/ ./skills/

# Copy workflows
COPY workflows/ ./workflows/

# Copy compiled tools from builder
COPY --from=builder /app/tools/ ./tools/

# Set ownership
RUN chown -R openclaw:openclaw /app

USER openclaw

# OpenClaw default port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1

# Environment variables (set via docker-compose or runtime)
ENV NODE_ENV=production
ENV OPENCLAW_CONFIG=/app/config.yaml

# Start OpenClaw agent
# Replace with actual OpenClaw start command once the runtime is finalized.
CMD ["node", "node_modules/.bin/openclaw", "start", "--config", "/app/config.yaml"]
