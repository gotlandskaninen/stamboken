#!/bin/sh
set -e

# Start RustFS server in the background (its own /entrypoint.sh sets up /data
# and /logs).
/entrypoint.sh rustfs &

# Wait until RustFS is up
until curl --output /dev/null --silent --head --fail http://127.0.0.1:9000/health; do
    printf '.'
    sleep 1
done

# Create the bucket using the S3_BUCKET environment variable. PUT is
# idempotent (a repeat call against an already-owned bucket still returns
# 200), so this is safe to re-run against an existing ./s3data on restart.
curl -sS --fail-with-body -X PUT \
    --aws-sigv4 "aws:amz:${RUSTFS_REGION:-us-east-1}:s3" \
    --user "${RUSTFS_ACCESS_KEY}:${RUSTFS_SECRET_KEY}" \
    "http://127.0.0.1:9000/${S3_BUCKET:-test}" || true

# Keep RustFS in foreground
wait
