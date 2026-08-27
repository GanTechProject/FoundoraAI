FROM node:24.19.0-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43

ENV NODE_ENV=production \
    FOUNDORA_SANDBOX_RUNNER_HOST=0.0.0.0 \
    FOUNDORA_SANDBOX_RUNNER_PORT=8080 \
    FOUNDORA_SANDBOX_RECEIPT_PATH=/var/lib/foundora-sandbox/receipts \
    FOUNDORA_SANDBOX_ENGINE_SOCKET=/var/run/docker.sock \
    FOUNDORA_SANDBOX_RUNTIME_IMAGE=foundora-sandbox-runtime:phase22

WORKDIR /opt/foundora/sandbox-runner

COPY apps/sandbox-runner/package.json apps/sandbox-runner/package-lock.json ./
RUN apk add --no-cache --upgrade \
        libcrypto3=3.5.8-r0 \
        libssl3=3.5.8-r0 \
        openssl=3.5.8-r0 \
    && npm ci --omit=dev --ignore-scripts \
    && npm cache clean --force \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx

COPY apps/sandbox-runner/src ./src
COPY apps/sandbox-runner/test ./test
COPY apps/sandbox-runtime/seccomp-profile.json /opt/foundora/sandbox/seccomp-profile.json
COPY apps/sandbox-runtime/fixtures /opt/foundora/sandbox-fixtures

RUN addgroup -S -g 10001 foundora \
    && adduser -S -D -H -u 10001 -G foundora foundora \
    && mkdir -p /var/lib/foundora-sandbox/receipts \
    && chown -R foundora:foundora /opt/foundora/sandbox-runner /var/lib/foundora-sandbox

LABEL org.foundora.component="sandbox-runner" \
      org.foundora.sandbox.protocol="1"

USER foundora

EXPOSE 8080

CMD ["node", "src/server.mjs"]
