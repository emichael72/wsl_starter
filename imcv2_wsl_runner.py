#!/usr/bin/env python3

"""
Script:       imcv2_wsl_runner.py
Author:       Intel IMCv2 Team
Version:      1.0.1

Description:
Automates the creation and configuration of a Windows Subsystem for Linux (WSL) instance,
tailored for the IMCv2 SDK. It performs the following steps:

1. Verifies prerequisites, including required directories and resources.
2. Imports a base Linux image into a new WSL instance.
3. Configures the instance with a user account, sudo privileges, and environment settings.
4. Installs essential packages and tools specified in a configuration file.
5. Applies additional configurations for time zone, Kerberos authentication, and proxy settings.

Key Features:
- Supports proxy configuration for downloading resources.
- Ensures idempotency by verifying existing configurations before applying changes.
- Provides robust error handling and detailed logging.

Usage:
    python imcv2_wsl_runner.py -n <InstanceName>

Arguments:
    -n, --name          The name of the WSL instance to create. (Required)
Examples:
    Create a new WSL instance named 'IMCv2Instance' and install default packages:
        python imcv2_wsl_runner.py -n IMCv2Instance

Dependencies:
- Python 3.x
- curl (for downloading resources)
- WSL installed and configured on the Windows system

Notes:
- This script is designed for internal use by the Intel IMCv2 team.
"""

import argparse
import itertools
import os
import re
import subprocess
import sys
import time
import threading
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

# Script defaults, some of which could be override using command arguments
IMCV2_WSL_DEFAULT_BASE_PATH = os.path.join(os.environ["USERPROFILE"], "IMCV2_SDK")
IMCV2_WSL_DEFAULT_INTEL_PROXY = "http://proxy-dmz.intel.com:911"
IMCV2_WSL_DEFAULT_LINUX_IMAGE_PATH = "Bare"
IMCV2_WSL_DEFAULT_SDK_INSTANCES_PATH = "Instances"
IMCV2_WSL_DEFAULT_UBUNTU_URL = ("https://cdimage.ubuntu.com/ubuntu-base/releases/24.04.1/release/"
                                "ubuntu-base-24.04.1-base-amd64.tar.gz")
IMCV2_WSL_DEFAULT_PACKAGES_URL = "https://raw.githubusercontent.com/emichael72/wsl_starter/main/packages.txt"
MCV2_WSL_DEFAULT_PASSWORD = "intel@1234"

# Script version
IMCV2_SCRIPT_NAME = "WSLRunner"
IMCV2_SCRIPT_VERSION = "1.0.0"
IMCV2_SCRIPT_DESCRIPTION = "WSL Host Installer"

# Spinning characters for progress indication
spinner_active = False


class StepError(Exception):
    """
    Custom exception to signal errors during setup steps.

    Usage:
        Raise this exception when a specific setup step fails and requires
        distinct handling compared to generic exceptions.
    """
    pass


class TextType(Enum):
    """
    Enum to specify the type of text display for status messages.

    Attributes:
        PREFIX: Indicates the text should appear before the status (e.g., action name).
        SUFFIX: Indicates the text should appear after the status (e.g., OK, ERROR).
        BOTH:   Combines PREFIX and SUFFIX for full inline messages.

    Usage:
        Use this enum to control the display format of status messages.

    """
    PREFIX = 1
    SUFFIX = 2
    BOTH = 3


def wsl_runner_print_logo():
    """
    Prints the logo with alternating bright white and bright blue colors.
    """
    # ANSI escape codes for colors
    bright_white = "\033[97m"
    bright_blue = "\033[94m"
    reset = "\033[0m"

    lines = [
        "                                                           ", 
        "                    ██╗███╗   ███╗ ██████╗         ██████╗ ",
        "                    ██║████╗ ████║██╔════╝██║   ██║╚════██╗",
        "                    ██║██╔████╔██║██║     ██║   ██║ █████╔╝",
        "                    ██║██║╚██╔╝██║██║     ╚██╗ ██╔╝██╔═══╝ ",
        "                    ██║██║ ╚═╝ ██║╚██████╗ ╚████╔╝ ███████╗",
        "                    ╚═╝╚═╝     ╚═╝ ╚═════╝  ╚═══╝  ╚══════╝",
        "                          ██╗    ██╗███████╗██╗            ",
        "                          ██║    ██║██╔════╝██║            ",
        "                          ██║███╗██║╚════██║██║            ",
        "                          ╚███╔███╔╝███████║███████╗       ",
        "                           ╚══╝╚══╝ ╚══════╝╚══════╝       "
    ]

    # Print each line with alternating colors
    for i, line in enumerate(lines):
        color = bright_white if i % 2 == 0 else bright_blue
        print(f"{color}{line}{reset}")

    
def wsl_runner_show_info():
    """
        Provides detailed information about the steps performed by
        the IMCv2 WSL installer. It outlines the tasks, such as downloading a
        Linux image, setting up a WSL instance, configuring the environment, and
        installing necessary packages for the SDK. The message is formatted to
        be easily readable within an 80-character width terminal.
    """
    
    reset = "\033[0m"
    bold = "\033[1m"
    blue = "\033[34m"
    green = "\033[32m"
    yellow = "\033[33m"
    red = "\033[31m"

    wsl_runner_print_logo()
    
    separator = "=" * 80
    info = f"""

    {bold}{green}1.{reset} Download a basic Ubuntu image version (e.g., ubuntu-base-24.04.1),
       known to work with WSL.
    {bold}{green}2.{reset} Create a new WSL Linux instance and import the Linux image into it.
    {bold}{green}3.{reset} Configure the instance with a user account, sudo privileges, and
       environment settings.
    {bold}{green}4.{reset} Apply additional configurations such as time zone, proxy, and console
       defaults, making the process seamless.
    {bold}{green}5.{reset} Install essential packages required later by the SDK.

    {bold}Lastly,{reset} the installer will create a desktop shortcut named {yellow}"IMCv2 SDK"{reset},
    pointing to the new WSL instance.

    {bold}{red}NOTE:{reset} This prerequisites installation section may take some time to complete
    and will use about 4GB of disk space. Please keep your PC connected to Intel
    throughout the process.
    """
    print(info)


