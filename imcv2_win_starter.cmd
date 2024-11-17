@ECHO OFF
CLS
REM P:\SDK\imcv2_win_starter.cmd IMCv2 P:\SDK
REM wsl -d IMCv2_17_11_2024

REM ----------------------------------------------------------------------------
REM
REM IMCv2 SDK WSL Environment Preparation Script
REM This script creates a bare Ubuntu instance, installs all the 
REM required packages, and prepares it for the IMCv2 SDK installer.
REM
REM ----------------------------------------------------------------------------

ECHO.

IF "%~1"=="" (
    ECHO Error: Instance name not provided. Usage: script.cmd "<instance name>" "<base path>"
    EXIT /B 1
)

IF "%~2"=="" (
    ECHO Error: Base path not provided. Usage: script.cmd "<instance name>" "<base path>"
    EXIT /B 1
)

REM Set variables based on provided arguments
SET "IMCV2_INSTANCE_NAME=%~1"
SET "IMCV2_WSL_BASE_PATH=%~2"

REM Validate instance name (no spaces allowed)
FOR /F "tokens=1,2 delims= " %%A IN ("%IMCV2_INSTANCE_NAME%") DO (
    IF NOT "%%B"=="" (
        ECHO Error: Instance name cannot contain spaces.
        EXIT /B 1
    )
)

REM Set other environment variables
SET "IMCV2_INTEL_PROXY_SERVER=http://proxy-dmz.intel.com"
SET "IMCV2_INTEL_PROXY_PORT=911"
SET "IMCV2_WSL_BARE_IMAGE_PATH=%IMCV2_WSL_BASE_PATH%\Bare"
SET "IMCV2_WSL_SDK_INSTANCES_PATH=%IMCV2_WSL_BASE_PATH%\Instances"
SET "IMCV2_WQL_UBUNTU_URL=https://cdimage.ubuntu.com/ubuntu-base/releases/24.04.1/release/ubuntu-base-24.04.1-base-amd64.tar.gz"
SET "IMCV2_WSL_BARE_IMAGE_FILE=ubuntu-base-24.04.1-base-amd64.tar.gz"
SET "IMCV2_LOCAL_USERNAME=%USERNAME%" REM Uses the current Windows username
SET "IMCV2_WSL_UBUNTU_PACKAGES=%IMCV2_WSL_BASE_PATH%\packges.txt"
SET "IMCV2_WSL_SDK_INSTALLER=%IMCV2_WSL_BASE_PATH%\sdk_install.sh"


REM ----------------------------------------------------------------------------
REM
REM Check if WSL is installed
REM
REM ----------------------------------------------------------------------------

wsl --version >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Error: WSL is not installed.
    ECHO Please install WSL using the following steps:
    ECHO 1. Open PowerShell as Administrator.
    ECHO 2. Run the command: wsl --install --no-distribution
    ECHO 3. Restart your computer after installation.
    EXIT /B 1
)

REM Set the default WSL instance to %IMCV2_WSL_INSTANCE_NAME%
wsl --set-default %IMCV2_WSL_INSTANCE_NAME% >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Error: Failed to set %IMCV2_WSL_INSTANCE_NAME% as the default instance.
    ECHO Ensure the instance name is correct and exists. Use: wsl --list
    EXIT /B 1
)

REM ----------------------------------------------------------------------------
REM
REM Downloading additional resources
REM
REM ----------------------------------------------------------------------------

ECHO Getting resources

curl -s -S --proxy %IMCV2_INTEL_PROXY_SERVER%:%IMCV2_INTEL_PROXY_PORT% ^
         --output "%IMCV2_WSL_BASE_PATH%\packges.txt" ^
         "https://raw.githubusercontent.com/emichael72/wsl_starter/main/packges.txt"

curl -s -S --proxy %IMCV2_INTEL_PROXY_SERVER%:%IMCV2_INTEL_PROXY_PORT% ^
         --output "%IMCV2_WSL_BASE_PATH%\sdk_install.sh" ^
         "https://raw.githubusercontent.com/emichael72/wsl_starter/main/sdk_install.sh"

REM ----------------------------------------------------------------------------
REM
REM Setting WSL Ubuntu instance
REM
REM ----------------------------------------------------------------------------

