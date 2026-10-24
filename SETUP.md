# Setup and reference

For agent-led installation, follow [AGENTS.md](AGENTS.md). This guide covers requirements, manual setup, settings and troubleshooting.

## What you need

- An **Oura Ring Gen3 or Ring 4**, an active **Oura Membership**, and **Daytime Stress already showing** in the Oura app.
- **Telegram on your iPhone**, with notifications allowed. Other phones with Telegram can receive these alerts too.
- **Telegram on your computer during setup**, using [Telegram Web](https://web.telegram.org/) or the desktop app. This lets you copy the bot token directly into the setup window.
- A **Mac, Linux or Windows computer** that stays on during your day. Checks run while the computer is awake; the default setup also requires you to be logged in. Mac has been tested live. Windows support is experimental and has not had a live account setup test. Linux scheduling still needs live testing; cron is experimental.
- An AI agent with access to your computer, or the manual instructions below.

There is no separate iPhone app to install. The program runs on your computer; the notification arrives through Telegram. Windows needs a standard Python runtime and Windows PowerShell 5.1; your agent handles the technical steps.

## Make sure it reaches your iPhone

Open **Settings > Notifications > Telegram**, turn on **Allow Notifications**, and select **Lock Screen** or **Banners**. Your **Show Previews** setting controls when the message text is visible. Focus or Do Not Disturb may delay notifications. [Apple's notification settings guide](https://support.apple.com/guide/iphone/change-notification-settings-iph7c3d96bab/ios).

Open your new bot in Telegram and press **Start** during pairing. Then put Telegram in the background: **lock your iPhone** to test Lock Screen alerts, or **go to the Home Screen** to test Banners. Have your agent send the test.

Expect **🧪 Test from Oura Stress Alerts. Telegram works.** Confirm that it appears on the lock screen or as an iOS banner while Telegram is in the background. An in-app Telegram banner or a message on the computer does not pass this check. Every stress alert reads only **🔴 Oura recorded high stress**. The notification in the [README demo](docs/DEMOS.md) also shows a second line from an earlier message format.

## After setup

- The program checks every **5 minutes** and sends a message when today's high-stress total increases.
- A new installation silently records its first valid stress total as a starting point. This happens once. If there is no data yet, it waits for the first valid reading, even on a later day. A measured zero counts. Normal new-day alerts resume from zero each day after initialization.
- Quiet hours default to **midnight to 8 AM**. Ask your agent to change them or make alerts less frequent.
- Keep the Oura app syncing your ring. Alerts describe **what Oura recorded**, with a delay; they are not an instant stress alarm.
- Ask your agent **"Stop Oura Stress Alerts"** to remove the background job. Your saved connection can be kept for later.

### Bot profile picture

Setup automatically adds the included [ring image](bot-avatar.jpg) to a bot without
a profile photo. Existing custom photos are kept. The image is an AI-generated,
unbranded smart ring, not official Oura artwork. It is included under this
repository's MIT license.

To apply or restore the ring image later, run from the project folder:

```bash
python3 oura_stress_telegram.py set-bot-photo
```

Use `python` or your chosen interpreter on Windows. This replaces the bot's current
profile picture. Keep `bot-avatar.jpg` beside the script; the installer copies it
alongside the installed program. A missing image or failed upload does not stop
guided setup or stress alerts. You can also set a different image through
BotFather's `/setuserpic` command. The bot picture does not replace Telegram's app
icon; its appearance in notifications depends on Telegram and iOS.

The upload uses Telegram's [setMyProfilePhoto API](https://core.telegram.org/bots/api#setmyprofilephoto).

## Manual setup

### Windows

Windows support is experimental. A live Windows setup with Oura and Telegram has
not been tested. The program is designed for Windows 10/11 and uses the built-in
Task Scheduler while you are signed in and the computer is awake.

1. Download the [project ZIP](https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress/archive/refs/heads/main.zip), unzip it and put the folder in your user folder.
2. Open **PowerShell** from the Start menu, using an ordinary window rather than "Run as administrator". Keep the same Windows account throughout setup.
3. Check `python --version`. If Python is missing, install the [Python install manager](https://www.python.org/downloads/), then run that command again. Use a standard runtime, not the older Microsoft Store Python package. Existing python.org installations are also supported. Python 3.9 or newer is required.
4. Go to the unzipped folder, for example `cd "$env:USERPROFILE\oura-stress-alerts"`, and run:

   ```powershell
   python .\oura_stress_telegram.py setup
   ```

Follow the Telegram, Oura and background-check prompts described below. No Windows
password is stored. The scheduler uses `pythonw.exe` so a terminal window does not
flash on every check. The matching `python.exe` remains the interpreter for
interactive setup and reconnect commands.

Save data on a local NTFS drive. The default data folder is
`%LOCALAPPDATA%\oura-stress-telegram`; the installed script lives in the sibling
`%LOCALAPPDATA%\oura-stress-telegram-app` folder. Use `--data-dir` before the command
to choose a dedicated folder. Paths containing a `%NAME%` pair cannot be used in
the scheduled action because Windows expands those references.

If the program detects settings from the earlier unsupported Windows path, it
prints an exact command to reuse that folder, plus a separate cleanup command.
Choose whether to keep or delete those settings. It rejects Store Python's private
package folders before asking for credentials; use the install-manager runtime.

### Mac and Linux

**1. Get the code.** Download the [project ZIP](https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress/archive/refs/heads/main.zip). Unzip it, rename the folder to `oura-stress-alerts`, and move it into your home folder (on a Mac, the folder with your name and the house icon). Or, if you know git:

```bash
git clone https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress.git ~/oura-stress-alerts
```

**2. Open Terminal** (on a Mac: press Cmd+Space, type "Terminal", press Enter) and go to the folder:

```bash
cd ~/oura-stress-alerts
```

**3. Check Python:**

```bash
python3 --version
```

You need 3.9 or newer. On a Mac, if a window asks to install "command line developer tools", click **Install**, wait for it to finish, then run the command again. If you installed Python from python.org, open its folder in Applications and run **Install Certificates.command** before continuing.

**4. Run setup and follow the prompts:**

```bash
python3 oura_stress_telegram.py setup
```

Setup walks you through three parts:

- **Telegram.** In Telegram, message **@BotFather**, send `/newbot`, name it `Oura Stress Alerts`, and choose a username ending in `bot`. Paste the token it gives you into setup. Then open your new bot, press **Start**, and send it the 6 character pairing code that setup shows you.
- **Oura.** Go to [developer.ouraring.com/applications](https://developer.ouraring.com/applications), log in, and create a new application. Name it `Oura Stress Alerts`, then add a description and contact email. For a personal app, use `https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress` for Website, Privacy Policy and Terms of Service. Select **Daily** under Scopes. Set the **Redirect URI** to exactly:

  ```text
  http://localhost:8765/callback
  ```

  Accept the Oura API Agreement and create the app, then paste the **Client ID** and **Client Secret** into setup. Your browser opens Oura's login page. Log in, turn on **Sleep, readiness, and activity**, then press **Allow**. This is the Daily permission the tool needs, even for stress data.
- **Background checks.** Answer **Y** when setup asks to check automatically. It runs one real check, installs the background job, and waits until the job has run once by itself.

That is it. Keep the Oura app on your phone so your ring keeps syncing.

## Everyday commands

Run these from the project folder in Terminal. On Windows use PowerShell and replace `python3` with `python` (or your agent's chosen absolute interpreter path).

| What you want | Command |
|---|---|
| See if everything is working | `python3 oura_stress_telegram.py status` |
| Send a test message | `python3 oura_stress_telegram.py test` |
| Change quiet hours, frequency or sensitivity | `python3 oura_stress_telegram.py settings --help` |
| Log in to Oura again | `python3 oura_stress_telegram.py connect-oura` |
| Turn it off | `python3 oura_stress_telegram.py uninstall` |
| Turn it off and delete saved keys | `python3 oura_stress_telegram.py uninstall --delete-data` |

If you move or update the project folder, run `python3 oura_stress_telegram.py install`
from the **updated project folder**, using the same interpreter and saved-data
folder as the existing job. Do not run the old installed copy to update itself.
Check the installed script's `--version` against the new source afterward, then
verify `status` and the scheduled check. Existing alert history is preserved;
installation verification can send a catch-up alert, even during quiet hours.
If automatic checks were intentionally removed, leave them off unless you want
to enable them again. Agent-specific steps are in [AGENTS.md](AGENTS.md#update-an-existing-installation).

Downloads and ordinary updates use the latest `main` branch. [Release tags](https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress/releases)
provide fixed snapshots when you want a specific version. Extract ZIP updates into
a new permanent folder rather than overwriting an existing one.

## Settings

```bash
# No checks between 10 PM and 8 AM (default: midnight to 8 AM)
python3 oura_stress_telegram.py settings --quiet 22:00-08:00

# Check every 10 minutes instead of 5
python3 oura_stress_telegram.py settings --interval 10

# Only message after at least 15 new minutes of high stress (default: any increase)
python3 oura_stress_telegram.py settings --min-increase 15
```

## Good to know

- **Alerts are not instant.** Timing depends on your ring syncing through the phone app and Oura making the reading available. Alerts can arrive well after the stress; there is no fixed delivery-delay guarantee.
- **It reports what Oura recorded**, not a live reading. A message after a quiet stretch can describe stress from earlier in the day.
- **The default is sensitive:** any new high stress sends a message. Use `--min-increase` if that is too many.
- **Updates and reconnects keep your alert history.** Upgrades preserve old installations' behavior, including an old installation that has not received data yet. Deleting or losing the state file starts again with a silent baseline; a corrupt state file is treated the same way.
- **If checks keep failing**, you get a Telegram message saying so. If Oura ever stops accepting the saved login, the message includes the exact command to fix it. It cannot tell you if Telegram itself is unreachable or the computer is off, so run `status` now and then.
- **Use a new bot just for this.** If another program already reads the same bot's messages, setup will tell you to create a new one.
- **This is not medical advice** and is not affiliated with Oura or Telegram.

## Troubleshooting

| Problem | What to do |
|---|---|
| "No stress data for today yet" | Open the Oura app so the ring syncs. Daytime Stress needs Gen3 or later, an active membership and about 5 days of wear. |
| "Python cannot verify secure connections" | If you installed Python from python.org, open its folder in Applications and run **Install Certificates.command**. |
| Oura says the redirect URI is invalid | In your Oura application, the Redirect URI must be exactly `http://localhost:8765/callback`. |
| The localhost return page fails after you press Allow | Copy the full address from the browser's address bar and paste it into the setup window. |
| Oura itself shows an error page during sign-in or consent | Press Ctrl+C in the terminal and run the same command again. If the error repeats, check the Client ID and Daily under Scopes, then run setup and enter the app details again. |
| The pairing code did not reach the bot | Open your bot in Telegram, press Start, then send the code as a normal message. |
| No alerts at all | Run `status` and look at "Last background run". On a Mac the log is in `~/Library/Logs/oura-stress-telegram.log`. |
| Windows: automatic checks stop when you sign out | Stay signed in and keep the computer awake. Checks resume when you sign in again; a locked screen is fine. |
| Windows: scheduler access or PowerShell error | Use a normal PowerShell window under the same account. Managed-computer policies may prevent automatic checks. The program reports this as a failure, not successful installation. |
| Windows: certificate verification fails | Check Windows date/time, apply Windows Update certificate updates and retry. On a managed computer, ask its administrator about the trusted certificate store. Do not disable certificate verification. |
| Linux: checks stop when you log out | Run `loginctl enable-linger $USER`, or answer yes when `install` offers it. |

## Privacy and security

- Your Telegram bot token, Oura app keys and Oura login are saved in `~/.config/oura-stress-telegram/` on Mac/Linux or `%LOCALAPPDATA%\oura-stress-telegram` on Windows. Unix files use private permissions; Windows access is restricted to your user, SYSTEM and local administrators.
- The program only asks Oura for **daily** data and only reads the daily stress summary.
- Telegram messages pass through Telegram's servers like any bot message. Alerts say only that Oura recorded high stress, with no stress minutes. Problem notices also include the error and the command to run, which shows folder paths on your computer.
- To remove everything: run `uninstall --delete-data`, delete your application at [developer.ouraring.com/applications](https://developer.ouraring.com/applications), and delete the bot by sending `/deletebot` to @BotFather.

## Project status

Version 0.2.3 is an early beta. The public name is Oura Stress Alerts. It has a silent first-reading baseline, a default ring
avatar, and experimental native Windows support. The new baseline behavior has
automated coverage only. Live Windows account setup, normal-user installation,
sign-out/sign-in and Windows-to-phone delivery have not been tested. Automated
Windows checks exercise native file permissions, locking,
PowerShell recovery commands and real Task Scheduler registration and execution.
A fresh nontechnical user's complete agent-led setup is also unverified.

On October 11, 2026, a manually triggered alert using the 0.2.1 formatter before
the headline was shortened was confirmed on the
physical iPhone lock screen and captured in a screenshot. The [README demo](docs/DEMOS.md)
shows a full phone walkthrough using that notification and real Home Screen and
Oura captures. The lock screen was cleaned, covered wallpaper was reconstructed,
Home Screen calendar titles were made generic, and interactions and transitions
were simulated. The calendar layout, event times and app notification counts remain.
The notification headline was shortened to "Oura recorded high stress", the
wording every alert now uses. A later demo edit uses example
graph points and matching 15-minute totals to show the day's first high-stress
period. Calendar titles are fictional. These edits do not change actual Oura data.
The walkthrough compresses the time between captures.
It is an edited walkthrough, not a continuous recording or an instant-alert claim.

The October 10, 2026 live macOS run verified fresh-app setup, Telegram delivery,
both callbacks, background startup, token refresh and lost-response recovery.
Later recovery changes and the platform work have automated coverage; the live
OAuth flow was not repeated after them. Tests run on macOS, Linux and Windows.
Details and remaining acceptance checks are in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
Please [open an issue](https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress/issues)
if anything is confusing or broken.

## For developers

One file, Python standard library only, Python 3.9+. The public name is Oura Stress Alerts. The script filename and existing Mac/Linux data and scheduler identifiers retain their original names for compatibility. Windows uses a task name containing the current user SID, so different Windows accounts have separate tasks.

```bash
python3 -m unittest discover -s tests -v
```

Oura retired personal access tokens in December 2025, so this uses OAuth2: authorization code with PKCE, a one-time local callback on `localhost:8765`, and automatic refresh. Oura refresh tokens are single use, so each new token pair is saved before it is used, and every command that touches tokens shares one file lock.

### Windows implementation notes

Checks use the same OAuth flow, refresh-token lock and alert logic on all platforms.
Windows uses a native byte-range lock, private Windows access rules and bounded
retries for file replacement when another process briefly has the file open.
Its 120-second check deadline is soft because Windows may delay a Python interrupt
until native work returns. The scheduled task has a ten-minute hard limit. The
interactive CLI has no hard process-kill deadline. A forced stop during token
rotation may require the normal reconnect flow.

The Windows test suite exercises real platform APIs and disposable scheduled tasks
without Oura or Telegram credentials. Hosted CI does not prove a normal user's
complete setup, even when native scheduler execution is available on the runner.

## License

[MIT](LICENSE)
