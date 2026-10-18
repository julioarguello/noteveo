#!/usr/bin/env bash
# dev-secret-scan.sh — the credential gate, and the proof that it works.
#
# SHARED, AND MAINTAINED CENTRALLY. Delivered into `scripts/` alongside `gitleaks-base.toml`;
# every repository of this family carries the same two copies. Fix it where it is authored, not
# here: the next delivery either overwrites this copy or reports it as a conflict and stops
# updating it.
#
# WHAT THE REPOSITORY OWNS, AND WHAT THIS FILE OWNS
#
#   scripts/gitleaks-base.toml     the family's two rules      — shared, delivered
#   scripts/dev-secret-scan.sh     the phases below            — shared, delivered
#   .gitleaks.toml                 `[extend] path` + the exemptions THIS corpus needs
#   .gitleaks-fixtures/<slug>.<x>  one green fixture per exemption, named by its `Fixture:`
#
# An exemption lives in the repository, never in the base, because it is an argument about a
# corpus: it is only believable where it was measured. It also has to be load-bearing, and
# phase 1d is what settles that — delete the block, and the fixture that names it must go red.
#
# THE PHASES, IN THIS ORDER AND FOR A REASON
#
#   PHASE 1   plants a credential of every shape this family is known to leak and asserts the
#             gate goes RED on each — red under a rule of OURS, not only under the generic
#             entropy rule, which is too easy to fall under. A check nobody has seen fail is
#             not a gate, so this runs first and on every invocation, CI included.
#   PHASE 1b  plants every LEGITIMATE shape and asserts the gate stays GREEN: the shapes the
#             base exempts for the whole family, and this repository's own fixtures.
#   PHASE 1c  builds a throwaway repository with one commit that adds a credential and one
#             that removes it, and asserts the tree scan is GREEN (that is the hole) and the
#             history scan is RED (that is what closes it).
#   PHASE 1d  deletes each exemption in turn — in the repository's config and in the base —
#             and asserts the fixture that names it goes RED. An exemption that covers nothing
#             cannot pass this phase, and a fixture no exemption names fails it too.
#   PHASE 2   scans the tree: what git tracks plus what it would add, never what `.gitignore`
#             hides. Ignored files are where a developer's own credentials legitimately live
#             (`config/.prd.env`, `*.env`, a downloaded service account), and `gitleaks dir .`
#             reads them. The set is copied to a temporary directory and scanned there.
#   PHASE 3   scans the history, every ref. A credential committed and then "removed" is still
#             in the history it was removed from. A shallow clone is REFUSED, not skipped: it
#             would make this phase pass for want of data.
#
# Whatever the history already carries is exempted by its COMMIT in `.gitleaks.toml`, with the
# finding written beside the SHA — never by `--baseline-path`, because a gitleaks baseline
# stores each finding's `Secret` and committing one puts the credential back into the tree.
#
# Every value below is INVENTED and has the right shape. Fixtures are generated into a
# temporary directory, so the tree the gate scans never contains a planted secret; this file
# is exempted by path in the base config because it holds them as text.

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}✔${NC} $*"; }
fail() { echo -e "${RED}✖${NC} $*" >&2; FAILED=1; }
FAILED=0

# git exports GIT_DIR into EVERY hook, and with GIT_DIR set but GIT_WORK_TREE unset git treats
# the CURRENT directory as the work tree. The `rev-parse --show-toplevel` below would then
# return this script's own directory instead of the repository root — and because the command
# SUCCEEDS, the `||` fallback never fires. The gate dies reporting "this repository has not
# adopted the gate", which sends the reader to the configuration when the fault is the
# environment. Measured 2026-09-14 running the gate from a pre-commit hook.
#
# None of the three is set in an ordinary invocation, so clearing them costs nothing and makes a
# hook behave exactly like a shell. GIT_INDEX_FILE is cleared too: during a PARTIAL commit
# (`git commit --only <path>`) it names a temporary index holding just that subset, and reading
# the real index instead scans a superset — which can only add findings, never hide one.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || (cd "$HERE/.." && pwd))"
CONFIG="$ROOT/.gitleaks.toml"
BASE_REL='scripts/gitleaks-base.toml'
BASE="$ROOT/$BASE_REL"
FIXDIR="$ROOT/.gitleaks-fixtures"
OWN_RULES='yoda-credential-key-in-clear|yoda-credential-inside-a-value'
PINNED='8.30.1'   # the version CI installs; the rule set travels with the version

