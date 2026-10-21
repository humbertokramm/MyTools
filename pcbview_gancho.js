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

  /* Deixa ligadas as duas externas (contexto para achar onde encostar a
     ponta) mais as camadas em que a net realmente tem cobre - uma trilha
     que corre por um layer interno sumiria, e parece que nada foi
     selecionado. Devolve as camadas da net, para o aviso. */
  function isolaNet() {
    const manter = new Set([IDS.topCobre, IDS.botCobre, IDS.padsVias]
                           .filter(id => S.pcb.layers.has(id)));
    const daNet = [];
    if (S.netGeo) {
      for (const [l, g] of S.netGeo) {
        if (g.any && typeof l === 'number' && S.pcb.layers.has(l)) {
          manter.add(l);
          daNet.push(l);
        }
      }
    }
    manter.add('holes');
    manter.add('board');
    S.visible = manter;
    S.active = null;
    return daNet;
  }

  /* Nomes de net costumam ter prefixo que ninguem digita ('#SWITCH_TRST'),
     entao aceita trecho quando ele identifica uma net so. */
  function acharNet(alvo) {
    const nomes = S.pcb.nets.map(n => (n.name || '').toUpperCase());
    const exato = nomes.indexOf(alvo);
    if (exato >= 0) return { i: exato };
    const perto = [];
    for (let k = 0; k < nomes.length; k++) if (nomes[k].includes(alvo)) perto.push(k);
    if (perto.length === 1) return { i: perto[0] };
    return { i: -1, perto: perto };
  }

  function focarNet(q) {
    const alvo = q.net.trim().toUpperCase();
    const achado = acharNet(alvo);
    const i = achado.i;
    if (i < 0) {
      const perto = (achado.perto || []).map(k => S.pcb.nets[k].name);
      setStatus(perto.length
        ? 'Net "' + alvo + '" casa com ' + perto.length + ': ' + perto.slice(0, 8).join(', ')
        : 'Net ' + alvo + ' nao encontrada nesta placa');
      return false;
    }
    if (S.view !== 'pcb') setView('pcb');
    S.selComp = null; S.schSel = null;
    selectNet(i);
    const daNet = q.iso ? isolaNet() : [];
    const b = new BBox();
    (S.pcb.nets[i].pads || []).forEach(p => b.add(p.x, p.y, Math.max(p.sx, p.sy) / 2));
    if (b.ok) enquadrarQuandoDer(b, 40);
    renderSide();
    redraw();
    const nomes = daNet.map(l => (S.pcb.layers.get(l) || {}).name || l);
    setStatus('Net ' + S.pcb.nets[i].name + ' - ' + (S.pcb.nets[i].pads || []).length
              + ' pads' + (nomes.length ? ' - cobre em ' + nomes.join(', ') : ''));
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

  /* ------------------------------------------------------------------
     Girar a vista

     Medindo com a placa na mao, ela quase nunca esta na orientacao do
     desenho. Girar e independente do "Ver por baixo" (F): aquele troca o
     lado, este so acompanha como a placa esta na bancada.

     O viewer monta toda a vista numa matriz so, entao basta acrescentar a
     rotacao nela e refazer as duas conversoes que assumiam matriz diagonal.
     ------------------------------------------------------------------ */
  let giro = 0;

  function matrizDaVista() {
    const d = devicePixelRatio || 1, v = S.pcbView;
    const sx = (v.flip ? -1 : 1) * v.s * d, sy = -v.s * d;
    const t = giro * Math.PI / 180, co = Math.cos(t), si = Math.sin(t);
    const a = sx * co, b = sx * si, c = -sy * si, e = sy * co;
    return [a, b, c, e,
            cv.width / 2 - (a * v.cx + c * v.cy),
            cv.height / 2 - (b * v.cx + e * v.cy)];
  }

  viewMatrix = matrizDaVista;

  screenToBoard = function (ex, ey) {
    const r = cv.getBoundingClientRect(), d = devicePixelRatio || 1;
    const m = viewMatrix();
    const X = (ex - r.left) * d - m[4], Y = (ey - r.top) * d - m[5];
    const det = m[0] * m[3] - m[1] * m[2];
    if (!det) return [0, 0];
    return [(m[3] * X - m[2] * Y) / det, (m[0] * Y - m[1] * X) / det];
  };

  toDev = function (x, y) {
    const m = viewMatrix();
    return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
  };

  /* O arrasto do viewer calcula o pan direto em x/y da tela. Em vez de
     interferir no listener dele (que tambem cuida do HUD e de separar
     clique de arrasto), este corrige o resultado logo depois, no mesmo
     evento - e so quando ha giro. */
  let arrasto = null;
  cv.addEventListener('pointerdown', e => {
    arrasto = { x: e.clientX, y: e.clientY, cx: S.pcbView.cx, cy: S.pcbView.cy };
  });
  const soltar = () => { arrasto = null; };
  cv.addEventListener('pointerup', soltar);
  cv.addEventListener('pointercancel', soltar);
  cv.addEventListener('pointermove', e => {
    if (!giro || !arrasto || !S.pcb) return;
    if (Math.abs(e.clientX - arrasto.x) + Math.abs(e.clientY - arrasto.y) <= 3) return;
    S.pcbView.cx = arrasto.cx; S.pcbView.cy = arrasto.cy;   // desfaz a conta sem giro
    const ini = screenToBoard(arrasto.x, arrasto.y);
    const fim = screenToBoard(e.clientX, e.clientY);
    S.pcbView.cx = arrasto.cx - (fim[0] - ini[0]);
    S.pcbView.cy = arrasto.cy - (fim[1] - ini[1]);
    redraw();
  });

  function girarVista(passo) {
    giro = (((giro + passo) % 360) + 360) % 360;
    const mostra = document.getElementById('pcbviewGiroValor');
    if (mostra) mostra.textContent = giro + '°';
    redraw();
  }

  /* O controle vai no painel Exibicao, junto do "Ver por baixo (F)", que e
     a outra transformacao de vista. O painel e remontado pelo renderSide,
     entao o botao e recolocado depois dele. */
  function poeControleDeGiro() {
    const flip = document.getElementById('optFlip');
    if (!flip || document.getElementById('pcbviewGiro')) return;
    const linha = flip.closest('label') || flip.parentNode;
    if (!linha || !linha.parentNode) return;
    const caixa = document.createElement('div');
    caixa.id = 'pcbviewGiro';
    caixa.className = 'opt';
    caixa.style.cssText = 'display:flex;gap:6px;align-items:center;margin:4px 0';
    caixa.innerHTML = '<span>Girar (R)</span>'
      + '<button type="button" data-giro="-90" title="Girar para a esquerda">⟲</button>'
      + '<button type="button" data-giro="90" title="Girar para a direita">⟳</button>'
      + '<span id="pcbviewGiroValor">' + giro + '°</span>';
    linha.parentNode.insertBefore(caixa, linha.nextSibling);
    caixa.querySelectorAll('button').forEach(b => {
      b.onclick = () => girarVista(parseInt(b.dataset.giro, 10));
    });
  }

  const renderSideDoViewer = renderSide;
  renderSide = function () {
    const r = renderSideDoViewer.apply(this, arguments);
    try { poeControleDeGiro(); } catch (e) {}
    return r;
  };

  addEventListener('keydown', e => {
    if (e.target && e.target.tagName === 'INPUT' && e.target.type !== 'checkbox') return;
    if (e.key === 'r' || e.key === 'R') girarVista(e.shiftKey ? -90 : 90);
  });

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
    carregando = true;
    try {
      if (!S.pcb) await carregarDoServidor();
    } catch (e) {
      setStatus('Nao consegui carregar o projeto do servidor: ' + (e.message || e));
      carregando = false;
      return;
    }
    carregando = false;
    // se o script ja pediu outro ponto enquanto a placa carregava, vale o ultimo
    if (pendente) { focar(comoPedido(pendente)); pendente = null; }
    else focar(q);
  }

  // pedidos seguintes (mesma aba): so refoca
  try {
    (parent !== window ? parent : window).addEventListener('hashchange', () => focar(pedido()));
  } catch (e) {}
  window.addEventListener('pcbview:foco', () => focar(pedido()));

  /* O script de bancada troca o alvo no servidor; a aba acompanha sem
     recarregar nem perder o projeto ja lido. Quando o script passa para
     outra placa, o 'proj' do alvo muda e a aba carrega a placa nova ali
     mesmo, em vez de o script abrir outra aba. */
  let ultimoSeq = -1, projAtual = null, carregando = false, pendente = null;
  const comoPedido = a => ({ comp: a.comp || '', pino: a.pino || '', net: a.net || '',
                             iso: a.iso !== false });

  async function trocarDePlaca(a) {
    carregando = true;
    pendente = a;
    setStatus('Carregando a outra placa…');
    try {
      await carregarDoServidor();
    } catch (e) {
      setStatus('Nao consegui carregar a outra placa: ' + (e.message || e));
      carregando = false;
      return;
    }
    carregando = false;
    // o que pediram por ultimo enquanto carregava e o que vale
    if (pendente && (pendente.comp || pendente.net)) focar(comoPedido(pendente));
    pendente = null;
  }

  async function vigiarAlvo() {
    try {
      const r = await fetch('alvo.json', { cache: 'no-store' });
      if (r.ok) {
        const a = await r.json();
        if (a.seq !== ultimoSeq) {
          const primeiro = ultimoSeq < 0;
          ultimoSeq = a.seq;
          if (primeiro) {
            projAtual = a.proj;
          } else if (a.proj !== projAtual) {
            projAtual = a.proj;
            trocarDePlaca(a);                  // sem await: o vigia continua
          } else if (carregando) {
            pendente = a;                      // aplica quando a placa terminar
          } else if (a.comp || a.net) {
            focar(comoPedido(a));
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
