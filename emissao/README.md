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

## Captura

- **Radiada**: ambiente e EUT por polarização e tensão, em
  `Radiada\<data>\<polarização>\<tensão>\<HHhMM>`.
- **Conduzida**: L1 e L2 por tensão, em `Conduzida\<data>\<HHhMM>`. Salva a
  imagem, os traces (CSV) e as linhas de limite lidas do analisador.
- Cada execução grava numa subpasta com a hora, então repetir o ensaio não
  sobrescreve nada.
- Na conduzida, depois da faixa mais larga de cada linha, a ferramenta
  compara os traces com os limites em 150 kHz–1 MHz, 1–5 MHz e 5–30 MHz. Se
  uma região sem captura detalhada tiver pico a menos de 6 dB do limite, ela
  pergunta se deve capturá-la também. A resposta vale para o resto da
  execução.

## Análise

Árvore ensaio > data > hora > medida, gráfico com os limites, tabela de
picos e Salvar PNG. **Excluir** (ou Delete) apaga uma medida ou uma execução
inteira; não vai para a lixeira.

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
