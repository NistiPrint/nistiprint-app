import { createClient } from "npm:@supabase/supabase-js@2";

const json = (body: Record<string, unknown>, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });

function hexToBytes(hex: string): Uint8Array {
  if (!/^(?:[0-9a-fA-F]{2})+$/.test(hex)) {
    throw new Error("SHOPEE_PARTNER_KEY must be an even-length hexadecimal string");
  }
  return new Uint8Array(hex.match(/.{2}/g)!.map((byte) => Number.parseInt(byte, 16)));
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

async function validSignature(url: string, body: string, secret: string, signature: string) {
  const key = await crypto.subtle.importKey(
    "raw",
    hexToBytes(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(`${url}|${body}`),
  );
  const expected = [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return constantTimeEqual(expected, signature.toLowerCase());
}

Deno.serve(async (request) => {
  if (request.method === "GET") return new Response("OK", { status: 200 });
  if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const partnerKey = Deno.env.get("SHOPEE_PARTNER_KEY");
  const callbackUrl = Deno.env.get("SHOPEE_CALLBACK_URL");
  const signature = request.headers.get("Authorization");
  if (!supabaseUrl || !serviceKey || !partnerKey || !callbackUrl) {
    console.error("Shopee webhook configuration is incomplete");
    return json({ error: "Webhook is not configured" }, 503);
  }
  if (!signature) return json({ error: "Unauthorized" }, 401);

  const rawBody = await request.text();
  let payload: { code?: number; data?: { ordersn?: string; status?: string; update_time?: number } };
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return json({ error: "Invalid JSON payload" }, 400);
  }

  try {
    if (!await validSignature(callbackUrl, rawBody, partnerKey, signature)) {
      return json({ error: "Unauthorized" }, 401);
    }
  } catch (error) {
    console.error("Shopee signature validation failed", error);
    return json({ error: "Unauthorized" }, 401);
  }

  const supabase = createClient(supabaseUrl, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const data = payload.data;
  let status = "SUCESSO";
  let errorMessage: string | null = null;

  if (data?.ordersn) {
    const update: Record<string, unknown> = {
      codigo_pedido: data.ordersn,
      updated_at: new Date().toISOString(),
    };
    if (data.status !== undefined) update.status_pedido = data.status;
    if (data.update_time) update.data_atualizacao = new Date(data.update_time * 1000).toISOString();
    const { error } = await supabase.from("pedidos_shopee")
      .upsert(update, { onConflict: "codigo_pedido" });
    if (error) {
      status = "ERRO";
      errorMessage = `Supabase upsert error: ${error.message}`;
    }
  } else {
    status = "AVISO";
    errorMessage = "No ordersn found in webhook data";
  }

  const { error: logError } = await supabase.from("webhook_logs").insert({
    plataforma: "shopee",
    payload,
    status,
    erro_mensagem: errorMessage,
    codigo_webhook: payload.code ?? null,
    created_at: new Date().toISOString(),
  });
  if (logError) console.error("Failed to persist Shopee webhook log", logError.message);
  if (status === "ERRO") return json({ error: errorMessage }, 500);
  return json({ message: "Webhook processed successfully", status });
});
