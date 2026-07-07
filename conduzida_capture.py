"""
conduzida_capture.py  --  Captura de emissao conduzida (N9010A)
Compativel com Python 3.4+. Dependencia: pyvisa.

Uso:
    python conduzida_capture.py
"""

import os
import sys
import winsound
from datetime import datetime
import msvcrt
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sa import SA


state={
    "A": r'D:\State\Setup_Emissao_Conduzida_Classe_A_Desenvolvimento.state',
    "B": r'D:\State\Setup_Emissao_Conduzida_Classe_B_Desenvolvimento.state',
}

# -----------------------------------------------------------------------
# CONFIGURACAO  (edite aqui antes de rodar)
# -----------------------------------------------------------------------
CONFIG = {
    'ip':       '192.168.0.30',
    'classe':   'A',
    'tensao':   ['teste'],#'backup','127Vac + backup','220Vac', '127Vac', '48Vdc'],
    'n':        100,          # numero de varreduras (average count)
    'saida':    r'T:\1berto\Medidas',  # pasta raiz; sera criada uma subpasta com a data
    'bands': [
        [150e3, 30e6],
        [150e3, 1e6]
    ],
}
# -----------------------------------------------------------------------


def _beep_ok():
    for i in range(1, 3):
        winsound.Beep(i * 1000, i * 300)


def _beep_alerta():
    winsound.Beep(800, 800)

def _screen_blink():
    print("\nPressione ENTER para sair...")
    i = 0
    colors = ["4E","60"]
    while not msvcrt.kbhit():
         os.system("color "+colors[i % len(colors)])
         i += 1
         time.sleep(0.5)
    msvcrt.getch()
    os.system("color 07")


def _faixa_str(freq_ini, freq_fim):
    def _fmt(hz):
        if hz >= 1e6 and hz % 1e6 == 0:
            return '{:.0f}MHz'.format(hz / 1e6)
        if hz >= 1e3:
            return '{:.0f}kHz'.format(hz / 1e3)
        return '{:.0f}Hz'.format(hz)
    return '{}-{}'.format(_fmt(freq_ini), _fmt(freq_fim))


def _nome_arquivo(linha, tensao, freq_ini, freq_fim):
    return '{}_{}_{}'.format(linha, tensao, _faixa_str(freq_ini, freq_fim))


def capturar(sa, linha, tensao, freq_ini, freq_fim, n, pasta):
    faixa = _faixa_str(freq_ini, freq_fim)
    nome  = _nome_arquivo(linha, tensao, freq_ini, freq_fim)
    png_path = os.path.join(pasta, nome + '.png')

    print('  Varrendo {}x ... aguarde.'.format(n))
    ok = sa.sweep_single(count=n)
    if not ok:
        print('  AVISO: timeout na varredura!')
    sa.pause()

    sa.set_fullscreen(True)
    img = sa.capture_screen()
    with open(png_path, 'wb') as fh:
        fh.write(img)
    print('  PNG salvo: ' + png_path)
    _beep_ok()
    return png_path


def main():
    cfg = CONFIG

    data_str = datetime.now().strftime('%Y-%m-%d')
    pasta = os.path.join(cfg['saida'], 'Conduzida', data_str)
    if not os.path.exists(pasta):
        os.makedirs(pasta)
    print('Pasta de saida: ' + pasta)

    resource = 'TCPIP0::' + cfg['ip'] + '::inst0::INSTR'
    print('Conectando em ' + resource + ' ...')
    sa = SA(resource)

    n_total    = len(cfg['tensao']) * 2 * len(cfg['bands'])
    n_feitas   = 0

    try:
        for tensao in cfg['tensao']:
            print('\n' + '=' * 60)
            print('TENSAO: ' + tensao + '  (classe ' + cfg['classe'] + ')')
            print('=' * 60)
            print('Configure o EUT para operar em ' + tensao + '.')

            for linha in ['L1', 'L2']:
                print('\n' + '-' * 50)
                print('LINHA: ' + linha + '  |  tensao: ' + tensao)
                print('-' * 50)
                print('Conecte a entrada da LISN ao condutor ' + linha + '.')
                _screen_blink()

                for band in cfg['bands']:
                    freq_ini, freq_fim = band[0], band[1]
                    faixa = _faixa_str(freq_ini, freq_fim)
                    n_feitas += 1
                    print('\n[{}/{}] Faixa: {}'.format(n_feitas, n_total, faixa))

                    sa.load_state(state[cfg['classe']])
                    sa.set_freq_range(freq_ini, freq_fim)
                    print('  State carregado. Iniciando varredura...')
                    _beep_alerta()

                    capturar(sa, linha, tensao, freq_ini, freq_fim, cfg['n'], pasta)

        print('\n' + '=' * 60)
        print('Todas as capturas concluidas!')
        print('Arquivos salvos em: ' + pasta)
        print('=' * 60)

    finally:
        sa.set_fullscreen(False)
        sa.close()


if __name__ == '__main__':
    main()
