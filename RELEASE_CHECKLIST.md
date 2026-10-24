# Release checklist

Automated tests mock Oura and Telegram. Before calling a version tested end to end,
do this once on a real account and record the date and result below.

## Distribution acceptance

The release succeeds when a nontechnical person can give an agent the public
GitHub URL and say "Set this up", then receive a test notification on their phone
with automatic checks running. A working API call or a Telegram Web receipt is
not sufficient for this acceptance check.

- Start from the public README and its exact copyable agent request, on a fresh
  account or clean machine. The request does not name AGENTS.md, so confirm the
  agent finds and follows it. Follow the guide without unexplained developer steps.
- Confirm the agent handles downloading, Python selection, setup and verification,
  including a path that does not require Git.
- Record where the person needed account sign-in, consent or private key entry,
  and any point where they were unsure what to do next.
- Put Telegram in the background before the phone test: lock the iPhone to test
  Lock Screen alerts, or go to the Home Screen to test Banners. Confirm the iOS
  notification says "Test from Oura Stress Alerts. Telegram works." An in-app
  Telegram banner does not pass. Check real-alert wording separately when an
  actual stress alert arrives. The README demo uses real screenshots from one
  manually triggered alert; it does not replace this person's real-device check.
- Confirm automatic checks, a simple way to change quiet hours, and a clear way
  to stop the alerts. Record time and assistance rather than estimating them.
- Separately observe the public tool through an ordinary day: its own scheduled
  check must notice a natural increase in Oura's recorded daily stress and send
  a notification that the owner confirms on the physical phone. Do not force a
  baseline change or manually send the alert. Record observed sync/check/arrival
  times where available; do not infer physiological onset from an API total.

**Still pending:** a fresh nontechnical person's full setup and the ordinary-day
natural-increase check above. A manually triggered phone alert does not pass the
latter. The 0.2.2 beta does not claim either has been completed.

**Phone delivery confirmed on 2026-10-11:** Farhan saw the dedicated bot's alert
in the notification list on his physical iPhone's lock screen, outside Telegram.
It was manually triggered with a real current Oura reading. The supplied screenshot
also verifies the message and ring avatar on the lock screen. A transient banner
and continuous recording have not been verified. A fresh nontechnical user's
complete agent-led setup remains untested; this was an assisted existing account.

## Live run with a fresh Oura application

1. Register a new application at https://developer.ouraring.com/applications with
   Redirect URI `http://localhost:8765/callback`. Note which fields Oura required.
2. On a clean user account (or a machine without Python developer tools), follow the
   README setup request and AGENTS.md from the start, timing it.
3. Telegram: create a new bot, pair with the code, confirm the message arrives.
4. Oura: approve in the browser and confirm the automatic return works. Also try the
   paste-the-address fallback once.
5. `test` prints today's stress minutes (or "no data yet") and the Telegram test arrives.
6. Accept background checks. Confirm the verification run passes and `status` shows
   the schedule running. On macOS, log out and back in, then confirm `Last check`
   advances.
7. Force a token refresh: edit `expires_at` in `tokens.json` to a past time, run
   `check`, confirm `tokens.json` now has a new refresh token and the check succeeds.
8. Lost refresh response: copy `tokens.json`, force a refresh, then restore the old
   copy (its refresh token is now spent). Run `check`: expect the "paused, reconnect"
   Telegram message with an absolute command. Run that command and confirm checks resume.
9. Revoke access in the Oura app or website, confirm the same reconnect path.
10. Linux (if available): repeat 6 with the systemd timer, and once with cron
    (cron stays labeled experimental until this passes).
11. Windows: repeat setup, both callback paths, task installation, refresh/reconnect,
    settings, sign-out/sign-in and uninstall in a normal user session. Verify the
    iPhone notification independently. Native CI tests do not replace this run.

## Results

