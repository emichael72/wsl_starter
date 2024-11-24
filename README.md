## Welcome to the IMCv2 SDK / WSL Inage Creator. 
**Follow these steps to set up your environment:**

1. Open the Command Prompt on your Windows system.

  * Intel Proxy : Copy the command below and paste it into your terminal:

```cmd

curl -s -S --proxy http://proxy-dmz.intel.com:911 https://raw.githubusercontent.com/emichael72/wsl_starter/main/imcv2_image_creator.py | python - -n IMCv2 && timeout 1 && exit

```

  * Direct Acess: Copy the command below and paste it into your terminal:

 ```cmd

curl -s -S https://raw.githubusercontent.com/emichael72/wsl_starter/main/imcv2_image_creator.py | python - -n IMCv2 && timeout 1 && exit

```

2. If the Windows Terminal prompts you with "Paste anyway," choose to accept.
3. Follow the on-screen instructions to complete the setup.

**Notes**
* Make sure Python is installed and added to your system's PATH.
* Run this command only if you trust the source.

