#!/usr/bin/env bash
# Drive the TRACE workflow end to end against a running stack.
#
#   TRACE_TOKEN=<token from .env> ./scripts/smoke.sh
#
# Exercises: create case -> upload evidence -> SHA-256 -> stored -> listed
#            -> verify -> VERIFIED -> chain of custody intact
#            -> parse -> normalized events -> search -> timeline
#            -> original record bytes -> anchor -> offline proof verification.
set -euo pipefail

API="${TRACE_API_URL:-http://localhost:8000/api/v1}"
TOKEN="${TRACE_TOKEN:-}"
CASE_ID="${TRACE_CASE_ID:-CASE-DEMO-001}"
DATA_DIR="${TRACE_DATA_DIR:-sample-data/case-demo-001}"

if [[ -z "$TOKEN" ]]; then
  echo "TRACE_TOKEN is not set. Find it in .env (TRACE_API_TOKENS) or run 'make init'." >&2
  exit 2
fi

auth=(-H "Authorization: Bearer ${TOKEN}")
step() { printf '\n\033[36m==>\033[0m %s\n' "$1"; }
fail() { printf '\033[31mFAIL:\033[0m %s\n' "$1" >&2; exit 1; }

command -v jq >/dev/null || fail "jq is required"

step "Checking that TRACE is up"
curl -fsS "${API%/api/v1}/health" | jq -e '.status == "ok"' >/dev/null || fail "API is not healthy"

step "Generating synthetic evidence if needed"
[[ -d "$DATA_DIR" ]] || python3 scripts/generate_demo_data.py --out "$DATA_DIR"

step "Creating ${CASE_ID}"
create_body=$(jq -n --arg id "$CASE_ID" \
  '{title:"Phishing to lateral movement", description:"Synthetic demonstration incident.", severity:"CRITICAL", case_id:$id}')
http_code=$(curl -sS -o /tmp/trace-case.json -w '%{http_code}' "${auth[@]}" \
  -H 'Content-Type: application/json' -X POST "$API/cases" -d "$create_body")
if [[ "$http_code" == "409" ]]; then
  echo "    case already exists — continuing"
elif [[ "$http_code" != "201" ]]; then
  fail "case creation returned $http_code: $(cat /tmp/trace-case.json)"
fi

artifact="$DATA_DIR/sysmon-operational.jsonl"
expected_sha=$(sha256sum "$artifact" | cut -d' ' -f1)
step "Uploading $(basename "$artifact") (local sha256: ${expected_sha:0:16}…)"
curl -fsS "${auth[@]}" -X POST "$API/evidence" \
  -F "file=@${artifact}" \
  -F "case_id=${CASE_ID}" \
  -F "source=FINANCE-LAPTOP-07" \
  -F "source_type=SYSMON" \
  -F "acquisition_method=LOG_EXPORT" \
  -F 'original_path=C:\Windows\System32\winevt\Logs\Sysmon.evtx' \
  > /tmp/trace-evidence.json

evidence_id=$(jq -r '.evidence_id' /tmp/trace-evidence.json)
stored_sha=$(jq -r '.sha256' /tmp/trace-evidence.json)
[[ "$stored_sha" == "$expected_sha" ]] || fail "TRACE recorded a different digest: $stored_sha"
echo "    evidence_id: $evidence_id"
echo "    digest matches the local file"

step "Confirming the evidence appears in the case"
count=$(curl -fsS "${auth[@]}" "$API/evidence?case_id=${CASE_ID}" | jq '.total')
[[ "$count" -ge 1 ]] || fail "evidence is not listed against the case"
echo "    ${count} object(s) attached to ${CASE_ID}"

step "Verifying evidence integrity"
curl -fsS "${auth[@]}" "$API/evidence/${evidence_id}/verify" > /tmp/trace-verify.json
jq -e '.verified == true and .result == "VERIFIED"' /tmp/trace-verify.json >/dev/null \
  || fail "verification did not return VERIFIED: $(cat /tmp/trace-verify.json)"
jq -r '"    expected: \(.expected_hash)\n    actual:   \(.actual_hash)\n    result:   \(.result)"' \
  /tmp/trace-verify.json