def wsl_runner_get_desktop_path() -> str:
    """
    Retrieves the desktop path for the current user dynamically using PowerShell.

    Returns:
        str: The path to the desktop directory.

    Raises:
        FileNotFoundError: If the desktop path cannot be retrieved.
    """
    try:
        # Use PowerShell to fetch the desktop path
        command = [
            "powershell",
            "-Command",
            "[Environment]::GetFolderPath('Desktop')"
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)

        desktop_path = result.stdout.strip()
        if not os.path.exists(desktop_path):
            raise FileNotFoundError(f"Desktop path does not exist: {desktop_path}")
        return desktop_path
    except Exception as e:
        raise FileNotFoundError(f"Failed to retrieve desktop path: {e}")


def wsl_runner_spinner_thread():
    """
    Display a spinning progress indicator in the terminal.
    """
    global spinner_active
    bright_blue = "\033[94m"
    reset = "\033[0m"
    spinner_cycle = itertools.cycle(["|", "/", "-", "\\"])

    while spinner_active:
        sys.stdout.write(f"{bright_blue}{next(spinner_cycle)}{reset}")  # Print the next character
        sys.stdout.flush()
        sys.stdout.write("\b")  # Erase the character
        time.sleep(0.1)


def wsl_runner_set_spinner(state):
    """
    Manage the progress spinner thread.
    Args:
        state (bool): True to start the spinner, False to stop.
    """
    global spinner_active
    if state:
        spinner_active = True
        progress_thread = threading.Thread(target=wsl_runner_spinner_thread, daemon=True)
        progress_thread.start()
        return progress_thread
    else:
        spinner_active = False
        time.sleep(0.1)
        sys.stdout.write("\b")
        sys.stdout.flush()


def wsl_runner_ensure_directory_exists(args: list) -> int:
    """
    Simulates a command that ensures directories exist.

    Args:
        args (list): List of directory paths to check and create if necessary.

    Returns:
        int: 0 if all directories exist or are created successfully, 1 on failure.
    """
    try:
        for path in args:
            if not os.path.exists(path):
                os.makedirs(path)
        return 0  # Success
    except Exception as e:
        print(f"Error ensuring directory exists: {e}", file=sys.stderr)
        return 1  # Failure


def wsl_runner_download_resources(url, destination_path, proxy_server, timeout=30):
    """
    Downloads a file from the specified URL using curl, with optional proxy configuration.
    The downloaded file is saved to the specified destination path.

    Args:
        url (str): The URL of the resource to download.
        destination_path (str): The path where the downloaded file should be saved.
        proxy_server (str): The proxy server to use for the download.
        timeout (int, optional): The time in seconds to wait before the request times out. Default is 30 seconds.

    Returns:
        bool: True if the download succeeded (status code 200), False otherwise.
    """
    # Parse the URL and get the file name from the URL path
    parsed_url = urlparse(url)
    destination = os.path.join(destination_path, os.path.basename(parsed_url.path))

    # Set up curl arguments
    args = [
        "-s", "-S", "-w", "%{http_code}",  # silent mode, show errors, output HTTP status code
        "--proxy", proxy_server,  # Use specified proxy server
        "--output", destination,  # Specify the output file destination
        url  # URL of the resource to download
    ]

    # Execute the curl command and capture the output
    status_code, response_code = wsl_runner_exec_process("curl", args, hidden=True, timeout=timeout)

    # Check if the download was successful by verifying the HTTP status code
    if status_code == 0:
        if response_code == 200:
            return 0

    # If any check fails, return False
    return 1


def wsl_runner_console_decoder(input_string: str) -> str:
    """
    Decodes a console output string, attempting multiple encoding strategies and removing non-printable characters.

    Args:
        input_string (str): The string to decode and sanitize.

    Returns:
        str: The decoded and sanitized string with printable ASCII characters. If decoding fails,
        returns an empty string.
    """
    if not input_string:
        return ""

    try:
        # Attempt UTF-8 decoding
        decoded = input_string.encode('latin1').decode('utf-8', errors='replace')
        decoded = re.sub(r'[^\x20-\x7E]+', '', decoded)  # Keep printable ASCII characters
        if decoded:
            return decoded + "\n"

        # Fallback to UTF-16 LE decoding
        decoded = input_string.encode('latin1').decode('utf-16-le', errors='replace')
        decoded = re.sub(r'[^\x20-\x7E]+', '', decoded)
        if decoded:
            return decoded + "\n"

    except (UnicodeDecodeError, AttributeError):
        # Catch decoding errors or invalid input type
        pass

    # Return an empty string if all decoding attempts fail
    return ""


def wsl_runner_exec_process(process: str, args: list, hidden: bool = True, timeout: int = 30) -> tuple:
    """
    Executes an external process with the given arguments and streams its output in real-time.

    Args:
        process (str): The executable or command to run.
        args (list): List of arguments for the command.
        hidden (bool): If True, suppresses the output.
        timeout (int): Time in seconds to wait for the command to complete.

    Returns:
        tuple:
            - int: The exit status code of the process.
            - int: An extended status code (e.g., HTTP status for `curl`, or 0 otherwise).

    Raises:
        ValueError: If the process or arguments are invalid.
    """
    cmd = [process] + args
    ext_status = 0

    try:
        with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=4096,
                universal_newlines=True
        ) as proc:
            try:
                printed_lines = 0

                # Process stdout
                for line in proc.stdout:
                    if process == "curl" and printed_lines == 0:
                        try:
                            ext_status = int(line.strip())  # Extract HTTP status for `curl`
                        except ValueError:
                            ext_status = 0  # Handle non-integer first lines gracefully
                    if not hidden:
                        print(wsl_runner_console_decoder(line), end="")
                    printed_lines += 1

                # Process stderr
                for line in proc.stderr:
                    if not hidden:
                        print(wsl_runner_console_decoder(line), end="")

                # Wait for the process to complete and return codes
                return proc.wait(timeout=timeout), ext_status

            except subprocess.TimeoutExpired:
                proc.kill()  # Kill the process on timeout
                return 124, ext_status  # Return timeout-specific exit code

    except FileNotFoundError as file_error:
        # Handle missing executable
        print(f"Error: Command not found: {process} ({file_error})", file=sys.stderr)
        return 127, 0

    except ValueError as value_error:
        # Handle invalid arguments
        print(f"Error: Invalid command arguments: {value_error}", file=sys.stderr)
        return 1, 0

    except Exception as general_error:
        # Handle unexpected errors gracefully
        print(f"Unexpected error while executing '{process}': {general_error}", file=sys.stderr)
        return 1, 0


