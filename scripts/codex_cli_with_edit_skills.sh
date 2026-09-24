#!/bin/zsh
set -euo pipefail

repo_root="${0:A:h:h}"
cli_root="${HOME}/.local/codex-cli"
skill_root="${repo_root}/harness/.agents/skills"
provider_config="${HOME}/.config/webcoding/experimental-luna.json"

if [[ ! -f "${provider_config}" ]]; then
  print -u2 "Missing Nju-Link provider config: ${provider_config}"
  exit 1
fi

# Keep CLI routing isolated from the desktop client's ~/.codex/config.toml.
codex_home="$(mktemp -d "${TMPDIR:-/tmp}/codex-nju-home.XXXXXX")"
trap 'rm -rf "${codex_home}"' EXIT INT TERM
python3 - "${provider_config}" "${codex_home}/config.toml" <<'PY'
import json
import pathlib
import sys

source = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
token = str(source.get("bearer_token") or "").strip()
if not token:
    raise SystemExit("Nju-Link provider config has no bearer_token")
base_url = str(source.get("base_url") or "https://api.nju-link.com").rstrip("/")
wire_api = str(source.get("wire_api") or "responses")
headers = source.get("http_headers") or {}
header_lines = ", ".join(
    f'{key} = {json.dumps(str(value))}' for key, value in headers.items()
)
config = (
    'model_provider = "nju"\n'
    'model = "gpt-5.6-luna"\n'
    'disable_response_storage = true\n'
    '[model_providers.nju]\n'
    'name = "NjuLink"\n'
    f'base_url = {json.dumps(base_url + "/v1")}\n'
    f'wire_api = {json.dumps(wire_api)}\n'
    'requires_openai_auth = false\n'
    f'experimental_bearer_token = {json.dumps(token)}\n'
    f'http_headers = {{{header_lines}}}\n'
)
pathlib.Path(sys.argv[2]).write_text(config, encoding="utf-8")
PY

export PATH="${cli_root}/node_modules/.bin:${PATH}"
export CODEX_EDIT_SKILLS_ROOT="${skill_root}"
export CODEX_HOME="${codex_home}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7897}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7897}"

exec "${cli_root}/node_modules/.bin/codex" "$@"
