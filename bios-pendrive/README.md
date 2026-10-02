# BIOS Pendrive

Copia os arquivos de BIOS de um pendrive modelo para o PC e grava pendrives
novos a partir do PC. O pendrive fica espetado no equipamento DmOS (DM4800 /
48VS); o equipamento envia e baixa os arquivos por TFTP de um servidor que a
própria aplicação abre no PC.

## Uso

1. Abra `BiosPendrive.exe`.
2. Escolha como falar com o equipamento: **SSH** (IP do equipamento), **Telnet**
   (servidor serial remoto, ex. `172.22.239.100:4006`) ou **Serial local** (COM).
   Usuário/senha padrão `root/root`. O console tem que estar no shell Linux (`#`).
3. Escolha o **IP deste PC** que o equipamento consegue alcançar.
4. **Testar conexão**: mostra hostname, pendrives detectados e se o equipamento
   pinga o IP do PC.
5. **1) Copiar pendrive → PC**, com o pendrive modelo: monta somente leitura,
   copia tudo (menos `System Volume Information`) para a pasta e confere MD5.
6. Troque pelo pendrive novo e use **2) Gravar PC → pendrive**: pede
   confirmação, apaga o pendrive, cria MBR + FAT32 (rótulo `BIOS`), baixa todos
   os arquivos da pasta, remonta e confere MD5 lendo da mídia.

A pasta padrão é `arquivos_pendrive` ao lado do `.exe`. Dá pra pôr arquivos
nela à mão antes de gravar (outra BIOS, por exemplo). O log de tudo fica em
`bios_pendrive.log` ao lado do `.exe`.

Se nenhuma transferência chegar ao PC, use **Liberar no Firewall** (pede UAC e
cria uma regra de entrada UDP para o executável).

## Linha de comando

```
BiosPendrive.exe info   --ssh 172.22.239.56
BiosPendrive.exe backup --telnet 172.22.239.100:4006 --tftp-ip 10.0.120.23 --dir C:\bios
BiosPendrive.exe write  --serial COM3:115200 --tftp-ip 10.0.120.23 --dir C:\bios --yes
```

Opções: `--disk /dev/sdX` (se houver mais de um pendrive), `--layout floppy`
(FAT32 sem tabela de partição), `--blksize N` (padrão 1468).

## O que roda no equipamento

Só ferramentas nativas do DmOS: `busybox tftp`, `sfdisk`, `mkdosfs`, `blkid`,
`md5sum`. Só discos em `/dev/disk/by-id/usb-*` são aceitos, nunca a eMMC.

Gravação:

```
dd if=/dev/zero of=/dev/sda bs=1M count=8          # início
dd if=/dev/zero of=/dev/sda ... (últimos 4 MB)     # fim (GPT secundária)
printf 'label: dos\n2048,,c,*\n' | sfdisk --wipe always /dev/sda
mkdosfs -n BIOS /dev/sda1
mount /dev/sda1 /mnt/bios_usb
busybox tftp -g -b 1468 -l /mnt/bios_usb/<arq> -r <arq> <IP_PC>   # por arquivo
umount; drop_caches; mount -o ro; md5sum                          # conferência
```

O DmOS gera uma chave SSH nova a cada boot, por isso a aplicação aceita
qualquer host key.

## Build

```
pip install -r requirements.txt
build_exe.bat
```

Gera `dist\BiosPendrive.exe`, que roda sem Python instalado.

Arquivos: `bios_pendrive.py` (interface e CLI), `device.py` (SSH/telnet/serial
e operações no pendrive), `tftpserver.py` (servidor TFTP).
