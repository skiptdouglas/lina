FROM node:22-alpine
WORKDIR /app
COPY package.json ./
COPY src ./src
COPY scripts ./scripts
ENV NODE_ENV=production DATA_DIR=/data
RUN mkdir /data && chown node /data
VOLUME /data
USER node
EXPOSE 8787
CMD ["node", "src/server.js"]
