#!/bin/bash
# shellcheck disable=SC2317
# shellcheck disable=SC2059
# shellcheck disable=SC2181
# Formatting: shfmt -i 0 -w imcv2_sdk_runner.sh

# ------------------------------------------------------------------------------
#
# Script Name:  imcv2_sdk_runner.sh
# Description:  IMCv2 SDK auto starter.
# Version:      1.5
# Copyright:    2024 Intel Corporation.
# Author:       Intel IMCv2 Team.
#
# ------------------------------------------------------------------------------

# Script global variables
script_version="1.5"

#
# @brief Generates the .gitconfig file based on the provided template.
# @param[in] 1 Template name (path to the template file).
# @param[in] 2 Full name (may contain spaces).
# @param[in] 3 Email address.
# @return 0 if successful, 1 otherwise.
#

runner_create_git_config() {

	local template_name="$1"
	local full_name="$2"
	local email_address="$3"
	local output_file="/home/$USER/.gitconfig"

	# Ensure $http_proxy is set
	if [[ -z "$http_proxy" ]]; then
		echo "Error: \$http_proxy environment variable is not set."
		return 1
	fi

	# Check if the template exists
	if [[ ! -f "$template_name" ]]; then
		return 0
	fi

	# Generate the .gitconfig file by replacing placeholders
	sed -e "s|{proxy_server_port}|$http_proxy|g" \
		-e "s|{corp_email}|$email_address|g" \
		-e "s|{corp_name}|$full_name|g" \
		"$template_name" >"$output_file"

	# Check if the output file was created successfully, if so delete the template
	# to prevent future modifications.
	if [[ $? -eq 0 && -f "$output_file" ]]; then
		rm -f "$template_name" >/dev/null 2>&1
		return 0
	else
		echo "Error: Failed to create git configuration file."
		return 1
	fi
}

#
# @brief Ensures the auto-start configuration for IMCv2 SDK is correctly pinned at the end of the user's .bashrc file.
#
# This function appends the necessary lines to .bashrc to ensure the IMCv2 SDK runner script
# is executed on shell startup. If the lines are already present but not at the end, they
# are moved to the end of the file.
#
# @details
# - Detects the current script path dynamically.
# - Ensures no duplicate entries in .bashrc.
# - Appends the auto-start configuration in a clean and predictable way.
# @return 0 if the desired lines are already correctly positioned, 1 otherwise.
#

