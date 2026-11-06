#!/bin/bash
# Build legacy frontend in a container and extract to nginx folder
# Pattern based on tmp/theherdbook/frontend/update-package-lock
#
# Usage:
#   ./scripts/build-legacy.sh                    # Build from local tmp/theherdbook
#   ./scripts/build-legacy.sh --all              # Build both prod and test from GitHub
#   ./scripts/build-legacy.sh --test             # Build test-prod branch only
#   ./scripts/build-legacy.sh --prod             # Build production branch only

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LEGACY_DIR="$PROJECT_ROOT/tmp/theherdbook/frontend"
REPO="gotlandskaninen/stamboken-legacy"

MODE="local"
while [[ $# -gt 0 ]]; do
	case "$1" in
	--all)
		MODE="all"
		shift
		;;
	--test)
		MODE="test"
		shift
		;;
	--prod)
		MODE="prod"
		shift
		;;
	-h | --help)
		echo "Usage: $0 [--all|--test|--prod]"
		echo ""
		echo "  (default)  Build from local tmp/theherdbook → nginx/legacy-frontend"
		echo "  --prod     Build production branch → nginx/legacy-frontend-prod"
		echo "  --test     Build test-prod branch → nginx/legacy-frontend-test"
		echo "  --all      Build both prod and test from GitHub"
		exit 0
		;;
	*)
		echo "Unknown option: $1"
		exit 1
		;;
	esac
done

build_frontend() {
	local source_dir="$1"
	local output_dir="$2"
	local label="$3"
	local image_name="herdbook-legacy-builder-${label}"
	local container_name="herdbook-legacy-extract-${label}"

	echo "========================================="
	echo "Building Legacy Frontend: $label"
	echo "  Source: $source_dir"
	echo "  Output: $output_dir"
	echo "========================================="

	docker build \
		--no-cache \
		-f "$SCRIPT_DIR/build-legacy.dockerfile" \
		-t "$image_name" \
		"$source_dir"

	# Remove old container if it exists
	docker rm "$container_name" 2>/dev/null || true

	echo "Extracting built files..."
	docker create --name "$container_name" "$image_name"

	mkdir -p "$output_dir"
	rm -rf "${output_dir:?}"/*

	docker cp "$container_name":/home/node/app/dist/. "$output_dir"/
	mkdir -p "$output_dir/images"
	docker cp "$container_name":/home/node/app/public/images/. "$output_dir/images/" 2>/dev/null || true

	docker rm "$container_name"

	echo "Built: $output_dir ($(find "$output_dir" -maxdepth 1 -not -name '.' | wc -l) files)"
}

clone_branch() {
	local branch="$1"
	local target_dir="$2"

	echo "Cloning $REPO branch $branch..."
	rm -rf "$target_dir"
	git clone --depth 1 --branch "$branch" "https://github.com/$REPO.git" "$target_dir"
}

if [ "$MODE" = "local" ]; then
	if [ ! -d "$LEGACY_DIR" ]; then
		echo "Error: Legacy frontend not found at $LEGACY_DIR"
		echo "Use --prod or --test to build from GitHub instead."
		exit 1
	fi
	build_frontend "$LEGACY_DIR" "$PROJECT_ROOT/nginx/legacy-frontend" "local"
else
	TMPDIR=$(mktemp -d)
	trap 'rm -rf "$TMPDIR"' EXIT

	if [ "$MODE" = "prod" ] || [ "$MODE" = "all" ]; then
		clone_branch "production" "$TMPDIR/prod"
		build_frontend "$TMPDIR/prod/frontend" "$PROJECT_ROOT/nginx/legacy-frontend-prod" "prod"
	fi

	if [ "$MODE" = "test" ] || [ "$MODE" = "all" ]; then
		clone_branch "test-prod" "$TMPDIR/test"
		build_frontend "$TMPDIR/test/frontend" "$PROJECT_ROOT/nginx/legacy-frontend-test" "test"
	fi
fi

echo ""
echo "========================================="
echo "Done!"
echo "========================================="