def wsl_runner_print_status(
        text_type: TextType,
        description: Optional[str],
        new_line: bool = False,
        return_value: int = 0
):
    """
    Prints the status message to the console in a formatted manner with color codes.

    Args:
        text_type (TextType): PREFIX, SUFFIX, or BOTH.
        description (str, None): The message to display. If None, it defaults to an empty string.
        new_line (bool): If True, prints a new line after the status; otherwise overwrites the same line.
        return_value (int): The status code to display. 0 = OK, 124 = TIMEOUT, others = ERROR.
    """

    if text_type not in TextType:
        return

    # ANSI color codes
    green = "\033[32m"
    red = "\033[31m"
    bright_blue = "\033[94m"
    reset = "\033[0m"

    max_length = 60

    # Handle PREFIX or BOTH types
    if text_type in {TextType.BOTH, TextType.PREFIX} and description:
        # Adjust the number of dots for the alignment
        dots_count = max_length - len(description) - 2
        dots = "." * dots_count
        # Print the description with one space before and after the dots
        sys.stdout.write(f"\r    \033[K{description} {dots} ")
        sys.stdout.flush()

        # Show spinner
        wsl_runner_set_spinner(True)

    # Handle SUFFIX or BOTH types
    if text_type in {TextType.BOTH, TextType.SUFFIX}:

        # Stop spinner
        wsl_runner_set_spinner(False)

        if return_value == 0:
            pass
        elif return_value == 1000:  # Special code for step completed.
            sys.stdout.write(f"{green}OK{reset}")
        else:
            if return_value == 124:
                sys.stdout.write(f"{bright_blue}Timeout{reset}")
            else:
                sys.stdout.write(f"{red}Error({return_value}){reset}")

        sys.stdout.flush()
        time.sleep(0.3)  # Small delay for visual clarity

    # Handle newline printing or overwriting the same line
    if new_line:
        sys.stdout.write("\n")
        sys.stdout.flush()


def ws_runner_run_function(description: str, process, args: list,
                           ignore_errors: bool = False, new_line: bool = False):
    """
    Execute a process or a Python function and display a description with dots and OK/ERROR status.

    Args:
        description (str): Description of the step.
        process (str or callable): The name of the function to run or the executable/command.
        args (list): List of arguments for the function or command.
        ignore_errors (bool): Ignore step error and return OK.
        new_line (bool): If True, prints OK/ERROR on a new line; if False, overwrites the previous line.
    """
    # Prepare the dots

    wsl_runner_print_status(TextType.PREFIX, description, new_line)

    try:
        if callable(process):  # Check if process is a callable Python function
            status = process(*args)  # Call the Python function with arguments
        else:
            raise ValueError(f"Invalid process type: {type(process)}. Must be callable or a string.")
    except Exception as general_error:
        # If any exception is raised during the Python function or external command execution
        print(f"Error executing {description}: {general_error}")
        status = 1  # Indicate failure

    # Ignore errors if specified
    if ignore_errors:
        status = 0

    wsl_runner_print_status(TextType.SUFFIX, None, new_line, status)
    return status


def wsl_runner_run_process(description: str, process: str, args: list, hidden: bool = True, timeout: int = 30,
                           ignore_errors: bool = False, new_line: bool = False):
    """
    Run a process and display a description with dots and OK/ERROR status.

    Args:
        description (str): Description of the step.
        process (str): The executable or command to run.
        args (list): List of arguments for the command.
        hidden (bool): If True, suppress output.
        timeout (int): Time in seconds to wait for the command to complete.
        ignore_errors (bool): Ignore step error and return OK
        new_line (bool): If True, prints OK/ERROR on a new line; if False, overwrites the previous line.
    """

    wsl_runner_print_status(TextType.PREFIX, description, new_line)

    # Execute the function or process
    status, ext_status = wsl_runner_exec_process(process, args, hidden, timeout)

    # Ignore errors id set to do so
    if ignore_errors:
        status = 0

    # When the command is 'curl' the extended status is the HTTP code
    if process == "curl" and ext_status != 200:
        status = ext_status

    wsl_runner_print_status(TextType.SUFFIX, None, new_line, status)
    return status


def wsl_runner_win_to_wsl_path(windows_path):
    """
    Convert a Windows path to its corresponding WSL path.

    Args:
        windows_path (str): The path in Windows format (e.g., "C:\\Users\\YourUser\\file.txt").

    Returns:
        str: The corresponding WSL path (e.g., "/mnt/c/Users/YourUser/file.txt").
    """
    # Replace backslashes with forward slashes and prepend '/mnt/c/' to the Windows path
    wsl_path = windows_path.replace("\\", "/")
    if wsl_path[1] == ":":
        wsl_path = "/mnt" + "/" + wsl_path[0].lower() + wsl_path[2:]
    return wsl_path


def wsl_runner_create_shortcut(instance_name: str, shortcut_name: str) -> int:
    """
    Creates or replaces a desktop shortcut to launch a WSL instance.

    Args:
        instance_name (str): The name of the WSL instance.
        shortcut_name (str): The name for the desktop shortcut.

    Returns:
        int: 0 if the shortcut is created successfully, 1 otherwise.
    """
    try:
        # Get the desktop path programmatically
        desktop_dir = wsl_runner_get_desktop_path()
        shortcut_path = os.path.join(desktop_dir, f"{shortcut_name}.lnk")

        # Remove existing shortcut if it exists
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)

         # Define the command to launch the WSL instance
        target = "C:\\Windows\\System32\\wsl.exe"  # Path to wsl.exe
        arguments = f"-d {instance_name}"  # Arguments for the WSL instance

        # Create the shortcut using Windows' built-in 'powershell'
        shortcut_script = f"""
        $WScriptShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WScriptShell.CreateShortcut('{shortcut_path}')
        $Shortcut.TargetPath = '{target}'
        $Shortcut.Arguments = '{arguments}'
        $Shortcut.IconLocation = '{target},0'
        $Shortcut.Save()
        """

        # Execute the PowerShell script
        process = subprocess.run(["powershell", "-Command", shortcut_script],
                                 capture_output=True, text=True)

        # Check for success
        if process.returncode == 0:
            return 0
        else:
            return 1

    except Exception as e:
        print(f"An exception occurred: {e}", file=sys.stderr)
        return 1


