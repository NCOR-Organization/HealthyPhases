#!/bin/bash
set -e

# Use npm install instead of npm ci
npm install --legacy-peer-deps
npm run build 