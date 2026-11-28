# Windows: PJSIP with MSBuild and the SWIG wrapper, like scripts/build_pjsip.sh.
# Release-Dynamic links the C runtime as a DLL (/MD), as Python does.
#   PJSIP_VERSION=2.17  PJSIP_SRC=<repo>\build\pjproject  SWIG=swig
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Version = if ($env:PJSIP_VERSION) { $env:PJSIP_VERSION } else { "2.17" }
$Src = if ($env:PJSIP_SRC) { $env:PJSIP_SRC } else { Join-Path $Root "build\pjproject" }
$Swig = if ($env:SWIG) { $env:SWIG } else { "swig" }
$Out = Join-Path $Root "src\simple_phone\_native"

if (-not (Test-Path $Src)) {
    git clone --depth 1 --branch $Version https://github.com/pjsip/pjproject.git $Src
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
Copy-Item (Join-Path $Root "packaging\config_site.h") (Join-Path $Src "pjlib\include\pj\config_site.h")

$VsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
$MsBuild = & $VsWhere -latest -products * -requires Microsoft.Component.MSBuild -find "MSBuild\**\Bin\MSBuild.exe" | Select-Object -First 1
& $MsBuild (Join-Path $Src "pjproject-vs14.sln") "/t:libpjproject;pjsua2_lib" `
    /p:Configuration=Release-Dynamic /p:Platform=x64 /p:PlatformToolset=v143 `
    /p:WindowsTargetPlatformVersion=10.0 /m /v:minimal /nologo
if ($LASTEXITCODE) { exit $LASTEXITCODE }

# pjsua2.i plus our additions; next to it, so its %include lines resolve.
$Swigdir = Join-Path $Src "pjsip-apps\src\swig"
$Interface = Join-Path $Swigdir "simple_phone_pjsua2.i"
Get-Content (Join-Path $Swigdir "pjsua2.i"), (Join-Path $Root "packaging\pjsua2_extra.i") | Set-Content $Interface
$Includes = "pjlib", "pjlib-util", "pjmedia", "pjsip", "pjnath" | ForEach-Object { "-I" + (Join-Path $Src "$_\include") }
& $Swig -c++ -python -threads -doxygen -w312 @Includes -outdir $Out -o (Join-Path $Out "pjsua2_wrap.cpp") $Interface
if ($LASTEXITCODE) { exit $LASTEXITCODE }
"PJSIP_VERSION = `"$Version`"`nPJSIP_TLS = 0`nPJSIP_BUILD_ID = `"windows-msvc`"" | Set-Content (Join-Path $Out "_build.py")
Write-Output "PJSIP $Version built in $Src; wrapper generated in $Out"
