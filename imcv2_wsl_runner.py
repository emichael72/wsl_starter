#!/usr/bin/env python3

"""
Script:       imcv2_wsl_runner.py
Author:       Intel IMCv2 Team
Version:      1.1.9

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

import os

try:
    import winreg
except ImportError:
    raise EnvironmentError("This script must be run on Windows.")
import argparse
import itertools
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
IMCV2_SCRIPT_VERSION = "1.1.9"
IMCV2_SCRIPT_DESCRIPTION = "WSL Host Installer"

# Spinning characters for progress indication
spinner_active = False

# Intel Proxy availability
intel_proxy_detected = True


class StepError(Exception):
    """
    Custom exception to signal errors during setup steps.

    Usage:
        Raise this exception when a specific setup step fails and requires
        distinct handling compared to generic exceptions.
    """
    pass


class InfoType(int, Enum):
    """
    Enum to specify the type of event display for status messages.

    """
    OK = 0
    WARNING = 1001
    DONE = 1000


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


def wsl_runner_get_office_user_identity():
    """
    Extract ADUserDisplayName and ADUserName from the Windows Registry.
    Tries Office 16.0 and 15.0 first, then falls back to Common UserInfo.

    Returns:
        tuple: (Full name, Corporate email) if found, otherwise None.
    """
    registry_paths = [
        r"Software\Microsoft\Office\16.0\Common\Identity",
        r"Software\Microsoft\Office\15.0\Common\Identity"
    ]

    # Try to extract from Identity registry paths
    for path in registry_paths:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                display_name = winreg.QueryValueEx(key, "ADUserDisplayName")[0]
                email = winreg.QueryValueEx(key, "ADUserName")[0]
                return display_name, email
        except FileNotFoundError:
            # Try the next path if the current one doesn't exist
            continue
        except Exception as e:
            print(f"Error reading registry path {path}: {e}")
            return None, None

    # Fallback to Common UserInfo if no identity is found
    fallback_path = r"Software\Microsoft\Office\Common\UserInfo"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, fallback_path) as key:
            display_name = winreg.QueryValueEx(key, "UserName")[0]
            return display_name, None  # No email in this case
    except FileNotFoundError:
        print(f"Registry path {fallback_path} not found.")
    except Exception as e:
        print(f"Error reading fallback registry path {fallback_path}: {e}")

    # If no identity is found in any of the paths
    return None, None


def wsl_runner_print_logo():
    """
    Prints the logo with alternating bright white and bright blue colors.
    """

    blue = "\033[94m"
    white = "\033[97m"
    reset = "\033[0m"
    sys.stdout.write(f"\n{reset}")
    sys.stdout.write(f"{blue}     ██╗███╗   ███╗ ██████╗██╗   ██╗██████╗{reset}\n")
    sys.stdout.write(f"{white}     ██║████╗ ████║██╔════╝██║   ██║╚════██╗{reset}\n")
    sys.stdout.write(f"{blue}     ██║██╔████╔██║██║     ██║   ██║ █████╔╝{reset}\n")
    sys.stdout.write(f"{white}     ██║██║╚██╔╝██║██║     ╚██╗ ██╔╝██╔═══╝{reset}\n")
    sys.stdout.write(f"{blue}     ██║██║ ╚═╝ ██║╚██████╗ ╚████╔╝ ███████╗{reset}\n")
    sys.stdout.write(f"{white}     ╚═╝╚═╝     ╚═╝ ╚═════╝  ╚═══╝  ╚══════╝{reset}\n")
    sys.stdout.flush()


def wsl_runner_show_info(show_logo: bool = False):
    """
        Provides detailed information about the steps performed by
        the IMCv2 WSL installer. It outlines the tasks, such as downloading a
        Linux image, setting up a WSL instance, configuring the environment, and
        installing necessary packages for the SDK. The message is formatted to
        be easily readable within an 80-character width terminal.
    """

    reset = "\033[0m"
    bold = "\033[1m"
    green = "\033[32m"
    bright_blue = "\033[94m"
    bright_white = "\033[97m"

    sys.stdout.flush()
    os.system("cls")

    if show_logo:
        wsl_runner_print_logo()

    sys.stdout.write(f"\nWelcome to the {bright_white}IMCv2 SDK-WSL{reset} v{IMCV2_SCRIPT_VERSION} Image Creator!\n")
    sys.stdout.write(f"We're setting up your environment—here's what's next:\n\n")
    sys.stdout.write(f"{bold}{green}1.{reset} Download a compatible Ubuntu image (ubuntu-base-24.04.1).\n")
    sys.stdout.write(f"{bold}{green}2.{reset} Create and import a new WSL Linux instance.\n")
    sys.stdout.write(f"{bold}{green}3.{reset} Configure environment settings.\n")
    sys.stdout.write(f"{bold}{green}4.{reset} Install essential packages for the {bright_white}IMCv2{reset} SDK.\n\n")
    sys.stdout.write(f"Please keep your PC connected to {bright_blue}Intel{reset} throughout.\n\n")
    sys.stdout.flush()


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


def wsl_runner_is_proxy_available(proxy_server: str, timeout: int = 5) -> bool:
    """
    Checks if the specified proxy server is reachable by sending a curl request to a known URL.
    
    Args:
        proxy_server (str): The proxy server to test.
        timeout (int, optional): Timeout in seconds for the test. Default is 5 seconds.

    Returns:
        bool: True if the proxy server is reachable, False otherwise.
    """
    test_url = "https://www.google.com"  # Use a reliable public URL for connectivity testing
    try:
        result = subprocess.run(
            ["curl", "--proxy", proxy_server, "--silent", "--head", "--fail", test_url],
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def wsl_runner_start_wsl_shell(distribution=None):
    """
    Launches an interactive WSL shell. Optionally, specify a distribution.

    Args:
        distribution (str): The name of the WSL distribution to launch (e.g., 'Ubuntu-20.04').
                            If None, launches the default WSL distribution.
    """
    try:
        print (f"Starting  {distribution}..")

        # Prepare the base command
        command = ["wsl"]
        if distribution:
            command.extend(["-d", distribution])

        # Start the interactive shell and attach stdin/stdout
        process = subprocess.run(command, check=True)
        return process.returncode
    except FileNotFoundError:
        print("Error: WSL is not installed or not in the system PATH.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"WSL process exited with an error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        return 1


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


def wsl_runner_download_resources(url, destination_path, proxy_server: str = None, timeout: int = 30) -> int:
    """
    Downloads a file from the specified URL using curl, with optional proxy configuration.
    The downloaded file is saved to the specified destination path.

    Args:
        url (str): The URL of the resource to download.
        destination_path (str): The path where the downloaded file should be saved.
        proxy_server (str, optional): The proxy server to use for the download. Default is None.
        timeout (int, optional): The time in seconds to wait before the request times out. Default is 30 seconds.

    Returns:
        int: 0 if the download succeeded (status code 200), 1 otherwise.
    """
    # Parse the URL and get the file name from the URL path
    parsed_url = urlparse(url)
    destination = os.path.join(destination_path, os.path.basename(parsed_url.path))

    global intel_proxy_detected

    # Define curl arguments based on proxy availability
    if not proxy_server or intel_proxy_detected == False:
        args = [
            "-s", "-S", "-w", "%{http_code}",  # silent mode, show errors, output HTTP status code
            "--output", destination,  # Specify the output file destination
            url  # URL of the resource to download
        ]
    else:
        args = [
            "-s", "-S", "-w", "%{http_code}",  # silent mode, show errors, output HTTP status code
            "--proxy", proxy_server,  # Use specified proxy server
            "--output", destination,  # Specify the output file destination
            url  # URL of the resource to download
        ]

    # Execute the curl command and capture the output
    status_code, response_code = wsl_runner_exec_process("curl", args, hidden=True, timeout=timeout)

    # Check if the download was successful
    if status_code == 0 and str(response_code).strip() == "200":
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
        ret_val: InfoType = InfoType.OK
):
    """
    Prints the status message to the console in a formatted manner with color codes.

    Args:
        text_type (TextType): PREFIX, SUFFIX, or BOTH.
        description (str, None): The message to display. If None, it defaults to an empty string.
        new_line (bool): If True, prints a new line after the status; otherwise overwrites the same line.
        ret_val (InfoType or int): The status code to display. 0 = OK, 124 = TIMEOUT, others = ERROR.
    """

    if text_type not in TextType:
        return

    # ANSI color codes
    green = "\033[32m"
    yellow = "\033[33m"
    red = "\033[31m"
    bright_blue = "\033[94m"
    reset = "\033[0m"

    max_length = 60

    if isinstance(ret_val, InfoType):
        ret_val = int(ret_val)

    # Handle PREFIX or BOTH types
    if text_type in {TextType.BOTH, TextType.PREFIX} and description:
        # Adjust the number of dots for the alignment
        dots_count = max_length - len(description) - 2
        dots = "." * dots_count
        # Print the description with one space before and after the dots
        sys.stdout.write(f"\r\033[K{description} {dots} ")
        sys.stdout.flush()

        # Show spinner
        if text_type is not TextType.BOTH:
            wsl_runner_set_spinner(True)

    # Handle SUFFIX or BOTH types
    if text_type in {TextType.BOTH, TextType.SUFFIX}:

        # Stop spinner
        wsl_runner_set_spinner(False)

        if ret_val == InfoType.OK:
            pass
        elif ret_val == InfoType.DONE:  # Special code for step completed.
            sys.stdout.write(f"{green} OK{reset}")
        elif ret_val == InfoType.WARNING:  # Special code for step completed.
            sys.stdout.write(f"{yellow} Warning{reset}")
        else:
            if ret_val == 124:
                sys.stdout.write(f"{bright_blue} Timeout{reset}")
            else:
                ret_val = (ret_val - 2 ** 32) if ret_val >= 2 ** 31 else ret_val
                sys.stdout.write(f"{red} Error ({ret_val}){reset}")

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


def wsl_runner_delete_shortcut(shortcut_name: str) -> int:
    """
    Deletes a desktop shortcut.

    Args:
        shortcut_name (str): The name of the desktop shortcut to delete.

    Returns:
        int: 0 if the shortcut is deleted successfully, 1 otherwise.
    """
    try:
        desktop_dir = wsl_runner_get_desktop_path()
        shortcut_path = os.path.join(desktop_dir, f"{shortcut_name}.lnk")

        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)
            return 0
        return 1  # Shortcut not found
    except Exception as e:
        print(f"An exception occurred: {e}", file=sys.stderr)
        return 1


def run_post_install_steps(instance_name: str, username, proxy_server, hidden: bool = True, new_line: bool = False):
    """
    Configures the WSL instance post-installation by setting it as the default instance.

    Args:
        instance_name (str): Name of the WSL instance to set as the default.
        username: (str): WSL username
        proxy_server (str): HTTP/HTTPS proxy server address to set in .bashrc.
        hidden (bool): If True, suppresses command output during execution.
        new_line (bool): If True, displays status messages on a new line.

    Raises:
        StepError: If the step fails to execute successfully.
    """
    global intel_proxy_detected

    steps_commands = [
        # Set the WSL instance as the default
        ("Setting the WSL instance as the default",
         "wsl", ["--set-default", instance_name]),

        # Download git configuration template
        ("Downloading git configuration template",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 (
                     f"curl -sS --proxy {proxy_server} "
                     f"-o /home/{username}/downloads/git_config.template "
                     "https://raw.githubusercontent.com/emichael72/wsl_starter/main/git_config.template"
                     if intel_proxy_detected else
                     f"curl -sS "
                     f"-o /home/{username}/downloads/git_config.template "
                     "https://raw.githubusercontent.com/emichael72/wsl_starter/main/git_config.template"
                 )
                 ]),

        # Download SDK runner script
        ("Downloading SDK runner script",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 (
                     f"curl -sS --proxy {proxy_server} "
                     f"-o /home/{username}/.imcv2/sdk_runner.sh "
                     "https://raw.githubusercontent.com/emichael72/wsl_starter/main/sdk_runner.sh"
                     if intel_proxy_detected else
                     f"curl -sS "
                     f"-o /home/{username}/.imcv2/sdk_runner.sh "
                     "https://raw.githubusercontent.com/emichael72/wsl_starter/main/sdk_runner.sh"
                 )
                 ]),

        # Make the SDK Runner executable
        ("Make the SDK runner script executable",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"chmod +x /home/{username}/.imcv2/sdk_runner.sh"]),

        # Use the SDK Runner to patch bashrc
        ("Make 'sdk_runner' run at startup",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"/home/{username}/.imcv2/sdk_runner.sh runner_set_auto_start 1"]),

        # Terminate WSL session
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name]),

    ]

    # Execute the command and handle errors
    for description, process, args, *ignore_errors in steps_commands:
        ignore_errors = ignore_errors[0] if ignore_errors else False
        if wsl_runner_run_process(description, process, args, hidden=hidden, new_line=new_line,
                                  ignore_errors=ignore_errors) != 0:
            raise StepError(f"Failed during step: {description}")

    # Print success message
    wsl_runner_print_status(TextType.BOTH, "WSL post-installation steps completed", True, InfoType.DONE)


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

    global intel_proxy_detected

    # Define commands related to package installation
    steps_commands = [

        # Download pyenv installer
        ("Download 'pyenv' installer",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"curl -s -S "
                 f"{'--proxy ' + proxy_server if intel_proxy_detected else ''} "
                 f"-o /home/{username}/downloads/pyenv-installer "
                 "https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer"]),

        # Make the installer executable
        ("Make 'pyenv' installer executable",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"chmod +x /home/{username}/downloads/pyenv-installer"]),

        #  Clean up any previous pyenv installation
        ("Clean up any previous 'pyenv' installation",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"rm -rf /home/{username}/.pyenv"]),

        # Run pyenv-installer
        ("Run pyenv-installer",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 (
                     f"export http_proxy={proxy_server} && export https_proxy={proxy_server} && "
                     f"/home/{username}/downloads/pyenv-installer"
                     if intel_proxy_detected else
                     f"/home/{username}/downloads/pyenv-installer"
                 )
                 ]),

        # Check for errors during installation
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
                 (
                     f"export http_proxy={proxy_server} && "
                     f"export https_proxy={proxy_server} && "
                     f"$HOME/.pyenv/bin/pyenv install 3.9.0 -f"
                     if intel_proxy_detected else
                     f"$HOME/.pyenv/bin/pyenv install 3.9.0 -f"
                 )
                 ]),

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
            raise StepError(f"Failed during step: {description}")

    wsl_runner_print_status(TextType.BOTH, "Python 3.9 via 'pyenv' installation", True, InfoType.DONE)


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

    global intel_proxy_detected

    # Define commands related to package installation
    steps_commands = [
        # Ensure the target directory exists
        ("Creating target directory for Git completion scripts",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"sudo mkdir -p /usr/share/git-core/contrib/completion && sudo chown {username}:{username} "
                 f"/usr/share/git-core/contrib/completion"]),

        # Download git-completion.bash using curl
        ("Downloading git-completion.bash",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"curl -s -S "
                 f"{'--proxy ' + proxy_server if intel_proxy_detected else ''} "
                 "-o /usr/share/git-core/contrib/completion/git-completion.bash "
                 "https://raw.githubusercontent.com/git/git/master/contrib/completion/git-completion.bash"]),

        # Download git-prompt.sh using curl
        ("Downloading git-prompt.sh",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"curl -s -S "
                 f"{'--proxy ' + proxy_server if intel_proxy_detected else ''} "
                 "-o /usr/share/git-core/contrib/completion/git-prompt.sh "
                 "https://raw.githubusercontent.com/git/git/master/contrib/completion/git-prompt.sh"]),

        # Set a proper colored Git-aware prompt in .bashrc
        ("Add Git prompt source to .bashrc",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo 'source /usr/share/git-core/contrib/completion/git-prompt.sh' >> /home/{username}/.bashrc"]),

        # Set Git-aware PS1 prompt in .bashrc
        ("Set Git-aware PS1 prompt in .bashrc",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"cat << 'EOF' >> /home/{username}/.bashrc\n"
                 f"# Git-aware PS1 prompt \n"
                 f"export PS1='\\[\\e[1;32m\\]\\u \\[\\e[1;34m\\]\\w\\[\\e[1;31m\\]"
                 f"\\$(__git_ps1 \" (%s)\") \\[\\e[0m\\]> '\n"
                 f"EOF"]),

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
            raise StepError(f"Failed during step: {description}")

    wsl_runner_print_status(TextType.BOTH, "User package installation", True, InfoType.DONE)


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
        wsl_runner_print_status(TextType.BOTH, "Empty packages file", True, InfoType.DONE)
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
        (f"Installing {line_count} packages",
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
            raise StepError(f"Failed during step: {description}")

    wsl_runner_print_status(TextType.BOTH, "Ubuntu system package installation", True, InfoType.DONE)


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

    # Get email and full name or empty strings
    corp_name, corp_email = wsl_runner_get_office_user_identity()

    global intel_proxy_detected

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

        # Set full name in .bashrc if corp_name is not None
        *(
            [(
                f"Setting full name",
                "wsl", ["-d", instance_name, "--", "bash", "-c",
                        f"grep -q 'export IMCV2_FULL_NAME=' /home/{username}/.bashrc || "
                        f"echo 'export IMCV2_FULL_NAME={corp_name}' >> /home/{username}/.bashrc"]
            )] if corp_name is not None else []
        ),

        # Set email address in .bashrc if corp_email is not None
        *(
            [(
                f"Setting email address",
                "wsl", ["-d", instance_name, "--", "bash", "-c",
                        f"grep -q 'export IMCV2_EMAIL=' /home/{username}/.bashrc || "
                        f"echo 'export IMCV2_EMAIL={corp_email}' >> /home/{username}/.bashrc"]
            )] if corp_email is not None else []
        ),

        # Create necessary directories
        ("Create necessary directories",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"mkdir -p /home/{username}/downloads /home/{username}/projects /home/{username}/.imcv2 && "
                 f"sudo chown -R {username}:{username} "
                 f"/home/{username}/downloads /home/{username}/projects /home/{username}/.imcv2"]),

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
    wsl_runner_print_status(TextType.BOTH, "Setting user shell defaults", True, InfoType.DONE)


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
        (
            "Adding essential aliases to .bashrc",
            "wsl", [
                "-d", instance_name,
                "--",
                "bash", "-c",
                (
                    # Alias for shutting down the WSL instance
                    f"echo -e '\\nalias shutdown=\"wsl.exe --terminate \\$WSL_DISTRO_NAME\"' "
                    f">> /home/{username}/.bashrc && "

                    # Alias for rebooting the WSL instance
                    f"echo -e '\\nalias reboot=\"wt.exe -w 0 -p {instance_name} -- wsl.exe && "
                    f"wsl.exe --terminate \\$WSL_DISTRO_NAME && wsl.exe\"' "
                    f">> /home/{username}/.bashrc && "

                    # Alias for opening the current directory in Windows Explorer
                    f"echo -e '\\nalias start=\"explorer.exe .\"' "
                    f">> /home/{username}/.bashrc"
                )
            ]
        ),

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
    wsl_runner_print_status(TextType.BOTH, "Creating user account", True, InfoType.DONE)


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
    wsl_runner_print_status(TextType.BOTH, "WSL environment startup completed", True, InfoType.DONE)


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
    wsl_runner_print_status(TextType.BOTH, "Prerequisites satisfied", True, InfoType.DONE)


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

    print("IMCv2 SDK for Windows Subsystem for Linux.\n")

    # Install help message
    if wsl_version_unknown:
        print("WSL is installed but might not be WSL2, to reinstall it:")
    else:
        print("WSL2 is not installed, to install it:")

    print("1. Open Command Prompt or PowerShell as Administrator.")
    print("2. Run: wsl --install --no-distribution")
    print("3. Reboot if prompted, then rerun this installer.\n")
    return 1


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
    parser.add_argument("-t", "--start_step", type=int, default=0,
                        help="Start execution from a specific step other than 0.")
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

        # Remove current shortcut (if exist)
        wsl_runner_delete_shortcut("IMCv2 SDK")

        username = os.getlogin()
        instance_name = args.name
        global intel_proxy_detected

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
        sys.stdout.write("\033[?25l")  # Hide the cursor

        # This is designed to work at Intel
        if not wsl_runner_is_proxy_available(proxy_server):
            wsl_runner_print_status(TextType.BOTH, "Intel proxy is not available", True, InfoType.WARNING)
            intel_proxy_detected = False

        # Define all steps as a list of tuples (step_name, function_call)
        steps = [
            ("Pre-prerequisites",
             lambda: run_pre_prerequisites_steps(base_path, instance_path, bare_linux_image_path, ubuntu_url,
                                                 proxy_server)),
            ("Initial setup", lambda: run_initial_setup_steps(instance_name, instance_path, bare_linux_image_file)),
            ("User creation", lambda: run_user_creation_steps(instance_name, username, password)),
            ("Time zone setup", lambda: run_time_zone_steps(instance_name)),
            ("Kerberos setup", lambda: run_kerberos_steps(instance_name)),
            ("User shell setup", lambda: run_user_shell_steps(instance_name, username, proxy_server)),
            ("Install system packages", lambda: run_install_system_packages(instance_name, username, packages_file)),
            ("Install user packages", lambda: run_install_user_packages(instance_name, username, proxy_server)),
            ("Install pyenv", lambda: run_install_pyenv(instance_name, username, proxy_server)),
            ("Post-install steps", lambda: run_post_install_steps(instance_name, username, proxy_server)),
            ("Create desktop shortcut", lambda: wsl_runner_create_shortcut(instance_name, "IMCv2 SDK")),
        ]

        # Execute steps from the specified starting point
        if args.start_step < 0 or args.start_step >= len(steps):
            raise ValueError(f"Invalid start step: {args.start_step}. Must be between 0 and {len(steps) - 1}.")

        for i, (step_name, step_function) in enumerate(steps[args.start_step:], start=args.start_step):
            step_function()

        # Start WSL instance, setup will continue for there.
        wsl_runner_start_wsl_shell(instance_name)
        time.sleep(1)

        return 0

    except StepError as step_error:
        # Handle specific step errors
        print(f"\nError: {step_error}")
    except KeyboardInterrupt:
        # Handle user interruption gracefully
        print("\nOperation interrupted by the user. Exiting...")
    except Exception as general_error:
        # Handle unexpected exceptions
        print(f"\nException: {general_error}")

    return 1


if __name__ == "__main__":
    return_value = wsl_runner_main()
    print("\033[?25h")  # Restore the cursor
    sys.exit(return_value)
