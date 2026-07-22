// read-poster — turn a photo of a poster into prefilled event fields.
//
// WHY THIS EXISTS
// The in-browser OCR (Tesseract, in the page) reads flat, high-contrast text
// reasonably but falls apart on real posters: script fonts, text over photos,
// rotated words, "jeu. 23 juil. à partir de 18h" spread across the design. A
// vision model reads the poster the way a person does and returns clean fields.
//
// The photo is sent here (a Supabase Edge Function), this calls a vision model,
// and only the extracted TEXT fields come back — the image is never stored.
//
// STATUS: written from the API shapes, NOT yet run against a live deploy. Deploy
// with `supabase functions deploy read-poster`, set the secrets below, then wire
// the form to POST here (see ROADMAP.md → "AI poster prefill").
//
// SECRETS (supabase secrets set ...):
//   ANTHROPIC_API_KEY   your key
//   POSTER_MODEL        optional, defaults to a current Claude vision model
//
// COST: a few hundredths of a cent per poster on a small vision model. Not free,
// but only spent when someone actually taps "read this poster", so it scales with
// real submissions, not traffic. Add a per-IP daily cap before going wide.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const MODEL = Deno.env.get("POSTER_MODEL") ?? "claude-3-5-haiku-latest";
const KEY = Deno.env.get("ANTHROPIC_API_KEY") ?? "";

// The 12 categories the site actually renders. Kept in sync with models.py.
const CATEGORIES = [
  "brocante", "danse", "concert", "expo", "scene", "visite",
  "atelier", "business", "social", "sport", "marche", "autre",
];

// CORS: the form is on a different origin (whatsonnice.com) from the function.
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type, apikey",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const SYSTEM = `You read a photo of an event poster or flyer (usually French, sometimes English) and extract structured fields. Return ONLY a JSON object, no prose, with these keys:
- title: the event's own name, cleaned up (not the venue name, not a tagline)
- start_date: ISO YYYY-MM-DD. If the poster gives a day and month but no year, pick the NEXT occurrence relative to today (${new Date().toISOString().slice(0, 10)}). If no date is legible, use null.
- end_date: ISO YYYY-MM-DD for a run/exhibition ("jusqu'au 7 septembre"), else null.
- time: "HH:MM" 24h if a start time is shown ("à partir de 18h" -> "18:00"), else null.
- town: the commune (Nice, Antibes, Menton, ...), else null.
- venue: the place name and/or street address, else null.
- category: EXACTLY one of ${CATEGORIES.join(", ")}. A vernissage/exposition is "expo"; a concert is "concert"; a club/DJ night is "autre"; a tango/dance night is "danse".
- note: one short line a reader would want (price, "à partir de 18h", "entrée libre"), else null.
- confidence: 0..1, how sure you are overall.
Never invent a date or town that isn't on the poster — use null instead.`;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") {
    return json({ error: "POST an image" }, 405);
  }
  if (!KEY) return json({ error: "ANTHROPIC_API_KEY not set" }, 500);

  // Accept either multipart (file field "photo") or JSON {image_base64, media_type}.
  let b64 = "", media = "image/jpeg";
  try {
    const ct = req.headers.get("content-type") ?? "";
    if (ct.includes("multipart/form-data")) {
      const form = await req.formData();
      const file = form.get("photo");
      if (!(file instanceof File)) return json({ error: "no photo field" }, 400);
      media = file.type || media;
      b64 = base64(new Uint8Array(await file.arrayBuffer()));
    } else {
      const body = await req.json();
      b64 = String(body.image_base64 ?? "").replace(/^data:[^,]+,/, "");
      media = body.media_type ?? media;
    }
  } catch {
    return json({ error: "could not read the image" }, 400);
  }
  if (!b64) return json({ error: "empty image" }, 400);

  // ~5MB decoded ceiling — phone photos are big; the client should downscale
  // before upload, but guard here too so one huge upload can't run up the bill.
  if (b64.length > 7_000_000) return json({ error: "image too large" }, 413);

  const ai = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": KEY,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 500,
      system: SYSTEM,
      messages: [{
        role: "user",
        content: [
          { type: "image", source: { type: "base64", media_type: media, data: b64 } },
          { type: "text", text: "Extract the event fields as JSON." },
        ],
      }],
    }),
  });

  if (!ai.ok) {
    return json({ error: "vision model error", detail: (await ai.text()).slice(0, 300) }, 502);
  }

  const data = await ai.json();
  const text = (data?.content?.[0]?.text ?? "").trim();
  const fields = safeParse(text);
  if (!fields) return json({ error: "model did not return JSON", raw: text.slice(0, 300) }, 502);

  // Never trust the model's category blindly — clamp to the known set.
  if (!CATEGORIES.includes(fields.category)) fields.category = "";
  return json({ ok: true, fields }, 200);
});

function safeParse(s: string): any | null {
  const m = s.match(/\{[\s\S]*\}/);          // tolerate ```json fences etc.
  if (!m) return null;
  try { return JSON.parse(m[0]); } catch { return null; }
}
function base64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}
function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...CORS, "content-type": "application/json" },
  });
}
