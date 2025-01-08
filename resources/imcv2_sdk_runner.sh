#!/bin/bash
# shellcheck disable=SC2317
# shellcheck disable=SC2059
# shellcheck disable=SC2181
# shellcheck disable=SC2120
# Formatting: shfmt -i 0 -w imcv2_sdk_runner.sh

# ------------------------------------------------------------------------------
#
# Script Name:  imcv2_sdk_runner.sh
# Description:  IMCv2 SDK for WSL auto-runner and maintenance script.
# Version:      1.5
# Copyright:    2024 Intel Corporation.
# Author:       Intel IMCv2 Team.
#
# ------------------------------------------------------------------------------

# Script global variables
script_version="1.5"

#
# @brief Detects the current Linux distribution and returns its name in lowercase.
# @return The name of the Linux distribution in lowercase (e.g., "wsl", "fedora", "ubuntu").
#
# @example
# if [[ "$(runner_get_distro)" == "fedora" ]]; then
#     printf "fedora\n"
# fi
#

runner_get_distro() {

	local distro="unknown"

	if grep -qEi "(microsoft|wsl)" /proc/version &>/dev/null; then
		distro="wsl"
	elif [[ -f /etc/os-release ]]; then
		distro=$(grep '^ID=' /etc/os-release | cut -d'=' -f2 | tr -d '"')
	fi

	echo "$distro"
	return 0
}

#
# @brief Launches a command in the background with fully suppressed output and job notifications.
#        This function is 'WSL-aware', meaning the arguments will be translated to Windows paths prior to execution
#        when running under Windows Subsystem for Linux (WSL).
# @retval 0 Command successfully launched in the background.
# @retval 1 No command provided (usage error).
#

runner_launch() {

	# Check if a command is provided
	if [ -z "$1" ]; then
		echo "Usage: runner_launch <command> [args...]"
		return 1
	fi

	# Extract the command and shift the arguments
	command="$1"
	shift

	# Check if running under WSL
	if [[ "$(runner_get_distro)" == "wsl" ]]; then
		# Check if W: is accessible
		if ! powershell.exe -Command "Test-Path W:\\" | grep -q True; then
			echo "Error: W: drive not found. Ensure it is correctly mapped."
			return 1
		fi

		converted_args=()
		for arg in "$@"; do
			# Resolve the full path
			full_path=$(realpath "$arg" 2>/dev/null)
			if [[ -f "$full_path" || -d "$full_path" ]]; then
				# Replace \\wsl.localhost\IMCv2\ with W:\
				win_path=$(wslpath -w "$full_path")
				win_path="${win_path/\\\\wsl.localhost\\IMCv2\\/W:\\}" 
				converted_args+=("$win_path")
			else
				converted_args+=("$arg")
			fi
		done

		# Run the command with converted arguments
		(
			nohup "$command" "${converted_args[@]}" >/dev/null 2>&1 &
			echo $! >/tmp/topolbox_launch_pid
		) &>/dev/null
	else
		# Run the command as usual
		(
			nohup "$command" "$@" >/dev/null 2>&1 &
			echo $! >/tmp/topolbox_launch_pid
		) &>/dev/null
	fi

}

#
# @brief Detect the current user's shell.
# Extracts the current user's shell by reading the /etc/passwd
# file using the getent command. It returns an appropriate code based on the
# detected shell.
# @return 0 if Bash, 1 if Zsh, 2 if unknown or other shell.
#

runner_getshell() {

	local user_shell

	# Try getting the active shell using the ps method
	parent_shell=$(ps -p $PPID -o comm= | grep -E 'bash|zsh' || echo "$SHELL")
	user_shell=$(basename "$parent_shell")

	# If the ps command doesn't return a shell, fall back to getent
	if [ -z "$user_shell" ]; then
		user_shell=$(getent passwd "$(whoami)" | cut -d: -f7)
	fi

	case "$user_shell" in
	zsh)
		return 1 # Zsh
		;;
	bash)
		return 0 # Bash
		;;
	sh)
		return 0 # Jenkins runs sh, which is a subset of bash
		;;
	*)
		printf "$Error: Shell ${user_shell} is not supported\n"
		return 2 # Unknown or other shell
		;;
	esac
}

#
# @brief Configures Kerberos by authenticating a user with a given username and password.
# @param username The username to authenticate.
# @param password The password for the provided username.
# @param realm    (Optional) The Kerberos realm.
# @return 0 on success, 1 on failure.
#