if ! command -v gitleaks >/dev/null 2>&1; then
    fail "gitleaks is not installed — the gate cannot run."
    echo "    macOS:  brew install gitleaks" >&2
    echo "    linux:  curl -sSfL https://github.com/gitleaks/gitleaks/releases/download/v${PINNED}/gitleaks_${PINNED}_linux_x64.tar.gz | tar -xz -C /usr/local/bin gitleaks" >&2
    exit 1
fi
[[ -f "$CONFIG" ]] || {
    fail "no .gitleaks.toml at $ROOT — this repository has not adopted the gate."
    echo "    It needs a .gitleaks.toml with:  [extend]  path = \"$BASE_REL\"" >&2
    exit 1
}
[[ -f "$BASE" ]] || {
    fail "no $BASE_REL — the family's rules are missing and only the generic ones would run."
    echo "    It is delivered alongside this script — restore it from the copy that shipped them." >&2
    exit 1
}
installed="$(gitleaks version 2>/dev/null | tr -d '[:space:]')"
[[ "$installed" == "$PINNED" ]] || echo -e "${YELLOW}! gitleaks ${installed} here, ${PINNED} in CI — the default rule set may differ${NC}" >&2

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

count() {  # count <report.json> -> number of findings. `grep -c` exits 1 on zero matches under pipefail.
    { grep -o '"RuleID"' "$1" 2>/dev/null || true; } | wc -l | tr -d ' '
}

# gitleaks resolves `extend.path` against the WORKING DIRECTORY, not against the config that
# declares it, so every invocation runs from a directory where `scripts/gitleaks-base.toml`
# resolves: the repository root, or — in phase 1d — a temporary root holding a mutated base.
#
# gitleaks exits 0 on an ERROR, not only on a clean scan. Measured on 8.30.1: `gitleaks git`
# against a repository it cannot read prints an `ERR` line, writes an EMPTY report and returns
# 0 — with `--exit-code 0` and without it. So neither the exit status nor the report's presence
# can tell "found nothing" from "did not look". The report was also never removed between
# phases, so a scan that wrote nothing left the PREVIOUS phase's clean report to be counted as
# this one's result. That is the false green this whole file exists to prevent, and it was
# guarded for a shallow clone and nowhere else.
_gitleaks() {  # _gitleaks <cwd> <subcommand> <target> <config> -> findings; report in $TMP/report.json
    rm -f "$TMP/report.json" "$TMP/stderr.txt"
    ( cd "$1" && gitleaks "$2" "$3" --config "$4" --no-banner --report-format json \
        --report-path "$TMP/report.json" --exit-code 0 >/dev/null 2>"$TMP/stderr.txt" ) || true
    if [[ ! -f "$TMP/report.json" ]] || grep -qE '(^|[^A-Za-z])ERR([^A-Za-z]|$)' "$TMP/stderr.txt"; then
        fail "gitleaks did not complete — a zero here would mean 'it did not look', not 'it found nothing':"
        sed 's/^/    /' "$TMP/stderr.txt" >&2
        echo -e "${RED}dev-secret-scan failed${NC}" >&2
        exit 1
    fi
    count "$TMP/report.json"
}
scan_at()  { _gitleaks "$1" dir "$2" "${3:-$CONFIG}"; }        # scan_at <cwd> <dir> [config]
scan()     { scan_at "$ROOT" "$@"; }
scan_git() { _gitleaks "$ROOT" git "$1" "${2:-$CONFIG}"; }     # scan_git <repo> [config]

# A configuration error must not read as "nothing found". gitleaks exits non-zero and says why;
# the scans above discard that, so it is asked once, here, before any of them runs.
mkdir -p "$TMP/empty"
if ! err="$( cd "$ROOT" && gitleaks dir "$TMP/empty" --config "$CONFIG" --no-banner --exit-code 0 2>&1 >/dev/null )"; then
    fail "the configuration does not load — every scan below would report zero for that reason alone:"
    echo "$err" | sed 's/^/    /' >&2
    echo -e "${YELLOW}    A repository config extending the base must NOT also set extend.useDefault:${NC}" >&2
    echo -e "${YELLOW}    the base sets it, and gitleaks refuses both at once.${NC}" >&2
    exit 1
