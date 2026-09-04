# syntax=docker/dockerfile:1
# Multi-stage: build the Vite/React SPA with Node, serve the static output plus
# the API reverse proxy with nginx (docs/ARCHITECTURE.md §24, §27).

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json tsconfig.build.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

# nginx-unprivileged runs as uid 101 and listens on 8080 (no root, no privileged
# port) — see docs/ARCHITECTURE.md §24 / §27, trivy DS-0002.
FROM nginxinc/nginx-unprivileged:1.27-alpine
USER root
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER 101

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -q -O - http://127.0.0.1:8080/healthz || exit 1
