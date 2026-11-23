# Releasing DeQu

This document describes how a DeQu version is released.
Each release gets a version tag, release notes taken from [CHANGELOG.md](../CHANGELOG.md), and its own Change Date under the DeQu Source-Available License.

Only the maintainer creates tags and GitHub releases.
Contributors and coding agents prepare the release pull request (steps 1–3) and stop there.

## Before the first release

`LICENSE` must exist before any version is released, because every release records its Change Date there.

## Versions

- Versions follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.
  Tags are the version with a `v` prefix, such as `v0.1.0`.
- Before 1.0.0, a change that breaks the HTTP API, the MCP tools, the card schema, the `dequ` commands or the configuration file raises MINOR. Other changes raise PATCH.
- Use the same version in the tag and in these files:
  - `server/pyproject.toml` (`version`) and `server/uv.lock`
  - `web/package.json` (`version`) and `web/package-lock.json`
  - `LICENSE` (`Licensed Work`) and its copy at `server/LICENSE`

## Change Date

Each version becomes available under Apache-2.0 four years after MIBUKI first publicly releases it under the DeQu Source-Available License.
A version first released on 2026-12-01 has the Change Date 2030-12-01.

The Change Date is written in two places:

- `LICENSE` and `server/LICENSE`: the `Change Date` field, together with the version in `Licensed Work`.
  `LICENSE` on `main` always describes the latest release; the terms of an older version are in `LICENSE` at its tag.
- The release notes contain `License: DeQu Source-Available License, Change Date YYYY-MM-DD` directly under the version heading in `CHANGELOG.md`.
  That section is copied into the GitHub release.

## Keeping the changelog

Every pull request that changes what users see adds a line under `## [Unreleased]` in `CHANGELOG.md`, in the `Added`, `Changed`, `Fixed`, `Removed` or `Security` group.
Write what changed for someone running DeQu, not how the code changed.

## Steps

In the commands below, replace `0.1.0` with the new version and `2026-12-01` / `2030-12-01` with the release date and the Change Date.

### 1. Check `main`

```sh
git switch main
git pull --ff-only
```

`## [Unreleased]` in `CHANGELOG.md` must list everything in the release.
CI runs on pull requests, so the release pull request in step 3 is where CI must pass.

### 2. Prepare the release branch

```sh
git switch -c chore/release-v0.1.0
```

Update the versions:

```sh
(cd server && uv version --no-sync 0.1.0)
(cd web && npm version 0.1.0 --no-git-tag-version)
```

In `LICENSE`, set the version in `Licensed Work` and record the fourth anniversary of the planned release in `Change Date`.

```text
Licensed Work: DeQu 0.1.0
Change Date: 2030-12-01
```

Copy the updated license into the Python package with `cp LICENSE server/LICENSE`.
Run `uv build server` and check that both archives contain the updated license.
The wheel puts it under `.dist-info/licenses/`, and the source archive puts it at the top of the extracted source directory.

In `CHANGELOG.md`, rename `## [Unreleased]` to the version and date, add the license line, and start a new empty `## [Unreleased]` above it:

```markdown
## [Unreleased]

## [0.1.0] - 2026-12-01

License: DeQu Source-Available License, Change Date 2030-12-01

### Added
...
```

### 3. Open and merge the release pull request

```sh
git commit -am "chore(release): v0.1.0"
git push -u origin chore/release-v0.1.0
gh pr create --base main --title "chore(release): v0.1.0"
```

Fill in the pull request template, then hand the pull request to the maintainer, who merges it after CI passes.

### 4. Tag the release (maintainer only)

If the planned release date has changed, update the dates in both license files and the changelog through a release pull request before tagging.

Tag the merge commit of the pull request that put the final version and dates on `main`.
Replace `42` in the example with that pull request's number.

```sh
git switch main
git pull --ff-only
release_pr=42
commit=$(gh pr view "$release_pr" --json mergeCommit --jq .mergeCommit.oid)
git tag -a v0.1.0 "$commit" -m "DeQu v0.1.0"
git push origin v0.1.0
```

### 5. Publish the GitHub release (maintainer only)

Copy the version's section of `CHANGELOG.md` at the tag into the release notes:

```sh
git show v0.1.0:CHANGELOG.md |
  awk -v heading="## [0.1.0]" 'index($0, heading) == 1 {found=1; next} found && /^## \[/ {exit} found' > /tmp/dequ-release-notes.md
gh release create v0.1.0 --title "DeQu v0.1.0" --notes-file /tmp/dequ-release-notes.md
```

### 6. Check the result

```sh
gh release view v0.1.0
git show v0.1.0:LICENSE | grep -E 'Licensed Work|Change Date'
```

The release notes start with the license line, and `LICENSE` at the tag shows the same version and Change Date.
