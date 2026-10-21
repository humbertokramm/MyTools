# 📊 MyTools

Ferramentas para automação de testes de hardware: captura de sinais via osciloscópio, análise/visualização de waveforms, deploy de firmware e utilitários de bancada.

---

## 🧭 Arquitetura

```mermaid
flowchart TD

subgraph Análise
    CS[csvscope.py\nCsvScope]
    EM[engMath.py]
    CS --> EM
end

subgraph Instrumentação
    SC[scope.py\nScope]
    DS[detectScope.py]
    TK[tektronix.py\nTektronixScope]
    KS[keysight.py\nKeysightScope]
    DS --> SC
    SC -->|TEKTRONIX| TK
    SC -->|KEYSIGHT / AGILENT| KS
end

subgraph Serial & Firmware
    SI[serializefile.py]
    II[imageInstaller.py]
    COM[selectcom.py]
    SI --> COM
    II --> COM
end

subgraph Utilitários
    DH[dirHandle.py]
    IV[intranetVersionChecker.py]
    UL[updateLibScript.py]
end

Script([Script de teste]) --> SC
Script --> CS
SC -->|captura CSV| CS
```

---

## 📦 Módulos

### 🔬 Análise de sinal

| Módulo | Classe / Funções | Descrição |
|--------|-----------------|-----------|
| `csvscope.py` | `CsvScope` | Carrega CSVs de osciloscópio, plota waveforms, FFT, diagrama de olho PAM e anotações automáticas |
| `engMath.py` | `format_eng`, `format_eng_str`, `format_value` | Conversões de notação de engenharia (k, m, µ, n, …) |

### 📡 Drivers de instrumento

| Módulo | Classe / Funções | Descrição |
|--------|-----------------|-----------|
| `scope.py` | `Scope` | Hub VISA: detecta o instrumento e roteia para o driver correto |
| `tektronix.py` | `TektronixScope` | Driver SCPI para Tektronix DPO/MSO (waveform, screenshot, cursores, medições) |
| `keysight.py` | `KeysightScope` | Driver SCPI para Keysight / Agilent DSO-X (waveform, screenshot, markers, medições) |
| `detectScope.py` | `select_visa_resource` | Lista e seleciona recursos VISA disponíveis |

### 🔌 Serial & Firmware

| Módulo | Funções | Descrição |
|--------|---------|-----------|
| `selectcom.py` | `list_ports`, `open_port`, `select_and_open_port` | Seleção e abertura de portas seriais |
| `serializefile.py` | `send_line`, `wait_for_prompt` | Deploy de arquivos Lua via serial (HEREDOC) |
| `imageInstaller.py` | `run_installation` | Instalação de imagem via ONIE por serial |
| `RTC_Test.py` | — | Teste e sincronização de RTC via NTP + SSH/Serial |

### 🛠 Utilitários

| Módulo | Funções | Descrição |
|--------|---------|-----------|
| `dirHandle.py` | `print_colored`, `sanitize_filename`, `select_file`, `select_from_list` | Output colorido, seleção interativa de arquivos |
| `intranetVersionChecker.py` | `check_update`, `update_local` | Verifica e baixa versões de firmware da intranet |
| `updateLibScript.py` | `check_site`, `check_and_pull` | Atualiza repositórios Git locais |
| `registrarhook.py` | CLI | Instala o hook `commit-msg` do Gerrit num repo (Change-Id automático); baixa via `pscp`/Pageant com fallback HTTPS |
| `pcbview.py` | CLI / `abrir()` | Abre o *Viewer PCB & 3D* da empresa já no componente, com o projeto carregado e só a camada do lado dele |

---

## 🚀 Uso rápido

### Captura + análise de waveform

```python
from csvscope import CsvScope
from scope import Scope as SC

# 1. Captura o sinal e salva CSV + screenshot
SC.main(
    "minha_medicao",
    resource="USB::0x0699::0x0374::C013011::INSTR",
    channel="CH1",
    info={
        'meas':   ['Vmax', 'Vmin', 'RiseTime'],
        'cursor': {'y1': 0.8, 'y2': 2.0, 'x1': -200e-9, 'x2': 200e-9},
    },
    debug=False,
    overwrite=True,
)

# 2. Carrega, anota e plota
CS = CsvScope("Minha Medição")
CS.load(f="minha_medicao", n="CH1", config={'label x': 'Time[ns]', 'label y': 'Voltage[V]'})
CS.set_annotation_dir('Vmax', 'N')
CS.set_annotation_dir('Vmin', 'S')
CS.plot()
CS.hold()
```

### Deploy de arquivo Lua via serial

```bash
python serializefile.py COM3        # porta específica
python serializefile.py COM3 -p     # abre PuTTY após o envio
```

### Abrir o Viewer PCB & 3D direto no componente

```bash
python pcbview.py C:\Projetos\089100_PROJ -c C1052      # abre o navegador no componente
python pcbview.py C:\Projetos\089100_PROJ -c C200 -p 2  # destacando o pino 2
python pcbview.py C:\Projetos\089100_PROJ -n CORE_VDD   # uma net inteira
```

O nome da net aceita trecho: `-n SWITCH_TRST` acha `#SWITCH_TRST`. Com o `#` literal são
necessárias aspas (`-n "#SWITCH_TRST"`), senão o shell trata o resto da linha como comentário
e o argumento nem chega ao script.

Uma página `file://` não consegue ler pasta por caminho, então o `pcbview` serve o viewer e o
`.PcbDoc` em `http://127.0.0.1` e injeta um gancho que carrega o projeto sozinho, seleciona o
componente, vira a placa se ele estiver embaixo e deixa visível só a camada daquele lado.
Com `-n`/`net=` ele seleciona uma net inteira e liga a Top, a Bottom e as camadas em que
aquela net tem cobre — uma trilha que corre por um layer interno sumiria, e pareceria que
nada foi selecionado. A barra de status diz em quais camadas o cobre está.
O HTML original não é alterado — a injeção acontece na hora de servir.

Dentro de um script, a mesma aba acompanha os pontos seguintes (ela consulta o alvo no servidor):

```python
import pcbview
pcbview.abrir(r"C:\Projetos\089100_PROJ", "C1052")   # 1ª chamada abre o navegador
pcbview.abrir(r"C:\Projetos\089100_PROJ", "C200", pino="2")
```

### Instalar o hook commit-msg do Gerrit (Change-Id automático)

```bash
python registrarhook.py                       # no diretório do repo
python registrarhook.py C:\Projetos\dmos-docs --test   # aponta o repo e valida
python registrarhook.py --https               # força o fallback HTTPS
```

> Neste PC o `py` é Python 3.4 — use o 3.14:
> `%LOCALAPPDATA%\Programs\Python\Python314\python.exe registrarhook.py`

---

## ⚙️ Requisitos

Python **3.9+**

```
numpy
pandas
matplotlib
scipy
scikit-learn
pyvisa
pyvisa-py
pyserial
requests
gitpython
```

> Instale com: `pip install -r requirements.txt`

---

## 👨‍💻 Autor

Humberto Kramm
