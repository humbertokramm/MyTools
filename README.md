# 📊 CSVScope & Tools

Este repositório reúne ferramentas para automação de testes, análise de sinais, deploy de firmware e interação com dispositivos embarcados.

---

## 🧭 Visão Geral

```mermaid
flowchart TD

A[Início] --> B{Tipo de operação}

%% ANALISE
B -->|Análise de sinal| C[csvscope.py]
C --> C1[FFT / Plot / PAM]
C --> H[engMath.py]
C --> I[keysight.py]

%% INSTRUMENTO
B -->|Instrumentação| D[detectScope.py]
D --> I

%% INSTALAÇÃO
B -->|Instalar firmware| E[imageInstaller.py]
E --> E1[ONIE Install]

%% VERSIONAMENTO
B -->|Atualização| F[intranetVersionChecker.py]
F --> F1[Download FW]

%% DEPLOY
B -->|Deploy Lua| G[serializefile.py]
G --> K[dirHandle.py]

%% RTC
B -->|RTC Test| J[RTC_Test.py]
J --> J1[NTP + SSH/Serial]

```

---

## 📦 Conteúdo

### 🔹 csvscope.py
Análise de sinais (FFT, plot, PAM)

### 🔹 keysight.py
Integração com osciloscópios Keysight (SCPI)

### 🔹 engMath.py
Conversões de engenharia (k, m, µ, etc.)

### 🔹 detectScope.py
Detecção de instrumentos VISA

### 🔹 imageInstaller.py
Instalação via ONIE

### 🔹 intranetVersionChecker.py
Gerenciamento de firmware

### 🔹 serializefile.py
Deploy de arquivos via serial

### 🔹 dirHandle.py
Utilitário de interface e arquivos

### 🔹 RTC_Test.py
Teste e sincronização de RTC

---

## 🧠 Arquitetura

- **Core:** csvscope, imageInstaller, serializefile, RTC_Test  
- **Integração:** keysight, detectScope  
- **Utilitários:** engMath, dirHandle  

---

## ⚙️ Requisitos

Ver requirements.txt

---

## 👨‍💻 Autor

Humberto Kramm
