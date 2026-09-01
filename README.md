# Bangladesh Railway Ticket Reservation

Use this script to reserve train tickets through an existing Google Chrome session.

## Before You Begin

Run the reservation script at approximately **7:55 AM**.

## 1. Start Google Chrome

Launch a separate Google Chrome instance with remote debugging enabled. Choose the command for your operating system.

### macOS

Open Terminal 1 and run:

```bash
mkdir -p /tmp/chrome-reserve-profile

"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-reserve-profile
```

<details>
<summary><strong>Linux and Chromium commands</strong></summary>

### Linux

Open Terminal 1 and run:

```bash
mkdir -p /tmp/chrome-reserve-profile

google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-reserve-profile
```

On some Linux distributions, the executable is named `google-chrome-stable`:

```bash
google-chrome-stable \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-reserve-profile
```

### Chromium

For Chromium, use:

```bash
chromium \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-reserve-profile
```

</details>

<details>
<summary><strong>Windows PowerShell commands</strong></summary>

### Windows

Open PowerShell and run:

```powershell
$profile = "$env:TEMP\chrome-reserve-profile"
New-Item -ItemType Directory -Force -Path $profile | Out-Null

Start-Process "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" -ArgumentList `
  "--remote-debugging-port=9222", `
  "--user-data-dir=$profile"
```

If Google Chrome was installed only for the current Windows user, run:

```powershell
$profile = "$env:TEMP\chrome-reserve-profile"
New-Item -ItemType Directory -Force -Path $profile | Out-Null

Start-Process "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe" -ArgumentList `
  "--remote-debugging-port=9222", `
  "--user-data-dir=$profile"
```

</details>

### Sign In

In the Chrome window that opens:

1. Visit the [Bangladesh Railway e-ticket website](https://eticket.railway.gov.bd/).
2. Sign in to your account.
3. Keep the Chrome window open while running the reservation script.

## 2. Run the Reservation Script

Open a second terminal in the project directory and use one of the following examples.

## Booking Examples

### Reserve Three AC Seats from Dhaka to Cox's Bazar on 11 September 2026

This command attempts to reserve three `AC_S` seats on **Parjotak Express (816)** from **Dhaka** to **Cox's Bazar** on **11 September 2026**.

```bash
python train_reserve_browser.py \
  --cdp-port 9222 \
  --from "Dhaka" \
  --to "Cox's Bazar" \
  --doj 11-Sep-2026 \
  --train "PARJOTAK EXPRESS (816)" \
  --seats 3 \
  --seat-class AC_S \
  --seat-retry \
  --continue \
  --keep-open
```

### Reserve Four Snigdha Seats from Dhaka to Cox's Bazar on 11 September 2026

This command attempts to reserve four available `SNIGDHA` seats on **Parjotak Express (816)** from **Dhaka** to **Cox's Bazar** on **11 September 2026**.

```bash
python train_reserve_browser.py \
  --cdp-port 9222 \
  --from "Dhaka" \
  --to "Cox's Bazar" \
  --doj 11-Sep-2026 \
  --train "PARJOTAK EXPRESS (816)" \
  --seats 4 \
  --seat-class SNIGDHA \
  --seat-retry \
  --continue \
  --keep-open
```

### Reserve Two AC Berths from Dhaka to Chattogram on 11 September 2026

This command attempts to reserve two `AC_B` berths on **Cox's Bazar Express (814)** from **Dhaka** to **Chattogram** on **11 September 2026**.

```bash
python train_reserve_browser.py \
  --cdp-port 9222 \
  --from "Dhaka" \
  --to "Chattogram" \
  --doj 11-Sep-2026 \
  --train "COXS BAZAR EXPRESS (814)" \
  --seats 2 \
  --seat-class AC_B \
  --seat-retry \
  --continue \
  --keep-open
```

## Command Options

- `--cdp-port 9222`: Connects to the Chrome remote-debugging session.
- `--from`: Sets the departure station.
- `--to`: Sets the destination station.
- `--doj`: Sets the date of journey in `DD-Mmm-YYYY` format.
- `--train`: Selects the train by name and number.
- `--seats`: Sets the number of seats or berths to reserve.
- `--seat-class`: Selects the required seat class.
- `--seat-retry`: Keeps checking until suitable seats become available.
- `--continue`: Continues the booking process after selecting the seats.
- `--keep-open`: Keeps the browser open after the script finishes.

## Notes

- Sign in to the railway website before running the reservation script.
- Keep the Chrome remote-debugging session running throughout the process.
- Verify the route, journey date, train, seat class, and number of seats before running a command.
- The example commands use **11 September 2026** as the journey date.
- If port `9222` is already in use, close the previous debugging session before launching Chrome again.