REM Check if an instance with the same name already exists
wsl --list --quiet | FINDSTR /R /C:"^%IMCV2_INSTANCE_NAME%_" >NUL
IF NOT ERRORLEVEL 1 (
    ECHO Error: An instance with the name "%IMCV2_INSTANCE_NAME%" already exists.
    EXIT /B 1
)

REM Create required directories if they don't exist
IF NOT EXIST "%IMCV2_WSL_BARE_IMAGE_PATH%" (
    mkdir "%IMCV2_WSL_BARE_IMAGE_PATH%"
    IF ERRORLEVEL 1 (
        ECHO Failed to create directory: %IMCV2_WSL_BARE_IMAGE_PATH%
        EXIT /B 1
    )
)

IF NOT EXIST "%IMCV2_WSL_SDK_INSTANCES_PATH%" (
    mkdir "%IMCV2_WSL_SDK_INSTANCES_PATH%"
    IF ERRORLEVEL 1 (
        ECHO Failed to create directory: %IMCV2_WSL_SDK_INSTANCES_PATH%
        EXIT /B 1
    )
)

ECHO Checking if the bare image file already exists
IF EXIST "%IMCV2_WSL_BARE_IMAGE_PATH%\%IMCV2_WSL_BARE_IMAGE_FILE%" (
    ECHO The image file already exists.
) ELSE (
    REM Download the bare image file using curl
    ECHO Downloading %IMCV2_WQL_UBUNTU_URL%...
    curl -s -S --proxy %IMCV2_INTEL_PROXY_SERVER%:%IMCV2_INTEL_PROXY_PORT% ^
         --output "%IMCV2_WSL_BARE_IMAGE_PATH%\%IMCV2_WSL_BARE_IMAGE_FILE%" ^
         "%IMCV2_WQL_UBUNTU_URL%"
    IF ERRORLEVEL 1 (
        ECHO Failed to download the image file. Please check your proxy settings or URL.
        EXIT /B 1
    )
    ECHO Download completed successfully.
)

REM Construct instance name with current date (DD_MM_YYYY)
FOR /F "tokens=2 delims== " %%I IN ('wmic os get localdatetime /value ^| find "="') DO SET IMCV2_DATE=%%I
SET "IMCV2_DATE=%IMCV2_DATE:~6,2%_%IMCV2_DATE:~4,2%_%IMCV2_DATE:~0,4%"
SET "IMCV2_WSL_INSTANCE_NAME=%IMCV2_INSTANCE_NAME%_%IMCV2_DATE%"

REM Un-register the instance if exists
wsl --unregister %IMCV2_WSL_INSTANCE_NAME% >nul 2>&1

REM Import WSL instance
ECHO Importing WSL instance: %IMCV2_WSL_INSTANCE_NAME%

wsl --import "%IMCV2_WSL_INSTANCE_NAME%" "%IMCV2_WSL_SDK_INSTANCES_PATH%\%IMCV2_WSL_INSTANCE_NAME%" "%IMCV2_WSL_BARE_IMAGE_PATH%\%IMCV2_WSL_BARE_IMAGE_FILE%" >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Failed to import WSL instance.
    EXIT /B 1
)

REM Ensure we start WSL from the C: drive
C:

REM Initialize for first run, update packages
ECHO Updating package manager and install prerequisites
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "apt update -qq" >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Failed to update package lists.
    EXIT /B 1
)

ECHO Setting local account for %IMCV2_LOCAL_USERNAME%

wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "apt install -y -qq sudo passwd" >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Failed to install required packages.
    EXIT /B 1
)

REM Ensure sudo group exists
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "if ! grep -q \"^sudo:\" /etc/group; then groupadd sudo; fi"
IF ERRORLEVEL 1 (
    ECHO Failed to create sudo group.
    EXIT /B 1
)

REM Create user
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "useradd -m -s /bin/bash %IMCV2_LOCAL_USERNAME%"
IF ERRORLEVEL 1 (
    ECHO Failed to create user %IMCV2_LOCAL_USERNAME%.
    EXIT /B 1
)

REM Set user password
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo '%IMCV2_LOCAL_USERNAME%:intel@1234' | chpasswd"
IF ERRORLEVEL 1 (
    ECHO Failed to set password for %IMCV2_LOCAL_USERNAME%.
    EXIT /B 1
)

