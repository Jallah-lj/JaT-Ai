# Stage 1: Builder
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies strictly from the lockfile
COPY package.json package-lock.json ./
RUN npm ci

# Copy the source code and build the static assets
COPY . .
RUN npm run build

# Stage 2: Production
FROM nginxinc/nginx-unprivileged:alpine

# Copy the compiled static files to the Nginx HTML directory
# The target directory depends on your Vite output configuration (commonly 'dist')
COPY --from=builder /app/dist /usr/share/nginx/html

# The nginx-unprivileged image uses port 8080 by default to avoid root port restrictions
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]