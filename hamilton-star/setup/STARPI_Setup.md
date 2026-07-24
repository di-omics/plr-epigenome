# STARPI Setup

Raspberry Pi 5 -> Hamilton Microlab STAR control via PyLabRobot.

## Goal

Run PyLabRobot on a dedicated Raspberry Pi 5 (`starpi`), SSH into it from a Mac, and initialize the Hamilton STAR safely. The default startup path should **skip autoload movement**.

## Known-good connection info

- Hostname: `starpi`
- SSH address: `lab@starpi.local`
- Username: `lab`
- Password: `<PI_PASSWORD>`  (kept private; not published)
- Project directory: `~/star-lab`
- Virtualenv: `~/star-lab/env`
- Safe init script: `test_star_no_autoload.py`

## Hardware notes

- Use the **bottom USB-B port on the STAR**.
- Plug the STAR into one of the Pi's **blue USB 3.0 ports**.
- The STAR must be powered on before USB checks or initialization.
- Keep clear of the deck before running any init or homing step.

## Fresh-start workflow

### 1. SSH into the Pi

From your Mac terminal:

```bash
ssh lab@starpi.local
```

If prompted the first time, accept the fingerprint with `yes`.

### 2. Enter the project and activate the environment

```bash
cd ~/star-lab
source env/bin/activate
```

### 3. Verify the Python environment

```bash
which python
python --version
pip show pylabrobot
```

Expected:

- Python path under `/home/lab/star-lab/env/bin/python`
- PyLabRobot installed

### 4. Verify USB enumeration

With the STAR connected and powered on:

```bash
lsusb
lsusb | grep -i 08af
```

Expected:

- A Hamilton device or vendor ID `08af`

If nothing appears:

- confirm STAR power is on
- confirm the cable is in the **bottom** STAR USB-B port
- try the other blue USB port on the Pi

### 5. Safe startup: initialize STAR without autoload

```bash
python test_star_no_autoload.py
```

This is the default startup smoke test and should skip autoload movement.

## Daily quick-start

```bash
ssh lab@starpi.local
cd ~/star-lab
source env/bin/activate
lsusb | grep -i 08af
python test_star_no_autoload.py
```

## Troubleshooting

### SSH works, but STAR does not appear in `lsusb`

- Check cable seating
- Confirm STAR is powered on
- Confirm USB-B is in the **bottom** STAR port
- Try another blue USB port on the Pi

### `test_star_no_autoload.py` fails with USB or backend errors

Check whether PyUSB imports:

```bash
python -c "import usb; print(usb.__file__)"
```

Check recent kernel USB logs:

```bash
dmesg | tail -n 50
```

### Permission problems on USB

Check the udev rules:

```bash
cat /etc/udev/rules.d/99-usb.rules
```

Expected:

```text
SUBSYSTEM=="usb", MODE="0666"
SUBSYSTEM=="tty", MODE="0666"
```

Reload rules:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug/replug the USB cable and retry.

## Git workflow

From the Pi:

```bash
cd ~/star-lab
git status
git add STARPI_Setup.md
git commit -m "Add STARPI setup instructions"
git push
```

If the file is not in the repo yet, first copy it into the repo root.

## Clean push to `di-omics/plr-epigenome`

From the Pi, run:

```bash
cd ~/star-lab
git remote -v
git branch --show-current
```

If this repo is already cloned from `di-omics/plr-epigenome`, then copy in the file and push:

```bash
cp /path/to/STARPI_Setup.md ~/star-lab/STARPI_Setup.md
git add STARPI_Setup.md
git commit -m "Add STARPI setup instructions"
git push origin $(git branch --show-current)
```

If the remote is missing, add it:

```bash
git remote add origin git@github.com:di-omics/plr-epigenome.git
```

If SSH auth is not set up on the Pi and HTTPS is easier:

```bash
git remote add origin https://github.com/di-omics/plr-epigenome.git
```

Then push your current branch:

```bash
git push -u origin $(git branch --show-current)
```

## Recommended default

For normal startup, use:

```bash
python test_star_no_autoload.py
```

Avoid autoload scripts unless you are explicitly testing autoload behavior.
