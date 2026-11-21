# Next.js UI as a standalone server. Written and checked with `docker compose config`; not built here (disk).
FROM node:26-slim AS build
WORKDIR /web
# Node 26 no longer bundles corepack; the version matches package.json's packageManager
RUN npm install -g pnpm@10.4.1
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# rewrites() are resolved at build time, so the API address is baked into the build
ARG SHERPA_API_URL=http://api:8000
ENV SHERPA_API_URL=$SHERPA_API_URL NEXT_OUTPUT=standalone NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:26-slim
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /web/.next/standalone ./
COPY --from=build /web/.next/static ./.next/static
# no public/: the app has no static files outside .next
EXPOSE 3000
CMD ["node", "server.js"]