def run_post_install_steps(instance_name: str, hidden: bool = True, new_line: bool = False):
    """
    Configures the WSL instance post-installation by setting it as the default instance.

    Args:
        instance_name (str): Name of the WSL instance to set as the default.
        hidden (bool): If True, suppresses command output during execution.
        new_line (bool): If True, displays status messages on a new line.

    Raises:
        StepError: If the step fails to execute successfully.
    """
    steps_commands = [
        # Set the WSL instance as the default
        ("Setting the WSL instance as the default",
         "wsl", ["--set-default", instance_name])
    ]

    # Execute the command and handle errors
    for description, process, args, *ignore_errors in steps_commands:
        ignore_errors = ignore_errors[0] if ignore_errors else False
        if wsl_runner_run_process(description, process, args, hidden=hidden, new_line=new_line,
                                  ignore_errors=ignore_errors) != 0:
            raise StepError(f"Failed during step: {description}")

    # Print success message
    wsl_runner_print_status(TextType.BOTH, "WSL post-installation steps completed", True, 1000)


def run_install_pyenv(instance_name, username, proxy_server, hidden=True, new_line=False):
    """
    Use 'pyenv' to install specific Python 3.9 and set it ass default Python runtime.

    Args:
        instance_name (str): The name of the WSL instance.
        username: (str): WSL username
        proxy_server (str): HTTP/HTTPS proxy server address to set in .bashrc.
        hidden (bool): Specifies whether to suppress the output of the executed command.
        new_line (bool): Specifies whether each step should be displayed on its own line.
    """

    # Define commands related to package installation
    steps_commands = [

        # Step 1: Download pyenv installer
        ("Download 'pyenv' installer",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"curl -s -S -x {proxy_server} -L "
                 f"https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer "
                 f"-o /home/{username}/downloads/pyenv-installer"]),

        # Step 2: Make the installer executable
        ("Make 'pyenv' installer executable",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"chmod +x /home/{username}/downloads/pyenv-installer"]),

        # Step 3: Clean up any previous pyenv installation
        ("Clean up any previous 'pyenv' installation",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"rm -rf /home/{username}/.pyenv"]),

        # Step 4: Run pyenv installer with proxy settings
        ("Run 'pyenv' installer with proxy settings",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"export http_proxy={proxy_server} && export https_proxy={proxy_server} && "
                 f"/home/{username}/downloads/pyenv-installer"]),

        # Step 5: Check for errors during installation
        ("Verify 'pyenv' installation success",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "if [ $? -ne 0 ]; then echo 'Failed to install pyenv'; exit 1; fi"]),

        # Restarting session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name]),

        # Add Pyenv setup to .bashrc using cat <<EOF
        ("Add Pyenv setup to .bashrc",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"cat <<'EOF' >> /home/{username}/.bashrc\n"
                 f"# Pyenv setup\n"
                 f"export PYENV_ROOT=\"\\$HOME/.pyenv\"\n"
                 f"[ -d \"\\$PYENV_ROOT/bin\" ] && export PATH=\"\\$PYENV_ROOT/bin:\\$PATH\"\n"
                 f"eval \"\\$(pyenv init --path)\"\n"
                 f"EOF"]),

        # Restarting session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name]),

        # Install Python 3.9.0 using pyenv with forced re-installation
        ("Install Python 3.9.0 using 'pyenv'",
         "wsl", ["-d", instance_name, "--user", username, "--", "bash", "-c",
                 f"export http_proxy={proxy_server} && "
                 f"export https_proxy={proxy_server} && "
                 f"$HOME/.pyenv/bin/pyenv install 3.9.0 -f"]),

        # Set Python 3.9.0 as the global default version
        ("Set Python 3.9.0 as the global default version",
         "wsl", ["-d", instance_name, "--user", username, "--", "bash", "-c",
                 "$HOME/.pyenv/bin/pyenv global 3.9.0"]),

        # Restarting session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name]),

    ]

    # Execute each command in the steps commands list
    for description, process, args, *ignore_errors in steps_commands:
        # If ignore_errors is not specified, default it to False
        ignore_errors = ignore_errors[0] if ignore_errors else False
        if wsl_runner_run_process(description, process, args, hidden=hidden, new_line=new_line,
                                  ignore_errors=ignore_errors) != 0:
            raise StepError("Failed to complete step")

    wsl_runner_print_status(TextType.BOTH, "Python 3.9 via 'pyenv' installation", True, 1000)


