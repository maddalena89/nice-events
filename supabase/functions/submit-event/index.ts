// submit-event — accept a submission and email the submitter a confirm link.
//
// Replaces the browser's direct REST insert (see the {% if submit_mode ==
// 'supabase' %} block in the template). Flow:
//   1. browser POSTs the form JSON here
//   2. we insert the row (service key), email_verified=false, fresh verify_token
//   3. we email the submitter a link to /confirm-submission?token=...
//   4. they click -> confirm-submission flips email_verified=true
//   5. the daily build publishes rows that are approved AND email_verified
//
// STATUS: written from the API shapes, NOT run against a live deploy.
// SECRETS: SUPABASE_URL, SUPABASE_SERVICE_KEY, RESEND_API_KEY, CONFIRM_BASE_URL,
//          FROM_EMAIL (e.g. "What's on in Nice <hello@whatsonnice.com>").
// Resend's free tier (3k emails/mo) keeps this cost-free at this scale.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const SB_URL = Deno.env.get("SUPABASE_URL")!;
const SB_KEY = Deno.env.get("SUPABASE_SERVICE_KEY")!;
const RESEND = Deno.env.get("RESEND_API_KEY") ?? "";
const FROM = Deno.env.get("FROM_EMAIL") ?? "What's on in Nice <hello@whatsonnice.com>";
const CONFIRM_BASE = Deno.env.get("CONFIRM_BASE_URL") ?? `${SB_URL}/functions/v1/confirm-submission`;

const CATEGORIES = ["brocante","danse","concert","expo","scene","visite","atelier","business","social","sport","marche","autre"];
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type, apikey",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  let b: any;
  try { b = await req.json(); } catch { return json({ error: "bad JSON" }, 400); }

  // Minimal server-side validation — the DB CHECKs are the real gate, this is a
  // friendlier error than a raw constraint violation.
  const email = String(b.email ?? "").trim();
  const title = String(b.title ?? "").trim();
  const start = String(b.start_date ?? "").trim();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return json({ error: "A valid email is required." }, 400);
  if (title.length < 3) return json({ error: "Event name is too short." }, 400);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) return json({ error: "A start date is required." }, 400);
  const category = CATEGORIES.includes(b.category) ? b.category : "autre";

  const row = {
    title, start_date: start,
    end_date: b.end_date || null,
    town: String(b.town ?? "").trim(),
    venue: b.venue || null,
    category,
    url: b.url || null,          // now optional
    note: b.note || null,
    email,
    approved: false, published: false, email_verified: false,
  };

  // Insert with the service key and ask for the generated verify_token back.
  const ins = await fetch(`${SB_URL}/rest/v1/submissions?select=id,verify_token`, {
    method: "POST",
    headers: {
      apikey: SB_KEY, Authorization: `Bearer ${SB_KEY}`,
      "Content-Type": "application/json", Prefer: "return=representation",
    },
    body: JSON.stringify(row),
  });
  if (!ins.ok) return json({ error: "Not accepted: " + (await ins.text()).slice(0, 200) }, 400);
  const [created] = await ins.json();

  const link = `${CONFIRM_BASE}?token=${created.verify_token}`;

  if (RESEND) {
    const mail = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${RESEND}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from: FROM, to: [email],
        subject: "Confirm your event — What's on in Nice",
        html: `<p>Thanks for adding <b>${escapeHtml(title)}</b>.</p>
<p>Tap to confirm it's really you — then a human gives it a quick look before it goes live:</p>
<p><a href="${link}" style="background:#1f3bff;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none">Confirm my event</a></p>
<p style="color:#777;font-size:13px">If you didn't submit anything, just ignore this — nothing will be published.</p>`,
      }),
    });
    if (!mail.ok) {
      // Row exists but email failed — tell the client so they can retry/resend.
      return json({ ok: true, emailed: false, warn: "Saved, but the confirmation email didn't send." }, 200);
    }
  }
  return json({ ok: true, emailed: !!RESEND }, 200);
});

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]!));
}
function json(o: unknown, status = 200) {
  return new Response(JSON.stringify(o), { status, headers: { ...CORS, "content-type": "application/json" } });
}
