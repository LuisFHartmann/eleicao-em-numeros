/* Avisos dinâmicos (ex.: mudança de horário da apuração). Lidos de /vivo/avisos.json (R2, atualizável sem novo
   deploy, ver publicar_aviso.sh) ou, se não houver, de dados/avisos.json do próprio site. Cada aviso diz em quais
   páginas aparece ("ao-vivo", "votos", "inicio"...) e, opcionalmente, o período (desde/ate, ISO).
   Uso: <div class="avisos" data-pagina="ao-vivo"></div> e <script src="../avisos.js"></script>. */
(function () {
  "use strict";
  const caixas = [...document.querySelectorAll(".avisos[data-pagina]")];
  if (!caixas.length) return;
  const raiz = new URL(document.currentScript.src, location.href);
  const fontes = ["/vivo/avisos.json", new URL("dados/avisos.json", raiz).href];
  async function ler() {
    for (const u of fontes) {
      try {
        const r = await fetch(u, { cache: "no-cache" });
        if (r.ok) return await r.json();
      } catch { /* tenta a próxima fonte */ }
    }
    return { avisos: [] };
  }
  function vigente(a) {
    const agora = Date.now();
    return (!a.desde || Date.parse(a.desde) <= agora) && (!a.ate || agora < Date.parse(a.ate));
  }
  async function atualizar() {
    const { avisos = [] } = await ler();
    for (const cx of caixas) {
      const pg = cx.dataset.pagina;
      cx.replaceChildren(...avisos.filter(a => vigente(a) && (!a.paginas || a.paginas.includes(pg))).map(a => {
        const p = document.createElement("p");
        p.className = `aviso-dinamico ${a.nivel === "alerta" ? "alerta" : ""}`;
        p.setAttribute("role", "status");
        if (a.titulo) { const b = document.createElement("b"); b.textContent = a.titulo + " "; p.append(b); }
        p.append(document.createTextNode(a.texto ?? ""));
        if (a.link?.href) { p.append(" "); const l = document.createElement("a"); l.href = a.link.href; l.textContent = a.link.texto ?? "saiba mais"; l.rel = "noopener"; p.append(l); }
        return p;
      }));
    }
  }
  atualizar();
  setInterval(atualizar, 120000);
})();