step "Checking the chain of custody"
curl -fsS "${auth[@]}" "$API/audit?case_id=${CASE_ID}" | \
  jq -r '"    " + ([.items[].action] | unique | join(", "))'
curl -fsS "${auth[@]}" "$API/audit/verify-chain" | \
  jq -e '.verified == true' >/dev/null || fail "audit chain is broken"
echo "    chain verified"

step "Anchoring the transparency log"
if curl -fsS "${auth[@]}" "$API/anchoring/log" > /tmp/trace-log.json 2>/dev/null; then
  jq -r '"    log \(.log_id): \(.tree_size) entr(ies), \(.unanchored_entries) unanchored"' /tmp/trace-log.json
  jq -r '"    signing key \(.signing_key_id)"' /tmp/trace-log.json

  anchor_code=$(curl -sS -o /tmp/trace-anchor.json -w '%{http_code}' "${auth[@]}" \
    -H 'Content-Type: application/json' -X POST "$API/anchors" -d '{}')
  if [[ "$anchor_code" == "201" ]]; then
    jq -r '"    anchored tree size \(.tree_size) to \(.backend) [\(.independence)] -> \(.status)"' /tmp/trace-anchor.json
  elif [[ "$anchor_code" == "409" ]]; then
    echo "    already anchored at this tree size"
  else
    fail "anchoring returned $anchor_code: $(cat /tmp/trace-anchor.json)"
  fi

  step "Exporting a proof bundle and verifying it offline"
  curl -fsS "${auth[@]}" "$API/evidence/${evidence_id}/proof" > /tmp/trace-proof.json
  key_id=$(jq -r '.signature.key_id' /tmp/trace-proof.json)
  python3 scripts/verify_anchor.py /tmp/trace-proof.json \
      --evidence-file "$artifact" --expect-key-id "$key_id" --no-colour \
    || fail "offline verification failed"
else
  echo "    anchoring is not enabled on this deployment — skipping"
fi

step "Parsing the artifact into normalized events"
parse_code=$(curl -sS -o /tmp/trace-parse.json -w '%{http_code}' "${auth[@]}" \
  -H 'Content-Type: application/json' -X POST "$API/ingestion/parse/${evidence_id}" -d '{"force":true}')
if [[ "$parse_code" == "200" ]]; then
  jq -r '"    \(.parser_id): \(.events_produced) event(s) from \(.records_read) record(s), \(.unrecognised) unrecognised"' /tmp/trace-parse.json
  events=$(jq -r '.events_produced' /tmp/trace-parse.json)
  [[ "$events" -gt 0 ]] || fail "parsing produced no events"
else
  fail "parsing returned $parse_code: $(cat /tmp/trace-parse.json)"
fi

step "Searching normalized events"
curl -fsS "${auth[@]}" -H 'Content-Type: application/json' \
  -X POST "$API/search" -d '{"query":"powershell"}' > /tmp/trace-search.json
jq -r '"    \(.total) hit(s) in \(.took_ms)ms via backend \"\(.backend.name)\" (fuzzy: \(.backend.fuzzy))"' /tmp/trace-search.json

step "Reconstructing the case timeline"
curl -fsS "${auth[@]}" "$API/cases/${CASE_ID}/timeline?limit=500" > /tmp/trace-timeline.json
jq -r '"    \(.total) event(s), clock corrections applied: \(.clock_corrections_applied)"' /tmp/trace-timeline.json
jq -r '.entries[:6][] | "      \(.event.timestamp[11:19])  \(.event.event_type)"' /tmp/trace-timeline.json

step "Walking one event back to its original bytes"
ref=$(jq -r '.entries[0].event.raw_reference' /tmp/trace-timeline.json)
ev_id=$(jq -r '.entries[0].event.evidence_id' /tmp/trace-timeline.json)
curl -fsS "${auth[@]}" "$API/evidence/${ev_id}/record?reference=${ref}" > /tmp/trace-record.json
echo "    locator ${ref} ->"
jq -c '.' /tmp/trace-record.json | head -c 200 | sed 's/^/      /'
echo

printf '\n\033[32mTRACE workflow passed.\033[0m\n'