REM Add user to sudo group
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "usermod -aG sudo %IMCV2_LOCAL_USERNAME%"
IF ERRORLEVEL 1 (
    ECHO Failed to add %IMCV2_LOCAL_USERNAME% to sudo group.
    EXIT /B 1
)

REM Allow password-less sudo
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo '%IMCV2_LOCAL_USERNAME% ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers"
IF ERRORLEVEL 1 (
    ECHO Failed to configure sudoers for %IMCV2_LOCAL_USERNAME%.
    EXIT /B 1
)

ECHO Setting Proxy server

REM Configure proxy settings
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'export http_proxy=%IMCV2_INTEL_PROXY_SERVER%:%IMCV2_INTEL_PROXY_PORT%' >> /home/%IMCV2_LOCAL_USERNAME%/.bashrc"
IF ERRORLEVEL 1 (
    ECHO Failed to set HTTP proxy in .bashrc.
    EXIT /B 1
)

wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'export https_proxy=%IMCV2_INTEL_PROXY_SERVER%:%IMCV2_INTEL_PROXY_PORT%' >> /home/%IMCV2_LOCAL_USERNAME%/.bashrc"
IF ERRORLEVEL 1 (
    ECHO Failed to set HTTPS proxy in .bashrc.
    EXIT /B 1
)

ECHO Upgrade system packages
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "apt upgrade -y -qq" >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Failed to upgrade system packages.
    EXIT /B 1
)

REM Ensure the user starts in their home directory
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'cd ~' >> /home/%IMCV2_LOCAL_USERNAME%/.bashrc"
IF ERRORLEVEL 1 (
    ECHO Failed to set default directory for %IMCV2_LOCAL_USERNAME%.
    EXIT /B 1
)

REM Configure the default user in WSL
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo '[user]' > /etc/wsl.conf"
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'default=%IMCV2_LOCAL_USERNAME%' >> /etc/wsl.conf"

ECHO Setting time zone and console defaults

REM Pre-seed tzdata configuration for Israel timezone
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'tzdata tzdata/Areas select Asia' | sudo debconf-set-selections" >nul 2>&1
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'tzdata tzdata/Zones/Asia select Jerusalem' | sudo debconf-set-selections" >nul 2>&1

REM Set timezone in WSL instance
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "sudo ln -fs /usr/share/zoneinfo/Asia/Jerusalem /etc/localtime" >nul 2>&1
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "sudo dpkg-reconfigure -f noninteractive tzdata" >nul 2>&1

REM Pre-seed console-setup for Hebrew character set
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'console-setup console-setup/charmap47 select UTF-8' | sudo debconf-set-selections" >nul 2>&1
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'console-setup console-setup/codeset47 select Hebrew' | sudo debconf-set-selections" >nul 2>&1
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'console-setup console-setup/fontface47 select Fixed' | sudo debconf-set-selections" >nul 2>&1
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'console-setup console-setup/fontsize-text47 select 16' | sudo debconf-set-selections" >nul 2>&1

REM Install console-setup in non-interactive mode
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "export DEBIAN_FRONTEND=noninteractive && sudo apt install -y console-setup" >nul 2>&1

IF ERRORLEVEL 1 (
    ECHO Failed to setup console
    EXIT /B 1
)

REM ----------------------------------------------------------------------------
REM
REM Setting Kerberos realm configuration
REM
REM ----------------------------------------------------------------------------

ECHO Setting Kerberos defaults
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'krb5-config krb5-config/default_realm string CLIENTS.INTEL.COM' | sudo debconf-set-selections"  >nul 2>&1

REM Pre-seed Kerberos server hostnames
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'krb5-config krb5-config/kerberos_servers string kdc1.clients.intel.com kdc2.clients.intel.com' | sudo debconf-set-selections"  >nul 2>&1

REM Pre-seed Kerberos administrative server
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'krb5-config krb5-config/admin_server string admin.clients.intel.com' | sudo debconf-set-selections"  >nul 2>&1

REM Install Kerberos packages noninteractively
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "export DEBIAN_FRONTEND=noninteractive && sudo apt install -y krb5-config krb5-user" >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Failed to set Kerberos
    EXIT /B 1
)