fi

# ── PHASE 1. The gate must go red on each of these ──────────────────────────
# One case per way a credential has actually been written in this family, so a regression in
# any single one is named rather than hidden inside a total. a–f are the documentation site's
# catalogue shapes; g–l are a source repository's: a shell export in a Markdown fence (the one
# real finding in the toolkit's history had exactly this shape), a Python keyword argument and
# a Python assignment, a `.cfg` line, a quoted `.env` line, and a JWT.
mkdir -p "$TMP/red"
cat > "$TMP/red/a_plain_api_key.json"       <<'J'
{ "work_OCADO_API_key": "7f3a9c21-4d8e-4b17-9f52-c6a1e0b83d94" }
J
cat > "$TMP/red/b_uuid_under_ref.json"      <<'J'
{ "gravitee_key_ref": "b81c47de-2f60-4a93-8e15-7d0c9a4b62f1" }
J
cat > "$TMP/red/c_non_credential_name.json" <<'J'
{ "work_SMART_IGW_APIM_API_quota_user": "Kq7Zx2Vn9Lp4Rt6Ys8Wb1Dc3Fg5Hj0Mk2Nq4Pv6" }
J
cat > "$TMP/red/d_term_in_the_middle.json"  <<'J'
{ "work_OSP_API_TOKEN_client_secret_refund_receipt": "Xj4Nq8Rv2Bz6Ld0Ft3Hs7Kw1Mc5Py9Ga3Ue7Ir1" }
J
cat > "$TMP/red/e_gravitee_family.json"     <<'J'
{ "work_OSP_IGW_APIM_API_lockers_gravitee_key": "3e9d16ba-8c74-4f02-b5a1-9027debc4f38" }
J
cat > "$TMP/red/f_inside_the_value.json"    <<'J'
{ "work_PROBE_API_TOKEN_additional_param": "&username\\=probe_api_integration%40example.invalid&password\\=Rk3Zt8Wq1Mv5Ly9Bn2Cd6Hs4Jp0Xg7Ue" }
J
cat > "$TMP/red/g_export_in_a_fence.md"     <<'M'
# 6.1. API Key (Secret)

```bash
export JAWA_PROBE__API_KEY=7f3a9c21-4d8e-4b17-9f52-c6a1e0b83d94
```

> **Never commit the API key** to version-controlled files.
M
cat > "$TMP/red/h_python_keyword_argument.py" <<'P'
executor = GraviteeProbeExecutor(url=url, api_key="7f3a9c21-4d8e-4b17-9f52-c6a1e0b83d94")
P
cat > "$TMP/red/i_python_assignment.py"     <<'P'
api_key = "Kq7Zx2Vn9Lp4Rt6Ys8Wb1Dc3Fg5Hj0Mk2Nq4Pv6"
P
cat > "$TMP/red/j_cfg_line.cfg"             <<'C'
work_SMART_IGW_APIM_API_key = 3e9d16ba-8c74-4f02-b5a1-9027debc4f38
C
cat > "$TMP/red/k_quoted_env_line.env"      <<'E'
JAWA_PROBE__API_KEY="7f3a9c21-4d8e-4b17-9f52-c6a1e0b83d94"
E
# A JWT is dots between base64 runs, and a dotted-name exemption must not swallow it. The
# header and payload decode to {"alg":"HS256","typ":"JWT"} and {"sub":"probe","iat":1700000000};
# the signature is invented, so nothing signed this.
cat > "$TMP/red/l_jwt_under_access_token.env" <<'E'
JAWA_ACCESS_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJwcm9iZSIsImlhdCI6MTcwMDAwMDAwMH0.Kq7Zx2Vn9Lp4Rt6Ys8Wb1Dc3Fg5Hj0Mk2Nq4Pv6
E

