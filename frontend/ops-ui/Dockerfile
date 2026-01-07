FROM node:20-alpine AS build

WORKDIR /app

# Copy the frontend workspace (root + ops-ui).
COPY frontend/package.json frontend/package.json
COPY frontend/package-lock.json frontend/package-lock.json
COPY frontend/tsconfig.json frontend/tsconfig.json
COPY frontend/tsconfig.node.json frontend/tsconfig.node.json
COPY frontend/vite.config.ts frontend/vite.config.ts
COPY frontend/index.html frontend/index.html
COPY frontend/postcss.config.js frontend/postcss.config.js
COPY frontend/tailwind.config.ts frontend/tailwind.config.ts
COPY frontend/eslint.config.js frontend/eslint.config.js
COPY frontend/public frontend/public
COPY frontend/src frontend/src

COPY frontend/ops-ui frontend/ops-ui

WORKDIR /app/frontend

RUN npm ci --no-audit --no-fund
RUN npm -w ops-ui run build

FROM nginx:1.27-alpine

COPY frontend/ops-ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/ops-ui/docker-entrypoint.d/99-config.sh /docker-entrypoint.d/99-config.sh
RUN chmod +x /docker-entrypoint.d/99-config.sh

COPY --from=build /app/frontend/ops-ui/dist /usr/share/nginx/html

EXPOSE 80