runner_configure_kerberos() {

	local username="$1"
	local password="$2"
	local realm="${3:-GER.CORP.INTEL.COM}" # Default to GER.CORP.INTEL.COM if not provided

	# Ensure all arguments are provided
	if [[ -z "$username" || -z "$password" ]]; then
		return 1 # Exit silently if arguments are missing
	fi

	# Ensure required package is installed (silent installation)
	sudo apt install -y krb5-user >/dev/null 2>&1 || return 1

	# Set correct permissions for /etc/krb5.conf (silent)
	sudo chmod 644 /etc/krb5.conf >/dev/null 2>&1 || return 1
	sudo chown root:root /etc/krb5.conf >/dev/null 2>&1 || return 1

	# Use expect to automate 'kinit'
	expect <<EOF >/dev/null 2>&1
spawn kinit ${username}@${realm}
expect {
    "Password for ${username}@${realm}:" {
        send "${password}\r"
        exp_continue
    }
    "kinit: Password incorrect" {
        exit 1
    }
    eof {
        exit 0
    }
}
EOF

	# Return the exit code from expect
	return $?
}

#
# @brief Generates the .gitconfig file based on the provided template.
# @param[in] 1 Template name (path to the template file).
# @param[in] 2 Full name (may contain spaces).
# @param[in] 3 Email address.
# @return 0 if successful, 1 otherwise.
#

runner_create_git_config() {

	local template_name="${1:-/home/$USER/.imcv2/imcv2_git_config.template}" # Use if not provided
	local corp_name="${2:-$IMCV2_FULL_NAME}"                                 # Default to the exported corp. full name
	local corp_email="${3:-$IMCV2_EMAIL}"                                    # Default to the exported corp. email address
	local git_config_file="/home/$USER/.gitconfig"

	# Ensure $http_proxy is set
	if [[ -z "$http_proxy" ]]; then
		printf "Error: Proxy environment variable is not set.\n"
		return 1
	fi

	# Check if the template exists
	if [[ ! -f "$template_name" ]]; then
		return 0
	fi

	# Generate the .gitconfig file by replacing placeholders
	sed -e "s|{proxy_server_port}|$http_proxy|g" \
		-e "s|{corp_email}|$corp_email|g" \
		-e "s|{corp_name}|$corp_name|g" \
		"$template_name" >"$git_config_file"

	# Check if the output git configuration was created successfully.
	if [[ $? -eq 0 && -f "$git_config_file" ]]; then
		return 0
	else
		printf "Error: Failed to create git configuration file.\n"
		return 1
	fi
}

#
# @brief Ensures the auto-start configuration for IMCv2 SDK is correctly pinned at
#        the end of the user's rc file (bash / zsh)
# @details
# - Detects the current script path dynamically.
# - Ensures no duplicate entries in the shell 'rc' file.
# - Appends the auto-start configuration in a clean and predictable way.
# @return 0 if the desired lines are already correctly positioned, 1 otherwise.
#

runner_pin_auto_start() {

	local script_path="${1:-/home/$USER/.imcv2/bin/imcv2_sdk_runner.sh}" # Use if not provided
	local marker="# IMCv2 SDK Auto-start."

	# Determine which RC file to use based on the shell
	runner_getshell
	shell_type=$?

	if [ "$shell_type" -eq 0 ]; then
		rc_file="$HOME/.bashrc"
	elif [ "$shell_type" -eq 1 ]; then
		rc_file="$HOME/.zshrc"
	else
		# Unsupported shell
		return 1
	fi

	# Construct the expected content
	local expected_content="$marker
$script_path"

	# Check if the last lines of the shell '.rc' file match the expected content
	if tail -n 2 "$rc_file" | grep -Fxq "$expected_content"; then
		return 0 # Already correctly positioned
	fi

	# If the marker exists elsewhere, remove it
	if grep -Fxq "$marker" "$rc_file"; then
		sed -i "/^$marker$/,/^\/home\/.*\/imcv2_sdk_runner.sh$/d" "$rc_file"
	fi

	# Append the content to the end of the file
	echo -e "\n$expected_content" >>"$rc_file"
	return 0 # Done
}

#
# @brief Ensures the 'dt' (devtool) tool is installed and configured for use.
# Checks if 'dt' is available and attempts to retrieve a GitHub token.
# If the token is unavailable, it guides the user through the setup process.
# @return 0 if 'dt' is installed and a token is retrieved, 1 otherwise.
#

