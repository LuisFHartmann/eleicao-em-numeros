// Pages Function: serve o snapshot ao vivo gravado pelo coletor no R2, na mesma origem do site.
// GET /vivo/6258.json  ->  objeto "vivo_6258.json" do bucket ligado como VIVO (ver wrangler.toml).
export async function onRequestGet({ params, env }) {
  if (!env.VIVO || !/^\d+\.json$/.test(params.arq)) return new Response("not found", { status: 404 }); // sem R2 ligado: a página lê o TSE direto
  const obj = await env.VIVO.get(`vivo_${params.arq}`);
  if (!obj) return new Response("not found", { status: 404 });
  return new Response(obj.body, {
    headers: { "content-type": "application/json", "cache-control": "no-cache", etag: obj.httpEtag },
  });
}
