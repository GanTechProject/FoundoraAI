FROM node:24.19.0-bookworm-slim AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci

FROM dependencies AS development
COPY apps/web ./apps/web
WORKDIR /app
CMD ["npm", "run", "dev", "--workspace=@foundora/web", "--", "-H", "0.0.0.0"]

FROM development AS build
RUN npm run build --workspace=@foundora/web

FROM node:24.19.0-bookworm-slim AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
RUN groupadd --system --gid 10001 foundora && useradd --system --uid 10001 --gid foundora foundora
COPY --from=build --chown=foundora:foundora /app/apps/web/.next/standalone ./
COPY --from=build --chown=foundora:foundora /app/apps/web/.next/static ./apps/web/.next/static
USER foundora
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
