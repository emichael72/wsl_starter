#!/bin/bash

# ------------------------------------------------------------------------------
#
# Script Name:  go_sdk.sh
# Description:  Replacing the 'im' alias with a more versatile function.
# Version:      1.0
# Copyright:    2025 Intel Corporation.
# Author:       Intel IMCv2 Team.
#
# ------------------------------------------------------------------------------

setup_imcv2_sdk() {

	usage() {
		echo "Usage: $0 <IMCV2_INSTALL_PATH>"
		echo "Example: $0 /path/to/imcv2"
		return 1
	}

	# Check if the user provided an argument
	if [ $# -ne 1 ]; then
		echo "Error: Installation path is required."
		usage
		return 1
	fi

	local install_path="$1"

	# Resolve the installation path to an absolute path
	IMCV2_INSTALL_PATH=$(realpath "$install_path" 2>/dev/null)
	if [ -z "$IMCV2_INSTALL_PATH" ]; then
		echo "Error: Unable to resolve the installation path '$install_path'."
		return 1
	fi

	# Validate the path
	if [ ! -d "${IMCV2_INSTALL_PATH}" ]; then
		echo "Error: The specified path '${IMCV2_INSTALL_PATH}' does not exist or is not a directory."
		return 1
	fi

	# Validate the environment script
	ENV_SCRIPT="${IMCV2_INSTALL_PATH}/imcv2/scripts/imcv2_env.sh"
	if [ ! -f "${ENV_SCRIPT}" ]; then
		echo "Error: The environment script '${ENV_SCRIPT}' does not exist."
		return 1
	fi

	# Export the installation path
	export IMCV2_INSTALL_PATH

	# Change to the installation directory
	cd "${IMCV2_INSTALL_PATH}" || {
		echo "Failed to change directory to ${IMCV2_INSTALL_PATH}"
		return 1
	}

	# Reset positional parameters before sourcing
	set --

	# Source the environment script
	echo "Sourcing: ${ENV_SCRIPT}"
	# shellcheck disable=SC1090
	source "${ENV_SCRIPT}" || {
		echo "Failed to source ${ENV_SCRIPT}"
		return 1
	}
}

setup_imcv2_sdk "$@"
