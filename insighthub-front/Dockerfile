# ─── Stage 1 : dépendances ────────────────────────────────────────────────────
FROM node:20-alpine AS deps

WORKDIR /app

# Copie uniquement les fichiers de dépendances pour profiter du cache Docker
COPY package.json package-lock.json* ./

RUN npm ci --frozen-lockfile

# ─── Stage 2 : build ──────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Variable d'env disponible au build (Next.js "bake" les NEXT_PUBLIC_* dans le bundle)
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

# ─── Stage 3 : runner (image finale légère) ────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Utilisateur non-root pour la sécurité
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copie des artefacts de build (standalone output)
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