| Date | Version | Who | Platform | Result |
|---|---|---|---|---|
| 2026-10-11 | 0.2.2 beta | Farhan + Codex | macOS automated checks | Silent first-reading baseline implemented with explicit state migration. Automated regressions cover first reads, established no-data mornings, retries, quiet-hours verification, reconnects and date changes. No new live setup or phone alert was sent. Fresh-user setup, natural automatic phone delivery, transient banner, macOS logout/login, access revocation, live Linux scheduling and any live Windows setup remain untested. Final automated and review results are recorded below; see the release for the published commit and CI result. |
| 2026-10-10 | 0.1.0 | Farhan + Codex | macOS 26.5.2 (arm64) | Passed the tested macOS setup and recovery paths after the live-tested fixes; later review-driven fixes are unit-tested only: fresh app, Telegram pairing/delivery, automatic and pasted callbacks, real stress read, launchd startup, forced refresh and spent-token recovery. 80 tests pass on both local Python versions after follow-up review fixes. Exceptions: assisted existing account without timing; logout/login and revocation await approval; live Linux scheduling not tested. |
| 2026-10-10 | 0.2.0 | Farhan + Codex | macOS, Linux and Windows CI | 112 tests pass on all seven CI targets, including native Windows permissions, locking, scheduler lifecycle and full scheduler installation with synthetic API responses. Live Windows account setup, standard-user installation, logout/login and phone delivery not performed. Opus 5.5 proposal review: 75 then 87 at the round limit; final code and both GIFs light-reviewed at xhigh: 85. Supported fixes were tested after review, without another model round. Demos use example data. |
| 2026-10-11 | 0.2.1 | Farhan + Codex | macOS and physical iPhone; Linux/Windows CI | Ring profile picture uploaded, read back and visually verified. The 123-test suite passed both local Python versions and all seven CI targets on 84dc019, with expected platform-specific skips. Farhan confirmed a manually triggered real-data alert on the physical iPhone lock screen, outside Telegram, then supplied screenshot evidence showing the message and avatar. The README GIF now combines cropped real notification and Oura screenshots. Transient banner and continuous recording remain unverified. Assisted existing account, no fresh-user timing, no natural stress-increase event observed during this check. Earlier live-platform deviations remain. |

### 0.2.2 beta validation

The first successful check with valid stress data now records a new installation's
starting point silently. Established and legacy installations preserve their
baseline, including after no-data checks and failed sends. New-day behavior stays
unchanged. This change has automated coverage only.

The full suite discovers 137 tests and passes on both local interpreters
(`/opt/homebrew/bin/python3` 3.14.4 and `/usr/bin/python3` 3.9.6), with 10 expected
platform skips each. The native Windows installation fixture now supplies positive
stress data and rejects every Telegram call, verifying silent seeding in the actual
scheduled-command path when run on Windows CI.

The proposal received two Opus 5.5 deep-review rounds at requested max effort and
standard speed, scoring 86 then 88. It reached its two-round limit, not convergence.
Supported final findings were incorporated into the implementation: explicit marker
preservation across no-data checks, tests for that path, source-checkout update
commands and installed-version verification, conditional setup wording, qualified
live-test history, and reproducible outlined social-preview artwork.

The final implementation received one Opus 5.5 light-review round at requested
xhigh effort and reported standard speed, scoring 91/100 with no blocking findings.
Its two low-severity documentation findings were resolved by recording this result
and cleaning up the historical proposal. Those text corrections were checked by
the host after review. The reviewed code and media were unchanged. See the
[v0.2.2 release](https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress/releases/tag/v0.2.2)
for its final commit and CI result.

The first publication CI run exposed an inherited callback-test race on macOS:
the HTTP response could arrive before the handler set its completion event.
The test now waits for that event with a timeout. A controlled delayed-signal
reproduction demonstrated the old assertion failing and the corrected assertion
passing. This test-only follow-up was made after light review; application code
and media stayed unchanged. The complete suite was rerun on both local Python
versions and the corrective push requires all seven CI targets before publication.

