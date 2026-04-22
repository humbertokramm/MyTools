from RTC_Test import RTC_Test

com = RTC_Test('192.168.0.25')
com.servidor_ntp = ['ADELD002.datacom.net.br']

com.username = 'root'
com.password = 'root'

res = com.getTime()
print(res)
