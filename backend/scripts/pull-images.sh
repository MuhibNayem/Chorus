#!/bin/sh
# Pull all verification sandbox images so that _run_verification never
# blocks on a slow implicit docker pull.
#
# This script is meant to be run inside a container that has the Docker
# CLI and the host docker socket mounted (e.g. backend-api or backend-worker).

set -e

IMAGES="
${SWARM_VERIFY_IMAGE_PYTHON:-python:3.12-slim}
${SWARM_VERIFY_IMAGE_NODE:-node:20-bookworm}
${SWARM_VERIFY_IMAGE_GO:-golang:1.24}
${SWARM_VERIFY_IMAGE_JAVA:-maven:3.9.9-eclipse-temurin-21}
${SWARM_VERIFY_IMAGE_GRADLE:-gradle:8.5-jdk21}
${SWARM_VERIFY_IMAGE_RUST:-rust:1.75}
"

for img in $IMAGES; do
  if docker inspect "$img" > /dev/null 2>&1; then
    echo "[pull-images] $img already present — skipping"
  else
    echo "[pull-images] Pulling $img ..."
    docker pull "$img"
    echo "[pull-images] $img ready"
  fi
done

echo "[pull-images] All verification images are available."
