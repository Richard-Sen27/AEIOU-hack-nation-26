# Amber frontend image: production build of the Next.js app (standalone output).
# Build context: apps/frontend.
#   docker build -t amber-frontend:local \
#     --build-arg NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 apps/frontend
# NEXT_PUBLIC_* values are inlined into the browser bundle at build time: the API URL is the
# one the *browser* uses, so it stays http://127.0.0.1:<port> (never localhost).

ARG NODE_IMAGE=node:22-trixie-slim

FROM ${NODE_IMAGE} AS build
ENV NEXT_TELEMETRY_DISABLED=1 \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
ARG NEXT_PUBLIC_PRIVACY_EMAIL=
# Hosted only: where the /api and /auth rewrites send requests (see next.config.ts). Empty locally.
ARG API_PROXY_TARGET=
# Optional off switch for the page counter (src/lib/analytics.ts): "off" disables it.
ARG NEXT_PUBLIC_ANALYTICS=
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_PRIVACY_EMAIL=${NEXT_PUBLIC_PRIVACY_EMAIL} \
    NEXT_PUBLIC_ANALYTICS=${NEXT_PUBLIC_ANALYTICS} \
    API_PROXY_TARGET=${API_PROXY_TARGET} \
    NEXT_OUTPUT=standalone
RUN pnpm build

FROM ${NODE_IMAGE} AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3100
WORKDIR /app
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3100
CMD ["node", "server.js"]
