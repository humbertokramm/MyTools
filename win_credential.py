"""win_credential.py — gerenciamento de credenciais no Windows Credential Manager.

Armazena/recupera usuario+senha de forma segura via keyring (backend nativo do
Windows Credential Locker). Se a credencial nao existir, pede ao usuario e salva.

API principal:
    get_password(service, username, message=None)   -> senha (pede+salva se faltar)
    set_password(service, username, password)         -> grava
    get_credentials(service, message=None)            -> (user, senha) via dialogo WinAPI
    obter_username_servico(service)                   -> username salvo ou None
    listar_credenciais()                              -> imprime todas
    deletar_credenciais_servico(service)              -> remove

CLI:
    py win_credential.py --list
    py win_credential.py --get  MTS-5800
    py win_credential.py --set  MTS-5800 --user tb-5800
    py win_credential.py --del  MTS-5800
"""
import argparse
import ctypes
import getpass
from ctypes import wintypes

import keyring
import win32cred

# ------------------------ dialogo WinAPI (opcional) ------------------------
CREDUI_FLAGS = {
    'DO_NOT_PERSIST': 0x00002,
    'ALWAYS_SHOW_UI': 0x00080,
    'GENERIC_CREDENTIALS': 0x40000,
}


class CREDUI_INFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWndParent", wintypes.HWND),
        ("pszMessageText", wintypes.LPCWSTR),
        ("pszCaptionText", wintypes.LPCWSTR),
        ("hbmBanner", wintypes.HBITMAP),
    ]


def prompt_for_credentials(server_name, message="Insira suas credenciais"):
    """Mostra o dialogo padrao do Windows e devolve (username, password)."""
    credui = ctypes.windll.credui
    info = CREDUI_INFO()
    info.cbSize = ctypes.sizeof(info)
    info.hWndParent = None
    info.pszMessageText = message
    info.pszCaptionText = "Credenciais de Acesso"
    info.hbmBanner = None

    username = ctypes.create_unicode_buffer(256)
    password = ctypes.create_unicode_buffer(256)
    save = wintypes.BOOL(False)
    flags = (CREDUI_FLAGS['GENERIC_CREDENTIALS']
             | CREDUI_FLAGS['ALWAYS_SHOW_UI']
             | CREDUI_FLAGS['DO_NOT_PERSIST'])

    result = credui.CredUIPromptForCredentialsW(
        ctypes.byref(info), server_name, None, 0,
        username, 256, password, 256, ctypes.byref(save), flags)
    if result == 0:  # ERROR_SUCCESS
        return username.value, password.value
    return None, None


# ------------------------ armazenamento (keyring) ------------------------
def set_password(service, username, password):
    """Grava a senha para (service, username) no Credential Manager."""
    keyring.set_password(service, username, password)


def get_password(service, username, message=None):
    """Retorna a senha de (service, username). Pede e salva se ainda nao existir."""
    pw = keyring.get_password(service, username)
    if pw is None:
        prompt = message or f"Senha para {username}@{service}: "
        pw = getpass.getpass(prompt)
        keyring.set_password(service, username, pw)
    return pw


def obter_username_servico(service_name):
    """Recupera o username de um servico salvo (via enumeracao do Windows)."""
    try:
        for cred in win32cred.CredEnumerate(None, 0):
            if cred['TargetName'] == service_name:
                return cred.get('UserName')
    except Exception as e:
        print(f"Erro ao acessar credenciais: {e}")
    return None


def get_credentials(service, message="Insira suas credenciais"):
    """Devolve (user, senha); usa o dialogo WinAPI e salva se faltar."""
    user = obter_username_servico(service)
    if user is None:
        user, password = prompt_for_credentials(service, message)
        if user is None:
            return None, None
        keyring.set_password(service, user, password)
    return user, keyring.get_password(service, user)


# compat: nome antigo usado por outros scripts
def getUserData(service_name, blockIfNotExist=False):
    user = obter_username_servico(service_name)
    if user is None:
        if blockIfNotExist:
            return None, None
        return get_credentials(service_name)
    return user, keyring.get_password(service_name, user)


def deletar_credenciais_servico(service_name):
    try:
        win32cred.CredDelete(service_name, win32cred.CRED_TYPE_GENERIC, 0)
        print(f"Credenciais de '{service_name}' removidas.")
    except Exception as e:
        print(f"Erro ao remover '{service_name}': {e}")


def listar_credenciais():
    creds = win32cred.CredEnumerate(None, 0)
    print(f"Total de credenciais: {len(creds)}")
    for cred in creds:
        print(f"\nTargetName: {cred['TargetName']}")
        print(f"UserName:   {cred.get('UserName')}")


# ------------------------------- CLI -------------------------------
def main():
    p = argparse.ArgumentParser(description="Gerenciador de credenciais do Windows")
    p.add_argument('-l', '--list', action='store_true', help='lista todas as credenciais')
    p.add_argument('-g', '--get', metavar='SERVICE', help='mostra user/senha de um servico')
    p.add_argument('-s', '--set', metavar='SERVICE', help='grava senha para um servico')
    p.add_argument('-d', '--del', dest='delete', metavar='SERVICE', help='remove um servico')
    p.add_argument('--user', help='username (usado com --set/--get)')
    args = p.parse_args()

    if args.list:
        listar_credenciais()
    if args.get:
        if args.user:
            print(args.get, args.user, get_password(args.get, args.user))
        else:
            print(args.get, getUserData(args.get))
    if args.set:
        user = args.user or input("Username: ")
        pw = getpass.getpass("Senha: ")
        set_password(args.set, user, pw)
        print(f"Salvo em '{args.set}' para '{user}'.")
    if args.delete:
        deletar_credenciais_servico(args.delete)


if __name__ == "__main__":
    main()