runner_pin_auto_start() {

	local bashrc_file="$HOME/.bashrc"
	local marker="# IMCv2 SDK Auto start."
	local script_path="${BASH_SOURCE[0]}" # Dynamically get the current script path

	# Construct the expected content
	local expected_content="$marker
$script_path"

	# Check if the last lines of the .bashrc file match the expected content
	if tail -n 2 "$bashrc_file" | grep -Fxq "$expected_content"; then
		return 0 # Already correctly positioned
	fi

	# If the marker exists elsewhere, remove it
	if grep -Fxq "$marker" "$bashrc_file"; then
		sed -i "/^$marker$/,/^\/home\/.*\/imcv2_sdk_runner.sh$/d" "$bashrc_file"
	fi

	# Append the content to the end of the file
	echo -e "\n$expected_content" >>"$bashrc_file"
	return 1 # Modifications were made
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
	local dt_download_path="$HOME/downloads/dt"

	# Define ANSI color codes
	yellow="\033[93m"
	light_blue="\033[94m"
	bright_white="\033[1;37m"
	reset="\033[0m"

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
	printf " ${bright_white}•${reset} Accept defaults when prompted.\n\n"

	# Check if 'dt' is installed
	if [[ ! -f "$dt_path" ]]; then

		# Get it silently
		curl -s -S --noproxy '*' -k -L "$dt_tool_url" -o "$dt_download_path" 2>/dev/null

		# Check if download went OK
		if [[ $? -ne 0 || ! -f "$dt_download_path" ]]; then
			printf "Error: Failed to download 'dt' tool\n"
			return 1
		fi

		# Make it executable
		chmod +x "$dt_download_path" 2>/dev/null
		if [[ $? -ne 0 ]]; then
			printf "Error: Failed to make 'dt' executable\n"
			return 1
		fi

		# Execute 'dt' for installation
		"$dt_download_path" install >/dev/null 2>&1
		if [[ $? -ne 0 ]]; then
			printf "Error: 'dt' could not be installed\n"
			return 1
		fi
	fi

	"$dt_path" setup
	local setup_exit_code=$?

	# Cleanup
	rm -rf "$dt_download_path" 2>/dev/null

	# Make sure auto run is the last line
	runner_pin_auto_start

	# Attempt to generate token again
	token=$("$dt_path" github print-token "$github_url" 2>/dev/null)
	if [[ -n "$token" ]]; then
		export PATH="/home/$USER/bin:$PATH" \
			return 0
	fi

	# Return the exit code of the setup command if the token still could not be generated
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
	local force="${3:-0}" # Default to 0 if not provided

	# Check mandatory arguments
	if [[ -z "$action" || -z "$destination_path" ]]; then
		echo "Error: Both action and destination path are required."
		return 1
	fi

	# Force only safe paths
	if [[ "$destination_path" != "/home/$USER" && "$destination_path" != /home/$USER/* ]]; then
		echo "Error: Destination path must be under /home/$USER"
		return 1
	fi

	case "$action" in
	uninstall)
		if [[ -d "$destination_path" ]]; then
			rm -rf "$destination_path" >/dev/null 2>&1
			if [[ $? -eq 0 ]]; then
				return 0
			else
				echo "Error: Failed to uninstall from $destination_path."
				return 1
			fi
		else
			echo "No existing installation found at $destination_path."
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
			echo "Error: Failed to create destination path: $destination_path"
			return 1
		fi

		# Change to the destination path
		cd "$destination_path" || {
			echo "Error: Failed to change to destination path: $destination_path"
			return 1
		}

		# Run the curl command to fetch and execute the bootstrap script
		curl -sSL \
			-H "Authorization: token $(dt github print-token https://github.com/intel-innersource/firmware.ethernet.imcv2 2>/dev/null)" \
			-H "Cache-Control: no-store" \
			"https://raw.githubusercontent.com/intel-innersource/firmware.ethernet.imcv2/main/scripts/imcv2_boot_strap.sh" | bash -s -- -b main
		local exit_code=$?

		if [[ $exit_code -eq 0 ]]; then
			# SDK installed. Export the path now so we can immediately patch the missing Simics installation folder.
			export IMCV2_INSTALL_PATH="$destination_path"

			# Retrieve the Simics installation into /mnt/ci_tools to align with the Automation setup.
			runner_place_simics_installer
			exit_code=$?

			# Return the exit code from the Simics installer function.
			return $exit_code
		else
			printf "\n\nThe SDK installation failed with exit code $exit_code.\n"
			printf "This WSL instance will keep trying, simply close this window and reopen it to try again.\n"
		fi
		return "$exit_code"
		;;
	*)
		echo "Error: Invalid action: $action. Use 'install' or 'uninstall'."
		return 1
		;;
	esac
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
	local download_path="${HOME}/downloads"
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
		log "Tools directory: $sdk_tools_dir"

		# Check if sdk_tools_dir exists
		if [[ ! -d "$sdk_tools_dir" ]]; then
			log "Error: Could not find the SDK externs-tools path"
			return 1
		fi
	else
		log "Error: Could not find an SDK instance."
		return 1
	fi

	# Go to tools directory
	cd "$sdk_tools_dir" || {
		log "Error: Cannot access SDK tools directory"
		return 1
	}

	sdk_ci_tools_dir="$sdk_tools_dir/CI_Tools/wsl_support"

	# Step 2: Switch to em_wsl_simics branch
	git checkout em_wsl_simics >/dev/null 2>&1 || {
		log "Error: Failed to switch branch"
		return 1
	}
	log "Switched to branch: 'em_wsl_simics'"

	# Pull latest changes
	git pull >/dev/null 2>&1 || {
		log "Error: Failed to pull latest changes"
		return 1
	}
	log "Pulled latest changes"

	# Check for the required tools directory
	if [[ ! -d "$sdk_ci_tools_dir" ]]; then
		log "Error: Simics installer for WSL path not found (${sdk_ci_tools_dir})"
		return 1
	fi
	log "CI tools directory: $sdk_ci_tools_dir"

	# Assemble the parts
	cat "$sdk_ci_tools_dir"/part* >"$assembled_install_file" 2>/dev/null || {
		log "Error: Failed to assemble installer"
		return 1
	}
	log "Installer assembled: $assembled_install_file"

	# Extract the assembled install archive file
	cd "$download_path" || {
		log "Error: Cannot access download directory"
		return 1
	}
	tar -xzf "$simics_compressed_file" >/dev/null 2>&1 || {
		log "Error: Failed to extract installer"
		return 1
	}
	log "Installer extracted"

	# Remove and create installation path and move files
	rm -rf $extract_path >/dev/null 2>&1
	sudo mkdir -p "$extract_path" || {
		log "Error: Failed to create installation directory"
		return 1
	}
	sudo mv "$simics_folder_name" "$extract_path" >/dev/null 2>&1 || {
		log "Error: Failed to move $simics_folder_name to $extract_path"
		return 1
	}
	log "Files moved to: $extract_path"

	# Step 8: Change ownership of ci_tools
	sudo chown -R "$USER" /mnt/ci_tools >/dev/null 2>&1 || {
		log "Error: Failed to change ownership"
		return 1
	}
	log "Ownership changed for: /mnt/ci_tools"

	# Quiet cleanup
	rm -rf "$assembled_install_file" >/dev/null 2>&1
	rm -rf "$download_path"/simics_folder_name >/dev/null 2>&1

	return 0
}
#
# @brief Main entry point for the script.
# @details
# - Sets up the IMCv2 environment by creating Git configuration,
#   ensuring devtools are installed, installing the SDK if needed,
#   and pinning the auto-start configuration.
# @see https://en.wikipedia.org/wiki/Entry_point
# @param "$@" Command-line arguments passed to the script.
# @return 0 on success, propagates the return value of runner_install_sdk otherwise.
#

main() {

	local git_template_path="/home/$USER/downloads/imcv2_git_config.template"
	local sdk_install_path="/home/$USER/projects/sdk/workspace"
	local result=0
	local ansi_cyan="\033[96m"
	local ansi_reset="\033[0m"
	local patch_mode=0 # Flag for patch mode

	# Parse command-line arguments
	while [[ $# -gt 0 ]]; do
		case "$1" in
		-p | --patch)
			patch_mode=1
			shift
			;;
		-s | --get_simics)
			# Install Simics locally
			shift
			runner_place_simics_installer "$@"
			exit $?
			;;
		*)
			echo "Unknown argument: $1"
			exit 1
			;;
		esac
	done

	# If patch mode is enabled, execute runner_pin_auto_start and return
	if [[ $patch_mode -eq 1 ]]; then
		runner_pin_auto_start
		return 0
	fi

	# Clear the screen and restore the cursor
	clear
	echo -e "\033[?25h"

	# Display version information
	printf "\nIMCv2 WSL Autorun version ${ansi_cyan}${script_version}${ansi_reset}.\n"
	printf -- "------------------------------\n\n"

	# Create Git configuration
	runner_create_git_config "$git_template_path" "$IMCV2_FULL_NAME" "$IMCV2_EMAIL"

	# Ensure devtools are installed
	if runner_ensure_dt; then

		# Pin the auto-start configuration
		runner_pin_auto_start

		# Install the IMCv2 SDK if not installed
		if [[ -z "${IMCV2_INSTALL_PATH}" || ! -d "${IMCV2_INSTALL_PATH}" ]]; then
			runner_install_sdk install "$sdk_install_path" 1
			result=$?
		else
			printf "Type 'im' to star the SDK.\n"
		fi
	fi

	runner_pin_auto_start
	printf "\n"

	# Return the captured result
	return $result
}

#
# @brief Invoke the main function with command-line arguments.
# @return The exit status of the main function.
#

main "$@"
exit $?