Live evidence predates this change: macOS setup/recovery ran on 0.1.0 on October 10;
later recovery fixes have automated coverage. The October 11 lock-screen delivery
used the 0.2.1 formatter before commit `6b139d9` shortened its headline. Neither the
shortened wording nor the new baseline behavior has been delivered live in this run.
Windows evidence remains synthetic CI on administrator runners, not a live account
setup. The proposal and implementation detail are in [the beta release plan](docs/BETA_RELEASE_PROPOSAL.md).

### 2026-10-11 first stress period demo

The README GIF and current MP4 now use example stress readings within the captured
app layout: earlier graph points remain below Stressed, only the final rise enters
that band, and the plot ends there. Oura Today and the detail card both show 15m
stressed, with matching one-hour relative-time labels. This is an illustrative
first-period example, not a new live test or the owner's measured data.

The calendar keeps its event times, colors and notification counts. Only its titles
are replaced with "Finish Monday's slides", "Pick up Thai takeout" and
"Read Project Hail Mary". Pixel comparisons confirm the surrounding capture is
unchanged outside the graph, reading labels and event-title areas. The notification
wording, 4.67-second clean hold and complete animation timing are preserved.
The application code, saved data and real calendar were not changed.

The v0.2.2 source tag and its original MP4 remain the original release snapshot.
The updated MP4 is an additional media download, `demo-first-stress.mp4`, with
current provenance and hashes in [DEMOS.md](docs/DEMOS.md).

Opus 5.5 reviewed the visual changes at requested xhigh effort and reported standard
speed. The first acceptance pass scored 82 and agreed with the requested changes,
while identifying a timing mismatch and minor graph/provenance refinements. The
corrected graph uses native quarter-hour spacing, places its first stressed sample
at 13:00-13:15 before the 13:28 notification, and aligns its gridlines and one-hour
labels. A targeted final acceptance scored 93: "AGREE. All five prior findings are
fixed, and I found no new material defect." The final media bytes were kept unchanged
after that acceptance. Only this validation record was added afterward.

### 2026-10-11 physical iPhone delivery

A manually triggered alert used the current Oura API reading and the program's
normal stress-alert wording. Telegram accepted the send, and Farhan confirmed it
appeared in the notification list on the physical iPhone lock screen, outside
Telegram. This passes lock-screen delivery; it does not establish a transient
banner or an automatic alert triggered by a newly observed increase.

The iPhone's Telegram settings already allowed notifications, Lock Screen,
Notification Center and Banners. No notification preferences were changed.
iPhone Mirroring did not display the notification in the captured frames, so those
frames are not evidence of phone delivery. The owner then supplied a physical
iPhone lock-screen screenshot showing the real message, ring avatar and Telegram
badge. From that screenshot, the public demo uses only the alert notification
crop; other notifications and personal widgets are excluded.

The first replacement README GIF combined that notification with real Oura graph views,
including Oura's red background when an earlier stressed point is selected. Graph
and message data are unchanged. App display overlays were restored after capture.
The animation uses cropped screenshots and crossfades, not a continuous recording;
see [demo provenance and rebuild instructions](docs/DEMOS.md).

Opus 5.5 reviewed the replacement GIF and documentation in one light-review round
at requested xhigh effort and reported standard speed, scoring 88/100 with no
blocking findings. Six low-severity findings were accepted: clearer capture/edit
provenance, precise notification wording, historical tense, an in-image caption
for the earlier selected point, and explicit rebuild output/font instructions.
Those follow-up edits were checked by the host, not sent for a second model round.
That stacked layout did not meet the required phone walkthrough sequence; the
score did not establish acceptance of that sequence.

### 2026-10-11 full-phone walkthrough revision

The next revision uses one consistent iPhone frame: clear lock screen, real
notification reveal, unlock swipe, visible Oura icon tap, Oura Today, visible Stress
tap, and the real Daytime Stress screen. The Oura captures came from iPhone Mirroring.
Private notification/widget areas were removed from the lock screen with generated
wallpaper fill. The Home Screen calendar widget was kept with generic event titles;
its times, layout, app notification badges and counts were retained. App icons and
Oura UI/data were retained. Interactions
and transitions are simulated. The walkthrough compresses the time between
the original notification capture and the later app reading. Graph overlays were
restored after capture. This is an edited demonstration, not continuous footage.

