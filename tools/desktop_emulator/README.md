# SeedSigner desktop emulator

Run this SeedSigner branch in a window on your Linux PC, without a Raspberry Pi.
The launcher (`seedsigner_desktop.py`) swaps the Pi hardware for desktop
equivalents at runtime; no SeedSigner source files are changed.

| Pi hardware        | On the desktop                                  |
|--------------------|-------------------------------------------------|
| 1.3" SPI display   | Tkinter window (2x zoom by default)             |
| Joystick + 3 keys  | Keyboard and on-screen buttons                  |
| Pi camera          | Webcam via OpenCV (optional; for QR scanning)   |

> **Warning:** a PC is not air-gapped. Only use test seeds such as
> `abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about`.
> Never enter a seed that holds real funds.

## Installation (Ubuntu, Linux Mint, Pop!_OS, Zorin OS)

```bash
# System packages
sudo apt update
sudo apt install -y git python3-venv python3-tk libzbar0 qrencode

# Get this branch
git clone -b feature/account-index-selection https://github.com/wout2121/seedsigner.git
cd seedsigner

# Virtual environment + dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install --no-deps -e .

# Optional: webcam support for scanning QR codes
pip install opencv-python-headless
```

`requirements.txt` pins Pillow 10.3.0, which has wheels for Python 3.8–3.12.
On a distro with Python 3.13+ (check with `python3 --version`), create the venv
with Python 3.12 instead, e.g. via [uv](https://docs.astral.sh/uv/):
`uv venv -p 3.12 .venv && source .venv/bin/activate && uv pip install -r requirements.txt && uv pip install --no-deps -e .`

## Start

```bash
source .venv/bin/activate
python tools/desktop_emulator/seedsigner_desktop.py
```

Options: `--scale 3` (bigger window), `--camera 1` (other webcam).

## Controls

| Key               | SeedSigner button        |
|-------------------|--------------------------|
| Arrow keys        | Joystick                 |
| Enter / Space     | Joystick press (select)  |
| 1 / 2 / 3         | KEY1 / KEY2 / KEY3       |
| Esc               | Quit                     |

On keyboard screens (passphrase, account index, ...) KEY3 (`3`) is the
green "save" check mark.

## Testing the account index feature (issue #1037)

1. **Settings → Advanced → Account index selection → Enabled**
2. Load a test seed: **Seeds → Enter 12-word seed** (or Tools → New seed)
3. **Seeds → (your seed) → Export Xpub → Single Sig → Native Segwit**
4. The *Account Index* screen appears. Delete the `0` with the backspace key,
   type `1` and press `3` (save). The Xpub Details screen shows `m/84'/0'/1'`.
5. Address Explorer works the same way: **Tools → Address Explorer → (seed) →
   Native Segwit → account 1**. For the `abandon ... about` test seed, receive
   address #0 of account 1 is `bc1qku0qh0mc00y8tk0n65x2tqw4trlspak0fnjmfz`
   (account 0 is `bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu`).

Compare the xpub with Sparrow Wallet by creating a wallet with the same test
seed and derivation `m/84'/0'/1'`.

## Notes

- Settings are only saved (to `settings.json` in the repo root) when
  *Persistent settings* is enabled, just like on the device.
- The MicroSD, power-off and display-hardware settings have no effect here.
- Automated tests don't need the emulator: `pip install -r tests/requirements.txt && python -m pytest`.