def run_install_user_packages(instance_name, username, proxy_server, hidden=True, new_line=False):
    """
     Instance various Intel specific user packages , for example 'dt'.

    Args:
        instance_name (str): The name of the WSL instance.
        username: (str): WSL username
        proxy_server (str): HTTP/HTTPS proxy server address to set in .bashrc.
        hidden (bool): Specifies whether to suppress the output of the executed command.
        new_line (bool): Specifies whether each step should be displayed on its own line.
    """

    # Define commands related to package installation
    steps_commands = [
        # Ensure the target directory exists
        ("Creating target directory for Git completion scripts",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"sudo mkdir -p /usr/share/git-core/contrib/completion && sudo chown {username}:{username} "
                 f"/usr/share/git-core/contrib/completion"]),

        # Download git-completion.bash using curl
        ("Downloading git-completion.bash via proxy",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"curl -s -S --proxy {proxy_server} -o /usr/share/git-core/contrib/completion/git-completion.bash "
                 "https://raw.githubusercontent.com/git/git/master/contrib/completion/git-completion.bash"]),

        # Download git-prompt.sh using curl
        ("Downloading git-prompt.sh via proxy",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"curl -s -S --proxy {proxy_server} -o /usr/share/git-core/contrib/completion/git-prompt.sh "
                 "https://raw.githubusercontent.com/git/git/master/contrib/completion/git-prompt.sh"]),

        # Set a proper colored Git-aware prompt in .bashrc
        ("Add Git prompt source to .bashrc",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo 'source /usr/share/git-core/contrib/completion/git-prompt.sh' >> /home/{username}/.bashrc"]),

        # Step 2: Set Git-aware PS1 prompt in .bashrc
        ("Set Git-aware PS1 prompt in .bashrc",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"cat << 'EOF' >> /home/{username}/.bashrc\n"
                 f"# Git-aware PS1 prompt \n"
                 f"export PS1='\\[\\e[1;32m\\]\\u \\[\\e[1;34m\\]\\w\\[\\e[1;31m\\]"
                 f"\\$(__git_ps1 \" (%s)\") \\[\\e[0m\\]> '\n"
                 f"EOF"]),

        # Download 'dt' file
        (f"Downloading 'dt' to /home/{username}/downloads",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"curl -s -S --noproxy '*' -k -L "
                 f"https://gfx-assets.intel.com/artifactory/gfx-build-assets/build-tools/devtool-go/"
                 f"latest/artifacts/linux64/dt "
                 f"-o /home/{username}/downloads/dt"]),

        # Make the 'dt' file executable
        ("Making 'dt' executable",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"chmod +x /home/{username}/downloads/dt"]),

        # Execute 'dt' for installation
        ("Executing 'dt' for installation",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"/home/{username}/downloads/dt install"]),

        # Restarting session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name]),

    ]

    # Execute each command in the steps commands list
    for description, process, args, *ignore_errors in steps_commands:
        # If ignore_errors is not specified, default it to False
        ignore_errors = ignore_errors[0] if ignore_errors else False
        if wsl_runner_run_process(description, process, args, hidden=hidden, new_line=new_line,
                                  ignore_errors=ignore_errors) != 0:
            raise StepError("Failed to complete step")

    wsl_runner_print_status(TextType.BOTH, "User package installation", True, 1000)


def run_install_system_packages(instance_name, username, packages_file, hidden=True, new_line=False, timeout=120):
    """
    Transfers a packages file to the WSL instance and installs the packages listed in the file.

    Args:
        instance_name (str): The name of the WSL instance.
        username: (str): WSL username
        packages_file (str): Path to the file containing the list of packages to install.
        hidden (bool): Specifies whether to suppress the output of the executed command.
        new_line (bool): Specifies whether each step should be displayed on its own line.
        timeout (int, optional): Time in seconds to wait for the process to complete. Default is 120 seconds.
    """

    # Count lines (packages) within  the input file
    with open(packages_file, 'r') as file:
        line_count = sum(1 for _ in file)

    if line_count == 0:
        wsl_runner_print_status(TextType.BOTH, "Empty packages file", True, 1000)
        return 0

    wsl_windows_packages_file = wsl_runner_win_to_wsl_path(packages_file)
    wsl_instance_packages_file = f"/home/{username}/downloads/packages.txt"

    # Define commands related to package installation
    steps_commands = [
        # Transferring the packages file to the WSL instance
        ("Transferring packages to WSL instance",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"cp -f {wsl_windows_packages_file} {wsl_instance_packages_file}"]),

        # Clearing local apt cache
        ("Clearing local apt cache",
         "wsl", ["-d", instance_name, "--", "bash", "-c", "sudo apt clean"]),

        # Restarting session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name]),

        # Installing packages from file (ignore errors on first attempt)
        (f"Installing {line_count} packages from {os.path.basename(wsl_instance_packages_file)}",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"xargs -a {wsl_instance_packages_file} -r sudo apt install -y --ignore-missing -qq"], True),

        # Installing packages from file (retry without ignoring errors)
        ("Installing packages from file second round",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"xargs -a {wsl_instance_packages_file} -r sudo apt install -y --ignore-missing -qq"]),

        # Restarting session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name]),

        # Clearing local apt cache
        ("Final packages sync",
         "wsl", ["-d", instance_name, "--", "bash", "-c", "sudo apt update && sudo apt upgrade && sudo apt clean"]),

        # Restarting session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name]),
    ]

    # Execute each command in the steps commands list
    for description, process, args, *ignore_errors in steps_commands:
        # If ignore_errors is not specified, default it to False
        ignore_errors = ignore_errors[0] if ignore_errors else False
        if wsl_runner_run_process(description, process, args, hidden=hidden, new_line=new_line,
                                  timeout=timeout, ignore_errors=ignore_errors) != 0:
            raise StepError("Failed to complete step")

    wsl_runner_print_status(TextType.BOTH, "Ubuntu system package installation", True, 1000)


def run_user_shell_steps(instance_name: str, username: str, proxy_server: str, hidden: bool = True,
                         new_line: bool = False):
    """
    Configures the user's shell environment in a WSL instance.

    Args:
        instance_name (str): Name of the WSL instance to configure.
        username (str): The username for whom the environment is being configured.
        proxy_server (str): HTTP/HTTPS proxy server address to set in .bashrc.
        hidden (bool): If True, suppresses command output during execution.
        new_line (bool): If True, displays status messages on a new line.

    Raises:
        StepError: If any step in the process fails.
    """
    # Define the steps to configure the shell environment
    steps_commands = [
        # Set HTTP Proxy in .bashrc
        (f"Setting HTTP Proxy ({proxy_server})",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"grep -q 'export http_proxy=' /home/{username}/.bashrc || "
                 f"echo 'export http_proxy={proxy_server}' >> /home/{username}/.bashrc"]),

        # Set HTTPS Proxy in .bashrc
        (f"Setting HTTPS Proxy ({proxy_server})",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"grep -q 'export https_proxy=' /home/{username}/.bashrc || "
                 f"echo 'export https_proxy={proxy_server}' >> /home/{username}/.bashrc"]),

        # Create ~/downloads directory
        ("Create ~/downloads directory",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"mkdir -p /home/{username}/downloads && sudo chown {username}:{username}"
                 f" /home/{username}/downloads"]),

        # Create ~/projects directory
        ("Create ~/projects directory",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"mkdir -p /home/{username}/projects && sudo chown {username}:{username}"
                 f" /home/{username}/projects"]),

        # Create .hushlogin in the user's home directory
        ("Create .hushlogin in the user's home directory",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"touch /home/{username}/.hushlogin && sudo chown {username}:{username}"
                 f" /home/{username}/.hushlogin"]),

        # Restart session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name])
    ]

    # Execute each command and handle errors
    for description, process, args, *ignore_errors in steps_commands:
        ignore_errors = ignore_errors[0] if ignore_errors else False
        if wsl_runner_run_process(description, process, args, hidden=hidden, new_line=new_line,
                                  ignore_errors=ignore_errors) != 0:
            raise StepError(f"Failed during step: {description}")

    # Print success message
    wsl_runner_print_status(TextType.BOTH, "Setting user shell defaults", True, 1000)


