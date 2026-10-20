/* ------------------------------------------------------------------
   Gancho do pcbview.py para o "Visualizador de Projeto" do Viewer PCB & 3D.

   Injetado quando o pcbview.py serve o viewer por HTTP. Faz o que a mao
   faria: carrega o projeto, acha o componente, deixa visivel so a camada
   do lado dele e vira a placa se ele estiver embaixo.

   Parametros vem da query da pagina (?comp=C200&pino=2&iso=1) e tambem do
   hash (#projeto/C200/2), que continua funcionando na mao.
   ------------------------------------------------------------------ */
(function () {
  const IDS = { topCobre: 1, botCobre: 32, topSilk: 33, botSilk: 34, padsVias: 74 };

  function pedido() {
    let q = {};
    try {
      const u = new URLSearchParams((parent !== window ? parent.location : location).search);
      q = { comp: u.get('comp') || '', pino: u.get('pino') || '', iso: u.get('iso') !== '0' };
    } catch (e) { q = { comp: '', pino: '', iso: true }; }
    if (!q.comp) {
      let h = '';
      try { h = ((parent !== window ? parent.location : location).hash || ''); } catch (e) {}
      const p = h.replace('#', '').split('/');
      q.comp = p[1] ? decodeURIComponent(p[1]) : '';
      q.pino = p[2] ? decodeURIComponent(p[2]) : q.pino;
    }
    return q;
  }

  /* Deixa visivel so o que interessa para medir deste lado da placa. */
  function isolaLado(lado) {
    const baixo = lado === 'Bottom';
    const manter = new Set([baixo ? IDS.botCobre : IDS.topCobre,
                            baixo ? IDS.botSilk : IDS.topSilk,
                            IDS.padsVias, 'holes', 'board']);
    S.visible = new Set([...manter].filter(k => typeof k !== 'number' || S.pcb.layers.has(k)));
    S.active = null;
  }

  /* Na primeira carga o canvas ainda nao tem altura e o fitPCB sai com
     escala zero - a tela fica em branco. Insiste ate enquadrar. */
  function enquadrarQuandoDer(tentativas) {
    if (!S.selComp || !S.selComp.bbox) return;
    fitPCB(S.selComp.bbox);
    if (!(S.pcbView.s > 0) && tentativas > 0) {
      setTimeout(() => enquadrarQuandoDer(tentativas - 1), 150);
    }
  }

  function focar(q) {
    if (!S.pcb || !q.comp) return false;
    const alvo = q.comp.trim().toUpperCase();
    const c = S.pcb.comps.find(c => (c.designator || '').toUpperCase() === alvo);
    if (!c) { setStatus('Componente ' + alvo + ' nao encontrado nesta placa'); return false; }
    if (S.view !== 'pcb') setView('pcb');
    if (q.iso) isolaLado(c.layer);
    S.pcbView.flip = (c.layer === 'Bottom');
    let p = null;
    if (q.pino) {
      const n = q.pino.trim().toUpperCase();
      p = (c.pads || []).find(p => String(p.name).toUpperCase() === n) || null;
    }
    selectComp(c, p ? { pad: p, net: p.net } : {});
    renderSide();              // sincroniza o painel com as camadas isoladas
    redraw();
    enquadrarQuandoDer(40);
    setStatus('Componente ' + c.designator + ' no lado ' + c.layer
              + (p ? ', pino ' + p.name : '') + (q.iso ? ' - so a camada deste lado' : ''));
    return true;
  }

  /* Monta objetos File a partir do que o pcbview.py serve e entrega ao
     mesmo caminho que o botao "Abrir pasta..." usa. */
  async function carregarDoServidor() {
    const r = await fetch('projeto/manifest.json', { cache: 'no-store' });
    if (!r.ok) throw new Error('manifest ' + r.status);
    const lista = await r.json();
    const arquivos = [];
    for (const nome of lista) {
      setStatus('Baixando ' + nome + '…');
      const resp = await fetch('projeto/' + nome.split('/').map(encodeURIComponent).join('/'),
                               { cache: 'no-store' });
      if (!resp.ok) throw new Error(nome + ': ' + resp.status);
      const f = new File([await resp.blob()], nome.split('/').pop(),
                         { type: 'application/octet-stream' });
      f.path = nome;
      arquivos.push(f);
    }
    await loadFiles(arquivos);
  }

  async function inicio() {
    const q = pedido();
    try {
      if (!S.pcb) await carregarDoServidor();
    } catch (e) {
      setStatus('Nao consegui carregar o projeto do servidor: ' + (e.message || e));
      return;
    }
    focar(q);
  }

  // pedidos seguintes (mesma aba): so refoca
  try {
    (parent !== window ? parent : window).addEventListener('hashchange', () => focar(pedido()));
  } catch (e) {}
  window.addEventListener('pcbview:foco', () => focar(pedido()));

  /* O script de bancada troca o alvo no servidor; a aba acompanha sem
     recarregar nem perder o projeto ja lido. */
  let ultimoSeq = -1;
  async function vigiarAlvo() {
    try {
      const r = await fetch('alvo.json', { cache: 'no-store' });
      if (r.ok) {
        const a = await r.json();
        if (a.seq !== ultimoSeq) {
          const primeiro = ultimoSeq < 0;
          ultimoSeq = a.seq;
          if (!primeiro && a.comp) focar({ comp: a.comp, pino: a.pino || '', iso: a.iso !== false });
        }
      }
    } catch (e) { /* servidor fechou: a janela continua util do jeito que esta */ }
    setTimeout(vigiarAlvo, 700);
  }
  vigiarAlvo();

  if (document.readyState === 'complete') setTimeout(inicio, 0);
  else window.addEventListener('load', () => setTimeout(inicio, 0));
})();
