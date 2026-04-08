"""
**File: RTC_Test.py**

**Descrição**
    Módulo para teste e sincronização de relógio em tempo real (RTC).
    Conecta via SSH ou porta serial a dispositivo de teste.

**Classe Principal**

``class RTC_Test``
    
    Gerencia conexão com dispositivo para teste de RTC.
    
    **Atributos**
    
    - ``servidor_ntp``: Lista de servidores NTP para sincronização
    - ``host``: Endereço IP do dispositivo (ou False)
    - ``serial_port``: Porta serial (ex: COM3)
    - ``port``: Porta SSH (padrão: 22)
    - ``username``: Usuário SSH (padrão: root)
    
    **Métodos**
    
    ``__init__(connection=False)``
        Inicializa conexão (IP ou COM port).

**Servidores NTP Padrão**
    - pool.ntp.org

**Dependências**
    - ntplib
    - serial
    - paramiko
    - ipaddress

See: docs/guia_documentacao.rst
"""

import ntplib
from time import ctime
import serial
import time
from datetime import datetime, timedelta
import paramiko
import ipaddress



class RTC_Test:
	def __init__(self, connection=False):
		# Defina o servidor SNTP que deseja consultar
		self.servidor_ntp = ['pool.ntp.org']
		self.port = 22
		self.username = 'root'
		self.password = ''
		self.host = False
		self.serial_port = False
		
		try:
			ip = ipaddress.ip_address(connection)
			self.host = connection
		except:
			self.host = False
			if "COM" in connection:
				self.serial_port = connection

	def __str__(self):
		if self.serial_port: return "Serial port: "+self.serial_port
		elif self.host: return "IP address: "+self.host
		else: return 'NaN'

	def sendCMD(self,cmd='ls',serial_port=False,host=False):
		#Verifica se já tem destino
		if serial_port: self.serial_port = serial_port
		elif host: self.host = host
		
		if self.serial_port:
			# Configuração da porta serial e parâmetros de comunicação
			serial_baudrate = 115200
			serial_timeout = 1
			with serial.Serial(self.serial_port, serial_baudrate, timeout=serial_timeout) as ser:
				ser.write('root\n'.encode())
				# Aguarda a resposta
				response = [0]
				while response[-1] != '':
					response.append(ser.readline().decode().strip())
				
				ser.write(cmd.encode())
				# Ler a resposta da fonte de alimentação
				response = [' ']
				
				while (response[-1]!=''):
					# Ler a resposta da fonte de alimentação
					response.append(ser.readline().decode().strip())
				return response
					
		if self.host:
			# Crie um objeto SSHClient
			ssh = paramiko.SSHClient()
			# Defina uma política para lidar com chaves de host desconhecidas
			ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

			# Conecte-se ao host SSH
			ssh.connect(self.host, self.port, self.username, self.password)

			# Execute um comando remoto
			stdin, stdout, stderr = ssh.exec_command(cmd)

			# Obtenha a saída do comando
			response = stdout.read().decode('utf-8').split('\n')

			# Feche a conexão SSH
			ssh.close()
			
			return response
	
	def getTime(self,serial_port=False,host=False):
		#Verifica se já tem destino
		if serial_port: self.serial_port = serial_port
		elif host: self.host = host
		#Verifica o destino
		if self.serial_port: print('\nget time from:'+self.serial_port)
		elif self.host: print('\nget time from:'+self.host)
		getHwclock = 'date +"%Y-%m-%d %T.%s" ; hwclock\n'
		
		if self.serial_port:
			# Configuração da porta serial e parâmetros de comunicação
			serial_baudrate = 115200
			serial_timeout = 1
			with serial.Serial(self.serial_port, serial_baudrate, timeout=serial_timeout) as ser:
				ser.write('root\n'.encode())
				# Aguarda a resposta
				response = [0]
				while response[-1] != '':
					response.append(ser.readline().decode().strip())
				
				self.obter_hora_servidor_ntp([self.servidor_ntp[1]],precision=True)
				# Enviar o comando para a fonte de alimentação
				print('hora no SO e no RTC - ', end="")
				inicio = self.marcatempo()
				ser.write(getHwclock.encode())
				self.marcatempo(inicio)
				# Ler a resposta da fonte de alimentação
				response = [' ']
				
				while (response[-1]!=''):
					# Ler a resposta da fonte de alimentação
					response.append(ser.readline().decode().strip())
				for i in range(len(response)):
					if len(response[i])>26 and i>1: print(response[i][:26])
				#self.obter_hora_servidor_ntp(self.servidor_ntp)
		if self.host:
			# Crie um objeto SSHClient
			ssh = paramiko.SSHClient()

			# Defina uma política para lidar com chaves de host desconhecidas
			ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

			# Conecte-se ao host SSH
			ssh.connect(self.host, self.port, self.username, self.password)

			
			self.obter_hora_servidor_ntp([self.servidor_ntp[0]],precision=True)
			
			
			print('hora no SO e no RTC - ', end="")
			inicio = self.marcatempo()
			# Execute um comando remoto
			stdin, stdout, stderr = ssh.exec_command(getHwclock)
			self.marcatempo(inicio)
			
			# Obtenha a saída do comando
			response = stdout.read().decode('utf-8').split('\n')

			# Ler a resposta da fonte de alimentação
			for i in range(len(response)):
				if len(response[i])>26: print(response[i][:26])

			# Feche a conexão SSH
			ssh.close()


	def setTime(self,serial_port=False,host=False,rtc=True,SO=True,wrong=False,force=False):
		#Verifica se já tem destino
		if serial_port: self.serial_port = serial_port
		elif host: self.host = host
		#Verifica o destino
		if self.serial_port: print('\nset time on:'+self.serial_port)
		elif self.host: print('\nset time on:'+self.host)
		
		if not force:
			a = input("Você deseja realmente reconfigurar a data e hora do RTC? (y/n)")
			if not a.lower() == 'y': return
			
		if self.serial_port:
			# Configuração da porta serial e parâmetros de comunicação
			serial_baudrate = 115200
			serial_timeout = 1
			with serial.Serial(self.serial_port, serial_baudrate, timeout=serial_timeout) as ser:
				ser.write('root\n'.encode())
				# Aguarda a resposta
				response = [0]
				while response[-1] != '':
					response.append(ser.readline().decode().strip())
				
				#Habilita para gravação
				ser.write('mount / -o rw,remount\n'.encode())
				# Aguarda a resposta
				response = [0]
				while response[-1] != '':
					response.append(ser.readline().decode().strip())
				#print('response',response)
				# Comando para definir a tensão de saída para 5V
				hora_servidor = self.obter_hora_servidor_ntp([self.servidor_ntp[1]],precision=True)
				inicio = self.marcatempo()
				
				data = self.creatCMD(hora_servidor,rtc,SO,wrong)
				# Execute um comando remoto
				ser.write(data.encode())
				self.marcatempo(inicio)
				
				# Executa a leitura
				response = [0]
				while response[-1] != '':
					response.append(ser.readline().decode().strip())
				#print('response',response)
				
				#self.obter_hora_servidor_ntp(self.servidor_ntp)
		if self.host:
			# Crie um objeto SSHClient
			ssh = paramiko.SSHClient()

			# Defina uma política para lidar com chaves de host desconhecidas
			ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

			# Conecte-se ao host SSH
			ssh.connect(self.host, self.port, self.username, self.password)
			
			hora_servidor = self.obter_hora_servidor_ntp([self.servidor_ntp[1]],precision=True)
			#print(hora_servidor[:19])
			inicio = self.marcatempo()
			data = self.creatCMD(hora_servidor,rtc,SO,wrong)
			# Execute um comando remoto
			stdin, stdout, stderr = ssh.exec_command(data.encode())
			self.marcatempo(inicio)
			# Obtenha a saída do comando
			output = stdout.read().decode('utf-8').split('\n')
			#print(output)
			#self.obter_hora_servidor_ntp(self.servidor_ntp)
			# Feche a conexão SSH
			ssh.close()

	def wrongDate(self,data_hora_string):
		# String inicial no formato "AAAA-MM-DD HH:MM:SS"
		#data_hora_string = "2023-07-07 13:08:47"

		# Converter a string em um objeto datetime
		data_hora = datetime.strptime(data_hora_string, "%Y-%m-%d %H:%M:%S")

		# Incrementar 1 segundo
		data_hora_incrementada = data_hora + timedelta(seconds=1)

		# Incrementar 1 minuto
		data_hora_incrementada = data_hora_incrementada + timedelta(minutes=1)

		# Incrementar 1 hora
		data_hora_incrementada = data_hora_incrementada + timedelta(hours=1)

		# Converter o resultado de volta para uma string no formato desejado
		data_hora_incrementada_string = data_hora_incrementada.strftime("%Y-%m-%d %H:%M:%S")

		# Imprimir o resultado
		print('set wrong date from:',data_hora_string)
		print('wrong date to:',data_hora_incrementada_string)
		return data_hora_incrementada_string

	def creatCMD(self,hora = "2014-07-08 17:13:45",rtc=True,SO=True,wrong=False):
		if wrong: hora = self.wrongDate(hora[:19])
		if rtc and SO:
			data = 'date -s "'+hora[:19]+'"; hwclock -w'
			print('write date to OS and RTC - ', end="")
		elif rtc:
			data = 'hwclock --set --date="'+hora[:19]+'"'
			print('write date to RTC - ', end="")
		elif SO:
			data = 'date -s "'+hora[:19]+'"'
			print('write date to SO - ', end="")
		else:
			print("what's wrong with you?")
			data = "what's wrong with you?"
		return data

	def marcatempo(self,start = ''):
		if start != '':
			fim = time.perf_counter()
			tempo_total = (fim - start) * 1000
			print(f"O processo levou {tempo_total:.2f} milissegundos.")
		return time.perf_counter()

	def obter_hora_servidor_ntp(self,servidor_ntp,precision=False):
		inicio = self.marcatempo()
		print('hora no servidor ',servidor_ntp)

		for ntp in servidor_ntp:
			cliente_ntp = ntplib.NTPClient()
			resposta = cliente_ntp.request(ntp)
			hora_servidor = ctime(resposta.tx_time)
			if precision:
				hora_servidorLast = hora_servidor
				while hora_servidor == hora_servidorLast:
					resposta = cliente_ntp.request(ntp)
					hora_servidor = ctime(resposta.tx_time)

			hora_datetime = datetime.strptime(hora_servidor, "%a %b %d %H:%M:%S %Y")
			hora_formatada = hora_datetime.strftime("%Y-%m-%d %H:%M:%S.%f")
			#print('Hora do '+ntp+':\t'+hora_formatada)
			print(hora_formatada)
		self.marcatempo(inicio)
		return hora_formatada