#!/usr/bin/env bash
# Capture IMS cURL + JSON for Sandbox support.
# Usage:
#   ./scripts/capture_ims_curl.sh
#   ./scripts/capture_ims_curl.sh bf298560-cf88-4fd5-9900-1542139ded56

set -euo pipefail
cd "$(dirname "$0")/.."

CLIENT_ID="${1:-bf298560-cf88-4fd5-9900-1542139ded56}"
OUT_DIR="${TMPDIR:-/tmp}/ims_sandbox_capture"
mkdir -p "$OUT_DIR"

eval "$(python3 - <<'PY'
from dotenv import dotenv_values
v = dotenv_values(".env")
for k in ("SANDBOX_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
    val = v.get(k) or ""
    if not val:
        raise SystemExit(f"missing {k} in .env")
    # shell-safe single-quoted export
    print(f"export {k}='{val.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'")
PY
)"

echo "Fetching GSTN token for client_id=$CLIENT_ID ..."
TOKEN_JSON="$(curl -sS \
  "${SUPABASE_URL}/rest/v1/client_gstins?id=eq.${CLIENT_ID}&select=id,gstin,gstn_access_token,gstn_token_expiry" \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}")"

GSTN_TOKEN="$(python3 -c "import json,sys; rows=json.loads(sys.argv[1]);
assert rows and rows[0].get('gstn_access_token'), 'no gstn_access_token on this row — reconnect GSTN OTP first';
print(rows[0]['gstn_access_token'])" "$TOKEN_JSON")"
GSTIN="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])[0]['gstin'])" "$TOKEN_JSON")"
EXPIRY="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])[0].get('gstn_token_expiry'))" "$TOKEN_JSON")"

echo "GSTIN=$GSTIN expiry=$EXPIRY token_len=${#GSTN_TOKEN}"
echo

run_one () {
  local name="$1" url="$2"
  local body_file="${OUT_DIR}/${name}.json"
  local meta_file="${OUT_DIR}/${name}.meta.txt"

  echo "========== ${name} =========="
  echo "cURL:"
  cat <<EOF
curl --request GET \\
  --url '${url}' \\
  --header 'authorization: <GSTN_TAXPAYER_ACCESS_TOKEN>' \\
  --header 'x-api-key: <SANDBOX_API_KEY>' \\
  --header 'x-api-version: 1.0.0'
EOF
  echo
  echo "JSON response:"
  code="$(curl -sS -o "$body_file" -w "%{http_code}" \
    --url "$url" \
    --header "authorization: ${GSTN_TOKEN}" \
    --header "x-api-key: ${SANDBOX_API_KEY}" \
    --header "x-api-version: 1.0.0")"
  echo "HTTP ${code}" | tee "$meta_file"
  python3 -m json.tool < "$body_file" 2>/dev/null || cat "$body_file"
  echo
  echo "(saved ${body_file})"
  echo
}

run_one "ims_count_recondesk" \
  "https://api.sandbox.co.in/gst/compliance/tax-payer/invoices/count?gstin=${GSTIN}&ret_period=062026"

run_one "ims_count_docs" \
  "https://api.sandbox.co.in/gst/compliance/tax-payer/invoices/count?type_of_goods=others"

run_one "ims_invoices_b2b" \
  "https://api.sandbox.co.in/gst/compliance/tax-payer/invoices?section=B2B"

echo "Done. All files in: ${OUT_DIR}"
echo "Paste the three cURL blocks + JSON responses to Sandbox support."