Opus 5.5 explicitly accepted the final rendered sequence: "AGREE. This exact rendered
candidate meets the full walkthrough brief." Three acceptance checks used requested
xhigh effort and reported standard speed. The first two scored 78 and 86 and did
not agree, identifying unlock/launch defects and a status-bar seam. Those defects
were corrected. The final check scored 93/100 with no blocking findings and verified
the full sequence, generic calendar titles, original event times and badge counts.

The Opus-accepted baseline GIF had SHA-256
`16ce8be0273b15d67d20fd3becf619f599d4ce000c7059a16b73490cb6b93e36`.
Its image and animation bytes were kept unchanged for that publication. Minor
status-bar and palette limitations were explicitly accepted as nonblocking at the
README display size. A subsequent requested edit removes the "Later" intertitle,
its dimming and its interlude, then holds the notification for two extra seconds
before going directly into the unlock. Frame comparisons verify that the remaining
motion is unchanged, and the encoded notification hold increases from 2.67 to
4.67 seconds. The historical acceptance and hash above refer to the prior
16-second version, which included the intertitle.

Opus 5.5 separately accepted the timing follow-up: "AGREE. Both requested edits
are correctly implemented, and I found no unintended changes." The targeted
review used requested xhigh effort and reported standard speed, scoring 95/100.
The revised 17.27-second GIF has SHA-256
`0ea17395ecbf4a360de0391e1b2fcf4be3ec4d31b8451a306fdf344a88b56f5b`.

### 2026-10-11 notification headline

The first stress alert now begins "Oura recorded high stress", without the daily
minute total. The alert rule, saved baseline, later-increase messages and remaining
first-alert text are unchanged. The README GIF and poster use the same shortened
headline, edited in the original notification crop. Only the removed punctuation
and duration areas were changed; the surrounding captured pixels are preserved.
The complete animation timeline, including its extended notification hold, is
unchanged. The 123-test suite passes on both local Python versions with 10 expected
platform skips each. This wording change was not sent as a new live phone alert.

Opus 5.5 accepted the exact GIF and formatter change in one targeted light review
at requested xhigh effort and reported standard speed: "AGREE. The change does
what was asked." It scored 88/100 with no blocking findings. Follow-up documentation
clarifies retained preview spacing, the original formatter used for live delivery,
and first-alert versus later-alert contents. Those wording fixes were checked by
the host after review. Earlier artwork remains labeled historical. The accepted
GIF has SHA-256
`76cffd8546baf6ab5fb3f7d7c321b102c1ab3cc15aac5f0d01e2bb634a9e826e`.

### 2026-10-11 bot picture

The repository includes a generated, unbranded ring JPEG. Guided setup sets it only
when the bot has no profile photo. The explicit `set-bot-photo` command applies it
to an existing bot, and installation keeps the asset beside the copied program.
Tests cover multipart JPEG bytes, preserving custom photos, upload errors and
secret redaction, continued pairing after an image failure, and installed assets.
The live upload was verified by retrieving Telegram's latest profile image and
checking the public bot profile. Its placement beside the Telegram badge in the
iPhone notification was subsequently verified in the supplied lock-screen screenshot.

### 2026-10-10 live run details

- **Step 1, passed:** registered a fresh app in the new developer portal. The old
  `cloud.ouraring.com/oauth/applications` page no longer creates applications.
  Required fields: Display Name, Description, Contact Email, Website, Privacy
  Policy, Terms of Service and Redirect URIs, plus acceptance of the Oura API
  Agreement. The repository URL was accepted for all three website/policy/terms
  fields. Redirect: `http://localhost:8765/callback`. Initially selected only
  Daily. The first successful stress read occurred before the app owner enabled
  additional app scopes, so Daily-only registration was exercised. The tool's
  OAuth requests remained `scope=daily` throughout.
- **Step 2, deviation:** an agent assisted on the existing main macOS account,
  with developer tools already installed. No clean-account test or stopwatch
  measurement was performed.
