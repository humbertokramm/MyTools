# Sugestão para o Viewer PCB & 3D — abrir direto num componente ou net

Diogo, usei bastante o teu viewer numa campanha de medição de ruído (osciloscópio em
dezenas de capacitores de desacoplamento) e acabei fazendo umas mudanças na minha cópia
para não ter que procurar o componente na mão a cada ponto. Segue o que fiz, dividido em
três níveis independentes — dá para pegar só o primeiro, ou os três.

Nada aqui muda a interface existente: é só ponto de entrada. A inteligência toda já estava
no teu código (`selectComp`, `selectNet`, `loadFiles`); o que faltava era um jeito de
chamar de fora.

---

## Nível 1 — a casca aceitar mais do que o nome da ferramenta (1 linha)

Hoje o hash escolhe a ferramenta e nada mais, porque a comparação é exata:

```js
function current(){ const h=location.hash.replace('#',''); return Object.keys(KINDS).find(n=>KINDS[n].hash===h)||null; }
```

Ignorando o que vem depois da barra, `#projeto/C1052` continua abrindo o visualizador de
projeto e sobra espaço para o resto:

```js
function current(){ const h=location.hash.replace('#','').split('/')[0]; return Object.keys(KINDS).find(n=>KINDS[n].hash===h)||null; }
```

---

## Nível 2 — o visualizador de projeto focar no que veio no hash

Com o projeto já carregado, `#projeto/C1052` seleciona o componente, vira a placa se ele
estiver no Bottom e deixa visível só a camada daquele lado; `#projeto/C1052/2` destaca o
pino 2 e a net dele. Funciona na hora pelo `hashchange`, sem recarregar nem perder o
projeto lido.

```js
/* ---------- abrir direto num componente: #projeto/C1052 ou #projeto/C1052/2 ---------- */
const IDS = { topCobre:1, botCobre:32, topSilk:33, botSilk:34, padsVias:74 };

function isolaLado(lado){
  const baixo = lado === 'Bottom';
  const manter = new Set([baixo?IDS.botCobre:IDS.topCobre, baixo?IDS.botSilk:IDS.topSilk,
                          IDS.padsVias, 'holes', 'board']);
  S.visible = new Set([...manter].filter(k => typeof k!=='number' || S.pcb.layers.has(k)));
  S.active = null;
}

function focoPorHash(){
  if (!S.pcb) return;
  let h=''; try{ h=(parent!==window?parent.location.hash:location.hash)||''; }catch(e){}
  const partes = h.replace('#','').split('/');
  const ref = partes[1], pino = partes[2];
  if (!ref) return;
  const alvo = decodeURIComponent(ref).trim().toUpperCase();
  const c = S.pcb.comps.find(c => (c.designator||'').toUpperCase() === alvo);
  if (!c){ setStatus('Componente '+alvo+' nao encontrado nesta placa'); return; }
  if (S.view !== 'pcb') setView('pcb');
  isolaLado(c.layer);
  S.pcbView.flip = (c.layer === 'Bottom');
  let p = null;
  if (pino){ const n = decodeURIComponent(pino).trim().toUpperCase();
             p = (c.pads||[]).find(p => String(p.name).toUpperCase() === n) || null; }
  selectComp(c, p ? {pad:p, net:p.net} : {});
  renderSide();   // o painel acompanha as camadas isoladas
  redraw();
}
try{ (parent!==window?parent:window).addEventListener('hashchange', focoPorHash); }catch(e){}
```

E uma chamada a `focoPorHash()` no fim do `loadFiles()`, logo depois do
`if (S.pcb) fitPCB();`, para o caso de a URL já vir com o componente antes de o projeto ser
aberto.

### Duas coisas que apareceram aqui e podem te interessar à parte

**1. `fitPCB` sai com escala zero quando o canvas ainda não tem altura.** A guarda atual
cobre a largura:

```js
const b=box||S.pcb.bbox, r=cv.getBoundingClientRect(); if (!r.width) return;
```

Com `r.height === 0` (aba em segundo plano, janela minimizada, layout ainda assentando) ele
segue adiante e grava `S.pcbView.s = 0` — a tela fica em branco e só volta com um pan ou um
resize. Aqui apareceu sempre que o foco acontecia durante a carga. Talvez valha `if
(!r.width || !r.height) return;` e reenquadrar no `resize`.

