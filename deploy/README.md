# Deploying a Vitrine site to Cloudflare Pages, password-gated

This shows two paths: a **quick direct-upload prototype** (what shipped the first WSD Talks site) and the **productionized git-connected build**. Both put the site behind a shared password with the `_worker.js` in this directory.

## What you get

Vitrine builds an entity-manager repo into a static site (`build.sh <repo> <out>`). Cloudflare Pages hosts it; the `_worker.js` (an advanced-mode Pages Function) gates every request behind HTTP basic-auth — DEC-001's "shared password."

## Prerequisites

- `python3` with `markpub` + `pyyaml`, and node/npm (for search index) — same as Vitrine.
- `wrangler`, authenticated (`npx wrangler whoami`). If a stored OAuth login exists, no interactive login is needed.
- **The Cloudflare account id** (wrangler errors if the token has more than one account):
  `export CLOUDFLARE_ACCOUNT_ID=<id>` (find it with `npx wrangler whoami`).

## Path A — quick prototype (direct upload)

What the first WSD Talks site used. Nothing git-connected; you upload a local build.

```sh
# 1. build the site (title/author/repo are optional knobs)
SITE_TITLE='WSD Talks' SITE_REPO='github.com/WSD-Talks/comroom' \
  bash vitrine/build.sh /path/to/comroom ./_site

# 2. drop the gate in. For a throwaway prototype you may hardcode USER/PASS
#    in the worker; otherwise leave it reading env (Path B) and set a secret.
#    VITRINE_GATE=basic-auth on the build above installs it for you;
#    for a throwaway you may instead copy it and hardcode the constants:
cp vitrine/deploy/_worker.js ./_site/_worker.js

# 3. create the project once, then deploy
export CLOUDFLARE_ACCOUNT_ID=<id>
npx wrangler pages project create wsd-talks --production-branch main
npx wrangler pages deploy ./_site --project-name wsd-talks --branch main --commit-dirty=true
```

Site is then at `https://<project>.pages.dev`. If you hardcoded the password it works immediately; if you left it reading `env.SITE_PASSWORD`, set it and redeploy (Path B, step 3).

## Path B — productionized (git-connected build + secret)

CF rebuilds on every push to the content repo, and the password is a real secret.

1. **Fetch Vitrine in the build command, from outside the content root.** Vitrine is public, so the build can clone it — no vendored copy to drift.

   **Clone it to `/tmp`, not into the repo.** `build.sh` stages a copy of everything in the source root except `.git`, `.obsidian`, `.claude`, `.markpub`, `node_modules`, and the work/output directories. A `vitrine/` directory sitting in the content root is not on that list, so it would be copied into the staged content and **published as site pages** — Vitrine's README, its Python files, and its `deploy/_worker.js` all served as ordinary URLs. Cloning outside the content root avoids the whole question. (If you do vendor Vitrine into the content repo instead, add `vitrine/` to that repo's `.vitrineignore`.)

2. **Pin the version.** The build clones a tag, not `main`, so the group's live site does not silently change every time Vitrine does. Bump `VITRINE_REF` deliberately.

3. In the Pages project (Settings → Builds & deployments):
   - **Build command:**
     ```sh
     pip install markpub && \
       git clone --depth 1 --branch "$VITRINE_REF" https://github.com/markpub/vitrine /tmp/vitrine && \
       bash /tmp/vitrine/build.sh . _site
     ```
   - **Build output directory:** `_site`
   - **Environment variables:** `VITRINE_GATE=basic-auth`, `VITRINE_REF` (the Vitrine tag to build with), `VITRINE_PAGE_NAMES`, `SITE_TITLE`, `SITE_AUTHOR`, `SITE_REPO`. The image's `python3` must be ≥3.12 so `pip install markpub` resolves to 2.x; the build refuses markpub 0.x (see the version guard in `build.sh`).

   **Two of these decide things you will not notice from a successful build**, so check both afterward:
   - **`VITRINE_GATE` decides whether the site is gated at all.** It defaults to `none`, which publishes an ungated, publicly readable site. `basic-auth` installs the worker as part of the build. The build log states which one you got, in those words — read it. Then confirm from outside: `curl -s -o /dev/null -w '%{http_code}' https://<project>.pages.dev/` must be `401`.
   - **`VITRINE_PAGE_NAMES` decides every record's URL.** It defaults to `filename` (`/entities/decision/DEC-001.html`). A site previously built with `slug` publishes `/entities/decision/dec-001-<title>.html`, so omitting the variable silently changes every record URL and breaks existing links, including the ones in the content repo's own README. Set it to whatever the site already uses.
4. **Set the gate secret(s)**, before the first build finishes:
   ```sh
   npx wrangler pages secret put SITE_PASSWORD --project-name <proj>
   npx wrangler pages secret put SITE_USER --project-name <proj>   # optional; defaults to "wsd"
   ```
   The worker fails closed: with the secret unset it 401s everyone, which is the safe direction but is still an outage.
5. Connecting a **private org repo** needs the Cloudflare GitHub app authorized for that org — a one-time dashboard step. The app can be scoped to **selected repositories** rather than the whole org.
6. **Real SSO instead of a shared password:** swap the `_worker.js` gate for **Cloudflare Access** (Zero Trust) — email one-time-pin or SSO, per-person, revocable. That's the grown-up version of the gate; the shared password is fine for a small trusted group.

### A direct-upload project cannot become git-connected

Cloudflare is explicit that a Pages project created by direct upload cannot be switched to a Git integration later. Moving a Path A prototype to Path B therefore means **deleting the project and recreating it**, which takes the site down and frees its `<project>.pages.dev` hostname to be reclaimed on recreate.

Do it last, and rehearse it first: create a **second, throwaway Pages project** against the same content repo, prove the exact build command and environment there, and only then delete and recreate the real one. The build config is the part that takes iterations to get right, and the deletion is the only step that costs downtime — there is no reason for those two to happen at the same time.

## The WSD Talks production config

Recorded here rather than left only in the Cloudflare dashboard, where the group cannot read it.

| Setting | Value |
|---|---|
| Pages project | `wsd-talks`, on `kaminski@istori.com`'s account (`c4d56c078164c1183d46dfc31e51afd9`) |
| Content repo | `github.com/WSD-Talks/comroom`, production branch `main` |
| Build output | `_site` |
| `VITRINE_REF` | the pinned Vitrine tag |
| `VITRINE_PAGE_NAMES` | `slug` — the live site publishes slug URLs; `filename` would break every existing record link |
| `SITE_TITLE` | `WSD Talks` |
| `SITE_REPO` | `github.com/WSD-Talks/comroom` |
| `PYTHON` | `python3`, if the build image has no `python3.11` |
| `VITRINE_GATE` | `basic-auth` — without it the site publishes ungated |
| `SITE_USER` | `wsd` (worker default) |
| `SITE_PASSWORD` | a Pages secret, not in git |

## Notes / gotchas

- **Two accounts?** wrangler refuses to guess — always set `CLOUDFLARE_ACCOUNT_ID`.
- **`.html` → clean URLs:** Pages 308-redirects `/foo.html` → `/foo`. Harmless; browsers follow it. Vitrine writes `.html` link targets, which resolve fine through the redirect.
- **The worker source is not public** — it runs at the edge and is never served, so a hardcoded prototype password isn't web-exposed. Still, don't commit a real password to git; use the secret (Path B) for anything lasting.
- **First WSD Talks deploy:** project `wsd-talks` on Pete's `kaminski@istori.com` CF account; user `wsd`, password hardcoded in the deployed worker (not in git).
