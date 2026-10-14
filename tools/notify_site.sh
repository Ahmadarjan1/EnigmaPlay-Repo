#!/bin/sh
# Ask the website (EnigmaPlay-Source deploy-api.yml) to rebuild now that index.json changed, so new
# and updated plugins show on the site within minutes. Needs the SITE_DISPATCH_TOKEN secret
# (fine-grained token: EnigmaPlay-Source only, "Actions: read and write"). Without it nothing
# happens and the site keeps rebuilding on its own every 3 hours. Never fails the calling job.
if [ -z "$SITE_DISPATCH_TOKEN" ]; then
  echo "SITE_DISPATCH_TOKEN not set: the website rebuilds on its 3-hour schedule"
  exit 0
fi
SHA=$(git rev-parse HEAD)
if curl -fsS -o /dev/null -X POST \
     -H "Authorization: Bearer $SITE_DISPATCH_TOKEN" -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/Ahmadarjan1/EnigmaPlay-Source/actions/workflows/deploy-api.yml/dispatches \
     -d "{\"ref\":\"main\",\"inputs\":{\"index_sha\":\"$SHA\"}}"; then
  echo "::notice::website rebuild requested for $SHA"
else
  echo "::warning::website rebuild request failed (check SITE_DISPATCH_TOKEN); the 3-hour rebuild still runs"
fi
exit 0