**2. Isolar camada por net: o caminho que parecia melhor estava errado.** Comecei deixando
só a Top e a Bottom ligadas, com medo de que ligar as camadas da net acendesse a placa
inteira numa alimentação. Na prática deu ruim: a `#SWITCH_TRST` corre pela `L3 - MidLayer1`,
então a net era selecionada e **não aparecia nada** — parece defeito da ferramenta.

O certo foi ligar a Top, a Bottom e as camadas em que aquela net tem cobre, que saem de
graça das chaves do `S.netGeo` que o teu `selectNet` já monta:

```js
for (const [l,g] of S.netGeo) if (g.any && typeof l === 'number') S.visible.add(l);
```

E o medo não se confirmou, porque plano não é geometria de net: a `DGND` desta placa, com
5618 pads, acrescenta só duas camadas. O efeito colateral disso é que uma ligação feita
**pelo plano** (`L2 - GND`, `L4 - GND`…) não acende — para GND aparecem as trilhas e os
pads, não o plano. Achei melhor assim, mas é o tipo de decisão que você pode querer tomar
diferente.

Para net o foco é o mesmo caminho do teu `pickResult`:

```js
const i = S.pcb.nets.findIndex(n => (n.name||'').toUpperCase() === alvo);
S.selComp = null; S.schSel = null; selectNet(i);
const b = new BBox();
(S.pcb.nets[i].pads||[]).forEach(p => b.add(p.x, p.y, Math.max(p.sx,p.sy)/2));
if (b.ok) fitPCB(b);
```

---

## Nível 3 — carregar o projeto sozinho, para chamar de um script

Esse é o nível que resolve o meu caso de bancada, e é o mais invasivo — vale discutir se
faz sentido no teu viewer ou se é melhor ficar do lado de fora, como está hoje.

O problema: uma página `file://` não consegue ler pasta por caminho, então o projeto sempre
tem que ser escolhido na mão, e abrir a URL de novo cria outra aba que perde o que estava
carregado. Isso impede chamar o viewer de um script de medição.

A saída que usei foi servir o viewer e o `.PcbDoc` em `http://127.0.0.1` a partir do Python.
Aí a página consegue buscar o projeto sozinha e entregar ao **teu** carregador, sem duplicar
nada:

```js
async function carregarDoServidor(){
  const lista = await (await fetch('projeto/manifest.json')).json();
  const arquivos = [];
  for (const nome of lista){
    const resp = await fetch('projeto/' + nome.split('/').map(encodeURIComponent).join('/'));
    const f = new File([await resp.blob()], nome.split('/').pop(), {type:'application/octet-stream'});
    f.path = nome;            // mesmo contrato do webkitRelativePath
    arquivos.push(f);
  }
  await loadFiles(arquivos);  // caminho idêntico ao do "Abrir pasta..."
}
```

Serve só o `.PcbDoc` por padrão: com as dezenas de `.SchDoc` do nosso projeto a carga fica
bem mais lenta, e para medir na placa o esquemático não é necessário.

E, para a mesma aba acompanhar uma varredura sem recarregar, a página consulta um alvo no
servidor a cada 700 ms (`{comp, pino, net, iso, seq}`) e refoca quando o `seq` muda. É
simples, mas dá para pensar em algo melhor do teu lado — um `postMessage` padronizado, por
exemplo.

**Importante:** o teu arquivo não é alterado. O Python desempacota o documento base64 do
visualizador de projeto, injeta o gancho e reempacota **na hora de servir**; o
`Viewer_PCB_3D.html` em disco continua intacto. Se você mudar o viewer, basta trocar o
arquivo que o script continua funcionando, desde que os nomes internos (`loadFiles`,
`selectComp`, `selectNet`, `S.visible`, `renderSide`) se mantenham.

---

## Pedido à parte: girar a vista

Esse não tem nada a ver com automação, é uso de bancada puro. Medindo com a placa na mão,
ela quase nunca está na orientação do desenho — às vezes de cabeça para baixo, às vezes de
lado — e aí cada componente exige uma tradução mental. O Altium também não faz isso, e é
uma falta antiga.

