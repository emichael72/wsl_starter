mkdir -p workspace
cd workspace
curl -sSL -H "Authorization: token $(dt github print-token https://github.com/intel-innersource/firmware.ethernet.imcv2)" -H "Cache-Control: no-store" "https://raw.githubusercontent.com/intel-innersource/firmware.ethernet.imcv2/main/scripts/imcv2_boot_strap.sh" | bash -s -- -b main