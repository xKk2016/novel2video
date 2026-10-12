@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "ENTRY=%ROOT%novel_to_video.py"
rem ==================== storyboard version ====================
rem   change VER to switch storyboard: v2 / v3 / ...
rem   (v3 = bilingual + audio layer + back-view ref narrowing)
rem   assets are tiered: 01_script 02_design 03_keyframes 04_clips 05_audio 06_release
set "VER=v3"
set "SB=%ROOT%assets\01_script\storyboard\storyboard_ch1_%VER%.json"
set "PYTHONIOENCODING=utf-8"

if not exist "%PY%" (
  echo [ERROR] Python venv not found: "%PY%"
  goto :end
)
if not exist "%ENTRY%" (
  echo [ERROR] entry script not found: "%ENTRY%"
  goto :end
)
if not exist "%SB%" (
  echo [ERROR] storyboard not found: "%SB%"
  goto :end
)

rem ==================== parse args ====================
rem   run_chain.bat [from_shot] [to_shot] [extra options...]
rem   first two positional args = range when numeric; rest passes through.
set "FROM="
set "TO="
set "PASS="

echo %~1|findstr /r "^[0-9][0-9]*$" >nul 2>&1
if errorlevel 1 goto :collect
set "FROM=%~1"
shift
echo %~1|findstr /r "^[0-9][0-9]*$" >nul 2>&1
if errorlevel 1 goto :collect
set "TO=%~1"
shift

:collect
if "%~1"=="" goto :parsed
set "PASS=%PASS% %~1"
shift
goto :collect
:parsed

rem ==================== no range given -> interactive ====================
if defined FROM goto :run
if defined TO goto :run
if defined PASS goto :run

echo ============================================================
echo  novel2video - range generation (chain mode)
echo ------------------------------------------------------------
echo  usage:
echo    run_chain.bat                     interactive
echo    run_chain.bat 5 10                shots 5 to 10
echo    run_chain.bat 20                  shot 20 to the end
echo    run_chain.bat 5 10 --no-concat    range plus extra options
echo    run_chain.bat --plan-only         show plan only, no GPU
echo ------------------------------------------------------------
echo  range format:
echo    5-10   shots 5 to 10        20    shot 20 to the end
echo    1-5    shots 1 to 5         8-    shot 8 to the end
echo    Enter  = the whole chapter
echo ------------------------------------------------------------
echo  notes: done shots with valid clips are skipped (resume).
echo         force a re-run: run_chain.bat 5 10 --redo-from 5
echo         switched storyboard version: add --fresh-state (or --accept-state)
echo ============================================================
echo.
echo  scene / shot map:
"%PY%" -c "import json,collections;s=json.load(open(r'%SB%',encoding='utf-8'));s=s.get('shots',s) if isinstance(s,dict) else s;g=collections.OrderedDict();[g.setdefault(x.get('scene_no'),[]).append(int(x.get('index'))) for x in s];print('   total '+str(len(s))+' shots   '+'   '.join('scene'+str(k)+' : shot '+str(v[0])+'-'+str(v[-1]) for k,v in g.items()))"
echo.
set /p "RG=range: "

rem ==================== assemble and run ====================
rem   RG goes straight to python as --range (parsed there). Keeping the
rem   parsing in python avoids findstr/for quirks under chcp 65001.
:run
set "RANGE="
if defined RG if not "%RG%"=="" set "RANGE=--range "%RG%""

if defined RANGE goto :have_range
if defined FROM set "RANGE=--from-shot %FROM%"
if defined TO set "RANGE=%RANGE% --to-shot %TO%"
:have_range

set "SHOW="
if defined RG if not "%RG%"=="" set "SHOW=%RG%"
if defined SHOW goto :show_ok
set "S1=%FROM%"
if not defined S1 set "S1=1"
set "S2=%TO%"
if not defined S2 set "S2=last"
set "SHOW=%S1% ~ %S2%"
:show_ok

echo ============================================================
echo  novel2video - range generation
echo ------------------------------------------------------------
echo  storyboard: %VER%   (%SB%)
echo  range    : %SHOW%
echo  extra    : %PASS%
echo  reminder : start ComfyUI first; closing this window stops it
echo             final.mp4 is concatenated when the range is done
echo ============================================================
echo.

"%PY%" "%ENTRY%" --storyboard-file "%SB%" --mode chain --out "%ROOT%assets\06_release\final.mp4" %RANGE% %PASS%

set "RC=%ERRORLEVEL%"
echo.
echo ============================================================
if "%RC%"=="0"  echo [DONE    ] range finished and concatenated.
if "%RC%"=="1"  echo [ABORTED ] some shot failed or unfinished - read log tail.
if "%RC%"=="2"  echo [LOCKED  ] another runner is active - nothing started.
if "%RC%"=="4"  echo [BADARG  ] invalid range: check the from/to shot numbers.
if "%RC%"=="5"  echo [MISMATCH] run_state belongs to another storyboard version - aborted.
if "%RC%"=="5"  echo            fix: add --fresh-state (archive + restart) or --accept-state (trust old).
if "%RC%"=="10" echo [PAUSED  ] time budget reached; run again to resume.
echo exit code: %RC%
echo logs     : "%ROOT%output\logs\"
echo ============================================================

:end
if not defined N2V_NO_PAUSE pause
endlocal