# A Felix reference is exempt because it names where the value lives instead of being it —
# and `base_felix_secret_pointer` says so in those words: "Anchored whole, so a
# pointer-shaped prefix in front of a real value is still a finding." Nothing exercised
# that sentence, and a repository that spells its own exemption as a prefix test inherits
# the sentence without the behaviour. Measured 2026-09-14 in es-ares-jawa-toolkit,
# gitleaks 8.30.1: its local `secret_reference` was `^\$\[`, and this exact line scored 0
# findings there while scoring 2 with the exemption removed. A credential went through the
# gate for starting the right way.
cat > "$TMP/red/m_pointer_prefixed_value.cfg" <<'C'
work_SMART_IGW_APIM_API_key = $[secret:smart-api-key]7f3b9c1e4a8d2f6b0c5e9a3d7b1f4e8c
C
# The same sentence, for the spelling the exemption gained on 2026-09-15: a pointer whose
# name is a path. Widening the name must not widen the anchor -- without this plant, a
# character class that grew to admit `/` would be trusted on the strength of a test that
# only ever ran against the one-segment form.
cat > "$TMP/red/n_path_pointer_prefixed_value.cfg" <<'C'
work_API_TOKEN_client_secret = $[secret:esp-route/work-api-token-client-secret]7f3b9c1e4a8d2f6b0c5e9a3d7b1f4e8c
C

# A client id, three ways. Until 2026-09-16 neither rule named `client_id` and `..._id` is not
# `..._key`, so a Talend context file holding only the id was reported clean by both of them;
# whether anything fired at all was left to the generic entropy rule, which does not reach a
# structured id. The standing criterion in this family is that the id IS a credential, because
# what decides is the object the value lives in and not what the OAuth specification calls
# public — the context files pair it with the client secret every time. Every value here is
# invented.
#
# Three plants and not one, because the two rules overlap and a single plant would leave half the
# change unproven. Measured while writing them: `o` alone stayed GREEN with `client[_-]?id`
# deleted from the KEY rule, because the VALUE rule reads an `=` too and was catching it.
#
#   o  the shape the routes checkout actually holds — the id alone in a `.properties` file,
#      33 characters, which is the length of the shorter of the two real ones. The value rule
#      is what carries it.
#   p  the id as a field inside a longer value, 10 characters on purpose: under the key rule's
#      sixteen-character floor, so ONLY the value rule can see it.
#   q  the id under a `:`, the shape the documentation site's catalogue is written in. The value
#      rule reads only `=`, so ONLY the key rule can see it — this is the plant the key rule's
#      half of the change rests on.
cat > "$TMP/red/o_client_id_alone.properties" <<'P'
context=UAT
work_API_TOKEN_client_id=Qw7Zr2Nv9Lp4Xt6Ys8Wb1Dc3Fg5Hj0Mk4
P
cat > "$TMP/red/p_client_id_inside_a_value.properties" <<'P'
work_PROBE_API_TOKEN_additional_param=&client_id\=Qw7Zr2Nv9L
P
cat > "$TMP/red/q_client_id_under_a_colon.json" <<'J'
{ "work_SMART_API_TOKEN_client_id": "Qw7Zr2Nv9Lp4Xt6Ys8Wb1Dc3Fg5Hj0Mk4" }
J

