FROM node:20-alpine

WORKDIR /app

# Install dependencies first (layer cache — only re-runs if package*.json changes)
COPY package*.json ./
RUN npm ci

# Copy source (overridden by volume mount in docker-compose for hot-reload)
COPY . .

EXPOSE 3000

ENV NEXT_TELEMETRY_DISABLED=1

# next dev binds to 0.0.0.0 by default in Next.js 15+ so it's reachable from host
CMD ["npm", "run", "dev"]
