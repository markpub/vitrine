// Shared-password gate for a Vitrine/MarkPub site on Cloudflare Pages.
//
// This is an "advanced mode" Pages Function: place this file at the ROOT of
// the directory you deploy (the Vitrine build output). Pages then runs it for
// every request; static assets are served via env.ASSETS only after HTTP
// basic-auth passes. The source is never served to visitors.
//
// Recommended: set SITE_USER + SITE_PASSWORD as Pages env vars / secrets
//   wrangler pages secret put SITE_PASSWORD --project-name <proj>
// Quick prototype: hardcode the two constants below instead.
export default {
  async fetch(request, env) {
    const USER = env.SITE_USER || "wsd";
    const PASS = env.SITE_PASSWORD;                 // set as a Pages secret
    const auth = request.headers.get("Authorization") || "";
    if (PASS && auth.startsWith("Basic ")) {
      const decoded = atob(auth.slice(6));
      const i = decoded.indexOf(":");
      if (decoded.slice(0, i) === USER && decoded.slice(i + 1) === PASS)
        return env.ASSETS.fetch(request);
    }
    return new Response("Enter the shared username and password.", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="site", charset="UTF-8"' },
    });
  },
};