def run_kerberos_steps(instance_name: str, hidden: bool = True, new_line: bool = False):
    """
    Configures Kerberos authentication for a WSL instance.

    Args:
        instance_name (str): Name of the WSL instance to configure.
        hidden (bool): If True, suppresses command output during execution.
        new_line (bool): If True, displays status messages on a new line.

    Raises:
        StepError: If any step in the process fails.
    """
    # Define the steps for configuring Kerberos
    steps_commands = [
        # Setting Kerberos defaults
        ("Setting Kerberos defaults",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "grep -q 'krb5-config/default_realm' /var/cache/debconf/config.dat || "
                 "echo 'krb5-config krb5-config/default_realm string CLIENTS.INTEL.COM' "
                 "| sudo debconf-set-selections"]),

        # Pre-seed Kerberos server hostnames
        ("Pre-seed Kerberos server hostnames",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "grep -q 'krb5-config/kerberos_servers' /var/cache/debconf/config.dat || "
                 "echo 'krb5-config krb5-config/kerberos_servers string kdc1.clients.intel.com kdc2.clients.intel.com' "
                 "| sudo debconf-set-selections"]),

        # Pre-seed Kerberos administrative server
        ("Pre-seed Kerberos administrative server",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "grep -q 'krb5-config/admin_server' /var/cache/debconf/config.dat || "
                 "echo 'krb5-config krb5-config/admin_server string admin.clients.intel.com' "
                 "| sudo debconf-set-selections"]),

        # Install Kerberos packages non-interactively
        ("Install Kerberos packages non-interactively",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "export DEBIAN_FRONTEND=noninteractive && "
                 "dpkg -l | grep -q krb5-config || sudo apt install -y krb5-config krb5-user"]),

        # Restart session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name])
    ]

    # Execute each command in the steps list
    for description, process, args, *ignore_errors in steps_commands:
        ignore_errors = ignore_errors[0] if ignore_errors else False
        if wsl_runner_run_process(description, process, args, hidden=hidden, new_line=new_line,
                                  ignore_errors=ignore_errors) != 0:
            raise StepError(f"Failed during step: {description}")



