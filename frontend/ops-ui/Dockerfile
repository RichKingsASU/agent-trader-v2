FROM node:20-alpine AS build

WORKDIR /app

# Copy the frontend workspace (root + ops-ui).
COPY frontend/package.json frontend/package.json
COPY frontend/package-lock.json frontend/package-lock.json
COPY frontend/eslint.config.js frontend/eslint.config.js
COPY frontend/ops-ui/package.json frontend/ops-ui/package.json
COPY frontend/ops-ui/tsconfig.json frontend/ops-ui/tsconfig.json
COPY frontend/ops-ui/vite.config.ts frontend/ops-ui/vite.config.ts
COPY frontend/ops-ui/index.html frontend/ops-ui/index.html
COPY frontend/ops-ui/public frontend/ops-ui/public
COPY frontend/ops-ui/src frontend/ops-ui/src
COPY frontend/ops-ui/nginx.conf frontend/ops-ui/nginx.conf
COPY frontend/ops-ui/docker-entrypoint.d frontend/ops-ui/docker-entrypoint.d

WORKDIR /app/frontend

RUN npm ci --no-audit --no-fund
RUN npm -w ops-ui run build

FROM nginx:1.27-alpine

COPY frontend/ops-ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/ops-ui/docker-entrypoint.d/99-config.sh /docker-entrypoint.d/99-config.sh
RUN chmod +x /docker-entrypoint.d/99-config.sh

COPY --from=build /app/frontend/ops-ui/dist /usr/share/nginx/html

EXPOSE 80