- **Step 3, passed:** a new Telegram bot was created and paired in the preceding
  setup session. The pairing code and confirmation were verified in Telegram Web.
- **Step 4, passed with a deviation:** automatic localhost return completed.
  Separately reserved both callback addresses on port 8765, ran `connect-oura`
  in a terminal, and pasted the failed browser callback address. Reconnection
  and a subsequent check succeeded. After consent-page errors, this manual test
  used Oura's documented alternate `https://developer.ouraring.com/authorize`
  URL with the original query, state and PKCE values. The normal setup and later
  recovery command used the unchanged default authorization URL. Some consent
  attempts returned Oura's generic HTTP 400 page; a fresh attempt succeeded.
- **Step 5, passed:** `test` printed today's real stress minutes. Both the test
  message and a real stress alert were visible in Telegram Web. Personal stress
  values are intentionally omitted from this public result.
- **Step 6, passed for installation/startup:** answered Y during setup. The
  verification check succeeded, launchd started its own successful check, and
  `status` showed the installed five-minute schedule. After the fixes, reinstalled
  and verified the scheduler again. The installed script matched the source tested at that time (`805ebdd`). **Logout/login remains untested:** approval was requested and had not
  been received during this run.
- **Step 7, passed:** set `expires_at` to the past under the shared token lock,
  ran `check`, and confirmed a different refresh token, a future expiry and an
  `ok` result without displaying credentials.
- **Step 8, passed after a fix:** saved a private token copy, forced a successful
  rotation, restored the spent token, and ran `check`. Oura returned HTTP 400
  `invalid_request` with `Invalid request`, rather than the mocked
  `invalid_grant`. The original code failed without sending the pause notice.
  Fixed refresh-request rejection handling; rerunning the spent-token check
  paused and delivered the reconnect notice. Ran its exact absolute command
  from `/tmp`, reconnected and confirmed successful checks. Deleted the temporary
  token copy. Temporarily unloaded only this tool's job during token fault
  injection, then restored and verified it.
- **Additional fix:** declining Daily consent produced HTTP 401 with
  `Token is not authorized access daily scope.` The tool now explains the
  missing permission, pauses without an unnecessary token refresh, and directs
  the user to enable **Sleep, readiness, and activity** before pressing Allow.
  Added this instruction to setup, reconnect notices and documentation.
- **Step 9, not run:** approval to revoke the new app's access was requested and
  had not been received during this run. Revocation remains unverified.
- **Step 10, not run:** this live run is on macOS. Linux systemd and cron live
  checks remain unverified; cron remains experimental.
- **Automated checks, passed locally:** all 80 tests using
  `/opt/homebrew/bin/python3 -m unittest discover -s tests -v` (Python 3.14.4)
  and `/usr/bin/python3 -m unittest discover -s tests -v` (Python 3.9.6).
  Regression tests cover the observed spent-token response, missing Daily consent
  and the current registration portal.

The tested macOS paths pass. This is not a complete pass of every checklist item.

### Follow-up code review and cleanup

The first Opus 5.5 deep-review round identified a setup recovery gap: a
missing-permission error pointed to `connect-oura`, which could leave setup
unfinished without a background job. Setup failures now direct users back to
`setup`, preserving saved keys and allowing installation to finish. Standalone
`connect-oura` verifies a real stress read before reporting success and explains
how to install automatic checks when absent. Consent notices distinguish missing
permission from an invalid login; the missing-permission response parser accepts
the observed wording and the grammatical variant with `to access`. Setup prompts
and troubleshooting now match the verified portal and consent flow. These
follow-up changes are covered by isolated regression tests; the interactive
OAuth flow was not repeated after them.

After live validation, the new Mac job was uninstalled to avoid duplicate alerts.
The job and plist were verified absent, and saved settings and the Oura connection
were retained for later testing. Uninstall also retains the installed script
copy. The existing separate monitor was untouched.

