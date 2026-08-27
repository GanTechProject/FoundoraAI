FROM mcr.microsoft.com/playwright:v1.62.0-noble@sha256:baed2032d533817f3dbe6425de795788430ba345e819a1201337009ba17c9d07

ENV NODE_ENV=production \
    HOME=/home/pwuser

WORKDIR /opt/foundora/runtime

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts \
    && npm cache clean --force \
    && apt-get purge --auto-remove -y \
        gstreamer1.0-plugins-bad \
        libgstreamer-plugins-bad1.0-0 \
    && rm -rf \
        /usr/lib/node_modules/npm \
        /usr/bin/npm \
        /usr/bin/npx \
        /var/lib/apt/lists/*

COPY runtime.mjs runtime-manifest.json ./

LABEL org.foundora.sandbox.profile="static-website@1" \
      org.foundora.sandbox.harness-contract="1" \
      org.foundora.sandbox.build-manifest-sha256="ab73f13726b30608c83a212d7cf762ee2b74986f535680377560db69286d8601"

USER pwuser

ENTRYPOINT ["node", "/opt/foundora/runtime/runtime.mjs"]
