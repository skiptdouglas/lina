#!/usr/bin/env bash
# Drive the Sprint 1 workflow (brief §59) against a running TRACE stack.
#
#   TRACE_TOKEN=<token from .env> ./scripts/smoke_sprint1.sh
#
# Exercises: create case -> upload evidence -> SHA-256 -> stored -> listed
#            -> verify -> VERIFIED -> chain of custody intact.
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

printf '\n\033[32mSprint 1 workflow passed.\033[0m\n'
