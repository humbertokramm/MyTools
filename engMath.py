import numpy as np
from pprint import pprint

EngNotation ={
    'Y':	1e24 ,	'Z':	1e21 ,	'E':	1e18 ,	'P':	1e15 ,	'T':	1e12 ,	'G':	1e9  ,
    'M':	1e6  ,	'k':	1e3  ,	'h':	1e2  ,	'da':	1e1  ,	'' :	1e0  ,	'd':	1e-1 ,
    'c':	1e-2 ,	'm':	1e-3 ,	'u':	1e-6 ,	'µ':	1e-6 ,	'n':	1e-9 ,	'p':	1e-12,
    'f':	1e-15,	'a':	1e-18,	'z':	1e-21,	'y':	1e-24,
    #extras
    #'cm^4':	1e-8,	'cm^3':	1e-6,	'cm^2':	1e-4,	'cm³':	1e-6,	'cm²':	1e-4,	'mm^4':	1e-12,
    #'mm^3':	1e-9,	'mm^2':	1e-6,	'mm³':	1e-9,	'mm²':	1e-6,	'%':  	1e-2
}
Symbol = ['V','W','A','Ω','s','Hz']

def getEng(nota,s=False):
    """
    Extrai e converte notação de engenharia de uma string de label.
    
    Args:
        nota (str): String contendo notação de engenharia entre colchetes, ex: "Time[ms]".
        s (bool or str, optional): Modo de retorno:
            - False: Retorna o fator numérico (ex: 1e-3 para 'm').
            - True: Retorna string com notação e símbolo (ex: "mV").
            - 'symbol': Retorna apenas o símbolo (ex: "V").
            Padrão é False.
    
    Returns:
        float or str: Dependendo do parâmetro 's':
            - Se s=False: fator numérico da notação de engenharia.
            - Se s=True: string com notação e símbolo.
            - Se s='symbol': apenas o símbolo da unidade.
            - Se não encontrar notação: 1 (se s=False) ou '' (se s=True).
    """
    i = nota.find('[')+1
    o = nota.find(']')
    if i>o:
        if s: return ''
        return 1
    nota = nota[i:o]
    qt = ''
    for q in Symbol:
        if nota.find(q)>-1:
            qt = q
        nota = nota.replace(q,'')
    if s == 'symbol': return qt
    if s == True: return nota+qt
    return EngNotation[nota]

def getEngSTR(number,casas = 2, string = True):
    """
    Converte um número para notação de engenharia em string.
    
    Args:
        number (float or str): Número a ser convertido. Se for string, retorna com espaço.
        casas (int, optional): Número de casas decimais. Padrão é 2.
    
    Returns:
        str: Número formatado em notação de engenharia, ex: "1.23 k", "456.78 m".
            Se number for 0, retorna "0 ".
            Se number for string, retorna a string com espaço no final.
    """
    if number == 0: return '0 '
    if type(number) == type(''): return number + ' '
    exponent = int(np.floor(np.log10(abs(number))))
    exponent = (exponent // 3) * 3
    unit = {
        -30: 'q',-27: 'r',-24: 'y',-21: 'z',-18: 'a',-15: 'f',-12: 'p',-9: 'n',-6: 'µ',-3: 'm',
        0: '', 3: 'k', 6: 'M', 9: 'G', 12: 'T', 15: 'P', 18: 'E', 21: 'Z', 24: 'Y', 27: 'R', 30: 'Q'
    }
    eng_notation_string = "{:.{}f} {}".format(number / 10 ** exponent, casas, unit.get(exponent, ''))
    if string: return eng_notation_string
    else: return {
        'value': number / 10 ** exponent,
        'casas': casas, 
        'unit': unit.get(exponent, ''),
        'fator': 10 ** exponent,
        }

def getValue(number,s,axe,casas = 2):
    """
    Formata um valor numérico com notação de engenharia e unidade apropriada.
    
    Args:
        number (float): Valor numérico a ser formatado (em unidades normalizadas).
        s (dict): Dicionário com informações da série, contendo:
            - 'engNoteX': fator de escala do eixo X.
            - 'engNoteY': fator de escala do eixo Y.
            - 'symbolX': símbolo da unidade do eixo X.
            - 'symbolY': símbolo da unidade do eixo Y.
        axe (str): Tipo de valor a formatar:
            - 'x': tempo/posição no eixo X.
            - 'y': amplitude no eixo Y.
            - 'f': frequência (inverso do tempo).
            - 'bps': taxa de bits por segundo.
            - 'v/t': slew rate (V/µs).
        casas (int, optional): Número de casas decimais. Padrão é 2.
    
    Returns:
        str: Valor formatado com notação de engenharia e unidade, ex: "1.23 ms", "456.78 V".
            Retorna string de erro se 'axe' for inválido.
    """
    if axe == 'x':
        return getEngSTR(number*s['engNoteX'],casas)+s['symbolX']
    if axe == 'f':
        return getEngSTR(number/s['engNoteX'],casas)+'Hz'
    if axe == 'bps':
        return getEngSTR(number/s['engNoteX'],casas)+'bps'
    if axe == 'y':
        return getEngSTR(number*s['engNoteY'],casas)+s['symbolY']
    if axe == 'v/t':
        return getEngSTR(number*s['engNoteX']*1e6,casas)+'V/µs'
    return 'ERROR: getValue(axe = '+axe+')' 

def auto_scale(array):
    span = np.max(array) - np.min(array)
    return getEngSTR(span,string=False)
