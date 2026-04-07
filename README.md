# 📊 CSVScope & Tools

Este repositório reúne um conjunto de scripts Python voltados para
automação de testes, análise de sinais e gerenciamento de firmware em
ambientes embarcados e laboratoriais.

------------------------------------------------------------------------

## 🧭 Visão Geral

``` mermaid
flowchart TD

A[Início] --> B{Tipo de operação}

B -->|Análise de sinal| C[csvscope.py]
C --> C1[Carregar CSV]
C1 --> C2[Processar sinal]
C2 --> C3[Plot / FFT / PAM]

B -->|Detectar instrumento| D[detectScope.py]
D --> D1[Listar VISA]
D1 --> D2[Selecionar instrumento]

B -->|Instalar firmware| E[imageInstaller.py]
E --> E1[Boot device]
E1 --> E2[Entrar ONIE]
E2 --> E3[Configurar rede]
E3 --> E4[Instalar via HTTP]

B -->|Verificar versão| F[intranetVersionChecker.py]
F --> F1[Consultar servidor]
F1 --> F2{Atualizado?}
F2 -->|Sim| F3[Fim]
F2 -->|Não| F4[Download + limpar antigos]

B -->|Deploy scripts| G[serializefile.py]
G --> G1[Selecionar serial]
G1 --> G2[Enviar arquivos .lua]
G2 --> G3[Abrir terminal]
```

------------------------------------------------------------------------

## 📦 Conteúdo

### 🔹 `csvscope.py`

Classe principal para processamento e visualização de sinais de
osciloscópios e instrumentos de medição.

**Principais funcionalidades:** - Leitura de múltiplos formatos CSV -
Plotagem de sinais - FFT - Diagrama de olho (PAM) - Filtros digitais -
Integração PyVISA

------------------------------------------------------------------------

### 🔹 `detectScope.py`

Detecção de instrumentos VISA.

------------------------------------------------------------------------

### 🔹 `imageInstaller.py`

Instalação automatizada via ONIE.

------------------------------------------------------------------------

### 🔹 `intranetVersionChecker.py`

Verificação e atualização de firmware.

------------------------------------------------------------------------

### 🔹 `serializefile.py`

Deploy serial de arquivos `.lua`.

------------------------------------------------------------------------

## 🚀 Exemplos

``` python
from csvscope import csvscope

scope = csvscope("Teste")
scope.format("file.csv")
scope.plot()
```

------------------------------------------------------------------------

## ⚙️ Requisitos

-   Python 3.8+
-   VISA instalado (opcional)

------------------------------------------------------------------------

## 👨‍💻 Autor

Humberto Kramm
