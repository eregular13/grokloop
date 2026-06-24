#!/usr/bin/env bash
# Submit a goal to LocalGrokLoop
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
docker compose exec agent python -m main submit "$*"
echo "Goal submitted. Watch logs: docker compose logs -f agent"