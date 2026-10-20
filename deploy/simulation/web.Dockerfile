ARG NODE_IMAGE
FROM ${NODE_IMAGE}
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
ENV ALAP_API_ORIGIN=http://api:8000 NODE_ENV=production
RUN npm run build
EXPOSE 3000
CMD ["./node_modules/.bin/next", "start", "--hostname", "0.0.0.0"]