runner_ensure_dt() {

	local dt_path="/home/$USER/bin/dt"
	local netrc_path="/home/$USER/.netrc"
	local github_url="https://github.com/intel-innersource/firmware.ethernet.imcv2"
	local dt_tool_url="https://gfx-assets.intel.com/artifactory/gfx-build-assets/build-tools/devtool-go/latest/artifacts/linux64/dt"
	local dt_download_path="$HOME/Downloads/dt"
	local setup_exit_code

	# Define ANSI color codes
	local yellow="\033[93m"
	local light_blue="\033[94m"
	local bright_white="\033[1;37m"
	local reset="\033[0m"

	# Check for .netrc and attempt to get a token
	if [[ -f "$netrc_path" ]]; then
		token=$("$dt_path" github print-token "$github_url" 2>/dev/null)
		if [[ -n "$token" ]]; then
			export PATH="/home/$USER/bin:$PATH"
			return 0
		fi
	fi

	# If no .netrc or token could not be generated
	# Print welcome message
	clear
	printf "\nIMCv2 'dt' Installer.\n"
	printf -- "---------------------\n\n"
	printf "'dt' is essential for enabling this WSL instance to access ${light_blue}Intel${reset} internal resources.\n"
	printf " ${bright_white}•${reset} Ensure you have access to ${yellow}https://github.com/intel-innersource${reset}\n"
	printf " ${bright_white}•${reset} Accept defaults when prompted.\n"
	printf " ${bright_white}•${light_blue} Tip${reset}: URLs in the terminal can be opened using Ctrl + Click.\n\n"

	# Check if 'dt' is installed
	if [[ ! -f "$dt_path" ]]; then

		# Get it silently
		curl -s -S --noproxy '*' -k -L "$dt_tool_url" -o "$dt_download_path" 2>/dev/null

		# Check if download went OK
		if [[ $? -ne 0 || ! -f "$dt_download_path" ]]; then
			printf "Error: Failed to download 'dt'.\n"
			return 1
		fi

		# Make it executable
		chmod +x "$dt_download_path" 2>/dev/null
		if [[ $? -ne 0 ]]; then
			printf "Error: Failed to make 'dt' executable.\n"
			return 1
		fi

		# Execute 'dt' for installation
		"$dt_download_path" install >/dev/null 2>&1
		if [[ $? -ne 0 ]]; then
			printf "Error: 'dt' could not be installed.\n"
			return 1
		fi
	fi

	# PLace defaults in the git config file,
	# This could help in reducing user prompts.
	runner_create_git_config

	"$dt_path" setup
	# "$dt_path" setup github-auth --force
	local setup_exit_code=$?

	# Delete 'dt' installer once we're done with it.
	rm -rf "$dt_download_path" 2>/dev/null

	# Attempt to generate token again
	token=$("$dt_path" github print-token "$github_url" 2>/dev/null)
	if [[ -n "$token" ]]; then
		export PATH="/home/$USER/bin:$PATH"

		# Make sure auto run is the last line
		runner_pin_auto_start

		# 'dt' probably forced some Proxy server into the .gitconfig.
		# This will ensure that the proxy used by git is aligned with our environment.
		runner_create_git_config
		return 0
	fi

	# Delete any residual leftovers generated by 'dt' in the hope that another
	# attempt will fix the issue.
	rm -rf "$netrc_path" 2>/dev/null

	# Return the error exit code of the setup command
	return "$setup_exit_code"
}

#
# @brief Installs or uninstalls the SDK at the specified path.
# @param[in] 1 Action: "install" or "uninstall" (mandatory).
# @param[in] 2 Destination path (mandatory).
# @param[in] 3 Force flag (optional, default 0).
# @return Exit code of the curl command during installation, or 0/1 for uninstall.
#

