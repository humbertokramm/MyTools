import win32clipboard
import re

CF_HTML = win32clipboard.RegisterClipboardFormat("HTML Format")

# ── Lê clipboard ──────────────────────────────────────────────
win32clipboard.OpenClipboard()
html_raw = win32clipboard.GetClipboardData(CF_HTML).decode("utf-8")
win32clipboard.CloseClipboard()

match = re.search(r'<!--StartFragment\s*-->(.*?)<!--EndFragment\s*-->', html_raw, re.DOTALL)
fragment = match.group(1)

# ── Extrai os SPANs internos da DIV do terminal ───────────────
inner_match = re.search(r'<DIV[^>]*>(.*)</DIV>', fragment, re.DOTALL | re.IGNORECASE)
inner = inner_match.group(1)

# ── Converte cada SPAN do terminal para o formato Yodis ───────
def convert_spans(inner_html):
    result = []
    # Divide nas quebras de linha (<BR>)
    lines = re.split(r'<BR\s*/?>', inner_html, flags=re.IGNORECASE)
    
    for line in lines:
        if not line.strip():
            # Linha vazia: mantém um span vazio para preservar o espaçamento
            result.append('<span style="background-color:#0c0c0c; color:#cccccc"></span><br />')
            continue
        
        # Dentro de cada linha pode haver múltiplos SPANs (cores diferentes)
        spans = re.findall(r'<SPAN\s+STYLE="([^"]*)">(.*?)</SPAN>', line, re.DOTALL | re.IGNORECASE)
        
        line_html = ""
        for style, text in spans:
            # Extrai a cor do style original
            color_match = re.search(r'color\s*:\s*(#[0-9a-fA-F]+)', style, re.IGNORECASE)
            color = color_match.group(1).lower() if color_match else "#cccccc"
            
            # Só converte espaços — o resto já vem escapado corretamente do terminal
            text = text.replace(" ", "&nbsp;")
            
            line_html += f'<span style="background-color:#0c0c0c; color:{color}">{text}</span>'
        
        if line_html:
            result.append(line_html + "<br />")
    
    # Remove o último <br /> extra
    if result and result[-1].endswith("<br />"):
        result[-1] = result[-1][:-6]
    
    return "\n".join(result)

inner_converted = convert_spans(inner)

# ── Monta o HTML final no formato Yodis ───────────────────────
yodis_html = (
    '<div style="background:#0c0c0c; border:1px solid #cccccc; padding:5px 10px">'
    '<code>'
    + inner_converted
    + '</code></div>'
)

# ── Empacota no formato CF_HTML e joga no clipboard ───────────
def build_cf_html(fragment):
    body = f"<html><body>\r\n<!--StartFragment-->{fragment}<!--EndFragment-->\r\n</body></html>"
    header_template = (
        "Version:0.9\r\n"
        "StartHTML:00000000\r\n"
        "EndHTML:00000000\r\n"
        "StartFragment:00000000\r\n"
        "EndFragment:00000000\r\n"
    )
    full = header_template + body
    start_html = full.index("<html>")
    end_html   = full.index("</body></html>") + len("</body></html>")
    start_frag = full.index("<!--StartFragment-->") + len("<!--StartFragment-->")
    end_frag   = full.index("<!--EndFragment-->")
    result = (
        f"Version:0.9\r\n"
        f"StartHTML:{start_html:08d}\r\n"
        f"EndHTML:{end_html:08d}\r\n"
        f"StartFragment:{start_frag:08d}\r\n"
        f"EndFragment:{end_frag:08d}\r\n"
        + body
    )
    return result.encode("utf-8")

win32clipboard.OpenClipboard()
win32clipboard.EmptyClipboard()
win32clipboard.SetClipboardData(CF_HTML, build_cf_html(yodis_html))
win32clipboard.CloseClipboard()

print("OK - Clipboard convertido para formato Yodis!")