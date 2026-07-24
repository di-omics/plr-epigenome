# STARPI Setup

Raspberry Pi 5 -> Hamilton Microlab STAR control via PyLabRobot.

## Goal

Run PyLabRobot on a dedicated Raspberry Pi 5 (`starpi`), SSH into it from a Mac, and initialize the Hamilton STAR safely. The default startup path should **skip autoload movement**.

## Known-good connection info

- Hostname: `starpi`
- SSH address (mDNS / direct link): `lab@starpi.local`
- Current onsite VLAN IP (verified on 2026-04-21): `<PI_LAN_IP>`
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

---

## Access mode 1: Onsite Ethernet via research lab VLAN

This mode is for using the Raspberry Pi on the **onsite wall ethernet ports** at research lab.

### Current known-good behavior

- Wall ports were moved to the **research lab VLAN**
- The Pi currently receives a DHCP address on:

```text
<PI_LAN_IP>
```

- In general, the Pi should receive a DHCP address on:

```text
<PI_LAN_SUBNET>.x
```

- `starpi.local` may **not** resolve reliably in this mode
- SSH by IP is the preferred access method onsite

### Find the Pi from your Mac

First check whether the Pi appears on the VLAN:

```bash
arp -a | grep <PI_LAN_SUBNET>
```

If needed, try pinging the current known Pi IP:

```bash
ping -c 3 <PI_LAN_IP>
```

### SSH into the Pi onsite

Use the Pi's DHCP address directly:

```bash
ssh lab@<PI_LAN_IP>
```

If prompted the first time, accept the fingerprint with `yes`.

### Notes

- `starpi.local` was previously associated with the same host key as `<PI_LAN_IP>`
- If `starpi.local` fails with `Unknown host`, use the IP address instead
- If one IP refuses SSH, verify you are connecting to the Pi and not another device on the subnet

### Quick onsite start

```bash
ssh lab@<PI_LAN_IP>
cd ~/star-lab
source env/bin/activate
lsusb | grep -i 08af
python test_star_no_autoload.py
```

---

## Access mode 2: Direct connection / previous workflow

This mode is for the previous direct-connect setup from your computer. Keep using this workflow when you are not accessing the Pi through the onsite research lab wall ethernet VLAN.

### SSH into the Pi

From your Mac terminal:

```bash
ssh lab@starpi.local
```

If prompted the first time, accept the fingerprint with `yes`.

### Enter the project and activate the environment

```bash
cd ~/star-lab
source env/bin/activate
```

### Verify the Python environment

```bash
which python
python --version
pip show pylabrobot
```

Expected:

- Python path under `/home/lab/star-lab/env/bin/python`
- PyLabRobot installed

### Verify USB enumeration

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

### Safe startup: initialize STAR without autoload

```bash
python test_star_no_autoload.py
```

This is the default startup smoke test and should skip autoload movement.

## Daily quick-start (onsite VLAN)

```bash
ssh lab@<PI_LAN_IP>
cd ~/star-lab
source env/bin/activate
lsusb | grep -i 08af
python test_star_no_autoload.py
```

## Daily quick-start (direct / mDNS)

```bash
ssh lab@starpi.local
cd ~/star-lab
source env/bin/activate
lsusb | grep -i 08af
python test_star_no_autoload.py
```

## Troubleshooting

### `starpi.local` does not resolve

If you see:

```text
ping: cannot resolve starpi.local: Unknown host
```

use the onsite VLAN IP instead:

```bash
ssh lab@<PI_LAN_IP>
```

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
git commit -m "Update STARPI setup instructions for onsite VLAN access"
git push
```

## Recommended default

For normal startup, use:

```bash
python test_star_no_autoload.py
```

Avoid autoload scripts unless you are explicitly testing autoload behavior.
