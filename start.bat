@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title Shengwu Research Platform Launcher

set "ROOT_DIR=%~dp0"
set "APP_DIR=%ROOT_DIR%backup\src"
set "ENV_FILE=%APP_DIR%\.env"
set "ENV_EXAMPLE=%APP_DIR%\.env.example"
set "OCR_ENV=%APP_DIR%\.venv-ocr"
set "OCR_PYTHON=%OCR_ENV%\Scripts\python.exe"

if not exist "%APP_DIR%\pyproject.toml" (
    echo [ERROR] Backend project was not found: "%APP_DIR%"
    goto :failed
)

call :find_python
if errorlevel 1 goto :failed

echo [INFO] Python: "%PYTHON_EXE%"
"%PYTHON_EXE%" -c "import sys; v=sys.version_info.major*100+sys.version_info.minor; raise SystemExit(0 if v in range(311,315) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.11 through 3.14 is required.
    goto :failed
)

pushd "%APP_DIR%"

call :backend_ready
if errorlevel 1 (
    echo [INFO] Backend dependencies are missing. Starting automatic installation...
    call :install_backend
    if errorlevel 1 (
        echo [ERROR] Backend dependency installation failed on all configured mirrors.
        popd
        goto :failed
    )
)
echo [OK] Backend dependencies are ready.

call :ocr_ready
if errorlevel 1 (
    echo [INFO] PaddleOCR environment is missing or incomplete. Starting installation...
    call :install_ocr
    if errorlevel 1 (
        echo [ERROR] PaddleOCR installation failed. Check Python 3.12 and network access.
        popd
        goto :failed
    )
)
echo [OK] PaddleOCR dependencies are ready.

if /I "%~1"=="--check" (
    echo [OK] Dependency check completed. No service was started.
    popd
    exit /b 0
)

if not exist "%ENV_FILE%" (
    if not exist "%ENV_EXAMPLE%" (
        echo [ERROR] Configuration template was not found: "%ENV_EXAMPLE%"
        popd
        goto :failed
    )
    copy /Y "%ENV_EXAMPLE%" "%ENV_FILE%" >nul
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='%ENV_FILE%'; $s=[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48)); $c=[IO.File]::ReadAllText($p); $c=$c.Replace('change-this-to-a-long-random-secret',$s); [IO.File]::WriteAllText($p,$c,[Text.UTF8Encoding]::new($false))" >nul 2>&1
    echo [INFO] A local .env file was created for the backend.
)

if not exist "models\paddleocr\PP-OCRv5_mobile_det" echo [WARN] OCR detection model directory is missing.
if not exist "models\paddleocr\PP-OCRv5_mobile_rec" echo [WARN] OCR recognition model directory is missing.

call :api_running
if errorlevel 1 (
    echo [INFO] Starting FastAPI...
    start "Shengwu API Logs" /D "%APP_DIR%" cmd.exe /k ""%PYTHON_EXE%" -m app"
) else (
    echo [OK] FastAPI is already listening on port 8000.
)

call :worker_running
if errorlevel 1 (
    echo [INFO] Starting background worker...
    start "Shengwu Worker Logs" /D "%APP_DIR%" cmd.exe /k ""%PYTHON_EXE%" -m app.worker"
) else (
    echo [OK] Background worker is already running.
)

echo [INFO] Waiting for the API readiness check...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$end=(Get-Date).AddSeconds(45); do { try { $r=Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health/ready' -TimeoutSec 3; if ($r.status -eq 'ready') { exit 0 } } catch {}; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $end); exit 1"
if errorlevel 1 (
    echo [ERROR] The API did not become ready within 45 seconds.
    echo [ERROR] Check the API window and the database settings in "%ENV_FILE%".
    popd
    goto :failed
)

echo [OK] Shengwu backend is ready.
echo [INFO] API and worker log windows will remain open until you close them.
echo [INFO] API docs: http://127.0.0.1:8000/docs
start "" "http://127.0.0.1:8000/docs"
popd
timeout /t 3 /nobreak >nul
exit /b 0

:find_python
set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if defined PYTHON_EXE exit /b 0
echo [ERROR] Python was not found in PATH. Install Python 3.11 through 3.14 first.
exit /b 1

:backend_ready
"%PYTHON_EXE%" -c "import importlib.util as u; m=('fastapi','uvicorn','pydantic','pydantic_settings','sqlalchemy','psycopg2','multipart','httpx','fitz','docx','openpyxl','pandas','matplotlib','sklearn','xgboost','shap','joblib','rapidfuzz','jieba','email_validator'); raise SystemExit(1 if any(u.find_spec(x) is None for x in m) else 0)" >nul 2>&1
exit /b %errorlevel%

:install_backend
"%PYTHON_EXE%" -m ensurepip --upgrade >nul 2>&1
call :pip_backend "https://pypi.doubanio.com/simple" "Douban"
if not errorlevel 1 exit /b 0
call :pip_backend "https://pypi.tuna.tsinghua.edu.cn/simple" "Tsinghua"
if not errorlevel 1 exit /b 0
call :pip_backend "https://mirrors.aliyun.com/pypi/simple/" "Taobao-Aliyun"
if not errorlevel 1 exit /b 0
exit /b 1

:pip_backend
echo [INFO] Trying %~2 mirror: %~1
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --timeout 30 --retries 2 -e . --index-url "%~1"
if errorlevel 1 exit /b 1
call :backend_ready
exit /b %errorlevel%

:ocr_ready
if not exist "%OCR_PYTHON%" exit /b 1
"%OCR_PYTHON%" -c "import paddle, paddleocr" >nul 2>&1
exit /b %errorlevel%

:install_ocr
if not exist "%OCR_PYTHON%" (
    where uv >nul 2>&1
    if not errorlevel 1 uv venv "%OCR_ENV%" --python 3.12
)
if not exist "%OCR_PYTHON%" (
    py -3.12 -m venv "%OCR_ENV%" >nul 2>&1
)
if not exist "%OCR_PYTHON%" exit /b 1

"%OCR_PYTHON%" -m ensurepip --upgrade >nul 2>&1
call :pip_ocr "https://pypi.doubanio.com/simple" "Douban"
if not errorlevel 1 exit /b 0
call :pip_ocr "https://pypi.tuna.tsinghua.edu.cn/simple" "Tsinghua"
if not errorlevel 1 exit /b 0
call :pip_ocr "https://mirrors.aliyun.com/pypi/simple/" "Taobao-Aliyun"
if not errorlevel 1 exit /b 0
exit /b 1

:pip_ocr
echo [INFO] Trying %~2 mirror for PaddleOCR: %~1
"%OCR_PYTHON%" -m pip install --disable-pip-version-check --timeout 30 --retries 2 -r ocr-requirements.txt --index-url "%~1"
if errorlevel 1 exit /b 1
call :ocr_ready
exit /b %errorlevel%

:api_running
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:worker_running
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match '(?i)(^|\s)-m\s+app\.worker(\s|$)' }; if ($p) { exit 0 } else { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:failed
echo.
echo Startup failed. Review the message above and try again.
if /I "%~1"=="--check" exit /b 1
pause
exit /b 1
