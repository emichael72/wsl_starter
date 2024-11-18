import argparse
import os
import time
import sys
import re
import subprocess
from urllib.parse import urlparse

# WSL Launcher Constants
IMCV2_WSL_RUNNER_BASE_PATH = os.path.join(os.environ["USERPROFILE"], "IMCV2_SDK")
IMCV2_WSL_RUNNER_INTEL_PROXY = "http://proxy-dmz.intel.com:911"
IMCV2_WSL_RUNNER_LINUX_IMAGE_PATH = os.path.join(IMCV2_WSL_RUNNER_BASE_PATH, "Bare")
IMCV2_WSL_RUNNER_SDK_INSTANCES_PATH = os.path.join(IMCV2_WSL_RUNNER_BASE_PATH, "Instances")
IMCV2_WSL_RUNNER_UBUNTU_URL = ("https://cdimage.ubuntu.com/ubuntu-base/releases/24.04.1/release/"
                               "ubuntu-base-24.04.1-base-amd64.tar.gz")
IMCV2_WSL_RUNNER_PACKAGES_URL = "https://raw.githubusercontent.com/emichael72/wsl_starter/main/packges.txt"
IMCV2_WSL_RUNNER_SDK_LAUNCHER_URL = "https://raw.githubusercontent.com/emichael72/wsl_starter/main/sdk_install.sh"


class StepError(Exception):
    """Custom exception for setup errors."""
    pass


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


def wsl_runner_console_decoder(input_string):
    try:
        # First, attempt to decode the string as UTF-8
        decoded_string = input_string.encode('latin1').decode('utf-8', errors='replace')

        # Remove any non-printable characters from the decoded string
        decoded_string = re.sub(r'[^\x20-\x7E]+', '', decoded_string)  # Keep printable ASCII characters

        if decoded_string:
            return decoded_string + "\n"

        # If UTF-8 decoding fails (or it was not UTF-8), attempt to decode as UTF-16 LE
        decoded_string = input_string.encode('latin1').decode('utf-16-le', errors='replace').replace('�', '')
        decoded_string = re.sub(r'[^\x20-\x7E]+', '', decoded_string)

        if decoded_string:
            return decoded_string + "\n"

        return ""

    except UnicodeDecodeError:
        return input_string


def wsl_runner_exec_process(process: str, args: list, hidden: bool = True, timeout: int = 30) -> tuple:
    """
    Execute a process or a simulated command with the given arguments and stream its output in real-time.

    Args:
        process (str): The executable or "function" to run.
        args (list): List of arguments for the command.
        hidden (bool): If True, suppress output.
        timeout (int): Time in seconds to wait for the command to complete.

    Returns:
        int: The status code of the process.
    """

    try:
        cmd = [process] + args
        ext_status = 0
        with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=10,
                universal_newlines=True
        ) as proc:
            try:
                printed_lines = 0
                for line in proc.stdout:
                    if process == "curl" and printed_lines == 0:
                        ext_status = int(line)  # curl : Store the http result as extended status
                    if not hidden:
                        if printed_lines == 0:
                            print("\n", end="")
                        print(wsl_runner_console_decoder(line), end="")  # Print stdout line by line
                        printed_lines += 1
                for line in proc.stderr:
                    if not hidden:
                        if printed_lines == 0:
                            print("\n", end="")
                        print(wsl_runner_console_decoder(line), end="")  # Print stderr line by line
                        printed_lines += 1

                # Wait for the process to complete and get the return code
                return proc.wait(timeout=timeout), ext_status
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"Error: Command timed out after {timeout} seconds: {process}", file=sys.stderr)
                return 124, 0  # Timeout exit code
    except FileNotFoundError:
        print(f"Error: Command not found: {process}", file=sys.stderr)
        return 127, 0
    except Exception as e:
        print(f"Error while executing step: {e}", file=sys.stderr)
        return 1, 0


