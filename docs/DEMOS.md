# iPhone walkthrough

The README demo stays inside one iPhone frame throughout:

1. A clear lock screen.
2. The real Telegram stress notification appears and stays visible for about five seconds.
3. An unlock swipe directly after the notification.
4. A simulated tap on the actual Oura Home Screen icon opens Oura Today.
5. A simulated tap on Stress opens Daytime Stress, edited to show the first
   high-stress period of an example day.

<img src="images/demo-walkthrough.gif?v=48337b5dcbb8" alt="Full iPhone walkthrough: notification arrives, unlock, tap Oura, then open Daytime Stress." width="420">

[Still image](images/demo-walkthrough.png)

## Sources and edits

This is an edited walkthrough with simulated interactions, not a continuous screen
recording. The notification is from the owner's physical iPhone screenshot.
The Home Screen, Oura Today and Daytime Stress views were captured through iPhone
Mirroring on the Mac on October 11, 2026. The app layout, controls, colors and
navigation come from those captures. The stress graph and matching numbers have
been edited to show an example first high-stress period: earlier readings stay
below Stressed, only the final rise enters that band, and the graph stops there.
Samples use the native 15-minute spacing. The first stressed sample represents
13:00-13:15, before the 13:28 notification and one hour before the 14:15 app view.
Both Oura screens show 15 minutes stressed. Relative-time labels were changed to
one hour ago. These are illustrative readings, not the owner's measured day.
The example assumes checks were already running before the first increase; a
new installation's initial baseline is still silent.

The lock-screen notification was captured at 13:28. Its headline was edited to
"Oura recorded high stress", removing the daily minute total to match the current
short-headline wording. The Home Screen and Oura captures retain their 14:12 and
14:15 clocks. This edited sequence compresses separate captures; their times and
the example graph are not a measurement of detection or delivery delay. The demo
does not imply an instant Oura reading or alert.
The capture also shows a second line of body text from the earlier message format.
Current first alerts send only the headline, "🔴 Oura recorded high stress", so a new
alert shows that line alone.

The empty lock screen was made from the same screenshot by removing notification
cards and widgets and filling the covered wallpaper with image-generation cleanup.
Its original clock, date, status bar and bottom controls were retained. The Home
Screen calendar widget is kept, with fictional but specific event titles:
"Finish Monday's slides", "Pick up Thai takeout" and "Read Project Hail Mary".
Its layout, colors and event times are preserved.
The actual app icons, positions, labels, notification badges and counts are retained.
Image-generation cleanup and precisely positioned graph samples are confined to
the graph, associated displayed readings and calendar titles, composited into the
original screenshots. The surrounding
captured pixels are retained. No actual Oura account data or calendar was changed.
Raw originals containing unrelated private information are not in this repository.

The native movement and tag overlays were temporarily turned off for a clean graph
and restored after capture. Other edits are screen cropping, a consistent rounded
phone boundary, transparent outer margins, notification reveal, unlock/launch/slide
transitions, simulated touch indicators, and a fade through black at the loop seam.
The launch-only snapshot omits the moving clock, battery and Dynamic Island using
the app's own background pixels; the held app view restores the original status
bar directly. This avoids duplicated device overlays during the simulated zoom.
GIF encoding uses a palette per frame and light lossy compression to reduce the
download size. Only the demo images contain the example stress data; the tool's
API data, alert rule and saved state are unchanged.

The Telegram notification opens Telegram when tapped. The demo correctly unlocks
and taps the separate Oura icon to open Oura. The original alert was manually
triggered using the tool's then-current formatter and a real API reading; delivery
was confirmed on the physical iPhone lock screen. The shortened headline was not
sent as a new live alert. Notification appearance varies with iOS,
Telegram and the person's settings.

## Rebuild

The safe source assets are in [images/walkthrough](images/walkthrough).
The composition source is [render_walkthrough.mjs](images/render_walkthrough.mjs).
Use a scratch folder with Node and `@resvg/resvg-js`, plus ffmpeg and gifsicle.
These development tools are only for the GIF; the alert program remains Python
standard-library only. Copy the renderer into the scratch folder so Node can find
its dependency, then use absolute paths:

```sh
node render_walkthrough.mjs /path/to/repo/docs/images /path/to/scratch/frames
ffmpeg -y -framerate 15 -i /path/to/scratch/frames/%04d.png \
  -filter_complex '[0:v]split[a][b];[a]palettegen=max_colors=256:reserve_transparent=1:stats_mode=single[p];[b][p]paletteuse=new=1:dither=bayer:bayer_scale=4:alpha_threshold=128' \
  -loop 0 -final_delay 7 /path/to/scratch/unoptimized.gif
gifsicle -O3 --lossy=20 /path/to/scratch/unoptimized.gif -o /path/to/repo/docs/images/demo-walkthrough.gif
cp /path/to/scratch/frames/poster.png /path/to/repo/docs/images/demo-walkthrough.png
```

