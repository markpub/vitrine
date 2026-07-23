# Deploying a Vitrine site to Cloudflare Pages, password-gated

This shows two paths: a **quick direct-upload prototype** (what shipped the first WSD Talks site) and the **productionized git-connected build**. Both put the site behind a shared password with the `_worker.js` in this directory.

## What you get

Vitrine builds an entity-manager repo into a static site (`build.sh <repo> <out>`). Cloudflare Pages hosts it; the `_worker.js` (an advanced-mode Pages Function) gates every request behind HTTP basic-auth — DEC-001's "shared password."

## Prerequisites

- `python3` with `markpub` + `pyyaml`, `rsync`, and node/npm (for search index) — same as Vitrine.
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
cp vitrine/deploy/_worker.js ./_site/_worker.js
#    (quick: edit the two constants in ./_site/_worker.js)

# 3. create the project once, then deploy
export CLOUDFLARE_ACCOUNT_ID=<id>
npx wrangler pages project create wsd-talks --production-branch main
npx wrangler pages deploy ./_site --project-name wsd-talks --branch main --commit-dirty=true
```

Site is then at `https://<project>.pages.dev`. If you hardcoded the password it works immediately; if you left it reading `env.SITE_PASSWORD`, set it and redeploy (Path B, step 3).

## Path B — productionized (git-connected build + secret)

CF rebuilds on every push to the content repo, and the password is a real secret.

1. **Vendor Vitrine** into the content repo (or fetch it in the build command).
2. In the Pages project (Settings → Builds & deployments):
   - **Build command:** `pip install markpub && bash vitrine/build.sh . _site && cp vitrine/deploy/_worker.js _site/_worker.js`
   - **Build output directory:** `_site`
   - **Environment variables:** `SITE_TITLE`, `SITE_AUTHOR`, `SITE_REPO`; `PYTHON=python3` if no `python3.11`.
3. **Set the gate secret(s):**
   ```sh
   npx wrangler pages secret put SITE_PASSWORD --project-name <proj>
   npx wrangler pages secret put SITE_USER --project-name <proj>   # optional; defaults to "wsd"
   ```
4. Connecting a **private org repo** needs the Cloudflare GitHub app authorized for that org — a one-time dashboard step.
5. **Real SSO instead of a shared password:** swap the `_worker.js` gate for **Cloudflare Access** (Zero Trust) — email one-time-pin or SSO, per-person, revocable. That's the grown-up version of the gate; the shared password is fine for a small trusted group.

## Notes / gotchas

- **Two accounts?** wrangler refuses to guess — always set `CLOUDFLARE_ACCOUNT_ID`.
- **`.html` → clean URLs:** Pages 308-redirects `/foo.html` → `/foo`. Harmless; browsers follow it. Vitrine writes `.html` link targets, which resolve fine through the redirect.
- **The worker source is not public** — it runs at the edge and is never served, so a hardcoded prototype password isn't web-exposed. Still, don't commit a real password to git; use the secret (Path B) for anything lasting.
- **First WSD Talks deploy:** project `wsd-talks` on Pete's `kaminski@istori.com` CF account; user `wsd`, password hardcoded in the deployed worker (not in git).
