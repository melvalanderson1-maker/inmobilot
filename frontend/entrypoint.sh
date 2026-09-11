#!/bin/sh
set -e

cat <<EOF > /usr/share/nginx/html/env.json
{
  "apiUrl": "${API_URL:-http://localhost:8000}"
}
EOF

exec nginx -g "daemon off;"