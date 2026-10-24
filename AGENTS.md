# Set up Oura Stress Alerts for this person

Use this guide for installation or setup requests. For development or review requests, use the [SETUP.md developer section](SETUP.md#for-developers) and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md); do not start account setup or install a background job unless requested.

Assume the person is not a developer. Their request may be only "Set this up" plus the repository URL. Do the technical work yourself and guide them through account steps one at a time. Do not stop at a plan or a list of commands.

**Done means both:** the person confirms the test as an iOS notification with Telegram in the background, and the connection check and scheduler verification described in section 3 pass. A successful send response or a message in Telegram Web alone does not verify phone delivery.

## How to help

- Explain the next action in plain English: where to click, what to paste, and what they should see. Avoid unexplained terms such as OAuth, PKCE, launchd, cron and environment variables.
- Handle downloading, choosing Python, running commands and checking results. Ask the person only for steps that need their account access, consent or private input.
- Never ask them to paste a bot token or Client Secret into the AI chat. Use the setup program's hidden input in a terminal they control. Existing privately supplied environment variables are also supported; never print their values.
- Never print, copy, commit or upload the saved-data folder or its contents: `~/.config/oura-stress-telegram/` on Mac/Linux, `%LOCALAPPDATA%\oura-stress-telegram` on Windows, or any `--data-dir` / `OURA_STRESS_HOME` override. This includes config.json, tokens.json, state and logs.
- Have the person complete Oura or Telegram sign-in if needed. Do not sign in for them unless they explicitly ask you to.
- For ordinary installation, do not edit `oura_stress_telegram.py` to work around a failure. Use the troubleshooting guidance, report a clear blocker, or help prepare an issue without secrets. A maintainer's explicit development request is separate from installation.
- If your agent environment blocks network, file or scheduler access, use its normal permission flow or the person's own Terminal. Verify in that user environment before calling a restriction a program failure.
- Use a new Telegram bot dedicated to this tool. Do not reuse a bot another program already polls.

## 1. Check the computer and get the code

Confirm they have an Oura Ring Gen3 or Ring 4 with an active membership, Telegram
on their phone with notifications allowed, and a computer that can stay awake.
Ask whether Daytime Stress already appears in Oura. If it does not, explain that
it needs several days of wear and syncing. Setup can still finish: the first
valid reading, whenever it appears, becomes a silent starting point. Alerts begin
with later increases. Do not promise immediate stress readings or a fixed delay.

Use a Mac, Linux or Windows computer. Windows support is experimental: automated checks cover the Windows implementation, but a live Windows account setup and phone delivery have not been tested. Explain that limitation before setup. Use a normal, non-elevated PowerShell window on Windows; do not switch to a different administrator account.

Find Python 3.9 or newer: `python3 --version` on Mac/Linux or `python --version` on Windows. On Windows, `py` can select an existing runtime if needed. Obtain the real interpreter path with `python -c "import sys; print(sys.executable)"` and use that path consistently for setup and later commands. No pip packages, Node, Docker or other project dependencies are needed.

If Python is missing on Windows, guide the person through the [Python install manager](https://www.python.org/downloads/), then run `python --version` and confirm a runtime is available. Use an ordinary runtime launched by the manager, not the older Microsoft Store Python package. The program rejects Store package virtualization before saving credentials. Existing traditional python.org installations also work if they include both `python.exe` and `pythonw.exe`. On Mac, use the offered command line developer tools or a supported Python from python.org. Explain that this is a prerequisite the agent will use, not something they need to learn. For a python.org installation on macOS, run **Install Certificates.command** in that version's Applications/Python folder before setup, as described in the [Python macOS installation guide](https://docs.python.org/3/using/mac.html). Do not claim setup is complete while installation is pending.

Put the project in a permanent folder such as `~/oura-stress-alerts` (on Windows, a folder named `oura-stress-alerts` under their user profile). Earlier installations may use `stress-nudge`, `oura-stress-notification`, or `oura-stress-telegram` instead. If any of these folders already exists, inspect and reuse it without overwriting local changes.

- If Git is already available, clone `https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress.git` there.
- If Git is unavailable, download `https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress/archive/refs/heads/main.zip` and extract it there using available download/archive tools. The person does not need to install Git.

Read [SETUP.md](SETUP.md) for requirements and reference before continuing. Do not run the release checklist or fault-injection tests during a person's installation.

The default installation channel is the latest `main` branch. Published release
tags are fixed snapshots; use a specific tag if the person requests that version.

## 2. Start the guided setup

Explain: "I'll set up the program. You'll create a sender for your Telegram alerts, give it permission to read Oura, and check one test notification on your phone."

Run the chosen Python with `oura_stress_telegram.py setup` from the project folder in a real interactive terminal or PTY. Stay with it through every prompt.

On Windows, PowerShell needs `&` before a quoted executable path, for example `& 'C:\path\python.exe' 'C:\path\oura_stress_telegram.py' setup`. Substitute the real paths. The program prints PowerShell-compatible recovery commands. Saved data defaults to `%LOCALAPPDATA%\oura-stress-telegram`; use a dedicated local NTFS folder, not a shared/removable folder. Keep runtime, project and data paths free of `%NAME%` pairs, which Task Scheduler expands.

If your terminal tool cannot let the person enter private values, help them open their own Terminal and give them one exact command with the real project path. Continue guiding the prompts and return to verification afterward. Do not leave them with an unexplained command and call the task done.

If setup already has their Telegram or Oura app details, keep them unless the error says those details are rejected.

### Telegram

Open [Telegram Web](https://web.telegram.org/) or Telegram Desktop on the computer used for setup. Have the person sign in themselves, using the phone's QR-code login if offered. This puts BotFather and the terminal on the same computer so they can copy the token directly into the hidden prompt without retyping it or sharing it in AI chat.

1. Have them open the official [@BotFather](https://t.me/BotFather) in Telegram and send `/newbot`.
2. Suggest the display name **Oura Stress Alerts**. They choose an available username ending in `bot`. Explain that the username must be unique if their first choice is taken.
3. They copy the token from BotFather on the computer and paste it into the hidden setup prompt in their terminal. Explain that no characters appear while pasting; press Enter once after pasting.
4. They open their new bot, press **Start**, and send the six-character pairing code shown by setup as a normal private message.
5. Confirm the bot's pairing confirmation arrives. That verifies the chat connection; the phone notification is checked separately below.

Setup adds the bundled [ring profile picture](bot-avatar.jpg) if the bot has no photo.
It keeps an existing custom photo. The picture is a generated, unbranded smart-ring
illustration, not an official Oura asset. If the upload fails, continue setup and
retry with `python3 oura_stress_telegram.py set-bot-photo` from the project folder
(use the chosen Python on Windows). That command replaces the current bot photo.
No additional BotFather step is needed. This sets the bot's avatar; Telegram and
iOS control whether it appears in a notification and still identify Telegram as
the delivering app.

### Oura

Have them sign in at <https://developer.ouraring.com/applications> and choose **Create New**. Explain that Oura calls this an "application", but they are only filling in a connection form.

Provide these values so they do not have to invent them:

| Field | Value |
|---|---|
| Display Name | `Oura Stress Alerts` |
| Description | `Personal Telegram alerts when Oura records more high stress.` |
| Contact Email | Their own email address |
| Website | `https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress` |
| Privacy Policy | `https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress` |
| Terms of Service | `https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress` |
| Redirect URIs | `http://localhost:8765/callback` |
| Scopes | Select **Daily** |

The repository links are for this personal setup. Have them review and accept the Oura API Agreement and create the app. They paste the displayed **Client ID** and **Client Secret** into the setup prompts, keeping the secret out of chat.

When the consent screen opens, tell them to turn on **Sleep, readiness, and activity**, then press **Allow**. That switch is the Daily permission, including the stress read this tool needs. Clicking Allow with the switch off is not enough. A separate sign-in may appear even if the developer portal is already signed in.

### Automatic checks

For a new installation, the first check with valid stress data saves today's
existing total without sending a stress alert. Missing data does not start this
step; a measured zero does. This happens once, not every morning. Reconnecting or
reinstalling preserves existing alert history. An established installation's
verification check can send a pending alert or today's accumulated stress after
a date change, even during quiet hours. The separate `test` message is unchanged.

Answer **Y** to automatic background checks as part of the requested setup. The program tests the scheduled command and then waits for the scheduler to run it. Confirm those checks succeed before moving on. On macOS, explain that a notice about Python running in the background is expected for this job; keep it enabled if they want automatic checks. On Windows, checks use the built-in scheduler and run while the person is signed in and the computer is awake. No Windows password or administrator permission is needed by the designed setup. A registration or verification failure is unfinished setup; do not label it successful or work around it by changing accounts.

## 3. Verify the result on their phone

Run with the same chosen Python:

```bash
python3 oura_stress_telegram.py status
python3 oura_stress_telegram.py test
```

Check that `status` shows the connection and installed background checks. A successful run has outcome `ok` or `ok: alert sent`. If setup's verification check passed but the scheduler reports `skipped: quiet hours`, the scheduler is working and waiting for quiet hours to end; explain that rather than reinstalling or claiming a stress read occurred in that scheduled run. Other skips, paused, failed and degraded results need investigation. "No stress data for today yet" can be normal; it does not prevent the Telegram test.

On iPhone, guide them to **Settings > Notifications > Telegram**. Allow notifications and enable **Lock Screen** or **Banners**. Let them choose when message previews appear; do not silently change their privacy preferences. Check Focus or Do Not Disturb if delivery is delayed.

Before sending the test, have them put Telegram in the background: lock the iPhone if Lock Screen alerts are enabled, or go to the Home Screen if testing Banners. Then run `test` and ask whether it appeared on the lock screen or as an iOS banner while Telegram was in the background. Expect **🧪 Test from Oura Stress Alerts. Telegram works.** Every stress alert reads only **🔴 Oura recorded high stress**; the README GIF's notification also shows a second line from an earlier message format (see docs/DEMOS.md). The GIF is an edited phone walkthrough using a real notification, Home Screen and Oura captures, with example stress readings, fictional calendar titles and simulated interactions; it is not a continuous recording or a promise of instant delivery. To view details, open Oura separately and tap Stress; the Telegram notification opens Telegram. An in-app Telegram banner, a chat message or a computer notification does not pass this phone-push check. If phone confirmation is unavailable, explicitly report it as unverified instead of claiming completion.

For Linux, verify the actual systemd timer or cron run rather than relying on a successful install command. Cron remains experimental. Explain the logout limitation and the installer's option to keep running after logout.

## 4. Finish with a short handoff

Tell the person:

- Which bot sends the alerts, and that the phone test and automatic checks passed.
- The computer needs to stay awake. Oura updates can arrive late, so alerts report recorded stress rather than an instant reading.
- Quiet hours are midnight to 8 AM by default. They can ask their agent to change the schedule or stop the alerts.

Provide the exact command to stop the job, using the chosen Python and an absolute script path. Explain that `uninstall` keeps their saved connection; `uninstall --delete-data` also removes saved keys. Do not delete data unless requested.

## Update an existing installation

1. Inspect the existing checkout and scheduled job before updating. Preserve local
   changes and saved settings. For Git, update the checkout without overwriting
   local changes; for a ZIP, extract the new version into a new permanent folder.
   Use latest `main` unless a specific release tag was requested.
2. Recover the original interpreter and data-folder paths from this tool's
   launchd arguments/environment, systemd service, cron command, or Windows task
   action. Read only the relevant command/path fields; do not dump credentials or
   saved-data files. On Windows, use the sibling `python.exe` for interactive
   commands when the task names `pythonw.exe`. If no job is installed, reuse a
   known custom data path; otherwise use the documented defaults.
3. If checks were running, run `install` with that interpreter and data folder,
   invoking **the script in the updated checkout**, not the installed copy named
   in the scheduler. Use `--data-dir` before `install` when needed. Running the
   installed copy would reinstall old code. If checks were intentionally removed,
   a source-only update should leave them off unless enabling them was requested.
4. Verify the installed script's `--version` against the updated checkout, or
   compare their hashes. Run `status` and confirm installation's scheduled-check
   verification passed. A green status alone does not prove the code was updated.
   Existing baselines remain intact; verification may send a real stress alert,
   including a catch-up for today, even during quiet hours.

If the installed command or data path cannot be determined, resolve that before
replacing an active job. Do not guess a new data folder and disconnect the person.

## When something goes wrong

- **Missing Daily permission during setup:** run `setup` again, keep the saved app details, and enable **Sleep, readiness, and activity** on the consent screen. Finish the automatic-checks step afterward.
- **Rejected app keys:** run `setup`, answer **n** when asked to keep Oura app details, and enter the correct Client ID and Client Secret.
- **Oura's own sign-in or consent error page:** press Ctrl+C and restart the command. If it repeats, check the Client ID and Daily scope in the registered app before reentering its details.
- **Failed localhost return:** paste the full address from the browser into the waiting terminal. It includes a temporary login code, so keep it out of chat and logs.
- **No stress data yet:** have them sync the ring through the Oura app. Daytime Stress needs a supported ring, active membership and a few days of wear.
- **Telegram polling conflict:** create a new dedicated bot; do not stop another program's bot.
- **Connection works but no schedule exists:** run `install`, then check `status` again. Reconnecting alone does not install automatic checks.
- **Windows certificate error:** confirm the computer's date/time, apply Windows Update certificate updates, then retry. On a managed computer, the administrator may need to repair the trusted certificate store. Never disable TLS verification.
- **Windows scheduler query or permission failure:** use the exact error and the person's ordinary PowerShell session. A policy-restricted or unavailable scheduler is a blocker, not an absent task or permission to request an administrator password.
- **Legacy Windows settings detected:** use the exact printed `--data-dir` command to keep the connection. Do not delete or move saved keys without the person choosing that action.
- **Other failures:** use [SETUP.md troubleshooting](SETUP.md#troubleshooting). Report the exact safe error and what is still unverified. Do not claim success or invent a provider outage.

## Advanced setup, only when needed

Existing private environment values can be used: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (skips pairing), `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET`. Do not make environment-variable setup the default for a nontechnical person. Secrets are never accepted as command-line arguments.

| What | Location |
|---|---|
| Keys, login, settings, state | Mac/Linux: `~/.config/oura-stress-telegram/`; Windows: `%LOCALAPPDATA%\oura-stress-telegram`; override with `--data-dir` or `OURA_STRESS_HOME` |
| Installed script | Mac/Linux: `~/.local/share/oura-stress-telegram/oura_stress_telegram.py`; Windows: `%LOCALAPPDATA%\oura-stress-telegram-app\oura_stress_telegram.py` |
| macOS schedule and log | `~/Library/LaunchAgents/local.oura-stress-telegram.plist`, `~/Library/Logs/oura-stress-telegram.log` |
| Linux schedule | systemd user timer `oura-stress-telegram.timer`, or a crontab line tagged `# oura-stress-telegram` |
| Windows schedule and log | Task Scheduler task `oura-stress-telegram-<user SID>`; `check.log` in the data folder |
