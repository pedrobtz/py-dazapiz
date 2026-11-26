@echo off
rem The fake `az` on Windows: run fake_az.py with the test's Python (tests/conftest.py).
"%DAZAPIZ_FAKE_AZ_PYTHON%" "%~dp0fake_az.py" %*
exit /b %ERRORLEVEL%
