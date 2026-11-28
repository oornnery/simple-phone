@echo off
rem The Windows half of the release, on Windows: PJSIP, wheel, wheel check,
rem PJSUA2 and unit tests. Run from the repository root; stops at the first error.
rem Needs Visual Studio 2022 Build Tools (C++), git, uv and swig (uv tool install swig).
setlocal
set PY=3.15
where swig >nul 2>&1 || set SWIG=%USERPROFILE%\.local\bin\swig.exe
if not "%1"=="" set PY=%1
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts\build_pjsip.ps1 || exit /b 1
if exist dist rmdir /s /q dist
uv build --wheel --python %PY% --out-dir dist || exit /b 1
if exist .venv-win rmdir /s /q .venv-win
uv venv -q --python %PY% .venv-win || exit /b 1
for %%f in (dist\*.whl) do (
    uv pip install -q --python .venv-win\Scripts\python.exe "%%f" || exit /b 1
    .venv-win\Scripts\python.exe scripts\check_package.py "%%f" || exit /b 1
)
cd tests
..\.venv-win\Scripts\python.exe native_checks.py || exit /b 1
..\.venv-win\Scripts\python.exe -m unittest discover -s . -p "test_*.py" || exit /b 1
echo ci-windows: all passed