reds=0
for f in "$TMP"/red/*; do
    d="$TMP/one"; rm -rf "$d"; mkdir -p "$d"; cp "$f" "$d/"
    n="$(scan "$d")"
    if [[ "$n" -lt 1 ]]; then
        fail "the gate does NOT see $(basename "$f") — it would let this shape through"
    elif ! grep -qE "$OWN_RULES" "$TMP/report.json"; then
        fail "$(basename "$f") is caught only by the generic entropy rule, not by a rule of ours — too fragile to rely on"
    else
        reds=$((reds + 1))
    fi
done
planted=$(ls "$TMP"/red/* | wc -l | tr -d ' ')
[[ "$reds" -eq "$planted" ]] && pass "the gate goes red on all $planted planted credential shapes, each under a rule of ours"

# ── PHASE 1b. And it must stay green on every legitimate shape ──────────────
# One file per exemption, named after the `Fixture:` line of the block that exercises it, so
# phase 1d can pair them. These three are the base's, shared by the family; the repository's
# own live in .gitleaks-fixtures/ and are picked up beside them.
mkdir -p "$TMP/green/shared"
cat > "$TMP/green/shared/base_value_rule_shapes.properties" <<'P'
work_SLF_API_TOKEN_additional_param = &username\=<REDACTED>&password\=<REDACTED>
work_CAMEL_EXPRESSION_uri = /o?uploadType=media&access_token=${header.authorization}
mongodb.password=ENC(HsYRY7Kq2Lp9Xv4Bd3Fh6Jk1Ms5Cy0Ae)
amq.password=ENC(HsYRY7Kq2Lp9Xv4Bd3Fh6Jk1Ms5Cy0Ae)
P
cat > "$TMP/green/shared/base_key_rule_shapes.json" <<'J'
{
  "work_OCADO_API_key": "<REDACTED>",
  "work_OCADO_IGW_APIM_API_key": "[REDACTED]",
  "work_OSP_GRAVITEE_API_key": "Bitwarden = ESP_PRD_exports-osp-gravitee-api-key",
  "work_SMART_IGW_APIM_API_key": "BitWarden = ESP_PRD_smart-igw-apim-api-key-picking",
  "work_HYBRIS_IGW_APIM_API_key": "ENC\\:[gVwaj5sRt7Yx2Qn8Lm4Kp6Zc1Bd3Fh9Js5Aw0Ue7Ir2Ov4Ty8Gk6Nq3Pl1Xz5Cb7Mv9]",
  "api_key_ref": "context.work_OSP_GRAVITEE_API_key",
  "work_CAMEL_ACCESS_token": "${header.authorization}",
  "work_OSP_API_TOKEN_base_url": "https://api-gateway.internal.example.com/v1",
  "link_PROJECTINPUT_GBQ_credentials_name": "projects/esp-ares-jawa-prd/secrets/projectinput-sa",
  "work_OSP_API_TOKEN_grant_type": "client_credentials",
  "work_API_TOKEN_client_id": "<REDACTED>",
  "work_SMART_IGW_APIM_API_key_empty": ""
}
J
cat > "$TMP/green/shared/base_name_not_value.json" <<'J'
{
  "gravitee_key_ref": "work_SMART_API_TOKEN_gravitee_key",
  "work_OSP_API_TOKEN_host_ref": "api-gateway.internal.example.com",
  "work_YODA_OUT_IGW_SFTP_private_key_filepath": "/opt/yoda/keys/id_rsa_yoda_out",
  "link_PROJECTINPUT_GBQ_credentials_location": "./gcp/sa-projectinput.json"
}
J

cat > "$TMP/green/shared/base_dotted_name.py" <<'P'
api_key = settings.probe.api_key
client_id = settings.oauth.client_id
executor = GraviteeProbeExecutor(url=settings.probe.url, api_key=settings.probe.api_key)
P
cat > "$TMP/green/shared/base_dotted_name.ts" <<'T'
const username = env.AUTH_USERNAME || 'team';
const password = env.AUTH_PASSWORD;
T
cat > "$TMP/green/shared/base_call_expression.py" <<'P'
api_key = os.environ.get("GEMINI_API_KEY")
inner = GraviteeProbeExecutor(url=probe.url, api_key=subscription_key(probe, runtime))
P
cat > "$TMP/green/shared/base_tuple_expression.py" <<'P'
app_key = (app_ref.get('type'), app_ref.get('id'))
P

cat > "$TMP/green/shared/base_felix_secret_pointer.cfg" <<'P'
work_SMART_API_TOKEN_client_secret = $[secret:smart-api-client-secret]
work_SMART_IGW_APIM_API_key = $[secret:smart-api-key]
work_API_TOKEN_client_secret = $[secret:esp-sma-esp-companyupdate-smart2yoda/work-api-token-client-secret]
work_API_TOKEN_client_id = $[secret:esp-sma-esp-companyupdate-smart2yoda/work-api-token-client-id]
P
cat > "$TMP/green/shared/base_default_store_password.config" <<'P'
-Djavax.net.ssl.trustStorePassword=changeit
wrapper.java.additional.3=-Djavax.net.ssl.keyStorePassword=password
P

# GREEN BY SHAPE, NOT BY EXEMPTION. These carry no `Fixture:` marker and phase 1d does not pair
# them with one, because there is no block to delete: what keeps them green is the shape the rule
# itself requires — a separator, and then sixteen characters of value. They are the negative
# control of a rule that has just been widened. `client_id` reached both rules on 2026-09-16 and
# the field NAME is written far more often than the value is: an OpenAPI schema declares it, a
# runbook tells the reader to set it. Turning either of those red is how a gate stops being run,
# so both are scanned on every invocation rather than argued about once.
mkdir -p "$TMP/green/shape"
cat > "$TMP/green/shape/openapi_field_name_without_a_value.yaml" <<'Y'
components:
  schemas:
    TokenRequest:
      required: [client_id, client_secret]
      properties:
        client_id:
          type: string
          description: OAuth 2.0 client identifier issued by the gateway
        client_secret:
          type: string
          format: password
Y
cat > "$TMP/green/shape/doc_mention_without_a_value.md" <<'M'
Take `client_id` and `client_secret` from the Bitwarden entry for the environment
and set them in the context file; the gateway rejects a token request whose
client_id it does not know.
M

mkdir -p "$TMP/green/ours"
ours=0
if [[ -d "$FIXDIR" ]]; then
    for f in "$FIXDIR"/*; do
        [[ -f "$f" ]] || continue
        cp "$f" "$TMP/green/ours/"
        ours=$((ours + 1))
    done
fi

n="$(scan "$TMP/green")"
if [[ "$n" -ne 0 ]]; then
    fail "$n false positive(s) over the legitimate shapes — the gate would flag documentation or code:"
    grep -o '"File": "[^"]*"' "$TMP/report.json" | sed "s|$TMP/green/||; s/^/    /" | sort -u >&2
else
    shapes=$(ls "$TMP"/green/shape/* | wc -l | tr -d ' ')
    pass "no false positives over the family's legitimate shapes, its $shapes green-by-shape controls and this repository's $ours"
fi

# ── PHASE 1c. The history hole, demonstrated and closed ─────────────────────
HREPO="$TMP/hist"
mkdir -p "$HREPO"
(
    cd "$HREPO"
    git init -q .
    git config user.email gate@example.invalid
    git config user.name 'dev-secret-scan'
    printf '{ "work_PROBE_API_TOKEN_api_key": "Zt7Qw9Lp2Xr4Nv8Bd3Fh6Jk1Ms5Cy0Ae" }\n' > ctx.json
    git add ctx.json && git commit -q -m 'plant'
    git rm -q ctx.json && git commit -q -m 'remove it again'
) >/dev/null 2>&1

hole="$(scan "$HREPO")"
caught="$(scan_git "$HREPO")"
if [[ "$hole" -ne 0 ]]; then
    fail "the history fixture leaves the credential in its tree — the fixture is wrong, not the gate"
elif [[ "$caught" -lt 1 ]]; then
    fail "the history scan does NOT see a credential added and removed in one commit pair — phase 3 is not a gate"
else
    pass "a credential added and removed in one commit pair is invisible to the tree scan and caught by the history scan"
fi

# ── PHASE 1d. Every exemption is load-bearing, and every fixture is claimed ──
# For each `Fixture: <slug>` marker, write a copy of the config it lives in WITHOUT the block
# that carries it, and scan that fixture alone against it. Green there means the exemption
# covers nothing the fixture shows — a dead entry, or a fixture that exercises something else.
# Both are findings, and so is a marker with no fixture, or a fixture no marker claims.
without_block() {  # without_block <file> <marker> <out> — the file minus the block carrying <marker>
    awk -v marker="$2" '
        { L[NR] = $0; if ($0 ~ /^[ \t]*\[\[/) hdr[NR] = 1
          if (index($0, marker) && !bs) { for (i = NR; i > 0; i--) if (hdr[i]) { bs = i; break } } }
        END {
            if (!bs) exit 3
            be = NR; for (i = bs + 1; i <= NR; i++) if (hdr[i]) { be = i - 1; break }
            for (i = 1; i <= NR; i++) if (i < bs || i > be) print L[i]
        }' "$1" > "$3"
}
markers_in() { { grep -o 'Fixture: [A-Za-z0-9_-]*' "$1" || true; } | sed 's/^Fixture: //' | sort -u; }
fixture_for() {  # fixture_for <slug> -> the file that exercises it, if any
    local f
    for f in "$TMP"/green/shared/"$1".* "$TMP"/green/ours/"$1".*; do
        [[ -f "$f" ]] && { echo "$f"; return 0; }
    done
    return 1
}

mkdir -p "$TMP/mutroot/scripts"
held=0; claimed=""
for src in "$CONFIG" "$BASE"; do
    for slug in $(markers_in "$src"); do
        claimed="$claimed $slug"
        if ! f="$(fixture_for "$slug")"; then
            fail "$(basename "$src") names 'Fixture: $slug' and no such fixture exists — the exemption is unproven"
            continue
        fi
        d="$TMP/one"; rm -rf "$d"; mkdir -p "$d"; cp "$f" "$d/"
        if [[ "$src" == "$BASE" ]]; then
            without_block "$BASE" "Fixture: $slug" "$TMP/mutroot/$BASE_REL"
            mutated="$(scan_at "$TMP/mutroot" "$d")"
        else
            without_block "$CONFIG" "Fixture: $slug" "$TMP/mutated.toml"
            mutated="$(scan "$d" "$TMP/mutated.toml")"
        fi
        if [[ "$mutated" -lt 1 ]]; then
            fail "$slug stays GREEN without its exemption — the entry covers nothing this fixture shows; delete one or fix the other"
        else
            held=$((held + 1))
        fi
    done
done
for f in "$TMP"/green/shared/* "$TMP"/green/ours/*; do
    [[ -f "$f" ]] || continue
    slug="$(basename "$f")"; slug="${slug%.*}"
    case " $claimed " in
        *" $slug "*) ;;
        *) fail "$slug is a fixture no exemption names — add 'Fixture: $slug' to the block it proves, or delete it" ;;
    esac
done
[[ "$held" -gt 0 ]] && pass "each of the $held exemptions in force turns its fixture red when deleted"

# ── PHASE 2. The tree: what git tracks, plus what it would add ──────────────
TREE="$TMP/tree"; mkdir -p "$TREE"
(
    cd "$ROOT"
    git ls-files -z --cached --others --exclude-standard \
        | while IFS= read -r -d '' f; do [[ -f "$f" ]] && printf '%s\0' "$f"; done \
        | tar --null -T - -cf - | tar -xf - -C "$TREE"
)
n="$(scan "$TREE")"
if [[ "$n" -ne 0 ]]; then
    fail "$n clear-text credential(s) in the working tree:"
    grep -o '"File": "[^"]*"' "$TMP/report.json" | sed "s|$TREE/||; s/^/    /" | sort -u >&2
    echo -e "${YELLOW}    A value under a credential-shaped key must be a secret reference, <REDACTED>,${NC}" >&2
    echo -e "${YELLOW}    ENC(…), a Bitwarden pointer, an expression, a path, or empty.${NC}" >&2
else
    pass "no clear-text credentials in the $(find "$TREE" -type f | wc -l | tr -d ' ') files git tracks or would add"
fi

# ── PHASE 2b. What the next commit would actually contain ───────────────────
# `git commit` writes the INDEX. The copy above takes its CONTENT from the working tree —
# `git ls-files` yields names and `tar` reads the files on disk — so the ordinary sequence
# "git add, notice the credential, redact it in the editor, commit" passes phase 2 green while
# the staged blob, still holding the live value, goes into the commit. Reproduced 2026-09-14:
#     index    : client_secret: "Zq7…vT9"      <- what the commit would contain
#     worktree : client_secret: "<REDACTED>"   <- what phase 2 copied and scanned
# The hook was therefore bypassable by the most ordinary edit there is, and the next commit
# would then be blocked by phase 3 instead, telling the author the history needs rewriting.
#
# The set re-scanned is every file whose INDEX content differs from its working copy — which is
# `git diff --name-only`, and includes a file merely edited and not staged as well as one staged
# and then edited. Scanning the first kind is harmless (its index content is HEAD's, already
# covered), and separating the two would cost a second `git diff` to buy nothing. In CI, where
# the tree is a fresh checkout, the set is empty and this costs one `git diff`.
STAGED="$TMP/staged"; mkdir -p "$STAGED"
staged_n=0
while IFS= read -r -d '' f; do
    mkdir -p "$STAGED/$(dirname "$f")"
    git -C "$ROOT" show ":$f" > "$STAGED/$f" 2>/dev/null || continue
    staged_n=$((staged_n + 1))
done < <(git -C "$ROOT" diff -z --name-only --diff-filter=ACM 2>/dev/null)
if [[ "$staged_n" -eq 0 ]]; then
    pass "the index and the working tree agree — phase 2 saw exactly what a commit would contain"
else
    n="$(scan "$STAGED")"
    if [[ "$n" -ne 0 ]]; then
        fail "$n clear-text credential(s) in the INDEX — content phase 2 could not see:"
        grep -o '"File": "[^"]*"' "$TMP/report.json" | sed "s|$STAGED/||; s/^/    /" | sort -u >&2
        echo -e "${YELLOW}    The working tree is clean; the index is not. What you fixed in the editor was${NC}" >&2
        echo -e "${YELLOW}    never staged. Run \`git add\` on those files and commit again.${NC}" >&2
    else
        pass "the index content of the $staged_n file(s) that differ from the working tree is clean too"
    fi
fi

# ── PHASE 3. The history of this repository ─────────────────────────────────
# A shallow clone would make this phase pass for want of data, which is the false green this
# file exists to prevent, so it is refused rather than skipped. CI checks out with
# `fetch-depth: 0` for exactly this reason, and the commit count printed on success is how a
# CI log shows the depth took effect.
if [[ "$(git -C "$ROOT" rev-parse --is-shallow-repository 2>/dev/null)" == "true" ]]; then
    fail "this is a shallow clone — the history cannot be scanned, and a green here would mean nothing."
    echo "    git fetch --unshallow   (CI: actions/checkout with fetch-depth: 0)" >&2
else
    n="$(scan_git "$ROOT")"
    # gitleaks prints how many commits it walked. An errored scan says 0 while still writing an
    # empty report, so this is the one number that distinguishes "clean" from "did not look".
    # It is NOT equal to `rev-list --all --count` — measured 546 against git's 570 on this
    # corpus, gitleaks counting differently — so only "more than none" can be asserted, and the
    # line below reports both rather than presenting git's number as if gitleaks had produced it.
    walked="$(sed -n 's/.*[^0-9]\([0-9][0-9]*\) commits scanned.*/\1/p' "$TMP/stderr.txt" | tail -1)"
    commits="$(git -C "$ROOT" rev-list --all --count)"
    if [[ -z "$walked" || "$walked" -eq 0 ]] && [[ "$commits" -gt 0 ]]; then
        fail "gitleaks walked ${walked:-no} commits in a repository with $commits — the history was not scanned."
        sed 's/^/    /' "$TMP/stderr.txt" >&2
        echo -e "${RED}dev-secret-scan failed${NC}" >&2
        exit 1
    fi
    refs="$(git -C "$ROOT" for-each-ref | wc -l | tr -d ' ')"
    exempt="$( { grep -oE "[0-9a-f]{40}" "$CONFIG" || true; } | sort -u | wc -l | tr -d ' ')"
    if [[ "$n" -ne 0 ]]; then
        fail "$n clear-text credential(s) in the history, outside the $exempt commit(s) allowlisted in .gitleaks.toml:"
        grep -o '"Commit": "[^"]\{0,12\}' "$TMP/report.json" | sed 's/^/    /' | sort -u >&2
        echo -e "${YELLOW}    History is immutable: redacting the file in a new commit does not remove this.${NC}" >&2
        echo -e "${YELLOW}    Do not add the commit to the allowlist to get green — that is what the allowlist${NC}" >&2
        echo -e "${YELLOW}    is NOT for. Bring it to the issue that owns the gate.${NC}" >&2
    else
        pass "no clear-text credentials in the history ($walked of $commits commits walked, $refs refs) beyond the $exempt commit(s) named in .gitleaks.toml"
    fi
fi

echo
if [[ "$FAILED" -ne 0 ]]; then
    echo -e "${RED}dev-secret-scan failed${NC}" >&2; exit 1
fi
echo -e "${GREEN}dev-secret-scan passed${NC}"