runner_install_sdk() {

	local action="$1"
	local destination_path="$2"
	local force="${3:-0}"                 # Default to 0 if not provided
	local netrc_path="/home/$USER/.netrc" # 'dt' auto-login file.
	local exit_code=0

	# Check mandatory arguments
	if [[ -z "$action" || -z "$destination_path" ]]; then
		printf "Error: Both action and destination path are required.\n"
		return 1
	fi

	# Force only safe paths
	if [[ "$destination_path" != "/home/$USER" && "$destination_path" != /home/$USER/* ]]; then
		printf "Error: Destination path must be under /home/$USER.\n"
		return 1
	fi

	case "$action" in
	uninstall)
		if [[ -d "$destination_path" ]]; then
			rm -rf "$destination_path" >/dev/null 2>&1
			if [[ $? -eq 0 ]]; then
				return 0
			else
				printf "Error: Failed to uninstall from $destination_path.\n"
				return 1
			fi
		else
			printf "No existing installation found at $destination_path.\n"
			return 0
		fi
		;;
	install)
		# Handle existing path without force flag
		if [[ -d "$destination_path" && "$force" -eq 0 ]]; then
			return 1
		fi
		# Handle existing path with force flag
		if [[ -d "$destination_path" && "$force" -eq 1 ]]; then
			runner_install_sdk "uninstall" "$destination_path" || return 1
		fi

		# Create the destination path
		mkdir -p "$destination_path" >/dev/null 2>&1
		if [[ $? -ne 0 ]]; then
			printf "Error: Failed to create destination path: $destination_path.\n"
			return 1
		fi

		# Change to the destination path
		cd "$destination_path" || {
			printf "Error: Failed to change to destination path: $destination_path.\n"
			return 1
		}

		# Attempt to fetch and execute the SDK 'bootstrap', capturing curl's stdout and stderr separately.
		curl_output=$(mktemp)
		curl_error=$(mktemp)

		http_status=$(curl -sSL \
			-H "Authorization: token $(dt github print-token https://github.com/intel-innersource/firmware.ethernet.imcv2 2>/dev/null)" \
			-H "Cache-Control: no-store" \
			-w "%{http_code}" -o "$curl_output" \
			"https://raw.githubusercontent.com/intel-innersource/firmware.ethernet.imcv2/main/scripts/imcv2_boot_strap.sh" 2>"$curl_error")

		# Check the HTTP status code
		if [[ "$http_status" -ne 200 ]]; then

			printf "\nSDK Installer Error: Failed to fetch 'bootstrap' with HTTP status $http_status.\n"
			printf "This typically indicates a problem with the token generated by 'dt'.\n"
			printf "WSL will be restarted, and 'dt' setup will start automatically.\n"

			# Delete the file generated by 'dt', which will force 'dt' to run its setup after reopening the terminal.
			rm -f "$netrc_path" >/dev/null 2>&1
			rm -f "$curl_output" "$curl_error" >/dev/null 2>&1
			sleep 3
			runner_wsl_reset
			exit "$http_status"
		fi

		# Execute the downloaded script
		bash "$curl_output" -s -- -b main
		exit_code=$?

		if [[ $exit_code -eq 0 ]]; then

			# SDK installed. Export the path now so we can immediately patch
			# the missing Simics installation folder.
			export IMCV2_INSTALL_PATH="$destination_path"
		else
			printf "\n\nSDK installation failed with exit code $exit_code.\n"
			printf "Typically, it's a network issue related to Intel's proxy.\n"
			printf "Your environment proxy settings are: $http_proxy\n\n"
			printf "Auto-runner will keep on trying until the SDK is installed.\n"
			printf "Simply close this window and reopen it to try again.\n"
		fi

		# Clean up temporary files
		rm -f "$curl_output" "$curl_error"
		return "$exit_code"
		;;
	*)
		printf "Error: Invalid action: $action. Use 'install' or 'uninstall'.\n"
		return 1
		;;
	esac
}

#
# @brief Resets the WSL instance by restarting the WSL session.
# @return Always returns 0.
#

runner_wsl_reset() {

	wt.exe -w 0 -p "$WSL_DISTRO_NAME" -- wsl.exe &&
		wsl.exe --terminate "$WSL_DISTRO_NAME" &&
		wsl.exe
	return 0
}

#
# @brief Currently, WSL does not have access to the /mnt/ci_tools mount, which is available out of
#        the box on the automatons. Therefore, we need to create it manually. The steps are as follows:
#        1. Determine where the SDK is installed and verify if it contains the expected extern/tools directory.
#        2. Temporary step: Switch the Git branch to one that contains the installer split into several tar.gz fragments.
#        3. [Provide a description for step 3 if applicable].
#
# @return 0 if successful, 1 otherwise.
#

runner_place_simics_installer() {

	local verbose_mode=0
	local sdk_tools_dir
	local sdk_ci_tools_dir
	local sdk_default_path="/home/$USER/projects/sdk/workspace"
	local download_path="${HOME}/Downloads"
	local simics_compressed_file="simics_installer.tar.gz"
	local extract_path="/mnt/ci_tools/intel-simics-package-manager"
	local simics_folder_name="intel-simics-package-manager-1.7.0-intel-internal"
	local assembled_install_file="${download_path}/${simics_compressed_file}"

	# Parse arguments
	while [[ $# -gt 0 ]]; do
		case "$1" in
		-v | --verbose)
			verbose_mode=1
			shift
			;;
		*)
			echo "Unknown argument: $1"
			return 1
			;;
		esac
	done

	# Helper function for conditional echo
	log() {
		if [[ $verbose_mode -eq 1 ]]; then
			printf "IMCv2 Simics Installer: %s\n" "$*"
		fi
	}

	# Check if we have a default project defined
	if [[ -n "$IMCV2_INSTALL_PATH" && -d "$IMCV2_INSTALL_PATH" ]]; then
		# Define sdk_tools_dir
		sdk_tools_dir="${IMCV2_INSTALL_PATH}/externs/tools"
		log "SDK Tools directory: $sdk_tools_dir"

		# Check if the SDK tools path exists
		if [[ ! -d "$sdk_tools_dir" ]]; then
			log "Error: Could not find the SDK externs-tools path."
			return 1
		fi
	else
		log "Warning: SDK variables not exported, trying defaults."

		# SDK variables not exported, try default path
		if [[ -e "$sdk_default_path" ]]; then
			# Found something in the default path
			sdk_tools_dir="${sdk_default_path}/externs/tools"
			log "SDK Tools directory: $sdk_tools_dir"

			if [[ ! -d "$sdk_tools_dir" ]]; then
				log "Error: Could not find the SDK externs-tools path in the default path."
				return 1
			fi
		else
			log "Error: Could not find an SDK instance in the default path."
			return 1
		fi
	fi

	# Go to tools directory
	cd "$sdk_tools_dir" || {
		log "Error: Cannot access SDK tools directory."
		return 1
	}

	sdk_ci_tools_dir="$sdk_tools_dir/CI_Tools/wsl_support"

	# Step 2: Switch to em_wsl_simics branch
	git checkout em_wsl_simics >/dev/null 2>&1 || {
		log "Error: Failed to switch branch"
		return 1
	}
	log "Switched to branch: 'em_wsl_simics'."

	# Pull latest changes
	git pull >/dev/null 2>&1 || {
		log "Error: Failed to pull latest changes."
		return 1
	}
	log "Pulled latest changes"

	# Check for the required tools directory
	if [[ ! -d "$sdk_ci_tools_dir" ]]; then
		log "Error: Simics installer for WSL path not found (${sdk_ci_tools_dir})"
		return 1
	fi
	log "CI tools directory: $sdk_ci_tools_dir."

	# Assemble the parts
	cat "$sdk_ci_tools_dir"/part* >"$assembled_install_file" 2>/dev/null || {
		log "Error: Failed to assemble installer"
		return 1
	}
	log "Installer assembled: $assembled_install_file."

	# Extract the assembled install archive file
	cd "$download_path" || {
		log "Error: Cannot access '$download_path' directory."
		return 1
	}
	tar -xzf "$simics_compressed_file" >/dev/null 2>&1 || {
		log "Error: Failed to decompress installer archive."
		return 1
	}
	log "Installer extracted."

	# Remove and create installation path and move files
	rm -rf $extract_path >/dev/null 2>&1
	sudo mkdir -p "$extract_path" || {
		log "Error: Failed to create '$extract_path' directory."
		return 1
	}
	sudo mv "$simics_folder_name" "$extract_path" >/dev/null 2>&1 || {
		log "Error: Failed to move '$simics_folder_name' to '$extract_path'."
		return 1
	}
	log "Files ware moved to: '$extract_path'."

	# Step 8: Change ownership of ci_tools
	sudo chown -R "$USER" /mnt/ci_tools >/dev/null 2>&1 || {
		log "Error: (Root) Failed to change ownership."
		return 1
	}
	log "Ownership changed for: '/mnt/ci_tools'."

	# Quiet cleanup
	rm -rf "$assembled_install_file" >/dev/null 2>&1
	rm -rf "$download_path"/simics_folder_name >/dev/null 2>&1

	return 0
}

#
# @brief Main entry point for the script.
# @details
# - Sets up the IMCv2 environment by creating Git configuration,
#   ensuring 'dt' are installed, installing the SDK if needed,
#   and pinning the auto-start configuration.
# @param "$@" Command-line arguments passed to the script.
# @return 0 on success, propagates the return value of runner_install_sdk otherwise.
#

main() {

	local sdk_install_path="/home/$USER/projects/sdk/workspace"
	local ansi_cyan="\033[96m"
	local ansi_reset="\033[0m"
	local ansi_yellow="\033[93m"
	local ret_val=0

	# Disable globbing in Zsh to avoid issues with -? and --?
	setopt noglob 2>/dev/null

	# Display usage if -h or --help is provided
	if [ "$#" -eq 1 ] && { [ "$1" = "-h" ] || [ "$1" = "-help" ] || [ "$1" = "--h" ] || [ "$1" = "--help" ]; }; then
		printf "\nIMCv2 Auto-Runner usage:\n\n"
		printf "  -p, --pin_shell          Insert this script to the shell startup and exit.\n"
		printf "  -s, --get_simics         Install Simics locally and exit.\n"
		printf "  -k, --set_kerberos       Configure Kerberos and exit.\n"
		printf "  -g, --git_config         Apply Git configuration and exit.\n"
		printf "  -i, --install_path PATH  Override default SDK install path.\n"
		printf "  -l, --launch             General purpose WSL specific launcher.\n"
		printf "  -v, --ver                Prints the 'IMCv2 Runner' script version and exit.\n"
		printf "  -r, --restart_wsl        Restart the WSL Session.\n"
		printf "\n"
		exit 0
	fi
	# Re-enable globbing in Zsh if needed later in the script
	setopt glob 2>/dev/null

	# Parse command-line arguments
	while [[ $# -gt 0 ]]; do
		case "$1" in
		-p | --pin_shell)
			shift
			# Pin auto start script to the shell rc file and exit.
			runner_pin_auto_start "$@" || ret_val=$?
			exit $ret_val
			;;
		-s | --get_simics)
			shift
			runner_place_simics_installer "$@" || ret_val=$?
			exit $ret_val
			;;
		-k | --set_kerberos)
			shift
			runner_configure_kerberos "$@" || ret_val=$?
			if [[ $ret_val -eq 0 ]]; then
				echo "Kerberos setup succeeded."
			else
				echo "Kerberos setup failed."
			fi
			exit $ret_val
			;;
		-g | --git_config)
			shift
			runner_create_git_config || ret_val=$?
			exit $ret_val
			;;
		-r | --restart_wsl)
			shift
			runner_wsl_reset
			exit 0
			;;
		-l | --launch)
			shift
			runner_launch "$@" || ret_val=$?
			exit $ret_val
			;;
		-v| --ver)
			shift
			printf "IMCv2 Runner version ${script_version}\n" 
			exit 0
			;;
		-i | --install_path)
			shift
			if [[ $# -eq 0 ]]; then
				echo "Error: Missing value for --install_path."
				exit 1
			fi
			if [[ $# -gt 1 ]]; then
				echo "Error: Too many values for --install_path."
				exit 1
			fi
			sdk_install_path="$1"
			shift
			;;
		*)
			echo "Unknown argument: $1"
			echo "Use $0 --help for usage details."
			exit 1
			;;
		esac
	done

	# Clear the screen
	clear
	echo -e "\033[?25h"

	# Make sure we're last in startup shell script
	runner_pin_auto_start

	# Display version information
	printf "\nIMCv2 WSL Auto-runner version ${ansi_cyan}${script_version}${ansi_reset}\n"
	printf -- "---------------------------------\n\n"

	# Install the IMCv2 SDK if needed
	if [[ -z "${IMCV2_INSTALL_PATH}" || ! -d "${IMCV2_INSTALL_PATH}" ]]; then

		# First, ensure 'dt' is installed
		if runner_ensure_dt; then

			# Now, install the latest SDK , fail if exist!
			runner_install_sdk install "$sdk_install_path" 0 || ret_val=$?

			if [[ ret_val -eq 0 ]]; then

				# Add 'Simics' installer to /mnt/ci_tools: a WSL specific step.
				runner_place_simics_installer || ret_val=$?
				if [[ ret_val -ne 0 ]]; then
					printf "${ansi_yellow}Warning${ansi_reset}: 'Simics' local installer step did not complete.\n"
				else
					# Make sure we're last in startup shell script
					runner_pin_auto_start

					printf "Restarting... "
					sleep 2
					runner_wsl_reset
				fi

			fi

		else
			printf "Error: Failed to ensure 'dt' success installation.\n"
			printf "Auto-runner will keep on trying until the SDK is installed.\n"
			printf "Simply close this window and reopen it to try again.\n"
			ret_val=1
		fi
	else
		printf "Type '${ansi_yellow}im${ansi_reset}' to start the SDK.\n"
	fi

	printf "\n"
	exit $ret_val
}

#
# @brief Invoke the main function with command-line arguments.
# @return The exit status of the main function.
#

main "$@"
exit $?
