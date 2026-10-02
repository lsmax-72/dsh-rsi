FROM node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6
RUN apt-get update && apt-get install -y --no-install-recommends bash git ripgrep python3 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/dsh
RUN npm init -y && npm install --save-exact @deepseek-ai/dsh@0.2.0-rc.2
RUN node /opt/dsh/node_modules/@deepseek-ai/dsh-subprocess-local/scripts/ensure-spawn-helper.mjs
COPY plugin /opt/rsi
WORKDIR /opt/rsi
RUN npm ci
COPY persistent.json oneshot.json /opt/rsi/scripts/
ENV PATH=/opt/dsh/node_modules/.bin:$PATH
ENV DSH_HOME=/state/home DSH_AGENTS_HOME=/state/agents HOME=/state/user
WORKDIR /workspace
USER node
