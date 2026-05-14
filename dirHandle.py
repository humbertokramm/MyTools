"""
**File: dirHandle.py**

Utility module for directory/file handling and user interaction.
Provides colored terminal output, filename sanitization and file selection.

**Main Functions**

``sanitize_filename(name)``
    Adjust a string to be a valid Windows filename (max 255 chars).

``print_colored(msg, color='RESET')``
    Print a colored message to the terminal using ANSI codes.

``assert_or_abort(confirm_msg, abort_msg='')``
    Prompt the user to confirm or abort an operation.

``contains_all(string, substrings)``
    Return True if string contains every item in substrings.

``lacks_any(string, substrings)``
    Return True if string contains none of the items in substrings.

``select_file(rules, exclude=[], msg='...', directory='local')``
    Let the user pick a file from a filtered list.

``select_from_list(file_list=[], msg='...', path='')``
    Let the user pick from a list ordered newest-first.

``select_option(options=[], msg='...', path='')``
    Let the user pick from an alphabetically sorted list.

**Available colors**

- RED, GREEN, YELLOW, BLUE, RESET
"""

import os
from datetime import datetime
import re
from pprint import pprint

# ANSI color codes
COLORS = {
    'RED':    '\033[91m',
    'GREEN':  '\033[92m',
    'YELLOW': '\033[93m',
    'BLUE':   '\033[94m',
    'RESET':  '\033[0m',
}


def sanitize_filename(name: str) -> str:
    """Adjust a string to be a valid Windows filename.

    Args:
        name (str): The string to sanitize.

    Returns:
        str: Sanitized string, limited to 255 characters.

    Note:
        Substitution rules:

        - ``*`` and ``:`` → ``.``
        - ``<`` and ``>`` → ``-``
        - ``/ " \\ | ?`` → ``_``
        - Leading/trailing spaces removed.
    """
    name = name.replace('*', '.').replace(':', '.')
    name = name.replace('<', '-').replace('>', '-')
    name = re.sub(r'[/"\\|?]', '_', name)
    return name.strip()[:255]


def print_colored(msg, color='RESET'):
    """Print a colored message to the terminal.

    Args:
        msg (str): Message to display.
        color (str, optional): Color name: ``'RED'``, ``'GREEN'``,
            ``'YELLOW'``, ``'BLUE'``, ``'RESET'``. Defaults to ``'RESET'``.
    """
    print(f"{COLORS[color.upper()]}{msg}{COLORS['RESET']}")


def file_modified_date(file_path, path=''):
    """Return the last-modified datetime of a file (microseconds truncated).

    Args:
        file_path (str): Path to the file.
        path (str, optional): Optional prefix to prepend. Defaults to ``''``.

    Returns:
        datetime: Last-modified datetime without microseconds.
    """
    timestamp = os.path.getmtime(file_path)
    return datetime.fromtimestamp(timestamp).replace(microsecond=0)


def assert_or_abort(confirm_msg, abort_msg=''):
    """Prompt the user to confirm or abort an operation.

    Loops indefinitely until a valid response is received.

    Args:
        confirm_msg (str): The string the user must type to continue.
        abort_msg (str, optional): The string the user must type to abort.
            If empty, aborting is not allowed. Defaults to ``''``.

    Returns:
        str: ``'continue'`` if confirmed, ``'abort'`` if aborted.
    """
    while True:
        print(f'\n\tType "{confirm_msg}" to continue\n')
        x = input().lower()
        if x == confirm_msg.lower():
            return "continue"
        if x == abort_msg.lower():
            return "abort"


def contains_all(string, substrings):
    """Return True if *string* contains every item in *substrings*.

    Args:
        string (str): String to check.
        substrings (list): List of substrings that must all be present.

    Returns:
        bool: True if all substrings are found.
    """
    return all(s in string for s in substrings)


def lacks_any(string, substrings):
    """Return True if *string* contains none of the items in *substrings*.

    Args:
        string (str): String to check.
        substrings (list): List of substrings that must all be absent.

    Returns:
        bool: True if no substring is found (or list is empty).
    """
    if len(substrings) == 0:
        return True
    return all(s not in string for s in substrings)