The Opus 5.5 review ended at its two-round limit, scoring 85 then 88, rather
than converging. Host corrections after round two distinguish rejected app keys
from missing consent, use the running source for interactive recovery commands,
persist interactive reconnect failures under the read lock, avoid duplicate
Telegram notices after a terminal error, explain saved logins after temporary
read failures, and include a recovery command in paused installation failures.
These final corrections have regression coverage but were not sent for a third
model review. No approval score is claimed for them.

### Distribution guide follow-up

At that time, the public README put a one-line agent setup request above an illustrative
iPhone notification with example data. The image has a transparent outer
background for light and dark themes. Detailed requirements, manual setup,
troubleshooting and project status live in SETUP.md.
AGENTS.md tells installation agents to perform the technical work, provide exact
Oura form values, support downloading without Git, and stay until phone delivery
and automatic checks are verified. This is preparation for the distribution
acceptance test above; it is not a claim that a fresh user or phone test passed.

The subsequent one-round Opus 5.5 light review scored the onboarding 80/100.
Follow-up documentation changes require testing with Telegram in the background,
state the actual test-message text, explain using Telegram on the computer to copy
the token, restore the python.org certificate step, classify quiet-hours skips,
and scope AGENTS.md to installation requests. The iPhone illustration was updated
to show a lower-screen card with plain preview text. These host changes were
visually and structurally checked after review, not sent for another model round.

### Windows support and animated demos, 0.2.0

The Windows proposal received two Opus 5.5 deep-review rounds, scoring 75 then 87.
The review reached its round limit; it did not converge. The implementation uses
one repeating Task Scheduler trigger, a console interpreter for recovery commands,
a windowless interpreter for scheduled checks, Windows file locks, private access
rules, a pre-write Store-runtime check, a soft interrupt deadline and the scheduler's
hard limit. Native CI tests cover actual Task Scheduler registration and cleanup,
file permissions, file replacement, callback binding, PowerShell quoting and
windowless execution, with no Oura or Telegram credentials.

The first Windows CI run found that SDDL can abbreviate the current built-in
administrator account as LA, and that Task Scheduler omits default XML properties.
Both were corrected with regression coverage. Older notification assertions were
updated to accept correctly quoted PowerShell commands, and recovery-command tests
now use a UTF-8 PowerShell session and compare canonical data paths.

Live Windows account setup, a normal non-administrator's installation, logout/login,
and physical iPhone delivery remain untested. The user explicitly accepted that
live Windows setup would not be available for this release. Windows stays labeled
experimental. CI run 38113955600 passed all seven targets on commit c15e1d9 after the final
review fixes, with 112 tests discovered per target. Mac/Linux skip the 10 native
Windows tests; Windows skips 6 POSIX-specific tests. All four Windows versions
passed a full scheduler installation using synthetic API responses, including
copying the program, the verification check, registration, read-back, actual
scheduler execution and cleanup. Windows runners were administrators with
interactive sessions; this does not establish a standard-user setup.

The final one-round Opus 5.5 light review used the requested xhigh effort and
reported standard speed. It scored the complete implementation and both GIFs
85/100, with no blocking findings. Follow-up fixes remove an unverified task
and identify differing fields after a read-back mismatch, preserve useful status
and successful reconnect results when scheduler queries fail, and add the full
native scheduler-install test. Visual fixes add readable caption pills for both
themes, consistent 12-hour labels, slide/zoom transitions, a clean loop boundary,
reference-based UI details and a corrected static time axis. Lossless GIF
optimization preserves decoded frames while reducing download size. These host
fixes have automated and visual checks; they were not sent for another model
round and do not inherit a new review score.

The [two earlier GIF demos](docs/DEMOS.md#earlier-versions) show simulated Telegram delivery, unlocking the
phone, opening Oura, tapping Stress and viewing an example whose first high-stress
reading is at 3 PM. Their layout was checked against the provided screenshot and
Oura in iPhone Mirroring. No real personal screenshots or readings were published in that release.
The graph overlays were briefly hidden for reference and restored afterward.
These are visual demonstrations, not evidence of a real phone push test.
