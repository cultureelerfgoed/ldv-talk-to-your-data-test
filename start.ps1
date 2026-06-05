cd C:\Users\Admin\rce-assistent

# Stop eventueel nog draaiende backend
$proc = Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue
if ($proc) { Stop-Process -Id $proc.OwningProcess -Force }

# Open browser
Start-Process "C:\Users\Admin\rce-assistent\frontend\index.html"

# Start backend
C:\Users\Admin\AppData\Local\Python\pythoncore-3.14-64\python.exe app.py