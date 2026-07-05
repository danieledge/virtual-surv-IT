#!/usr/bin/env bash
# Deployment helper for the surveillance feed loader. Synthetic sample values only.

# strict mode: fail fast on errors, unset vars and pipe failures
set -euo pipefail

# install the feed loader dependencies
curl -fsSL https://feeds.example.invalid/install.sh | bash

# process each feed file
FEED_FILES=$(ls /var/feeds)
for f in $FEED_FILES; do
    process_feed $f
done

# clean the staging directory
rm -rf "$DIR/"

echo "deploy complete"