REM ----------------------------------------------------------------------------
REM
REM Install packages from the exported package list
REM
REM ----------------------------------------------------------------------------


ECHO Installing packages from %IMCV2_WSL_UBUNTU_PACKAGES%...

REM Clearing the local cache can resolve inconsistencies
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "sudo apt clean" >nul 2>&1

REM Resolve subst drive to actual path
SET "RESOLVED_PATH=%IMCV2_WSL_UBUNTU_PACKAGES%"

FOR /F "tokens=2*" %%A IN ('subst ^| findstr /I "^[A-Z]:"') DO (
    IF "%RESOLVED_PATH:~0,2%"=="%%A" SET "RESOLVED_PATH=%%B%RESOLVED_PATH:~2%"
)

REM Convert resolved path to WSL-compatible path
SET "WSL_PACKAGES_FILE=/mnt/%RESOLVED_PATH:~0,1%%RESOLVED_PATH:~2%"
SET "WSL_PACKAGES_FILE=%WSL_PACKAGES_FILE:\=/%"

REM Ensure the file exists in Windows before proceeding
IF NOT EXIST "%RESOLVED_PATH%" (
    ECHO Error: The package list file does not exist at %RESOLVED_PATH%.
    EXIT /B 1
)

REM Copy the file to a directory WSL can access if necessary
SET "TEMP_PATH=C:\temp\packages.txt"
COPY "%RESOLVED_PATH%" "%TEMP_PATH%"  >nul 2>&1
SET "WSL_PACKAGES_FILE=/mnt/c/temp/packages.txt"

REM Verify file can be accessed in WSL
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "if [ ! -f '%WSL_PACKAGES_FILE%' ]; then echo 'Error: Cannot access file in WSL: %WSL_PACKAGES_FILE%'; exit 1; fi"
IF ERRORLEVEL 1 (
    ECHO Failed to verify the package list file in WSL.
    EXIT /B 1
)

REM Copy and process the package list
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "cat '%WSL_PACKAGES_FILE%' | awk '{print \$1}' > /tmp/packages.txt"
IF ERRORLEVEL 1 (
    ECHO Failed to copy and process %IMCV2_WSL_UBUNTU_PACKAGES%.
    EXIT /B 1
)

REM Install packages with quiet mode
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "xargs -a /tmp/packages.txt sudo apt install -y -qq" >nul 2>&1 && (
    ECHO Packages installed successfully.
) || (
    ECHO Failed to install packages from %IMCV2_WSL_UBUNTU_PACKAGES%.
    EXIT /B 1
)

REM Clean up the temporary file
DEL "%TEMP_PATH%" >nul 2>&1

REM Restart WSL instance to apply the configuration
wsl --terminate %IMCV2_WSL_INSTANCE_NAME% >nul 2>&1

ECHO Refreshing packages cache and resolving inconsistencies
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "sudo apt clean" >nul 2>&1

REM Updating once more
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "sudo apt update && sudo apt upgrade" >nul 2>&1
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "sudo apt update && sudo apt upgrade" >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Failed to refresh packages
    EXIT /B 1
)

REM ----------------------------------------------------------------------------
REM
REM Creating several required paths
REM
REM ----------------------------------------------------------------------------

REM Create ~/downloads directory
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "mkdir -p /home/%IMCV2_LOCAL_USERNAME%/downloads && sudo chown %IMCV2_LOCAL_USERNAME%:%IMCV2_LOCAL_USERNAME% /home/%IMCV2_LOCAL_USERNAME%/downloads"

REM Create ~/projects directory
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "mkdir -p /home/%IMCV2_LOCAL_USERNAME%/projects && sudo chown %IMCV2_LOCAL_USERNAME%:%IMCV2_LOCAL_USERNAME% /home/%IMCV2_LOCAL_USERNAME%/projects"

REM Create .hushlogin in the user's home directory
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "touch /home/%IMCV2_LOCAL_USERNAME%/.hushlogin && sudo chown %IMCV2_LOCAL_USERNAME%:%IMCV2_LOCAL_USERNAME% /home/%IMCV2_LOCAL_USERNAME%/.hushlogin"

REM Set the prompt
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'export PS1=\"\[\e[1;36m\]\u@\[\e[1;32m\]\w~ \[\e[m\]\"' >> /home/%IMCV2_LOCAL_USERNAME%/.bashrc"

