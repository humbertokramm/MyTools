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
from time import sleep

# garante que sa.py e agilent_sa.py sao encontrados
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sa import SA


# -----------------------------------------------------------------------
# CONFIGURACAO  (edite aqui antes de rodar)
# -----------------------------------------------------------------------
bands = [
    [30e6,1000e6],
    [30e6,130e6],
    [130e6,230e6],
    [230e6,330e6],
    [330e6,430e6],
    [430e6,530e6],
    [530e6,630e6],
    [630e6,730e6],
    [730e6,830e6],
    [830e6,930e6],
    [930e6,1000e6],
]
CONFIG = {
    'ip':       '192.168.0.30',
    'state':    r'D:\State\Setup_Emissao_Radiada_Classe_A_Desenvolvimento.state',
    'classe':   'A',
    'tensao':   '220_48',   # tensao de operacao do EUT
    'pol':      'H',        # H ou V
    'n':        30,         # numero de varreduras (average count)
    # lista de (trace_no_analisador, sufixo_no_nome_do_arquivo)
    'traces':   [('Trace1', 'Max'), ('Trace2', 'Med')],
    'saida':    r'T:\1berto\Medidas',  # pasta raiz; sera criada uma subpasta com a data
    'bands':    bands,
}
CONFIG['saida'] = CONFIG['saida']+'\\' + CONFIG['pol']+'\\' + CONFIG['tensao']
# -----------------------------------------------------------------------


def _beep_ok():
    for i in range(1, 3):
        winsound.Beep(i * 1000, i * 300)


def _beep_alerta():
    winsound.Beep(800, 800)


def _nome_arquivo(modo, cfg, trace_label=''):
    """Retorna o nome base do arquivo sem extensao."""
    faixa = '{:.0f}MHz-{:.0f}MHz'.format(cfg['freq_ini'] / 1e6, cfg['freq_fim'] / 1e6)
    suffix = ' - ' + trace_label if trace_label else ''
    if modo == 'EUT':
        return '{} Radiada - {} - EUT - Classe {} {}V{}'.format(
            faixa, cfg['pol'], cfg['classe'], cfg['tensao'], suffix
        )
    else:
        return '{} Radiada - {} - Ambiente - Classe {}{}'.format(
            faixa, cfg['pol'], cfg['classe'], suffix
        )


def capturar(sa, modo, cfg, pasta):
    """Executa uma varredura completa e salva CSV (um por trace) + PNG."""
    print('\n' + '=' * 55)
    print('Iniciando: ' + modo)
    print('=' * 55)

    print('Varrendo ' + str(cfg['n']) + 'x ... aguarde.')
    ok = sa.sweep_single(count=cfg['n'])
    if not ok:
        print('AVISO: timeout na varredura!')
    sa.pause()

    traces = cfg.get('traces', [('Trace1', '')])
    csv_paths = []
    for trace_name, trace_label in traces:
        nome = _nome_arquivo(modo, cfg, trace_label)
        csv_path = os.path.join(pasta, nome + '.csv')
        sa.export_csv(trace_name, csv_path)
        print('CSV salvo: ' + csv_path)
        csv_paths.append(csv_path)

    # PNG uma vez (tela atual com todos os traces visiveis + tabela de picos)
    sa.set_fullscreen(True)   # load_state pode ter resetado o modo full screen
    sa.set_peak_table(True)
    png_path = os.path.join(pasta, _nome_arquivo(modo, cfg) + '.png')
    img = sa.capture_screen()
    sa.set_peak_table(False)
    with open(png_path, 'wb') as fh:
        fh.write(img)
    print('PNG salvo: ' + png_path)

    _beep_ok()
    return csv_paths


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
    sa.set_fullscreen(True)

    try:
        for local in ['EUT','Ambiente']:
            if local == 'EUT':
                print('\nGarantir: EUT ligado, antena polarizacao ' + cfg['pol'])
            if local == 'Ambiente':
                print('\nDesligue o EUT (ou desconecte a antena).')
            input('Pressione ENTER para iniciar captura')

            for i in CONFIG['bands']:
                cfg['freq_ini'] = i[0]
                cfg['freq_fim'] = i[1]
                # carrega state e configura faixa
                sa.load_state(cfg['state'])
                sa.set_freq_range(cfg['freq_ini'], cfg['freq_fim'])
                print('State carregado. Faixa: {:.0f} MHz - {:.0f} MHz'.format(
                    cfg['freq_ini'] / 1e6, cfg['freq_fim'] / 1e6
                ))
                
                # ---- local -------------------------------------------------------
                _beep_alerta()
                paths = capturar(sa, local, cfg, pasta)
                for p in paths:
                    print(p)

    finally:
        sa.set_fullscreen(False)
        sa.close()

        # resumo
        print('\n' + '=' * 55)
        print('Concluido!')
        print('=' * 55)
        print('\nPara analisar (no PC de analise):')


if __name__ == '__main__':


        main()
