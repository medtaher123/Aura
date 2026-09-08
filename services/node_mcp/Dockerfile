FROM node:22-bookworm-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends wget ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY package.json ./
RUN npm install --omit=dev

COPY servers.json entrypoint.js ./

EXPOSE 8101

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD wget -q -O- http://127.0.0.1:8101/health >/dev/null || exit 1

CMD ["node", "entrypoint.js"]