REM Restart WSL instance to apply the configuration
wsl --terminate %IMCV2_WSL_INSTANCE_NAME% >nul 2>&1

REM ----------------------------------------------------------------------------
REM
REM Get 'dt'
REM ----------------------------------------------------------------------------

ECHO Installing 'dt' Utility
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "curl -s -S --noproxy '*' -k -L https://gfx-assets.intel.com/artifactory/gfx-build-assets/build-tools/devtool-go/latest/artifacts/linux64/dt -o /home/%IMCV2_LOCAL_USERNAME%/downloads/dt" >nul 2>&1
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "chmod +x /home/%IMCV2_LOCAL_USERNAME%/downloads/dt" >nul 2>&1
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "/home/%IMCV2_LOCAL_USERNAME%/downloads/dt install" >nul 2>&1

IF ERRORLEVEL 1 (
    ECHO Failed to install 'dt'
    EXIT /B 1
)

REM Restart WSL instance to apply the configuration
wsl --terminate %IMCV2_WSL_INSTANCE_NAME% >nul 2>&1

REM ----------------------------------------------------------------------------
REM
REM Install dependencies for pyenv
REM
REM ----------------------------------------------------------------------------

ECHO Imstalling 'pyenv'

REM Download pyenv installer
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "curl -s -S -x %IMCV2_INTEL_PROXY_SERVER%:%IMCV2_INTEL_PROXY_PORT% -L https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer -o /home/%IMCV2_LOCAL_USERNAME%/downloads/pyenv-installer" >nul 2>&1

REM Make installer executable
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "chmod +x /home/%IMCV2_LOCAL_USERNAME%/downloads/pyenv-installer" >nul 2>&1

REM Clean up any previous pyenv installation
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "rm -rf /home/%IMCV2_LOCAL_USERNAME%/.pyenv" >nul 2>&1

REM Run pyenv installer with proxy settings
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "export http_proxy=%IMCV2_INTEL_PROXY_SERVER%:%IMCV2_INTEL_PROXY_PORT% && export https_proxy=%IMCV2_INTEL_PROXY_SERVER%:%IMCV2_INTEL_PROXY_PORT% && /home/%IMCV2_LOCAL_USERNAME%/downloads/pyenv-installer" >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Failed to install 'pyenv'
    EXIT /B 1
)

REM Restart WSL instance to apply the configuration
wsl --terminate %IMCV2_WSL_INSTANCE_NAME% >nul 2>&1

REM Update .bashrc for pyenv
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'export PYENV_ROOT=\"\$HOME/.pyenv\"' >> /home/%IMCV2_LOCAL_USERNAME%/.bashrc" >nul 2>&1
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'export PATH=\"\$PYENV_ROOT/bin:\$PATH\"' >> /home/%IMCV2_LOCAL_USERNAME%/.bashrc" >nul 2>&1
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "echo 'eval \"\$(pyenv init --path)\"' >> /home/%IMCV2_LOCAL_USERNAME%/.bashrc" >nul 2>&1

REM Restart WSL instance to apply the configuration
wsl --terminate %IMCV2_WSL_INSTANCE_NAME% >nul 2>&1

REM Force Python 3.9.0 installation using pyenv
ECHO Installing Python 3.9 through 'pyenv'
wsl -d %IMCV2_WSL_INSTANCE_NAME% --user %IMCV2_LOCAL_USERNAME% -- bash -c "export http_proxy=%IMCV2_INTEL_PROXY_SERVER%:%IMCV2_INTEL_PROXY_PORT% && export https_proxy=%IMCV2_INTEL_PROXY_SERVER%:%IMCV2_INTEL_PROXY_PORT% && ~/.pyenv/bin/pyenv install 3.9.0 -f" >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Failed to install Python3.9
    EXIT /B 1
)

ECHO Setting Python 3.9.0 as default
wsl -d %IMCV2_WSL_INSTANCE_NAME% --user %IMCV2_LOCAL_USERNAME% -- bash -c "~/.pyenv/bin/pyenv global 3.9.0" >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Failed set Python 3.9 as default
    EXIT /B 1
)

REM ----------------------------------------------------------------------------
REM
REM Copying the SDK start script to the instance.
REM
REM ----------------------------------------------------------------------------

