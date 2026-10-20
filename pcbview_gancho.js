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
      q = { comp: u.get('comp') || '', pino: u.get('pino') || '',
            net: u.get('net') || '', iso: u.get('iso') !== '0' };
    } catch (e) { q = { comp: '', pino: '', net: '', iso: true }; }
    if (!q.comp && !q.net) {
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

  /* Enquanto a aba esta em segundo plano o canvas pode ficar sem altura, e
     o fitPCB sai com escala zero - a tela fica em branco. Guarda o que
     deveria estar enquadrado e insiste, inclusive quando a janela volta. */
  let ultimoQuadro = null;

  function enquadrar(box) {
    if (box) ultimoQuadro = box;
    if (!ultimoQuadro) return;
    fitPCB(ultimoQuadro);
  }

  function enquadrarQuandoDer(box, tentativas) {
    enquadrar(box);
    if (!(S.pcbView.s > 0) && tentativas > 0) {
      setTimeout(() => enquadrarQuandoDer(null, tentativas - 1), 150);
    }
  }

  const retomar = () => { if (ultimoQuadro && !(S.pcbView.s > 0)) enquadrar(null); };
  window.addEventListener('resize', retomar);
  document.addEventListener('visibilitychange', retomar);

  /* Uma net costuma andar por muitas camadas, e qual delas interessa depende
     do que se vai medir. Entao deixa so as duas externas ligadas e o resto
     por conta de quem esta olhando. */
  function isolaNet() {
    const manter = new Set([IDS.topCobre, IDS.botCobre, IDS.padsVias]
                           .filter(id => S.pcb.layers.has(id)));
    manter.add('holes');
    manter.add('board');
    S.visible = manter;
    S.active = null;
  }

  function focarNet(q) {
    const alvo = q.net.trim().toUpperCase();
    const i = S.pcb.nets.findIndex(n => (n.name || '').toUpperCase() === alvo);
    if (i < 0) { setStatus('Net ' + alvo + ' nao encontrada nesta placa'); return false; }
    if (S.view !== 'pcb') setView('pcb');
    S.selComp = null; S.schSel = null;
    selectNet(i);
    if (q.iso) isolaNet();
    const b = new BBox();
    (S.pcb.nets[i].pads || []).forEach(p => b.add(p.x, p.y, Math.max(p.sx, p.sy) / 2));
    if (b.ok) enquadrarQuandoDer(b, 40);
    renderSide();
    redraw();
    setStatus('Net ' + S.pcb.nets[i].name + ' - ' + (S.pcb.nets[i].pads || []).length
              + ' pads' + (q.iso ? ' - so Top e Bottom ligadas; ligue as internas no painel'
                                 : ''));
    return true;
  }

  function focar(q) {
    if (!S.pcb) return false;
    if (q.net) return focarNet(q);
    if (!q.comp) return false;
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
    enquadrarQuandoDer(c.bbox, 40);
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
          if (!primeiro && (a.comp || a.net)) {
            focar({ comp: a.comp || '', pino: a.pino || '', net: a.net || '',
                    iso: a.iso !== false });
          }
        }
      }
    } catch (e) { /* servidor fechou: a janela continua util do jeito que esta */ }
    setTimeout(vigiarAlvo, 700);
  }
  vigiarAlvo();

  if (document.readyState === 'complete') setTimeout(inicio, 0);
  else window.addEventListener('load', () => setTimeout(inicio, 0));
})();