def wsl_runner_print_status(description, status):
    max_length = 70
    dots = "." * (max_length - len(description))

    # Clear the line if new_line is False
    sys.stdout.write("\r\033[K" + description + dots + status + "\n")
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
    max_length = 70
    dots = "." * (max_length - len(description))

    # Clear the line if new_line is False
    sys.stdout.write("\r\033[K" + description + dots)
    sys.stdout.flush()

    try:
        if callable(process):  # Check if process is a callable Python function
            status = process(*args)  # Call the Python function with arguments
        else:
            raise ValueError(f"Invalid process type: {type(process)}. Must be callable or a string.")
    except Exception as e:
        # If any exception is raised during the Python function or external command execution
        print(f"Error executing {description}: {e}")
        status = 1  # Indicate failure

    # Ignore errors if specified
    if ignore_errors:
        status = 0

    # Print OK or ERROR without newline if new_line=False, or with newline if new_line=True
    if status == 0:
        sys.stdout.write("OK")
    else:
        sys.stdout.write(f"ERROR ({status})")

    # Handle newline printing or overwrite the line
    if new_line:
        sys.stdout.write("\n")
    sys.stdout.flush()
    time.sleep(0.2)

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
    # Prepare the dots
    max_length = 70
    dots = "." * (max_length - len(description))

    # Clear the line if new_line is False
    sys.stdout.write("\r\033[K" + description + dots)
    sys.stdout.flush()

    # Execute the function or process
    status, ext_status = wsl_runner_exec_process(process, args, hidden, timeout)

    # Ignore errors id set to do so
    if ignore_errors:
        status = 0

    # When the command is 'curl' the extended status is the HTTP code
    if process == "curl" and ext_status != 200:
        status = ext_status

    # Print OK or ERROR without newline if new_line=False, or with newline if new_line=True
    if status == 0:
        sys.stdout.write("OK")
    elif status == 124:  # Special handling for timeout
        sys.stdout.write("TIMEOUT")
    else:
        sys.stdout.write(f"ERROR ({status})")

    # Handle newline printing or overwrite the line
    if new_line:
        sys.stdout.write("\n")
    sys.stdout.flush()
    time.sleep(0.2)

    return status


def convert_win_to_wsl_path(windows_path):
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


def run_install_packages(wsl_instance, username, packages_file, timeout=120):
    """
    Transfers a packages file to the WSL instance and installs the packages listed in the file.

    Args:
        wsl_instance (str): The name of the WSL instance.
        username: (str): WSL username
        packages_file (str): Path to the file containing the list of packages to install.
        timeout (int, optional): Time in seconds to wait for the process to complete. Default is 30 seconds.
    """

    wsl_packages_file_path = convert_win_to_wsl_path(packages_file)

    # Path where the packages file will be stored in the WSL instance
    wsl_file_path = f"/home/{username}/downloads/packages.txt"

    # Transfer the packages file to the WSL instance
    transfer_description = f"Transferring packages to WSL instance {wsl_instance}"
    transfer_process = "wsl"
    transfer_args = [
        "-d", wsl_instance,
        "--", "bash", "-c",
        f"cp -f {wsl_packages_file_path} {wsl_file_path}"
    ]

    # Run the file transfer command
    transfer_status = wsl_runner_run_process(transfer_description, transfer_process, transfer_args, hidden=False,
                                             timeout=timeout, new_line=False)

    # If the transfer is successful, proceed to install packages
    if transfer_status == 0:
        install_description = "Installing packages from file"
        install_process = "wsl"
        install_args = [
            "-d", wsl_instance,
            "--", "bash", "-c",
            f"xargs -a {wsl_file_path} sudo apt install -y"
        ]

        # Run the apt install command
        install_status = wsl_runner_run_process(install_description, install_process, install_args, hidden=False,
                                                timeout=timeout, new_line=True)

        return install_status


