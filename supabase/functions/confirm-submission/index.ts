// confirm-submission — the link target in the confirmation email.
//
// GET ?token=<verify_token>  ->  set email_verified=true for that one row, then
// show a friendly page. The token is a per-row random uuid, so holding it proves
// the person received the email we sent to the address on the submission.
//
// Idempotent and quiet: a token that's already used, unknown, or malformed all
// get the same neutral "you're all set / nothing to do" page — we never reveal
// whether a given token exists.
//
// STATUS: written from the API shapes, NOT run against a live deploy.
// SECRETS: SUPABASE_URL, SUPABASE_SERVICE_KEY.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const SB_URL = Deno.env.get("SUPABASE_URL")!;
const SB_KEY = Deno.env.get("SUPABASE_SERVICE_KEY")!;

Deno.serve(async (req) => {
  const token = new URL(req.url).searchParams.get("token") ?? "";
  const uuid = /^[0-9a-f-]{36}$/i.test(token);

  let confirmed = false;
  if (uuid) {
    // Only flip rows still unverified, so a re-click doesn't churn. return=headers
    // -> Content-Range tells us how many rows matched.
    const r = await fetch(
      `${SB_URL}/rest/v1/submissions?verify_token=eq.${token}&email_verified=eq.false`,
      {
        method: "PATCH",
        headers: {
          apikey: SB_KEY, Authorization: `Bearer ${SB_KEY}`,
          "Content-Type": "application/json", Prefer: "return=headers-only,count=exact",
        },
        body: JSON.stringify({ email_verified: true }),
      },
    );
    const range = r.headers.get("content-range") ?? "0/*";   // e.g. "0-0/1"
    confirmed = r.ok && !range.startsWith("*/0") && range !== "*/0";
  }

  return new Response(page(confirmed), {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
});

function page(ok: boolean): string {
  const msg = ok
    ? "Your event is confirmed — it's now in the review queue. Thank you for adding to the map. 💙"
    : "You're all set — there's nothing more to do here.";
  return `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>What's on in Nice</title>
<body style="margin:0;background:#f4f2ed;color:#0e0e0e;font:16px/1.5 'Helvetica Neue',Arial,sans-serif;display:grid;place-items:center;min-height:100vh">
<div style="max-width:460px;padding:40px 28px;text-align:center">
  <div style="font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:#7d7970">What's on in Nice</div>
  <h1 style="font-size:30px;font-weight:800;letter-spacing:-.03em;margin:14px 0 10px">${ok ? "Confirmed" : "All set"}</h1>
  <p style="color:#4a463f">${msg}</p>
  <p style="margin-top:26px"><a href="https://whatsonnice.com" style="background:#1f3bff;color:#fff;padding:11px 18px;border-radius:8px;text-decoration:none;font-weight:600">See what's on →</a></p>
</div></body>`;
}
