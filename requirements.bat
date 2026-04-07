pipreqs . --force --encoding=latin-1

powershell -Command "(Get-Content requirements.txt) -replace '==', '>=' | Set-Content requirements.txt"