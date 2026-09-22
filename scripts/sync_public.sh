#!/usr/bin/env bash
# Publish the scrubbed tree to GitHub.
#
# GitHub must not receive Gitea's history. `public` is main plus a scrub
# commit, but pushing `public` sends its ANCESTORS too -- including the
# commits that still contain DELIVERY.md, the Gitea backlog URLs and the
# /mnt/Develop paths. A scrub commit cleans the tip tree, not the history,
# so grepping the worktree and then pushing the branch published everything
# the scrub was supposed to hide. That happened once; hence this design.
#
# So the public history is built from TREES, not merges:
#
#   main    -> origin/main     (internal, Gitea, full history)
#   public  -> origin/public   (internal, Gitea, = main + scrub)
#   release -> github/main     (public: one commit per release, whose tree
#                               is public's tree and whose only parent is
#                               the previous release -- no internal ancestry)
#
# release stays append-only, so github/main always fast-forwards.
#
# Usage: scripts/sync_public.sh [--dry-run]
set -euo pipefail

MARKERS='iblvfx|git01|/mnt/Develop|/home/ats|SFpipe|SFsoftware|SFhoudini'
EXCLUDE=':(exclude)scripts/sync_public.sh'

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

cd "$(dirname "$0")/.."

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Working tree is dirty. Commit or stash first." >&2
    exit 1
fi

# Restore by commit, not by name: --abbrev-ref prints "HEAD" on a detached
# head and checking that out lands somewhere else entirely.
START_REF="$(git symbolic-ref --quiet --short HEAD || git rev-parse HEAD)"
restore() { git checkout -q "$START_REF" 2>/dev/null || true; }
trap restore EXIT

echo "==> merging main into public"
git checkout -q public
if ! git merge --no-edit main; then
    echo >&2
    echo "Merge conflict. Resolve keeping the scrubbed side (no internal" >&2
    echo "hostnames or paths), commit, then re-run this script." >&2
    git merge --abort 2>/dev/null || true
    exit 1
fi
git checkout -q "$START_REF"

# Scan the TREE THAT WILL BE PUBLISHED, not the working directory.
# git grep exits 0 on a match, 1 on none, and >1 on a real error; `|| true`
# would swallow the error case and report "clean".
echo "==> scanning the tree to be published"
set +e
LEAKS="$(git grep -I -n -E "$MARKERS" public -- . "$EXCLUDE")"
RC=$?
set -e
if [[ $RC -gt 1 ]]; then
    echo "git grep failed (exit $RC) -- refusing to publish on an unverified scan." >&2
    exit 1
fi
if [[ -n "$LEAKS" ]]; then
    echo "REFUSING TO PUBLISH -- internal references in the tree:" >&2
    echo "$LEAKS" >&2
    exit 1
fi
echo "    clean"

TREE="$(git rev-parse 'public^{tree}')"
PARENT="$(git rev-parse --verify --quiet refs/heads/release || true)"
if [[ -n "$PARENT" && "$(git rev-parse "$PARENT^{tree}")" == "$TREE" ]]; then
    echo "==> nothing new to publish"
    exit 0
fi

SUBJECT="$(git log -1 --format=%s public)"
if [[ -n "$PARENT" ]]; then
    RELEASE="$(git commit-tree "$TREE" -p "$PARENT" -m "$SUBJECT")"
else
    RELEASE="$(git commit-tree "$TREE" -m "$SUBJECT")"
fi

if [[ "$DRY_RUN" == "1" ]]; then
    echo "==> dry run; would publish tree $TREE as $RELEASE"
    echo "    origin main, origin public, github release:main"
    exit 0
fi

echo "==> pushing"
git update-ref refs/heads/release "$RELEASE"
git push origin main
git push origin public
# No --force: release is append-only by construction, so this must
# fast-forward. If it ever does not, something rewrote the public history
# and that deserves a look rather than an override.
git push github release:main
echo "==> done: github/main = $RELEASE"
