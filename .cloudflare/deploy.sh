#!/bin/bash
set -e

echo "Node.js version: $(node -v)"
echo "NPM version: $(npm -v)"

echo "Installing dependencies with npm..."
npm ci

echo "Building site..."
npm run build 