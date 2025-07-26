python -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile src\main.py --ico=reso-2-logo-png-transparent.ico --name=reso --windowed
copy .env dist\.env
copy src\reso.ini dist\reso.ini
pyinstaller --onefile src\manager_console.py