def run_user_shell_steps(instance_name, username, proxy_server):
    # Define the array of user shell-related commands
    user_shell_commands = [

        # Set HTTP Proxy in .bashrc
        (f"Setting HTTP Proxy ({proxy_server})",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo 'export http_proxy={proxy_server}' >> /home/{username}/.bashrc"]),

        # Set HTTPS Proxy in .bashrc
        (f"Setting HTTPS Proxy ({proxy_server})",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo 'export https_proxy={proxy_server}' >> /home/{username}/.bashrc"]),

        # Create ~/downloads directory
        ("Create ~/downloads directory",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"mkdir -p /home/{username}/downloads && sudo chown {username}:{username}"
                 f" /home/{username}/downloads"]),

        # Create ~/projects directory
        ("Create ~/projects directory",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"mkdir -p /home/{username}/projects && sudo chown {username}:{username} /home/{username}/projects"]),

        # Create .hushlogin in the user's home directory
        ("Create .hushlogin in the user's home directory",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"touch /home/{username}/.hushlogin && sudo chown {username}:{username} /home/{username}/.hushlogin"]),

        # Set the prompt in .bashrc
        # Correct the echo command with properly escaped quotes and ensure the export is valid
        ("Set the prompt in .bashrc",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo 'export PS1=\"\\[\\e[1;36m\\]\\u@\\[\\e[1;32m\\]\\w~ \\[\\e[m\\]\"'"
                 f" >> /home/{username}/.bashrc"]),

        # Restart session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name])
    ]

    # Run each user shell-related command with run_with_status
    for description, process, args in user_shell_commands:
        if wsl_runner_run_process(description, process, args, hidden=True) != 0:
            raise StepError("Failed to complete step")

    wsl_runner_print_status("Setting user shell defaults", "DONE")


def run_kerberos_steps(instance_name):
    # Define the array of Kerberos-related commands
    kerberos_commands = [
        # Setting Kerberos defaults
        ("Setting Kerberos defaults",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'krb5-config krb5-config/default_realm string CLIENTS.INTEL.COM'"
                 " | sudo debconf-set-selections"]),

        # Pre-seed Kerberos server hostnames
        ("Pre-seed Kerberos server hostnames",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'krb5-config krb5-config/kerberos_servers string kdc1.clients.intel.com kdc2.clients.intel.com'"
                 " | sudo debconf-set-selections"]),

        # Pre-seed Kerberos administrative server
        ("Pre-seed Kerberos administrative server",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'krb5-config krb5-config/admin_server string admin.clients.intel.com'"
                 " | sudo debconf-set-selections"]),

        # Install Kerberos packages non-interactively
        ("Install Kerberos packages non-interactively",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "export DEBIAN_FRONTEND=noninteractive && sudo apt install -y krb5-config krb5-user"]),

        # Restart session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name])
    ]

    # Run each Kerberos-related command with run_with_status
    for description, process, args in kerberos_commands:
        if wsl_runner_run_process(description, process, args, hidden=True) != 0:
            raise StepError("Failed to complete step")

    wsl_runner_print_status("Setting Kerberos defaults", "DONE")


