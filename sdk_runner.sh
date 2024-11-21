#!/bin/bash

#
# @brief Generates the .gitconfig file based on the provided template.
# @param[in] 1 Template name (path to the template file).
# @param[in] 2 Full name (may contain spaces).
# @param[in] 3 Email address.
#
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
		echo "Error: Template file '$template_name' not found."
		return 1
	fi

	# Generate the .gitconfig file by replacing placeholders
	sed -e "s|{proxy_server_port}|$http_proxy|g" \
		-e "s|{corp_email}|$email_address|g" \
		-e "s|{corp_name}|$full_name|g" \
		"$template_name" >"$output_file"

	# Check if the output file was created successfully
	if [[ $? -eq 0 && -f "$output_file" ]]; then
		echo "Git configuration file created successfully: $output_file"
		return 0
	else
		echo "Error: Failed to create git configuration file."
		return 1
	fi
}

##
# @brief Ensures the 'dt' (devtool) tool is installed and configured for use.
#
# Checks if 'dt' is available and attempts to retrieve a GitHub token.
# If the token is unavailable, it guides the user through the setup process.
# @return 0 if 'dt' is installed and a token is retrieved, 1 otherwise.
#

runner_ensure_dt() {

	local dt_path="/home/$USER/bin/dt"
	local netrc_path="/home/$USER/.netrc"
	local github_url="https://github.com/intel-innersource/firmware.ethernet.imcv2"
	local clear_screen_cmd="clear"

	# Define ANSI color codes
	yellow="\033[93m"
	light_blue="\033[94m"
	red="\033[91m"
	reset="\033[0m"
	bright_white="\033[97m"

	# Check if 'dt' is installed
	if [[ ! -f "$dt_path" ]]; then
		echo "Error: 'dt' (devtool) is not installed. Please install it to proceed."
		return 1
	fi

	# Check for .netrc and attempt to get a token
	if [[ -f "$netrc_path" ]]; then
		token=$("$dt_path" github print-token "$github_url" 2>/dev/null)
		if [[ -n "$token" ]]; then
			return 0
		fi
	fi

	# If no .netrc or token could not be generated
	$clear_screen_cmd
	# Print the message
	printf "\n\n${bright_white}IMCv2${reset} Installer, welcome to '${yellow}dt${reset}' (devtool) setup.\n"
	echo -------------------------------------------------

	printf "\nThis tool is an essential for enabling this WSL instance to\n"
	printf "access ${light_blue}Intel${reset} inner sources, including the ${bright_white}IMCv2${reset} repository.\n"
	printf "${yellow}Note:${reset} You need a registered GitHub account and must have completed\n"
	printf "all onboarding steps: https://1source.intel.com/onboard\n\n"

	"$dt_path" setup github-auth --force
	local setup_exit_code=$?

	# Attempt to generate token again
	token=$("$dt_path" github print-token "$github_url" 2>/dev/null)
	if [[ -n "$token" ]]; then
		return 0
	fi

	# Return the exit code of the setup command if the token still could not be generated
	return $setup_exit_code
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

	# Guard against dangerous paths
	if [[ "$destination_path" == "/" || "$destination_path" == "/dev" || "$destination_path" == "/home" ]]; then
		echo "Error: Unsafe destination path: $destination_path"
		return 1
	fi

	case "$action" in
	uninstall)
		if [[ -d "$destination_path" ]]; then
			rm -rf "$destination_path" >/dev/null 2>&1
			if [[ $? -eq 0 ]]; then
				echo "Successfully uninstalled from $destination_path."
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
			echo "Force flag enabled. Uninstalling existing SDK..."
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
			echo "SDK installed successfully at $destination_path."
		else
			echo "Error: SDK installation failed with exit code $exit_code."
		fi
		return $exit_code
		;;
	*)
		echo "Error: Invalid action: $action. Use 'install' or 'uninstall'."
		return 1
		;;
	esac
}

#
# @brief Enables or disables auto-start for IMCv2 SDK setup in .bashrc.
# @param[in] 1 Enable flag: 1 to enable, 0 to disable.
# When enabled:
#   - Adds auto-start steps to .bashrc, ensuring existing entries are updated.
# When disabled:
#   - Removes any auto-start entries from .bashrc.
# @return 0 if successful, 1 otherwise.
#

runner_set_auto_start() {

	local enable="$1"
	local bashrc_path="$HOME/.bashrc"
	local header="# IMCv2 Auto start 'dt' and IMCv2 SDK install."
	local auto_start_script="
if sdk_runner.sh runner_ensure_dt; then
    sdk_runner.sh runner_install_sdk uninstall /home/\$USER/projects/sdk
fi
"

	# Validate input
	if [[ "$enable" != "0" && "$enable" != "1" ]]; then
		echo "Error: Invalid argument. Use 1 to enable or 0 to disable."
		return 1
	fi

	# Backup .bashrc before modifying
	if [[ ! -f "$bashrc_path.bak" ]]; then
		cp "$bashrc_path" "$bashrc_path.bak"
	fi

	if [[ "$enable" -eq 1 ]]; then
		# Enable auto-start
		# Remove any existing auto-start block to avoid duplicates
		sed -i "/$header/,/fi/d" "$bashrc_path"

		# Append new auto-start block
		{
			echo "$header"
			echo "$auto_start_script"
		} >>"$bashrc_path"

		echo "Auto-start enabled in .bashrc."
		return 0
	else
		# Disable auto-start
		# Remove the auto-start block
		sed -i "/$header/,/fi/d" "$bashrc_path"

		echo "Auto-start disabled in .bashrc."
		return 0
	fi
}

# Ensure the script can invoke functions by name
if declare -f "$1" >/dev/null; then
	# Call the function with the remaining arguments
	"$@"
	exit $?
else
	echo "Error: '$1' is not a recognized function name."
	exit 1
fi
