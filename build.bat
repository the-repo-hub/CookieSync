if not exist ".env" (
    echo .env file was not found
    exit /b 1
)
if not exist ".venv\" (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r src\requirements.txt
    pip install pyinstaller
) else (
    echo Virtual environment already exists, pass this step.
    call .venv\Scripts\activate.bat
)
pyinstaller --onefile src\main.py --ico=reso-2-logo-png-transparent.ico --name=reso --windowed --add-data ".env;."
copy .env dist\.env
copy src\reso.ini dist\reso.ini
pyinstaller --onefile src\manager_console.py --add-data ".env;."