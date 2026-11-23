#!/usr/bin/env bash
# リポジトリの保護設定を gh でまとめて適用する。何度実行しても同じ状態になる。
# 使い方: scripts/apply-repo-settings.sh [owner/repo]（既定は ibukimatsubara/dequ-local）
# 公開前の private リポジトリでは GitHub の制限で通らない設定がある。
# その項目は失敗を表示して次へ進み、最後に失敗の数を終了コードで返す。
set -uo pipefail

repo="${1:-ibukimatsubara/dequ-local}"
failed=0

step() {
  local name="$1"
  shift
  if out=$("$@" 2>&1); then
    echo "ok   $name"
  else
    echo "FAIL $name: $(echo "$out" | head -c 300)"
    failed=$((failed + 1))
  fi
}

# 同じ名前のルールセットがあれば更新し、なければ作る。
upsert_ruleset() {
  local name="$1" body="$2" id
  id=$(gh api "repos/$repo/rulesets" --jq ".[] | select(.name == \"$name\") | .id") || return 1
  if [ -n "$id" ]; then
    gh api -X PUT "repos/$repo/rulesets/$id" --input - <<<"$body" >/dev/null
  else
    gh api -X POST "repos/$repo/rulesets" --input - <<<"$body" >/dev/null
  fi
}

# main: PR からだけ変更でき、メンテナー（CODEOWNERS）の承認と CI の成功が要る。
# 強制 push と削除は禁止。管理者は自分の PR を承認なしでマージできるが、直接 push はできない。
main_ruleset='{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}],
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 1,
      "require_code_owner_review": true,
      "dismiss_stale_reviews_on_push": true,
      "require_last_push_approval": true,
      "required_review_thread_resolution": false
    }}
  ]
}'

# main の CI: 管理者の例外はルールセット全体に効くので、CI の必須は例外なしの別のルールセットに置く。
# CI の結果は GitHub Actions（integration_id 15368）が出したものだけを認める。
checks_ruleset='{
  "name": "main checks",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "bypass_actors": [],
  "rules": [
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": false,
      "required_status_checks": [
        {"context": "server", "integration_id": 15368},
        {"context": "web", "integration_id": 15368}
      ]
    }}
  ]
}'

# v* タグ: 作成・移動・削除はメンテナー（管理者）だけ。
tag_ruleset='{
  "name": "release tags",
  "target": "tag",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
  "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
  "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}]
}'

step "main の保護" upsert_ruleset "main" "$main_ruleset"
step "main の CI" upsert_ruleset "main checks" "$checks_ruleset"
step "v* タグの保護" upsert_ruleset "release tags" "$tag_ruleset"
step "初めての貢献者のワークフロー実行だけ承認を求める" \
  gh api -X PUT "repos/$repo/actions/permissions/fork-pr-contributor-approval" \
  -f approval_policy=first_time_contributors
step "secret scanning と push protection" \
  gh api -X PATCH "repos/$repo" --input - <<<'{"security_and_analysis": {
    "secret_scanning": {"status": "enabled"},
    "secret_scanning_push_protection": {"status": "enabled"}}}'
step "Dependabot alerts" gh api -X PUT "repos/$repo/vulnerability-alerts"
step "private vulnerability reporting" gh api -X PUT "repos/$repo/private-vulnerability-reporting"

echo "failed: $failed"
exit "$failed"
