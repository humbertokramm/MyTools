# 📊 CSVScope & Tools

Este repositório reúne um conjunto de scripts Python voltados para
automação de testes, análise de sinais e gerenciamento de firmware em
ambientes embarcados e laboratoriais.

------------------------------------------------------------------------

## 📦 Conteúdo

### 🔹 `csvscope.py`

Classe principal para processamento e visualização de sinais de
osciloscópios e instrumentos de medição.

**Principais funcionalidades:** - Leitura de múltiplos formatos CSV
(Rohde, Tektronix, Master Tool, USB/VISA) - Plotagem de sinais no
domínio do tempo - Cálculo e plot de FFT - Geração de diagramas de olho
(PAM) - Anotações automáticas (RMS, Vmax, transições, etc.) - Filtros
digitais (Butterworth) - Integração com instrumentos via PyVISA

**Dependências:** - pandas - matplotlib - numpy - scipy - sklearn -
pyvisa

------------------------------------------------------------------------

### 🔹 `detectScope.py`

Ferramenta para detecção automática de instrumentos conectados via VISA.

**Funcionalidades:** - Lista dispositivos disponíveis - Consulta
identificação (`*IDN?`) - Permite seleção interativa do instrumento

------------------------------------------------------------------------

### 🔹 `imageInstaller.py`

Script para automação de instalação de firmware via serial (ex: ONIE).

**Fluxo:** 1. Abre porta serial 2. Aguarda boot do sistema 3. Interage
com GRUB 4. Entra em modo ONIE 5. Configura rede 6. Executa instalação
via HTTP

------------------------------------------------------------------------

### 🔹 `intranetVersionChecker.py`

Script para verificar e atualizar automaticamente versões de firmware
(.bin) a partir de servidores internos.

**Funcionalidades:** - Busca versões remotas (FT ou DMOS) - Compara com
arquivos locais - Detecta necessidade de atualização - Faz download
automático da versão mais recente - Remove versões antigas

------------------------------------------------------------------------

## 🚀 Exemplo de Uso

### CSVScope básico

``` python
from csvscope import csvscope

scope = csvscope("Teste de sinal")

scope.format("meu_arquivo.csv")
scope.plot()

scope.formatFFT()
scope.plotFFT()
```

------------------------------------------------------------------------

### Verificar atualização de firmware

``` python
from intranetVersionChecker import check_update, update_local

status, arquivo = check_update("FT", "4201")

if status == "UPDATE":
    update_local("FT", "4201")
```

------------------------------------------------------------------------

### Detectar instrumento VISA

``` bash
python detectScope.py
```

------------------------------------------------------------------------

## ⚙️ Requisitos

-   Python 3.8+
-   Acesso à rede (para downloads e instrumentos)
-   Drivers VISA instalados (para uso com instrumentos)

------------------------------------------------------------------------

## 🧠 Aplicações

Este conjunto de ferramentas é útil para:

-   Análise de sinais elétricos (laboratório / validação)
-   Automação de testes com osciloscópios
-   Processamento de dados de medições
-   Deploy automatizado de firmware
-   Integração com pipelines de validação de hardware

------------------------------------------------------------------------

## ⚠️ Observações

-   Alguns scripts assumem infraestrutura interna (URLs, imagens, etc.)
-   O `csvscope` depende de módulos auxiliares (`engMath`, `dirHandle`)
    que devem estar disponíveis no ambiente
-   O `imageInstaller` depende de um módulo externo `selectcom`

------------------------------------------------------------------------

## 📄 Licença

Uso interno / privado (ajustar conforme necessário)

------------------------------------------------------------------------

## 👨‍💻 Autor

Humberto Kramm
