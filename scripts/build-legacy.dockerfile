# Dockerfile for building legacy frontend
# Replicates the pattern from tmp/theherdbook/.docker/frontend + .docker/main
#
# Usage: See build-legacy.sh

# Stage 1: Install node_modules (like .docker/frontend)
FROM node:24-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS deps

USER node
RUN mkdir /home/node/app

WORKDIR /home/node
COPY --chown=node:node package.json package-lock.json ./
# No install scripts from the dependency tree; esbuild's is the only one the
# build needs (older esbuild fetches its binary there).
RUN npm ci --ignore-scripts --legacy-peer-deps && node node_modules/esbuild/install.js

ENV PATH=/home/node/node_modules/.bin:$PATH

# Stage 2: Build (like .docker/main bundler stage)
FROM node:24-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS bundler

USER node
RUN mkdir /home/node/app
WORKDIR /home/node/app

COPY --chown=node:node . /home/node/app/
COPY --from=deps --chown=node:node /home/node/node_modules/ /home/node/app/node_modules/

RUN npm run build

# The built files are now in /home/node/app/dist/
# Images are in /home/node/app/public/images/