All iPhone and app lettering is in the source images, including the edited
notification headline, example stress readings and fictional calendar titles. Review the full loop
on light and dark backgrounds, including the blank opening, notification arrival,
each visible tap, both app transitions and the loop seam.

## Sharing assets

- [MP4 walkthrough](images/demo-walkthrough.mp4): H.264, yuv420p, 652 x 1380,
  15 fps, 259 frames, 17.266667 seconds, no audio, fast-start playback.
- [Social preview](images/social-preview.png): 1280 x 640, 167,488 bytes, intended
  for the GitHub repository link preview. It combines the existing generated ring
  avatar with the [walkthrough notification crop](images/walkthrough/notification.png),
  which shows Oura Stress Alerts. It is labeled unofficial and an edited
  demo. No new Oura UI or reading was generated.

The current MP4 and GIF use the same source frames and 4.67-second clean notification
hold, with dark outer margins in the MP4. The tiny duration difference comes from
GIF centisecond rounding. This example-data revision is available as
[demo-first-stress.mp4](https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress/releases/download/v0.2.2/demo-first-stress.mp4)
in the beta downloads. The original release MP4 and tagged source archive retain
the earlier captured readings for reproducibility.

After rendering the walkthrough's source frames as above, export the MP4 with
ffmpeg 8.1 (libx264):

```sh
ffmpeg -y -framerate 15 -i /path/to/scratch/frames/%04d.png \
  -f lavfi -i color=c=0x0d1117:s=652x1380:r=15 \
  -filter_complex '[1:v][0:v]overlay=shortest=1:format=auto,format=yuv420p[v]' \
  -map '[v]' -an -c:v libx264 -preset slow -crf 18 -r 15 -frames:v 259 \
  -map_metadata -1 -movflags +faststart /path/to/repo/docs/images/demo-walkthrough.mp4
```

The [social-preview SVG](images/social-preview.svg) embeds its image assets and
outlines every letter, so it renders without installed fonts. In a scratch Node
folder, install `@resvg/resvg-js@2.6.2` and render it:

```sh
npm install @resvg/resvg-js@2.6.2
node --input-type=module - /path/to/repo/docs/images/social-preview.svg /path/to/repo/docs/images/social-preview.png <<'JS'
import fs from 'node:fs';
import { Resvg } from '@resvg/resvg-js';
fs.writeFileSync(process.argv[3], new Resvg(fs.readFileSync(process.argv[2])).render().asPng());
JS
```

To change the card composition, [render_social_preview.py](images/render_social_preview.py)
builds its SVG using `fonttools==4.66.1` in a development-only virtual environment.
Pass the two font files as arguments: Arial.ttf and Arial Bold.ttf. The renderer
pins their SHA-256 hashes to `525979822591a3447cfc49d943d6f7683508e25543407871c0ed8fed05fd2bd9`
and `d72db21f9242aedd6b917d8549ad5921766b24d5f8d0becfda2ff4c620b3c2e0` respectively.
The original fonts are not bundled; the committed outlined SVG is the portable
render source. The card uses walkthrough/notification.png, which shows the
Oura Stress Alerts notification from the demo. None of these development dependencies is needed to run the tool.

Current media and original release asset SHA-256:

```text
social-preview.png     9538b580bc23738bdd834d2cfb4b7da90256c64051146bf89aea83f2b1ab4836
demo-walkthrough.gif   48337b5dcbb8613fbc95a6e6faecc78e1beb0bff6631ce5d9ab4a16abb6cc139
demo-first-stress.mp4 (also the repo docs/images/demo-walkthrough.mp4)
                      853199ca747f30595eeca5cbaf268bb44fc5f893fb5b14d6c22b528ed4a9425a
original v0.2.2 release demo-walkthrough.mp4
                      35b8e149572b96191b4a9767e3de0940b446d49fedc9351c8a1cf338f6234149
```

## Earlier versions

The [older realistic mockup](images/demo-realistic.gif) and
[illustrated mockup](images/demo-illustrated.gif) use synthetic data and UI.
They are retained as earlier artwork, not the README demo. An earlier stacked
explainer built from unedited screenshots of a real day's stress readings was
removed so the repository does not publish that personal data.