def run_time_zone_steps(instance_name, hidden=True, new_line=False):
    """
    Configures timezone and console settings for a specified WSL instance.

    This function automates a series of steps to:
    1. Pre-seed timezone data (tzdata) for the Israel timezone in the WSL instance.
    2. Set the system timezone to Asia/Jerusalem.
    3. Ensure the `tzdata` package is installed.
    4. Reconfigure `tzdata` non-interactively.
    5. Configure the console to use Hebrew character sets and fonts.
    6. Install the `console-setup` package in a non-interactive mode.
    7. Restart the WSL session to apply changes.

    Parameters:
        instance_name (str): The name of the WSL instance to configure.
        hidden (bool, optional): Whether to hide the command output. Default is True.
        new_line (bool, optional): Whether to add a new line after each step's output. Default is False.
    """
    
    steps_commands = [
        # Pre-seed tzdata configuration for Israel timezone
        ("Pre-seed tzdata for Israel Area",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'tzdata tzdata/Areas select Asia' | sudo debconf-set-selections"]),

        ("Pre-seed tzdata for Israel",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'tzdata tzdata/Zones/Asia select Jerusalem' | sudo debconf-set-selections"]),

        # Set timezone in WSL instance
        ("Set timezone in WSL instance",
         "wsl",
         ["-d", instance_name, "--", "bash", "-c", "sudo ln -fs /usr/share/zoneinfo/Asia/Jerusalem /etc/localtime"]),

        # Check and install tzdata if not installed
        ("Ensure tzdata package is installed",
         "wsl", ["-d", instance_name, "--", "bash", "-c", "dpkg -l | grep tzdata || sudo apt-get install -y tzdata"]),

        # Reconfigure tzdata
        ("Reconfigure tzdata",
         "wsl", ["-d", instance_name, "--", "bash", "-c", "sudo dpkg-reconfigure -f noninteractive tzdata"]),

        # Pre-seed console-setup for Hebrew character set
        ("Pre-seed console Hebrew character set",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'console-setup console-setup/charmap47 select UTF-8' | sudo debconf-set-selections"]),

        ("Pre-seed console Hebrew character",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'console-setup console-setup/codeset47 select Hebrew' | sudo debconf-set-selections"]),

        ("Pre-seed console Hebrew character Fixed font",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'console-setup console-setup/fontface47 select Fixed' | sudo debconf-set-selections"]),

        ("Pre-seed console Hebrew character Font size",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'console-setup console-setup/fontsize-text47 select 16' | sudo debconf-set-selections"]),

        # Install console-setup in non-interactive mode
        ("Install console-setup in non-interactive mode",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "export DEBIAN_FRONTEND=noninteractive && sudo apt install -y console-setup"]),

        # Restart session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name])
    ]

    # Execute each command in the steps commands list
    for description, process, args, *ignore_errors in steps_commands:
        # If ignore_errors is not specified, default it to False
        ignore_errors = ignore_errors[0] if ignore_errors else False
        if wsl_runner_run_process(description, process, args, hidden=hidden, new_line=new_line,
                                  ignore_errors=ignore_errors) != 0:
            raise StepError("Failed to complete step")



def run_user_creation_steps(instance_name: str, username: str, password: str, hidden: bool = True,
                            new_line: bool = False):
    """
    Creates a user in the specified WSL instance and configures their environment.

    Args:
        instance_name (str): Name of the WSL instance.
        username (str): The username to create in the WSL instance.
        password (str): The password for the new user.
        hidden (bool): If True, suppresses command output during execution.
        new_line (bool): If True, displays status messages on a new line.

    Raises:
        StepError: If any step in the process fails.
    """
    # Define the steps to create and configure the user
    steps_commands = [
        # Install required packages (sudo, passwd)
        ("Installing required packages (sudo, passwd)",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "dpkg -l | grep -q sudo || apt install -y sudo passwd"]),

        # Add 'sudo' group if it doesn't exist
        ("Adding 'sudo' group if it doesn't exist",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "if ! grep -q '^sudo:' /etc/group; then groupadd sudo; fi"]),

        # Create the user if it doesn't exist
        (f"Creating user '{username}' if it doesn't exist",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"id -u {username} &>/dev/null || useradd -m -s /bin/bash {username}"]),

        # Set password for the user
        (f"Setting password for user '{username}'",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo '{username}:{password}' | chpasswd"]),

        # Add user to the 'sudo' group
        (f"Adding user '{username}' to sudo group",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"usermod -aG sudo {username}"]),

        # Add user to sudoers with NOPASSWD
        (f"Granting NOPASSWD sudo access to '{username}'",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo '{username} ALL=(ALL) NOPASSWD:ALL' | sudo tee -a /etc/sudoers"]),

        # Start a clear IMCv2 section in the user's .bashrc
        (f"Adding IMCv2 section to '{username}' .bashrc",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo -e '\\n# -- IMCv2 WSL initialization script --\\n' >> /home/{username}/.bashrc"]),

        # Ensure the user starts in their home directory
        (f"Setting '{username}' to start in their home directory",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo 'cd /home/{username}' >> /home/{username}/.bashrc"]),

        # Add essential aliases
        ("Adding essential aliases to .bashrc",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo -e '\\nalias shutdown=\"wsl.exe --terminate \\$WSL_DISTRO_NAME\"'"
                 f" >> /home/{username}/.bashrc && "
                 f"echo -e 'alias reboot=\"wt.exe --profile \\\"Ubuntu\\\" && wsl.exe --terminate"
                 f" \\$WSL_DISTRO_NAME && wsl.exe\"' >> /home/{username}/.bashrc && "
                 f"echo -e 'alias start=\"explorer.exe .\"' >> /home/{username}/.bashrc"]),

        # Add custom greeting message to .bashrc
        ("Adding custom greeting message to .bashrc",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"cat << 'EOF' >> /home/{username}/.bashrc\n"
                 f"clear\n"
                 f"printf \"Welcome to IMCv2️ SDK for WSL2.\\n\"\n"
                 f"printf \"IMCv2 Team 2024.\\n\\n\"\n"
                 f"EOF"]),

        # Set user section in /etc/wsl.conf
        ("Setting default user in /etc/wsl.conf",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo '[user]' > /etc/wsl.conf && echo 'default={username}' >> /etc/wsl.conf"]),

        # Restart session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name])
    ]

    # Execute each command and handle errors
    for description, process, args, *ignore_errors in steps_commands:
        ignore_errors = ignore_errors[0] if ignore_errors else False
        if wsl_runner_run_process(description, process, args, hidden=hidden, new_line=new_line,
                                  ignore_errors=ignore_errors) != 0:
            raise StepError(f"Failed during step: {description}")

    # Print success message
    wsl_runner_print_status(TextType.BOTH, "Creating user account", True, 1000)


def run_initial_setup_steps(instance_name: str, instance_path: str, bare_linux_image_path: str,
                            hidden: bool = True, new_line: bool = False):
    """
    Prepares the initial setup for a WSL instance by importing a Linux image and configuring the environment.

    Args:
        instance_name (str): Name of the WSL instance to create or reset.
        instance_path (str): Path to the directory where the WSL instance will be stored.
        bare_linux_image_path (str): Path to the Linux image to be imported into the WSL instance.
        hidden (bool): If True, suppresses command output during execution.
        new_line (bool): If True, displays status messages on a new line.

    Raises:
        StepError: If any step in the process fails.
    """
    steps_commands = [
        # Terminate the instance if it already exists
        ("Terminating existing instance (if any)",
         "wsl", ["--terminate", instance_name], True),

        # Unregister the instance if it exists
        ("Unregistering existing instance (if any)",
         "wsl", ["--unregister", instance_name], True),

        # Import the Linux image as a new WSL instance
        ("Importing Linux image as a new WSL instance",
         "wsl", ["--import", instance_name, os.path.join(instance_path, instance_name), bare_linux_image_path]),

        # Update the APT package lists
        ("Updating APT package lists",
         "wsl", ["-d", instance_name, "--", "bash", "-c", "apt update -qq"]),

        # List upgradable packages
        ("Listing upgradable packages",
         "wsl", ["-d", instance_name, "--", "bash", "-c", "apt list --upgradable -qq"]),

        # Restart the session to apply changes
        ("Restarting session to apply changes",
         "wsl", ["--terminate", instance_name])
    ]

    # Execute each command and handle errors
    for description, process, args, *ignore_errors in steps_commands:
        ignore_errors = ignore_errors[0] if ignore_errors else False
        if wsl_runner_run_process(description, process, args, hidden=hidden, new_line=new_line,
                                  ignore_errors=ignore_errors) != 0:
            raise StepError(f"Failed during step: {description}")

    # Print success message
    wsl_runner_print_status(TextType.BOTH, "WSL environment startup completed", True, 1000)


def run_pre_prerequisites_steps(base_path: str, instance_path: str, bare_linux_image_path: str,
                                ubuntu_url: str, proxy_server: str, new_line: bool = False):
    """
    Prepares the environment by verifying directories and downloading necessary resources.

    Args:
        base_path (str): Base directory where resources will be stored.
        instance_path (str): Directory path for WSL instance data.
        bare_linux_image_path (str): Directory path for the Ubuntu Linux image.
        ubuntu_url (str): URL to download the Ubuntu image.
        proxy_server (str): Proxy server address to use for downloads.
        new_line (bool): If True, displays status messages on a new line.

    Raises:
        StepError: If any step in the process fails.
    """
    steps_commands = [
        # Ensure necessary directories exist
        ("Verifying destination paths", wsl_runner_ensure_directory_exists,
         [(bare_linux_image_path, instance_path)]),

        # Download the packages list
        ("Downloading Packages list", wsl_runner_download_resources,
         [IMCV2_WSL_DEFAULT_PACKAGES_URL, base_path, proxy_server]),

        # Download Ubuntu bare Linux image
        ("Downloading Ubuntu image", wsl_runner_download_resources,
         [ubuntu_url, bare_linux_image_path, proxy_server])
    ]

    # Execute each command and handle errors
    for description, func, args in steps_commands:
        # Execute the function with the provided arguments
        if ws_runner_run_function(description, func, args, new_line=new_line) != 0:
            raise StepError(f"Failed during step: {description}")

    # Print success message
    wsl_runner_print_status(TextType.BOTH, "Prerequisites satisfied", True, 1000)


def wsl_runner_check_installed():
    """
    Checks if WSL2 is installed on Windows.
    If not, returns 1 and instructs the user on how to install it.
    """
    wsl_version_unknown = False

    try:
        # Run `wsl --version` to check for WSL2
        result = subprocess.run(["wsl", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            result_text = wsl_runner_console_decoder(result.stdout)
            if "Kernel version" in result_text:
                return 0  # WSL2 is installed
            else:
                wsl_version_unknown = True

    except FileNotFoundError:
        pass

    print("IMCv2 SDK for Windows Subsystem for Linux.")
    # Provide feedback based on findings
    if wsl_version_unknown:
        print("Please note, WSL is installed but might not be WSL2. Please verify your version.")
    else:
        print("Please note, WSL2 is not installed.")

    # Install help message
    print("\nWSL2 is an essential component, to install WSL2, follow these steps:")
    print("1. Open PowerShell as Administrator.")
    print("2. Run the following command: wsl --install")
    print("   This will install WSL and set up WSL2 as the default version.")
    print("3. Reboot your computer if prompted.")
    print("4. After rebooting, continue this installer.")

    return 1  # WSL2 is not installed or not confirmed


def wsl_runner_main() -> int:
    """
    Main entry point for the IMCV2 WSL Runner script.

    Parses command-line arguments, initializes paths and configurations, and runs the setup process in sequence.

    Returns:
        int: Exit code (0 for success, 1 for failure).
    """

    os.system('cls')
    
    parser = argparse.ArgumentParser(description="IMCV2 WSL Runner")
    parser.add_argument("-n", "--name",
                        help="Name of the WSL instance to create (e.g., 'IMCV2').")
    parser.add_argument("-b", "--base_path",
                        help=f"Specify alternate base local path to use instead of "
                             f"'{IMCV2_WSL_DEFAULT_BASE_PATH}'.")
    parser.add_argument("-s", "--proxy_server",
                        help=f"Specify alternate proxy server:port instead of "
                             f"'{IMCV2_WSL_DEFAULT_INTEL_PROXY}'.")
    parser.add_argument("-u", "--ubuntu_url",
                        help=f"Specify a URL for a bare Ubuntu image instead of "
                             f"'{IMCV2_WSL_DEFAULT_UBUNTU_URL}'.")
    parser.add_argument("-p", "--password",
                        help=f"Specify the initial user password instead of  "
                             f"'{MCV2_WSL_DEFAULT_PASSWORD}'.")
    parser.add_argument("-ver", "--version", action="store_true", help="Display version information.")
    args = parser.parse_args()

    # Show brief version and exit
    if args.version:
        print(f"{IMCV2_SCRIPT_NAME} v{IMCV2_SCRIPT_VERSION}\n{IMCV2_SCRIPT_DESCRIPTION}.")
        return 0

    # WS2 must be installed first, make sure we have it.
    if wsl_runner_check_installed() != 0:
        return 1

    if not args.name:
        print("Error: Instance name argument (-n) is mandatory.")
        return 1

    try:

        username = os.getlogin()
        instance_name = args.name

        # Set variables based on default are arguments if provided
        password = args.password if args.password else MCV2_WSL_DEFAULT_PASSWORD
        base_path = args.base_path if args.base_path else IMCV2_WSL_DEFAULT_BASE_PATH
        proxy_server = args.proxy_server if args.proxy_server else IMCV2_WSL_DEFAULT_INTEL_PROXY
        ubuntu_url = args.ubuntu_url if args.ubuntu_url else IMCV2_WSL_DEFAULT_UBUNTU_URL
        instance_path = os.path.join(base_path, IMCV2_WSL_DEFAULT_SDK_INSTANCES_PATH)
        bare_linux_image_path = os.path.join(base_path, IMCV2_WSL_DEFAULT_LINUX_IMAGE_PATH)

        # Construct file paths
        bare_linux_image_file = os.path.join(bare_linux_image_path, os.path.basename(urlparse(ubuntu_url).path))
        packages_file = os.path.join(base_path, os.path.basename(urlparse(IMCV2_WSL_DEFAULT_PACKAGES_URL).path))

        wsl_runner_show_info()

        print("\n    IMCv2 WSL Host Setup.\n")
        sys.stdout.write("\033[?25l")  # Hide the cursor

        # Run setup steps in sequence, by the end of this journey, we should have an instance up and running.
        run_pre_prerequisites_steps(base_path, instance_path, bare_linux_image_path, ubuntu_url, proxy_server)
        run_initial_setup_steps(instance_name, instance_path, bare_linux_image_file)
        run_user_creation_steps(instance_name, username, password)
        run_time_zone_steps(instance_name)
        run_kerberos_steps(instance_name)
        run_user_shell_steps(instance_name, username, proxy_server)
        run_install_system_packages(instance_name, username, packages_file)
        run_install_user_packages(instance_name, username, proxy_server)
        run_install_pyenv(instance_name, username, proxy_server)
        run_post_install_steps(instance_name)

        # Create desktop shortcut
        wsl_runner_create_shortcut(instance_name, "IMCv2 SDK")
        
        print("\n\n    This stage of the SDK setup is complete.")
        print("    The remaining steps will be carried out within your new WSL instance.") 
        print("    Please follow the instructions on the project's Wiki page.\n")
        print(f"    Instance '{instance_name}' created successfully, you may close this Window.")

        return 0

    except StepError as step_error:
        # Handle specific step errors
        print(f"\nStepError: {step_error}")
    except KeyboardInterrupt:
        # Handle user interruption gracefully
        print("\nOperation interrupted by the user. Exiting...")
    except Exception as general_error:
        # Handle unexpected exceptions
        print(f"\nUnexpected error: {general_error}")

    return 1


if __name__ == "__main__":
  
    return_value = wsl_runner_main()
    print("\033[?25h")  # Restore the cursor
    sys.exit()
