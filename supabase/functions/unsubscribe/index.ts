// unsubscribe — the link at the bottom of every weekly email.
//
// GET ?token=<unsubscribe_token>  ->  set unsubscribed_at on that one row, then
// show a small friendly page. Nothing else: no login, no confirmation step, no
// "are you sure?", no survey. Leaving has to be at least as easy as joining was,
// and one click is what the GDPR means by withdrawing consent being as easy as
// giving it.
//
// Deliberately idempotent: mail clients pre-fetch links, people click twice,
// Gmail's one-click unsubscribe POSTs it. A second call is a no-op that shows
// the same page rather than an error, because "something went wrong" on an
// unsubscribe page is how a mild annoyance becomes a complaint to the CNIL.
//
// The row is NOT deleted. A deleted subscriber is one a future import can
// silently re-add; a row with unsubscribed_at set is a permanent record that
// this person left, which is the thing that actually protects them.
//
// SECRETS: SUPABASE_URL, SUPABASE_SERVICE_KEY.
// The service key bypasses Row Level Security. It has to here — there is no anon
// policy that can update this table, and there must not be one, since the anon
// key is printed inside the public webpage.
//
// Deploy:  supabase functions deploy unsubscribe --no-verify-jwt
//          (--no-verify-jwt is required: the person clicking is a mail reader
//           with no Supabase session, not an authenticated caller.)

const SB_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SB_KEY = Deno.env.get("SUPABASE_SERVICE_KEY") ?? "";
const SITE = Deno.env.get("SITE_URL") ?? "https://whatsonnice.com";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function page(heading: string, body: string, status = 200): Response {
  return new Response(
    `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>${heading} · What's on in Nice</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f2ed;color:#0e0e0e;
 font:16px/1.6 "Helvetica Neue",Helvetica,Arial,sans-serif;padding:24px}
.card{max-width:34rem;text-align:center}
h1{font-size:clamp(30px,7vw,46px);line-height:.95;letter-spacing:-.04em;font-weight:800;
 text-transform:uppercase;margin:0 0 14px}
p{margin:0 0 12px;color:#3a382f}
a{color:#1f3bff}
</style></head>
<body><div class="card"><h1>${heading}</h1>${body}
<p><a href="${SITE}">← Back to what's on in Nice</a></p></div></body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8" } },
  );
}

Deno.serve(async (req) => {
  // Gmail and Outlook honour List-Unsubscribe-Post, which arrives as a POST.
  // Both verbs must work or one-click unsubscribe silently fails for the two
  // clients most of your readers will actually be using.
  if (req.method !== "GET" && req.method !== "POST") {
    return page("Hmm", "<p>That link didn't work as expected.</p>", 405);
  }

  const token = new URL(req.url).searchParams.get("token") ?? "";
  if (!UUID.test(token)) {
    // Don't distinguish "malformed" from "unknown" — no reason to let anyone
    // probe which tokens exist.
    return page(
      "That link looks broken",
      `<p>It may have been cut in half by your email app. Copy the whole link, or
       just email me and I'll take you off by hand.</p>`,
      400,
    );
  }

  if (!SB_URL || !SB_KEY) {
    return page("Something's off at my end", "<p>Please email me and I'll remove you by hand.</p>", 500);
  }

  // One targeted update. `unsubscribed_at is null` makes a repeat click a no-op
  // rather than moving the date forward — the first departure is the honest one.
  const r = await fetch(
    `${SB_URL}/rest/v1/messages?unsubscribe_token=eq.${token}` +
      `&kind=eq.hello&unsubscribed_at=is.null&select=id`,
    {
      method: "PATCH",
      headers: {
        apikey: SB_KEY,
        Authorization: `Bearer ${SB_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify({ unsubscribed_at: new Date().toISOString() }),
    },
  );

  if (!r.ok) {
    return page("Something's off at my end", "<p>Please email me and I'll remove you by hand.</p>", 502);
  }

  // Zero rows means the token was unknown OR they had already unsubscribed.
  // Both get the same reassuring answer: from the reader's point of view the
  // outcome is identical — they are not on the list — and telling a stranger
  // "that token isn't real" serves nobody.
  return page(
    "You're unsubscribed",
    `<p>No more weekly emails. Nothing else was deleted and your address won't be
     used for anything.</p>
     <p>The site itself stays exactly where it is, free and open, whenever you
      want to see what's on. No hard feelings. 💙</p>`,
  );
});
