"""
radiada_capture.py  --  Captura de emissao radiada (N9010A)
Compativel com Python 3.4+. Dependencia: pyvisa.

Uso:
    python radiada_capture.py
"""

import os
import sys
import winsound
from datetime import datetime

# garante que sa.py e agilent_sa.py sao encontrados
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sa import SA


# -----------------------------------------------------------------------
# CONFIGURACAO  (edite aqui antes de rodar)
# -----------------------------------------------------------------------

CONFIG = {
    'ip':       '192.168.0.30',
    'state':    r'D:\State\Setup_Emissao_Radiada_Classe_A_Desenvolvimento.state',
    'classe':   'A',
    'tensao':   '220_48',   # tensao de operacao do EUT
    'pol':      'H',        # H ou V
    'n':        30,         # numero de varreduras (average count)
    'trace':    'Trace2',   # trace de media no analisador
    'freq_ini': 30e6,       # Hz
    'freq_fim': 1000e6,     # Hz
    'saida':    r'C:\Medidas',  # pasta raiz; sera criada uma subpasta com a data
}

# -----------------------------------------------------------------------


def _beep_ok():
    for i in range(1, 3):
        winsound.Beep(i * 1000, i * 300)


def _beep_alerta():
    winsound.Beep(800, 800)


def _nome_arquivo(modo, cfg):
    """Retorna o nome base do arquivo sem extensao."""
    faixa = '{:.0f}MHz-{:.0f}MHz'.format(cfg['freq_ini'] / 1e6, cfg['freq_fim'] / 1e6)
    if modo == 'EUT':
        return '{} Radiada - {} - EUT - Classe {} {}V'.format(
            faixa, cfg['pol'], cfg['classe'], cfg['tensao']
        )
    else:
        return '{} Radiada - {} - Ambiente - Classe {}'.format(
            faixa, cfg['pol'], cfg['classe']
        )


def capturar(sa, modo, cfg, pasta):
    """Executa uma varredura completa e salva CSV + PNG."""
    print('\n' + '=' * 55)
    print('Iniciando: ' + modo)
    print('=' * 55)

    print('Varrendo ' + str(cfg['n']) + 'x ... aguarde.')
    ok = sa.sweep_single(count=cfg['n'])
    if not ok:
        print('AVISO: timeout na varredura!')
    sa.pause()

    nome = _nome_arquivo(modo, cfg)
    csv_path = os.path.join(pasta, nome + '.csv')
    png_path = os.path.join(pasta, nome + '.png')

    sa.export_csv(cfg['trace'], csv_path)

    img = sa.capture_screen()
    with open(png_path, 'wb') as fh:
        fh.write(img)
    print('PNG salvo: ' + png_path)

    _beep_ok()
    return csv_path


def main():
    cfg = CONFIG

    # cria pasta de saida com subpasta de data
    data_str = datetime.now().strftime('%Y-%m-%d')
    pasta = os.path.join(cfg['saida'], data_str)
    if not os.path.exists(pasta):
        os.makedirs(pasta)
    print('Pasta de saida: ' + pasta)

    # conecta
    resource = 'TCPIP0::' + cfg['ip'] + '::inst0::INSTR'
    print('Conectando em ' + resource + ' ...')
    sa = SA(resource)

    try:
        # carrega state e configura faixa
        sa.load_state(cfg['state'])
        sa.set_freq_range(cfg['freq_ini'], cfg['freq_fim'])
        print('State carregado. Faixa: {:.0f} MHz - {:.0f} MHz'.format(
            cfg['freq_ini'] / 1e6, cfg['freq_fim'] / 1e6
        ))

        # ---- EUT -------------------------------------------------------
        _beep_alerta()
        print('\nGarantir: EUT ligado, antena polarizacao ' + cfg['pol'])
        input('Pressione ENTER para iniciar captura do EUT ...')
        eut_csv = capturar(sa, 'EUT', cfg, pasta)

        # ---- Ambiente --------------------------------------------------
        _beep_alerta()
        print('\nDesligue o EUT (ou desconecte a antena).')
        input('Pressione ENTER para iniciar captura do Ambiente ...')
        amb_csv = capturar(sa, 'Ambiente', cfg, pasta)

    finally:
        sa.close()

    # resumo
    print('\n' + '=' * 55)
    print('Concluido!')
    print('EUT    : ' + eut_csv)
    print('Amb    : ' + amb_csv)
    print('=' * 55)
    print('\nPara analisar (no PC de analise):')
    print('  python radiada_plot.py "' + eut_csv + '" "' + amb_csv + '" <limit.csv>')


if __name__ == '__main__':
    main()
