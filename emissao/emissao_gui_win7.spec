# -*- mode: python ; coding: utf-8 -*-
# Build do emissao_gui.py para o Windows 7 (rodar com o Python 3.8; ver
# build_emissao_exe.bat).
#
# Dois cuidados alem do build normal:
#  1. O PyInstaller pega o MSVCP140.dll do system32 do PC de build. O do
#     Windows 10/11 atual (14.4x+) chama funcoes que so existem a partir do
#     Windows 8, e o exe morre no Windows 7 com "DLL load failed while
#     importing _cext". Troca pela copia 14.16 que vem no matplotlib.libs.
#  2. No fim, confere todos os binarios: se algum importar do kernel32 uma
#     funcao que o Windows 7 nao tem, o build falha aqui, e nao la.
import glob
import os
import struct

import pefile
from PyInstaller.utils.hooks import collect_submodules

BITS = struct.calcsize('P') * 8
NOME = 'EmissaoGUI_win7_%d' % BITS

# kernel32: funcoes que entraram depois do Windows 7
POS_WIN7 = {
    'GetSystemTimePreciseAsFileTime', 'CreateFile2', 'CopyFile2', 'WaitOnAddress',
    'WakeByAddressAll', 'WakeByAddressSingle', 'GetCurrentPackageId',
    'GetOverlappedResultEx', 'PrefetchVirtualMemory', 'SetThreadDescription',
    'GetThreadDescription', 'VirtualAlloc2', 'MapViewOfFile3', 'GetTempPath2W',
}

a = Analysis(
    ['emissao_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # pyvisa_py: backend em Python puro. O pyvisa cai nele sozinho quando o
    # PC nao tem VISA da arquitetura do exe (o PC do N9010A so tem o de 32
    # bits), e ele e carregado por nome, entao o PyInstaller nao o acha.
    hiddenimports=['pyvisa.ctwrapper'] + collect_submodules('pyvisa_py'),
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# 1. MSVCP140.dll compativel com o Windows 7
import matplotlib
_libs = os.path.join(os.path.dirname(os.path.dirname(matplotlib.__file__)), 'matplotlib.libs')
_antigas = glob.glob(os.path.join(_libs, 'msvcp140-*.dll'))
if not _antigas:
    raise SystemExit('matplotlib.libs sem msvcp140-*.dll: nao ha copia para o Windows 7')
a.binaries = [b for b in a.binaries if os.path.basename(b[0]).lower() != 'msvcp140.dll']
a.binaries.append(('MSVCP140.dll', _antigas[0], 'BINARY'))

# 2. nada no bundle pode depender de funcao posterior ao Windows 7
_ruins = []
for nome, caminho, _tipo in a.binaries:
    try:
        pe = pefile.PE(caminho, fast_load=True)
        pe.parse_data_directories([pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
    except pefile.PEFormatError:
        continue
    for imp in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
        usadas = {i.name.decode() for i in imp.imports if i.name} & POS_WIN7
        if usadas:
            _ruins.append('%s (%s): %s' % (nome, caminho, ', '.join(sorted(usadas))))
if _ruins:
    raise SystemExit('Binarios que nao carregam no Windows 7:\n  ' + '\n  '.join(_ruins))
print('Windows 7: %d binarios conferidos, nenhum usa funcao posterior' % len(a.binaries))

pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=NOME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
)
