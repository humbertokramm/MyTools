# Emissão radiada e conduzida (N9010A)

Captura no analisador de espectro e análise dos gráficos em uma janela só.

```
python emissao_gui.py
```

| Arquivo | Função |
|---------|--------|
| `emissao_gui.py` | Janela (abas Captura e Análise) |
| `emissao_captura.py` | Sequência de captura da radiada e da conduzida |
| `emissao_analise.py` | Lista as medidas, plota, calcula os picos, exclui |
| `sa.py`, `agilent_sa.py` | Driver VISA do analisador |
| `radiada_plot.py` | Leitura dos CSVs (usada pela análise) |
| `emissao_gui_win7.spec`, `build_emissao_exe.bat` | Build do exe |
| `organiza_medidas.py` | Passa as medidas antigas para as pastas e nomes atuais |
| `emissao.ico`, `gera_icone.py` | Ícone do exe e da janela, e o script que o desenha |

## Captura

Uma execução passa por todas as combinações marcadas na tela:

- **Tensões**: 48 VDC, 127 VAC, 220 VAC e outras digitadas (separadas por `;`).
- **Slots da PSU**: SL1, SL2 e outros digitados; nenhum marcado = equipamento
  sem slot.
- **Polarização** (radiada): H e V.
- **Ordem das trocas**: a de cima troca menos vezes, a de baixo a cada
  combinação. A janela mostra quantas combinações e capturas vão sair, e o
  aviso ao operador diz o que trocar em cada passo.
- **Pular esta combinação**: botão ao lado de Continuar, em cada aviso de
  troca. A sequência segue para a próxima combinação sem medir esta (na
  conduzida, a partir do condutor em que foi pulada), e a lista do que foi
  pulado sai no log no fim. Uma faixa que já começou a varrer não é pulada.
- **Ambiente** (radiada), sempre medido **depois** do EUT:
  - *em cada combinação*: EUT, depois o EUT é desligado e mede o ambiente,
    com a mesma hora no nome, então os dois ficam lado a lado na pasta;
  - *por polarização*: todas as combinações de uma polarização com o EUT
    ligado e, depois da última delas, n medições de ambiente com a antena
    ainda nessa polarização (EUT H, EUT H, ..., ambiente H n vezes, EUT V,
    ..., ambiente V n vezes). Na análise, o ambiente é o máximo ponto a
    ponto dessas medições (pega raias esporádicas);
  - *não medir*.
- **Conduzida**: L1 e L2 em cada combinação de slot e tensão. Depois da
  faixa mais larga de cada linha, compara os traces com os limites em
  150 kHz–1 MHz, 1–5 MHz e 5–30 MHz e, se uma região sem captura detalhada
  tiver pico a menos de 6 dB do limite, pergunta se deve capturá-la também.

Tudo de um ensaio fica em duas pastas, e o nome do arquivo identifica a
medida:

```
<Medidas>\Radiada\Imagens\   PNG da tela do analisador (com a peak table)
<Medidas>\Radiada\Traces\    CSV de cada trace (Max, Med) e do limite
<Medidas>\Conduzida\Imagens\ e \Traces\

Radiada 48 VDC SL1 - Classe A - 30MHz-130MHz - H - (17-11 11h30) EUT.png
Radiada 48 VDC SL1 - Classe A - 30MHz-130MHz - H - (17-11 11h30) Ambiente.png
Radiada - Classe A - 30MHz-130MHz - H - (17-11 14h05) Ambiente.png   (ambiente por polarização)
Conduzida 48 VDC SL1 - Classe A - 150kHz-30MHz - (17-11 11h30) L1 - Max.csv
```

A hora é a do início da combinação, com `h` porque o Windows não aceita
`:` em nome de arquivo. Duas medidas da mesma execução nunca ficam no mesmo
minuto: se cairiam, a hora da segunda avança um minuto.

## Análise

Árvore ensaio > data > hora > medida (as medidas do layout antigo, em
pastas por data, continuam aparecendo), gráfico com os limites, tabela de
picos e Salvar PNG. **Excluir** (ou Delete) apaga uma medida ou uma execução
inteira; não vai para a lixeira.

- **Travar amplitude / Travar frequência**: ao trocar de gráfico, mantém a
  escala que está na tela, para comparar medidas na mesma proporção. O
  Home da barra volta para a escala cheia.
- **Marcas**: um clique marca um ponto (gruda na curva mais próxima) e a
  marca aparece em todos os gráficos; clicar nela remove. Ficam salvas no
  `emissao_gui.json`.
- **Salvar todos...**: exporta em PNG todas as medidas do ramo selecionado
  na árvore (ensaio, data, execução ou uma medida) para uma pasta só, com
  a escala que está na tela e as marcas. Nome do arquivo: o que a árvore
  mostra, com data e hora no fim
  (`Radiada - V - 48 - 2026-11-16 12h45.png`).

## Organizar medidas antigas

`organiza_medidas.py` passa as medidas do layout antigo (pastas por data,
polarização, tensão e hora) para o atual. Sem `--executar` só mostra o
plano; com ele, move os arquivos e grava um log que o `--desfazer` usa.

```
python organiza_medidas.py "<pasta Medidas>"
python organiza_medidas.py "<pasta Medidas>" --executar
python organiza_medidas.py --desfazer "<pasta Medidas>\organiza_medidas_<data>.csv"
```

A tensão e o slot vêm do nome da pasta da tensão (`SL2_48` → `48 VDC SL2`)
na radiada e do nome do arquivo na conduzida (se só o PNG tem o slot, ele
vale para o CSV gravado junto). A data é a dos arquivos; a hora é a da
subpasta da execução.

## Exe para o Windows 7

O PC do analisador roda Windows 7 de 64 bits, fora da rede. O exe carrega o
Python que o gerou, por isso o build usa o Python 3.8, o último que roda no
Windows 7:

```
build_emissao_exe.bat
```

Sai em `dist\EmissaoGUI_win7_64.exe`. Pacotes do 3.8: numpy 1.24.4,
matplotlib 3.7.5, pyvisa 1.13.0, pyvisa-py 0.7.2, pyinstaller 5.13.2. O
`.spec` troca o `MSVCP140.dll` por um compatível com o Windows 7, embute o
pyvisa-py (o exe de 64 bits não enxerga o VISA de 32 bits do PC) e falha o
build se algum binário depender de função posterior ao Windows 7.

## Versão anterior

Os scripts de console que a janela substituiu (`radiada_capture.py`,
`conduzida_capture.py`, `radiada_plot_all.bat`) foram removidos e estão no
histórico do git. As medidas feitas com eles, sem a subpasta de hora,
continuam aparecendo na árvore, direto embaixo da data.
