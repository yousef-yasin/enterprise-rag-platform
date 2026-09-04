#!/usr/bin/env bash
# Golden end-to-end flow against a running stack (docs/ARCHITECTURE.md §33, §38):
#   register/login -> create KB -> upload a fixture -> poll to `ready`
#   -> POST /chat -> assert an answer with a valid citation to the fixture.
#
# Uses the API through the frontend nginx proxy (same origin the browser uses).
# Requires: curl, jq.
set -euo pipefail

BASE="${E2E_BASE_URL:-http://127.0.0.1:8080}"
API="$BASE/api/v1"
EMAIL="smoke+$(date +%s)@example.com"
PASSWORD="smoke-password-123"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }

say "waiting for $BASE/healthz"
for _ in $(seq 1 60); do
  curl -fsS "$BASE/healthz" >/dev/null 2>&1 && break || sleep 2
done

say "register + login ($EMAIL)"
curl -fsS -X POST "$API/auth/register" -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"display_name\":\"Smoke\"}" >/dev/null \
  || echo "register returned non-2xx (open registration may be off) — continuing to login"

TOKEN="$(curl -fsS -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" | jq -r .access_token)"
[ -n "$TOKEN" ] && [ "$TOKEN" != "null" ] || fail "no access token"
AUTH=(-H "authorization: Bearer $TOKEN")

say "create knowledge base"
KB_ID="$(curl -fsS -X POST "$API/knowledge-bases" "${AUTH[@]}" -H 'content-type: application/json' \
  -d '{"name":"Smoke KB","slug":"smoke-kb"}' | jq -r .id)"
[ -n "$KB_ID" ] && [ "$KB_ID" != "null" ] || fail "no KB id"

say "upload fixture document"
FIXTURE="$(mktemp --suffix=.md)"
cat > "$FIXTURE" <<'EOF'
# Employee Handbook

## Time off
Full-time employees receive 25 days of paid annual leave per year, accrued monthly.

## Code of conduct
Harassment of any kind results in disciplinary action up to termination.
EOF
DOC_ID="$(curl -fsS -X POST "$API/knowledge-bases/$KB_ID/documents" "${AUTH[@]}" \
  -F "file=@$FIXTURE;type=text/markdown;filename=handbook.md" | jq -r .id)"
[ -n "$DOC_ID" ] && [ "$DOC_ID" != "null" ] || fail "no document id"

say "poll document until ready"
STATUS=""
for _ in $(seq 1 90); do
  STATUS="$(curl -fsS "$API/documents/$DOC_ID" "${AUTH[@]}" | jq -r .status)"
  case "$STATUS" in
    ready|partially_indexed) break ;;
    failed) fail "ingestion failed: $(curl -fsS "$API/documents/$DOC_ID" "${AUTH[@]}" | jq -r .failure_reason)" ;;
  esac
  sleep 2
done
[ "$STATUS" = "ready" ] || [ "$STATUS" = "partially_indexed" ] || fail "document never became ready (last: $STATUS)"

say "ask a grounded question"
ANSWER_JSON="$(curl -fsS -X POST "$API/chat" "${AUTH[@]}" -H 'content-type: application/json' \
  -d "{\"knowledge_base_id\":\"$KB_ID\",\"message\":\"How much paid leave do employees get?\"}")"
echo "$ANSWER_JSON" | jq '{abstained, citations: (.citations|length), answer}'

ABSTAINED="$(echo "$ANSWER_JSON" | jq -r .abstained)"
N_CITED="$(echo "$ANSWER_JSON" | jq '[.citations[] | select(.was_cited)] | length')"
[ "$ABSTAINED" = "false" ] || fail "the system abstained on an answerable question"
[ "$N_CITED" -ge 1 ] || fail "answer had no valid citation"

say "golden flow passed ✔"