def select_file(rules, exclude=None, msg='Select a file to analyse', directory='local'):
    """Let the user pick a file from a filtered directory listing.

    Args:
        rules (list): Substrings the filename MUST contain.
        exclude (list, optional): Substrings the filename must NOT contain.
            Defaults to ``[]``.
        msg (str, optional): Prompt shown to the user.
            Defaults to ``'Select a file to analyse'``.
        directory (str, optional): Search location: ``'local'`` (cwd) or
            ``'parent'`` (parent directory). Defaults to ``'local'``.

    Returns:
        str or None: Full path of the selected file, or None if cancelled.

    Note:
        Files are listed newest-first. A single match is auto-selected.
    """
    path = ''
    if directory == 'local':
        files = os.listdir()
    elif directory == 'parent':
        path = os.path.dirname(os.getcwd()) + '\\'
        files = os.listdir(path)

    if exclude is None:
        exclude = []
    file_list = []
    print("\n")
    for f in files:
        if contains_all(f, rules) and lacks_any(f, exclude):
            file_list.append(f)

    return select_from_list(file_list, msg, path)


def select_from_list(file_list=None, msg='Select an option', path=''):
    """Let the user pick from a list ordered newest-first.

    Args:
        file_list (list): List of filenames to choose from.
        msg (str, optional): Prompt shown to the user. Defaults to
            ``'Select an option'``.
        path (str, optional): Directory prefix prepended to the chosen
            filename. Defaults to ``''``.

    Returns:
        str or None: ``path + chosen_filename``, or None if no files found.
    """
    if file_list is None:
        file_list = []
    if len(file_list) == 0:
        print_colored("\tNo file found\n", 'RED')
        if assert_or_abort("Y") == 'abort':
            exit()
        else:
            return None

    max_name = max(len(f) for f in file_list if f is not None) if file_list else 0

    if len(file_list) == 1:
        name = file_list[0]
        if "\\" in name:
            i = name.rfind("\\")
            name = name[:i + 1] + "\n\t\t" + name[i + 1:]
        print(f"\tSelected: {name} | {file_modified_date(path + file_list[0])}\n")
        return path + file_list[0]

    file_list = sorted(
        [f for f in file_list if f is not None],
        key=lambda x: os.path.getmtime(path + x),
        reverse=True
    )
    file_list.append(None)

    while True:
        print(f"\n\t{msg}\n")
        for idx, f in enumerate(file_list, start=1):
            if f is None:
                print(f"\t({idx}) - Exit")
            else:
                name = f
                if "\\" in name:
                    i = name.rfind("\\")
                    name = name[:i + 1] + "\n\t\t" + name[i + 1:]
                print(f"\t({idx}) - {name} {(max_name - len(f)) * ' '} | {file_modified_date(path + f)}\n")
        try:
            choice = int(input()) - 1
        except Exception:
            print("Enter a number")
            continue
        if choice < 0 or choice >= len(file_list):
            print("\n\tInvalid option\n")
        else:
            if file_list[choice] is None:
                exit()
            return path + file_list[choice]


def select_option(options=None, msg='Select an option', path=''):
    """Let the user pick from an alphabetically sorted list.

    Args:
        options (list): List of option strings.
        msg (str, optional): Prompt shown to the user. Defaults to
            ``'Select an option'``.
        path (str, optional): Prefix prepended to the chosen option.
            Defaults to ``''``.

    Returns:
        str or None: ``path + chosen_option``, or None if list is empty.
    """
    if options is None:
        options = []
    if len(options) == 0:
        print_colored("\tNo option found\n", 'RED')
        if assert_or_abort("Y") == 'abort':
            exit()
        else:
            return None

    max_name = max(len(o) for o in options if o is not None) if options else 0

    if len(options) == 1:
        name = options[0]
        if "\\" in name:
            i = name.rfind("\\")
            name = name[:i + 1] + "\n\t\t" + name[i + 1:]
        print(f"\tSelected: {name}\n")
        return path + options[0]

    options = sorted(options)
    options.append(None)

    while True:
        print(f"\n\t{msg}\n")
        for idx, opt in enumerate(options, start=1):
            if opt is None:
                print(f"\t({idx}) - Exit")
            else:
                name = opt
                if "\\" in name:
                    i = name.rfind("\\")
                    name = name[:i + 1] + "\n\t\t" + name[i + 1:]
                print(f"\t({idx}) - {name} {(max_name - len(opt)) * ' '}\n")
        try:
            choice = int(input()) - 1
        except Exception:
            print("Enter a number")
            continue
        if choice < 0 or choice >= len(options):
            print("\n\tInvalid option\n")
        else:
            if options[choice] is None:
                exit()
            return path + options[choice]