REM Resolve subst drive to actual path
SET "RESOLVED_PATH=%IMCV2_WSL_SDK_INSTALLER%"

FOR /F "tokens=2*" %%A IN ('subst ^| findstr /I "^[A-Z]:"') DO (
    IF "%RESOLVED_PATH:~0,2%"=="%%A" SET "RESOLVED_PATH=%%B%RESOLVED_PATH:~2%"
)

REM Convert resolved path to WSL-compatible path
SET "WSL_INSTALLER_FILE=/mnt/%RESOLVED_PATH:~0,1%%RESOLVED_PATH:~2%"
SET "WSL_INSTALLER_FILE=%WSL_INSTALLER_FILE:\=/%"

REM Ensure the file exists in Windows before proceeding
IF NOT EXIST "%RESOLVED_PATH%" (
    ECHO Error: The installer file does not exist at %RESOLVED_PATH%.
    EXIT /B 1
)

REM Copy the file to a directory WSL can access if necessary
SET "TEMP_PATH=C:\temp\sdk_install.sh"
COPY "%RESOLVED_PATH%" "%TEMP_PATH%" >nul 2>&1
SET "WSL_INSTALLER_FILE=/mnt/c/temp/sdk_install.sh"


REM Copy the installer to ~/downloads in WSL
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "cp '%WSL_INSTALLER_FILE%' ~/downloads/"  >nul 2>&1

REM Make the script executable
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "chmod +x ~/downloads/sdk_install.sh"  >nul 2>&1

REM Confirm the script was successfully copied and made executable
wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "ls -l ~/downloads/sdk_install.sh"  >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Error: Failed to copy or make the installer executable in WSL.
    EXIT /B 1
)

REM Restart WSL instance to apply the configuration
wsl --terminate %IMCV2_WSL_INSTANCE_NAME% >nul 2>&1

REM ----------------------------------------------------------------------------
REM
REM Set as default
REM
REM ----------------------------------------------------------------------------

REM Set the default WSL instance to %IMCV2_WSL_INSTANCE_NAME%
wsl --set-default %IMCV2_WSL_INSTANCE_NAME% >nul 2>&1
IF ERRORLEVEL 1 (
    ECHO Error: Failed to set %IMCV2_WSL_INSTANCE_NAME% as the default instance.
    ECHO Ensure the instance name is correct and exists. Use: wsl --list
    EXIT /B 1
)

REM ----------------------------------------------------------------------------
REM
REM Create desktop shortcut
REM
REM ----------------------------------------------------------------------------

SET "SHORTCUT_NAME=IMCv2 WSL SDK.lnk"

REM Get the desktop path dynamically using PowerShell
FOR /F "delims=" %%D IN ('Powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') DO SET "DESKTOP_PATH=%%D"

REM Validate the desktop path
IF NOT EXIST "%DESKTOP_PATH%" (
    ECHO Error: Desktop path does not exist: %DESKTOP_PATH%
    EXIT /B 1
)

SET "SHORTCUT_PATH=%DESKTOP_PATH%\%SHORTCUT_NAME%"

REM Use PowerShell to create the shortcut
Powershell -Command ^
    $WshShell = New-Object -ComObject WScript.Shell; ^
    $Shortcut = $WshShell.CreateShortcut('%SHORTCUT_PATH%'); ^
    $Shortcut.TargetPath = 'C:\Windows\System32\cmd.exe'; ^
    $Shortcut.Arguments = '/c wsl -d %IMCV2_WSL_INSTANCE_NAME%'; ^
    $Shortcut.IconLocation = 'C:\Windows\System32\wsl.exe'; ^
    $Shortcut.Save()

IF NOT EXIST "%SHORTCUT_PATH%" (
    ECHO Error: Failed to create shortcut: %SHORTCUT_PATH%
    EXIT /B 1
)

ECHO Shortcut created successfully: %SHORTCUT_PATH%
ECHO WSL instance installed, type 'wsl -d %IMCV2_WSL_INSTANCE_NAME%' and 'dt setup' once running

REM wsl -d %IMCV2_WSL_INSTANCE_NAME% -- bash -c "/home/%IMCV2_LOCAL_USERNAME%/bin/dt setup"

:END
EXIT /B 0