Girar é independente do `F`: o `F` troca o lado (espelha), girar mantém o lado e só
acompanha como a placa está na bancada. Placa de cabeça para baixo vista por baixo é `F`
mais 180°.

O controle caberia bem no painel **Exibição**, logo abaixo do "Ver por baixo (F)", com uma
tecla no mesmo espírito (`R` girando 90°, `Shift+R` para o outro lado).

Pelo que olhei, a mudança encosta em quatro lugares:

1. **`viewMatrix()`** — hoje só escala e espelho, com os termos cruzados zerados:
   ```js
   return [sx,0,0,sy, cv.width/2-sx*v.cx, cv.height/2-sy*v.cy];
   ```
   Com rotação eles deixam de ser zero.
2. **`screenToBoard()`** — inverte assumindo matriz diagonal (`(X-m[4])/m[0]`), e passaria a
   precisar da inversa de verdade.
3. **`toDev()`** — mesma coisa, usa só `m[0]` e `m[3]`.
4. **O arrasto**, no `pointermove`:
   ```js
   v.cx = drag.cx-(v.flip?-dx:dx)/v.s;  v.cy = drag.cy+dy/v.s;
   ```
   Aqui vale uma sugestão que resolve dois problemas de uma vez: medir o arrasto em
   coordenadas de placa, com o próprio `screenToBoard` do começo e do fim do movimento. Além
   de funcionar girado, some o caso especial do `flip`.

O zoom na roda não deve precisar de nada, porque ele já trabalha a partir do
`screenToBoard`.

Para não ficar só na sugestão, fiz isso por fora, no gancho que o `pcbview.py` injeta: troca
o `viewMatrix`, o `screenToBoard` e o `toDev`, e corrige o arrasto num listener registrado
depois do teu, no mesmo evento — só quando há giro. Conferi nos quatro ângulos: o componente
fica no centro, a ida-e-volta tela↔placa erra zero, o ponto sob o cursor não sai do lugar no
arrasto nem na roda, e o clique continua acertando o pad certo. A 0° a matriz sai idêntica à
tua, então sem giro nada muda.

O listener duplo é gambiarra de quem está do lado de fora, claro — no teu código isso vira
meia dúzia de linhas no lugar certo. O botão eu coloquei exatamente no painel Exibição, como
"Girar (R) ⟲ ⟳", para você ver se o lugar faz sentido.

---

## O lado Python (anexo)

Dois arquivos:

- `pcbview.py` — sobe o servidor local, injeta o gancho e abre o navegador.
- `pcbview_gancho.js` — o gancho completo (níveis 2 e 3 juntos).

Uso na linha de comando:

```bash
python pcbview.py C:\Projetos\089100_PROJ -c C1052       # componente
python pcbview.py C:\Projetos\089100_PROJ -c C200 -p 2   # pino 2 e a net dele
python pcbview.py C:\Projetos\089100_PROJ -n CORE_VDD    # net inteira
```

E dentro de um script de medição, que é o caso real: a primeira chamada abre o navegador, as
seguintes só reposicionam a mesma aba.

```python
import pcbview

PROJ = r"C:\Projetos\089100_PROJ"

for ponto in pontos_de_medicao:
    pcbview.abrir(PROJ, ponto["componente"])   # a aba pula no componente
    input("Enter para capturar: ")
    captura(ponto)
```

---

## Sugestão de uso, se você topar levar para o viewer

1. **Nível 1 + 2** já resolvem muita coisa sozinhos e são baratos: viram link. Dá para
   mandar `...#projeto/C1052` num chat ou colar num relatório, e quem abrir cai no
   componente certo (depois de apontar a pasta, como hoje).
2. Se for seguir para o **nível 3**, guardar o projeto no IndexedDB (você já guarda o
   handle do diretório) tornaria o "recarregar" automático e tiraria a necessidade do
   servidor no meu lado — seria melhor que a minha solução.
3. Um nome de parâmetro combinado (`?comp=`/`?net=`) vale mais que o hash se você quiser
   algo estável para automação; o hash eu usei por ser o que já existia.

Qualquer coisa me chama — testei no `089100_PROJ` (3831 componentes), com componente de
cima, de baixo, pino específico e net de alimentação, mas foi uso de bancada, não teste
sistemático.
