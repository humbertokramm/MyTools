import pyvisa
import csv
import detectScope as DS
import os
import dirHandle as dh
from time import sleep

from tektronix import TektronixScope
from tektronix_net import TektronixNetScope
from keysight import KeysightScope
from scope_ssh import SshScope

class _ScopeAusente:
    """Ocupa o lugar do driver quando o script seguiu sem osciloscopio.

    Qualquer tentativa de falar com o instrumento para aqui, dizendo o
    porque, em vez de estourar um AttributeError em NoneType la na frente,
    longe da causa. O close() e no-op para o fim de script continuar valendo.
    """

    offline = True

    def close(self):
        pass

    def __getattr__(self, nome):
        raise RuntimeError(
            f"sem osciloscopio: '{nome}' precisa do instrumento. O script "
            f"seguiu sem ele -- deixe get=False nos cenarios que nao vao "
            f"capturar, ou conecte o aparelho e rode de novo.")


class Scope:

    def __init__(self, resource=None, debug=False, overwrite=False):
        self.overwrite = overwrite
        self.inst = None
        self.idn = None
        self.rm = None
        # True quando o usuario optou por seguir sem o instrumento.
        self.offline = False

        # -------------------------------------------------
        # SSH connection (oscilloscope on a remote Linux host)
        # resource format: "SSH::user@host[::VISA_RESOURCE]"
        # -------------------------------------------------
        if resource is not None and resource.upper().startswith("SSH::"):
            self.resource = resource
            self.driver   = SshScope.from_resource_string(resource, debug)
            return

        # -------------------------------------------------
        # HTTP connection (TDS3052B or similar)
        # resource format: "HTTP::192.168.1.100"
        # -------------------------------------------------
        if resource is not None and resource.upper().startswith("HTTP::"):
            ip = resource.split("::", 1)[1]
            self.resource = resource
            self.driver = TektronixNetScope(ip, debug)
            print(f"HTTP connection established: {ip}")
            return

        # -------------------------------------------------
        # detect resource automatically (VISA)
        # -------------------------------------------------
        if resource is None:
            resource = DS.select_visa_resource()

            if resource is None or "USB" not in resource:
                # Nem todo script usa o osciloscopio de verdade: muitos so
                # reprocessam CSV ja capturado. Matar o script ai obrigava a
                # ligar o aparelho so para gerar grafico.
                if not self._seguir_sem_scope("Osciloscopio nao encontrado."):
                    print("Invalid instrument!!")
                    exit()
                self.resource = None
                self._sem_scope()
                return
            else:
                print(f"resource = {resource}")

        # -------------------------------------------------
        # connect VISA
        # -------------------------------------------------
        for attempt in range(3):
            try:
                self.resource = resource
                self.rm = pyvisa.ResourceManager()
                self.inst = self.rm.open_resource(resource)
                break
            except Exception:
                dh.print_colored(f"Connection attempt {attempt + 1} failed:", 'RED')
                print(f'RESOURCE = "{resource}"')
                if attempt > 1:
                    # Mesma saida do instrumento nao detectado: o script pode
                    # nao precisar capturar nada. Pergunta antes do sleep,
                    # que aqui so atrasaria a resposta.
                    if not self._seguir_sem_scope(
                            "Nao consegui conectar no osciloscopio."):
                        exit()
                    self._sem_scope()
                    return
                sleep(2)

        self.inst.timeout = 10000

        idn = self.inst.query("*IDN?")
        print("Instrument detected:", idn)
        self.idn = idn.strip()

        # -------------------------------------------------
        # select driver
        # -------------------------------------------------

        if "TEKTRONIX" in idn.upper():
            self.driver = TektronixScope(self.inst, debug)

        elif "KEYSIGHT" in idn.upper() or "AGILENT" in idn.upper():
            self.driver = KeysightScope(self.inst, debug)

        else:
            raise Exception("Unsupported instrument")
            
    # ---------------------------------------------------------
    # sem instrumento
    # ---------------------------------------------------------
    def _seguir_sem_scope(self, motivo):
        """Pergunta se o script segue sem o instrumento.

        O padrao e abortar: quem ia capturar nao perde a medida por ter
        batido ENTER no reflexo.
        """
        dh.print_colored(motivo, 'RED')
        return input("\tSeguir sem ele? (s/N): ").strip().lower() == 's'

    def _sem_scope(self):
        """Deixa o objeto utilizavel sem instrumento."""
        dh.print_colored("Seguindo sem osciloscopio.", 'YELLOW')
        self.offline = True
        self.driver = _ScopeAusente()

    # ---------------------------------------------------------
    # file overwrite guard
    # ---------------------------------------------------------
    def _file_exists(self, caminho_arquivo):
        if os.path.exists(caminho_arquivo):
            if self.overwrite:
                return False   # Sobrescreve direto sem perguntar
            nome = os.path.basename(caminho_arquivo)
            resposta = input(f'O arquivo "{nome}" já existe. \n\tDeseja sobrescrever? (s/N): ').strip().lower()

            if resposta == 's':
                return False   # Pode sobrescrever
            else:
                return True    # Não sobrescrever
        else:
            return False       # Arquivo não existe, pode continuar normalmente
        
    # ---------------------------------------------------------
    # waveform capture
    # ---------------------------------------------------------
    def capture_waveform(self, channel, filename):
        filename += ".csv"
        if self._file_exists(filename):
            return
        # Ler a forma de onda com o aparelho em RUN trava (no Keysight o
        # :WAV:MODE RAW exige aquisicao parada). Depois de um single concluido
        # o STOP nao muda nada; com um single armado e sem trigger, ele aborta
        # e a captura sai com a aquisicao anterior -- use wait_single() antes.
        # Parar aqui tambem garante que o print da tela (capture_screen, logo
        # depois no main) mostre a mesma aquisicao gravada no CSV.
        self.driver.stop()
        try:
            time, voltage, metadata = self.driver.capture_waveform(channel)
        except RuntimeError as e:
            dh.print_colored(e,'RED')
            return None, None, None
        
        with open(filename, "w") as f:

            for k, v in metadata.items():
                f.write(f"# {k}: {v}\n")

            f.write("Time,Voltage\n")

            for t, v in zip(time, voltage):
                f.write(f"{t},{v}\n")

        print("CSV saved:", filename)
        
        
    # ---------------------------------------------------------
    # screenshot
    # ---------------------------------------------------------
    def set_vertical(self, channel='CH1', scale=None, offset=None, position=None):
        """Configure a escala vertical de um canal (eixo Y).

        Equivalente vertical do :meth:`set_timebase` -- só o que for
        informado e aplicado, mas aqui por canal::

            SC.set_vertical('CH1', scale=0.5, offset=1.65)

        Args:
            channel (str): canal, ex ``'CH1'``.
            scale   (float): volts por divisao.
            offset  (float): tensao de offset, em volts.
            position (float): deslocamento em DIVISOES.

        Note:
            ``offset`` e nativo nos dois fabricantes e e a opcao previsivel.
            ``position`` em divisoes e nativo no Tektronix; no Keysight e
            convertido para offset e nao foi verificado em bancada. Nao
            suportado no TDS3052B via HTTP (no-op).
        """
        self.driver.set_vertical(channel=channel, scale=scale,
                                 offset=offset, position=position)

    def show_channels(self, channels, total=None):
        """Exibe apenas os canais da lista, desligando todos os outros.

        Útil antes de capturar, para que a tela e o PNG mostrem somente os
        sinais de interesse::

            SC.show_channels(['CH1', 'CH3'])

        Args:
            channels (str or list): ``'CH1'`` ou ``['CH1', 'CH3']``.
            total    (int): quantos canais varrer. Por padrao os drivers
                locais deduzem do modelo no ``*IDN?`` (ultimo digito), e o
                driver SSH assume 4.

        Note:
            Um canal desligado nao pode ter a forma de onda lida -- o
            :meth:`capture_waveform` recusa canais fora da tela. Nao desligue
            um canal que ainda vai ser capturado.
        """
        if total is None:
            self.driver.show_channels(channels)
        else:
            self.driver.show_channels(channels, total=total)

    def set_channel_settings(self, channel, info):
        """Apply label, cursors and measurements to *channel*.

        Chamado automaticamente por :meth:`capture_screen`, mas exposto aqui
        para ser usado antes da captura -- util para posicionar os cursores e
        conferir na tela antes de salvar.

        Nesse caso, passe ``info=False`` na captura para nao reaplicar tudo::

            SC.set_channel_settings('CH1', infos)
            input('Ajuste os cursores e tecle ENTER...')
            SC.main(file, scope=SC, channel='CH1')   # info=False (padrao)

        Args:
            channel (str): canal, ex ``'CH1'``.
            info    (dict): mesmo dicionario aceito por :meth:`main` --
                ``label``, ``cursor``, ``meas``, ``threshold``, ``text``.

        Note:
            No driver SSH isso apenas guarda a configuracao; ela e enviada ao
            instrumento no :meth:`capture_screen`, para que setup e captura
            aconteçam numa unica sessao remota.
        """
        self.driver.set_channel_settings(channel, info)

    def capture_screen(self, filename,ch,info=False):

        self.driver.set_channel_settings(ch,info)

        filename += "-screen.png"
        if self._file_exists(filename):
            return
        data = self.driver.capture_screen()

        if data is None:
            dh.print_colored("Screenshot not available for this instrument.", 'YELLOW')
            return

        with open(filename, "wb") as f:
            f.write(data)

        print("Screenshot saved:", filename)

    # ---------------------------------------------------------
    # trigger control
    # ---------------------------------------------------------
    def monitor_single(self, max_wait=3600, retry_timeout=30, interval=0.5):
        """Wait for a single acquisition, re-arming until triggered or timeout.

        For SSH scopes this keeps a single USB connection open for the entire
        wait — use this instead of looping :meth:`wait_single` to avoid USB
        device resets on every iteration.

        Args:
            max_wait      (float): Total seconds to wait. Default 3600 (1 h).
            retry_timeout (float): Seconds per attempt before re-arming.
            interval      (float): Polling interval in seconds.

        Returns:
            bool: ``True`` if triggered, ``False`` if *max_wait* expired.
        """
        return self.driver.monitor_single(
            max_wait=max_wait,
            retry_timeout=retry_timeout,
            interval=interval,
        )

    def set_timebase(self, scale=None, position=None, reference=None):
        """Configure the horizontal timebase (scale and trigger position).

        Only the informed arguments are applied.

        Args:
            scale     (float): seconds per division (ex: ``20e-9`` = 20 ns/div).
            position  (float): deslocamento em segundos entre o trigger e o
                ponto de referencia da tela.
            reference (str): ``'left'``, ``'center'`` ou ``'right'``.

        Note:
            No Keysight a posicao e nativa em segundos. No Tektronix ela e
            percentual e a conversao usa a largura da tela; via SSH isso
            exige informar ``scale`` junto. Nao suportado no TDS3052B via
            HTTP (no-op).
        """
        self.driver.set_timebase(scale=scale, position=position,
                                 reference=reference)

    def set_trigger(self, channel='CH1', level=0.0, slope='rise', mode='NORMal'):
        """Configure the edge trigger (source, level and slope).

        Args:
            channel (str): trigger source, e.g. ``'CH1'``.
            level   (float): trigger level in volts.
            slope   (str): ``'rise'`` or ``'fall'`` (also accepts
                ``'positive'``/``'negative'`` and ``'+'``/``'-'``).
            mode    (str): ``'NORMal'`` waits for a real edge; ``'AUTO'``
                free-runs when none arrives. Keep NORMal when arming
                :meth:`single`, senao a captura termina sem trigger real.

        Note:
            Nao suportado no TDS3052B via HTTP (no-op).
        """
        self.driver.set_trigger(channel=channel, level=level,
                                slope=slope, mode=mode)

    def single(self):
        """Arm the oscilloscope for a single triggered acquisition."""
        self.driver.single()

    def wait_single(self, timeout=30, interval=0.5):
        """Block until a single acquisition completes or *timeout* expires.

        Args:
            timeout  (float): Maximum seconds to wait. Default 30.
            interval (float): Polling interval in seconds. Default 0.5.

        Returns:
            bool: ``True`` if acquisition completed, ``False`` if timed out.
        """
        return self.driver.wait_single(timeout=timeout, interval=interval)

    def stop(self):
        """Stop the current acquisition."""
        self.driver.stop()

    # ---------------------------------------------------------
    # connection
    # ---------------------------------------------------------
    def close(self):
        if self.inst is not None:
            self.inst.close()
        if self.rm is not None:
            self.rm.close()
        if hasattr(self, 'driver') and hasattr(self.driver, 'close'):
            self.driver.close()

    # ---------------------------------------------------------
    # setup completo do aparelho
    # ---------------------------------------------------------
    def save_setup(self, filename):
        """Salva a configuracao completa do osciloscopio em arquivo.

        O arquivo comeca com uma linha '# IDN: ...' e segue com o setup
        exatamente como o aparelho o exporta (binario no Keysight, texto no
        Tektronix), para ser reaplicado com :meth:`load_setup`.

        Args:
            filename (str): caminho; ``.setup`` e acrescentado se faltar.

        Returns:
            str | None: caminho gravado, ou ``None`` se nao gravou.
        """
        if not filename.endswith('.setup'):
            filename += '.setup'
        if self._file_exists(filename):
            return None
        try:
            data = self.driver.save_setup()
        except AttributeError:
            dh.print_colored("Salvar setup nao suportado neste instrumento.", 'YELLOW')
            return None

        with open(filename, 'wb') as f:
            f.write(f"# IDN: {self.idn or ''}\n".encode())
            f.write(data)
        print(f"Setup saved: {filename} ({len(data)} bytes)")
        return filename

    def load_setup(self, filename):
        """Reaplica um setup gravado por :meth:`save_setup`.

        O setup so vale para o mesmo modelo: se o arquivo veio de outro
        aparelho, avisa e nao envia nada. Numero de serie e firmware
        diferentes so geram aviso, porque o setup costuma ser aceito.

        Aceita tambem o setup cru, sem a linha '# IDN:' (como sai de um
        script avulso); nesse caso nao ha o que conferir.

        Returns:
            bool: ``True`` se o setup foi enviado.
        """
        if not filename.endswith('.setup'):
            filename += '.setup'
        with open(filename, 'rb') as f:
            data = f.read()

        origem = ''
        if data.startswith(b'# IDN:'):
            cabecalho, _, data = data.partition(b'\n')
            origem = cabecalho.decode(errors='replace').removeprefix('# IDN:').strip()

        if origem and self.idn:
            o, a = origem.split(','), self.idn.split(',')
            if o[:2] != a[:2]:
                dh.print_colored(
                    f"Setup de outro modelo: {origem}\n"
                    f"  aparelho conectado: {self.idn}\nNada enviado.", 'RED')
                return False
            if o != a:
                dh.print_colored(f"Setup de outra unidade/firmware: {origem}", 'YELLOW')

        try:
            self.driver.load_setup(data)
        except AttributeError:
            dh.print_colored("Carregar setup nao suportado neste instrumento.", 'YELLOW')
            return False
        print(f"Setup loaded: {filename}")
        return True

    def ensure_setup(self, filename):
        """Carrega o setup se o arquivo existir; se nao, grava o atual.

        Na primeira rodada de um ensaio o osciloscopio e ajustado na mao e a
        configuracao fica gravada; nas seguintes ela e reaplicada, para que
        todas as capturas saiam com a mesma configuracao.

        Returns:
            str | None: ``'loaded'``, ``'saved'`` ou ``None`` se nada foi feito.
        """
        if not filename.endswith('.setup'):
            filename += '.setup'
        if os.path.exists(filename):
            return 'loaded' if self.load_setup(filename) else None
        return 'saved' if self.save_setup(filename) else None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ---------------------------------------------------------
    # HIGH LEVEL CAPTURE
    # ---------------------------------------------------------

    @staticmethod
    def main(file, resource=None, channel="CH1", screenshot=True,
             info=False, debug=False, overwrite=False, scope=None):
        """Capture waveform and optional screenshot.

        Args:
            scope (Scope, optional): Existing Scope instance to reuse.
                When provided the connection is NOT closed after capture —
                the caller is responsible for calling scope.close() (or
                using the 'with Scope(...) as scope:' pattern).
                When omitted a new connection is opened and closed
                automatically after each call.
        """
        owned = scope is None
        if owned:
            scope = Scope(resource, debug, overwrite)

        # Falha de uma vez: sem esta checagem a captura avanca passo a passo
        # e cada um reclama do instrumento ausente, embolando a saida.
        if getattr(scope, 'offline', False):
            raise RuntimeError(
                "sem osciloscopio: a captura precisa do instrumento. O "
                "script seguiu sem ele -- deixe get=False nos cenarios que "
                "nao vao capturar, ou conecte o aparelho e rode de novo.")

        if isinstance(channel, str):
            channel = [channel]

        try:
            for ch in channel:
                scope.capture_waveform(ch, file)

            if screenshot:
                scope.capture_screen(file, channel[0], info)

        finally:
            if owned:
                scope.close()