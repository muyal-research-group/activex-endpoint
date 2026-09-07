#!/usr/bin/env bash
set -euo pipefail

# Removes every document matching one account_id from xolo's users,
# scope_user, and licenses collections -- e.g. to wipe out a test account
# without touching any other account's data. Talks to Mongo via a throwaway
# `mongo:8-noble` container on --network host, matching XOLO_MONGODB_PUBLIC_PORT
# (deploy/env/compose.env) rather than assuming any particular xolo-mongodb
# container name -- works whether the mongo container is running locally,
# in docker-compose, or standalone, as long as it's reachable on that port.

usage() {
  echo "Usage: $0 [account_id] [--yes] [--dry-run]"
  echo ""
  echo "  account_id   Account to purge (default: ${DEFAULT_ACCOUNT_ID})"
  echo "  --yes, -y    Skip the confirmation prompt"
  echo "  --dry-run    Only show matching document counts, delete nothing"
  echo ""
  echo "Env overrides: XOLO_MONGODB_PUBLIC_PORT (default 27018),"
  echo "               XOLO_MONGO_DB (default xolo),"
  echo "               XOLO_MONGO_IMAGE (default mongo:8-noble)"
}

DEFAULT_ACCOUNT_ID="axo-2eeaaade566b762cfaaa28e9a3318bc0"
MONGO_PORT="${XOLO_MONGODB_PUBLIC_PORT:-27018}"
MONGO_DB="${XOLO_MONGO_DB:-xolo}"
MONGO_IMAGE="${XOLO_MONGO_IMAGE:-mongo:8-noble}"
COLLECTIONS=(users scope_user licenses)

ACCOUNT_ID="$DEFAULT_ACCOUNT_ID"
ASSUME_YES=false
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --yes|-y)   ASSUME_YES=true ;;
    --dry-run)  DRY_RUN=true ;;
    help|--help|-h) usage; exit 0 ;;
    -*) echo "Unknown option: $arg"; usage; exit 1 ;;
    *)  ACCOUNT_ID="$arg" ;;
  esac
done

run_mongo_eval() {
  docker run --rm --network host "$MONGO_IMAGE" \
    mongosh --quiet "mongodb://localhost:${MONGO_PORT}/${MONGO_DB}" --eval "$1"
}

echo "Mongo:      localhost:${MONGO_PORT} (db=${MONGO_DB})"
echo "account_id: ${ACCOUNT_ID}"
echo ""
echo "Matching documents:"
for col in "${COLLECTIONS[@]}"; do
  count="$(run_mongo_eval "db.getCollection('${col}').countDocuments({account_id: '${ACCOUNT_ID}'})")"
  echo "  ${col}: ${count}"
done

if $DRY_RUN; then
  echo ""
  echo "Dry run -- nothing deleted."
  exit 0
fi

if ! $ASSUME_YES; then
  echo ""
  read -r -p "Delete these documents? [y/N] " confirm
  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

echo ""
echo "Deleting:"
for col in "${COLLECTIONS[@]}"; do
  result="$(run_mongo_eval "printjson(db.getCollection('${col}').deleteMany({account_id: '${ACCOUNT_ID}'}))")"
  deleted="$(echo "$result" | grep -o "deletedCount: [0-9]*" | grep -o "[0-9]*" || echo "?")"
  echo "  ${col}: deleted ${deleted}"
done

echo ""
echo "Done."
