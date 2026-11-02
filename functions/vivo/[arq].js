// Pages Function: serve arquivos atualizados durante a noite a partir do R2, na mesma origem do site.
// GET /vivo/6258.json   ->  objeto "vivo_6258.json" (snapshot do coletor)
// GET /vivo/avisos.json ->  objeto "avisos.json" (avisos dinâmicos, ver publicar_aviso.sh)
export async function onRequestGet({ params, env }) {
  if (!env.VIVO) return new Response("not found", { status: 404 }); // sem R2 ligado: as páginas usam o TSE / a cópia do site
  const chave = /^\d+\.json$/.test(params.arq) ? `vivo_${params.arq}` : params.arq === "avisos.json" ? "avisos.json" : null;
  if (!chave) return new Response("not found", { status: 404 });
  const obj = await env.VIVO.get(chave);
  if (!obj) return new Response("not found", { status: 404 });
  return new Response(obj.body, {
    headers: { "content-type": "application/json", "cache-control": "no-cache", etag: obj.httpEtag },
  });
}