def run_time_zone_steps(instance_name):
    # List of time_zone_related commands to be executed
    timezone_commands = [
        # Pre-seed tzdata configuration for Israel timezone
        ("Pre-seed tzdata configuration for Israel timezone - Area",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'tzdata tzdata/Areas select Asia' | sudo debconf-set-selections"]),

        ("Pre-seed tzdata configuration for Israel timezone - Jerusalem",
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
        ("Pre-seed console-setup for Hebrew character set - UTF-8",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'console-setup console-setup/charmap47 select UTF-8' | sudo debconf-set-selections"]),

        ("Pre-seed console-setup for Hebrew character set - Hebrew",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'console-setup console-setup/codeset47 select Hebrew' | sudo debconf-set-selections"]),

        ("Pre-seed console-setup for Hebrew character set - Fixed font",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 "echo 'console-setup console-setup/fontface47 select Fixed' | sudo debconf-set-selections"]),

        ("Pre-seed console-setup for Hebrew character set - Font size 16",
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

    # Run each command with run_with_status
    for description, process, args in timezone_commands:
        if wsl_runner_run_process(description, process, args, hidden=True) != 0:
            raise StepError("Failed to complete step")

    wsl_runner_print_status("Setting time zone defaults", "DONE")


def run_user_creation_steps(instance_name, username, password):
    # Array of user creation and configuration commands
    user_commands = [
        # Install required packages (sudo, passwd)
        ("Installing required packages (sudo, passwd)",
         "wsl", ["-d", instance_name, "--", "bash", "-c", "apt install -y sudo passwd"]),

        # Add 'sudo' group if it doesn't exist
        ("Adding 'sudo' group if it doesn't exist",
         "wsl",
         ["-d", instance_name, "--", "bash", "-c", "if ! grep -q \"^sudo:\" /etc/group; then groupadd sudo; fi"]),

        # Create the user if it doesn't exist
        (f"Creating '{username}' if it doesn't exist",
         "wsl", ["-d", instance_name, "--", "bash", "-c", f"useradd -m -s /bin/bash {username}"]),

        # Set password for the user
        (f"Setting password for '{username}'",
         "wsl", ["-d", instance_name, "--", "bash", "-c", f"echo '{username}:{password}' | chpasswd"]),

        # Add user to the 'sudo' group
        (f"Adding '{username}' to sudo group",
         "wsl", ["-d", instance_name, "--", "bash", "-c", f"usermod -aG sudo {username}"]),

        # Add user to sudoers with NOPASSWD
        (f"Adding '{username}' to sudoers with NOPASSWD",
         "wsl", ["-d", instance_name, "--", "bash", "-c",
                 f"echo '{username} ALL=(ALL) NOPASSWD:ALL' | sudo tee -a /etc/sudoers"]),

        # Ensure the user starts in their home directory
        (f"Ensure the '{username}' starts in their home directory",
         "wsl", ["-d", instance_name, "--", "bash", "-c", f"echo 'cd ~' >> /home/{username}/.bashrc"]),

        # Set user section in /etc/wsl.conf
        ("Setting user section in /etc/wsl.conf",
         "wsl", ["-d", instance_name, "--", "bash", "-c", "echo '[user]' > /etc/wsl.conf"]),

        # Set default user in /etc/wsl.conf
        (f"Setting default user in /etc/wsl.conf",
         "wsl", ["-d", instance_name, "--", "bash", "-c", f"echo 'default={username}' >> /etc/wsl.conf"]),

        # Restart session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name])
    ]

    # Run each command with run_with_status
    for description, process, args in user_commands:
        if wsl_runner_run_process(description, process, args, hidden=True) != 0:
            raise StepError("Failed to complete step")

    wsl_runner_print_status("Creating user account", "DONE")


def run_initial_setup_steps(instance_name, instance_path, bare_linux_image_path):
    # Define commands related to basic WSL environment startup
    startup_commands = [

        # Checking if an instance with the same name already exists
        ("Checking if an instance with the same name already exists",
         "wsl", ["--terminate", instance_name], True),

        # Unregistering WSL instance if exists
        ("Unregistering WSL instance if exists",
         "wsl", ["--unregister", instance_name], True),

        # Importing WSL instance
        ("Importing WSL instance",
         "wsl", [
             "--import",
             instance_name,
             os.path.join(instance_path, instance_name),
             bare_linux_image_path
         ]),

        # Updating APT package lists
        ("Updating APT package lists",
         "wsl", ["-d", instance_name, "--", "bash", "-c", "apt update"]),

        # Listing upgradable packages
        ("Listing upgradable packages",
         "wsl", ["-d", instance_name, "--", "bash", "-c", "apt list --upgradable"]),

        # Restart session for changes to take effect
        ("Restarting session for changes to take effect",
         "wsl", ["--terminate", instance_name])
    ]

    # Execute each command in the startup_commands list using run_with_status
    for description, process, args, *ignore_errors in startup_commands:
        # If ignore_errors is not specified, default it to False
        ignore_errors = ignore_errors[0] if ignore_errors else False

        if wsl_runner_run_process(description, process, args, hidden=True, new_line=False,
                                  ignore_errors=ignore_errors) != 0:
            raise StepError("Failed to complete step")

    wsl_runner_print_status("WSL environment startup", "DONE")


def run_pre_prerequisites_steps(base_path, instance_path, bare_linux_image_path, ubuntu_url, proxy_server):
    prerequisites_commands = [
        ("Verifying destination path", wsl_runner_ensure_directory_exists,
         [(bare_linux_image_path, instance_path)], False),
        ("Downloading Packages list", wsl_runner_download_resources,
         [IMCV2_WSL_RUNNER_PACKAGES_URL, base_path, proxy_server],
         False),
        ("Downloading SDK Launcher script", wsl_runner_download_resources,
         [IMCV2_WSL_RUNNER_SDK_LAUNCHER_URL, base_path, proxy_server], False),
        ("Downloading Ubuntu image", wsl_runner_download_resources,
         [ubuntu_url, bare_linux_image_path, proxy_server], False)
    ]

    # Iterate through commands and run each with the appropriate arguments
    for description, func, args, new_line in prerequisites_commands:
        if ws_runner_run_function(description, func, args, new_line) != 0:
            raise StepError("Failed to complete step")

    wsl_runner_print_status("Prerequisites satisfied", "DONE")


def wsl_runner_main():

    parser = argparse.ArgumentParser(description="IMCV2 WSL Runner")
    parser.add_argument("-n", "--name", required=True, help="Instance name")
    parser.add_argument("-p", "--packages_file", help="Specify apt packages file to autoinstall")
    args = parser.parse_args()

    instance_name = args.name
    username = os.environ["USERNAME"]
    password = "intel@1234"
    proxy_server = IMCV2_WSL_RUNNER_INTEL_PROXY
    base_path = IMCV2_WSL_RUNNER_BASE_PATH
    instance_path = IMCV2_WSL_RUNNER_SDK_INSTANCES_PATH
    ubuntu_url = IMCV2_WSL_RUNNER_UBUNTU_URL
    bare_linux_image_path = IMCV2_WSL_RUNNER_LINUX_IMAGE_PATH
    bare_linux_image_file = os.path.join(bare_linux_image_path, os.path.basename(urlparse(ubuntu_url).path))
    packages_file = os.path.join(base_path, os.path.basename(urlparse(IMCV2_WSL_RUNNER_PACKAGES_URL).path))
    sdk_launch_file = os.path.join(base_path, os.path.basename(urlparse(IMCV2_WSL_RUNNER_SDK_LAUNCHER_URL).path))

    print("\n")
    wsl_runner_print_status("WSL SDK instance name", instance_name)

    try:
        # run_pre_prerequisites_steps(base_path, instance_path, bare_linux_image_path, ubuntu_url, proxy_server)
        # run_initial_setup_steps(instance_name, instance_path, bare_linux_image_file)
        # run_user_creation_steps(instance_name, username, password)
        # run_time_zone_steps(instance_name)
        # run_kerberos_steps(instance_name)
        # run_user_shell_steps(instance_name, username, proxy_server)
        run_install_packages(instance_name,username, packages_file)

        print("\nAll steps completed successfully!")
        return 0

    except StepError as set_error:
        print(f"\nException: {set_error}")
    except KeyboardInterrupt:
        # Handle Ctrl + Break or Ctrl + C gracefully
        print("\nOperation was interrupted by the user. Exiting gracefully...")
    except Exception as general_error:
        print(f"\nException: {general_error}")

    return 1


if __name__ == "__main__":
    sys.exit(wsl_runner_main())
