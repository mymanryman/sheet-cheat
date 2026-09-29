# Sheet Cheat

Open a sheet music PDF in your browser and see the name of every note
(C, C♯, D, E♭ …) printed right next to it. Big buttons on both sides of the
screen turn the pages.

It runs entirely on your own computer:

* **Viewer**: a web page (in `web/`) that shows the PDF with [pdf.js](https://mozilla.github.io/pdf.js/).
* **Note reading**: [Audiveris](https://github.com/Audiveris/audiveris), a free, open-source
  optical music recognition (OMR) program. It reads each page and exports MusicXML;
  `omr.py` turns that into positions on the page so the names can be drawn on top.
* **Server**: `server.py`, a small Python program with no extra packages to install.

Each page is read once and the result is saved in the `cache/` folder, so opening the
same PDF again is instant.

## How accurate is it?

Audiveris does well on clean, printed music: PDFs exported from MuseScore, Sibelius,
Finale or Dorico, and good scans (300 dpi, straight, not blurry). On those, expect the
large majority of notes to be named correctly. Things to watch out for:

* A misread **clef or key signature** makes a whole line wrong (every note shifted, or
  every F missing its ♯). If a whole line looks off, that's usually why.
* Dense chords, cross-staff notes, grace notes and tuplets are sometimes missed or merged.
* Handwritten music, phone photos and faint old scans work poorly.
* It takes roughly 15–60 seconds per page on a MacBook Air. The page you are looking at is
  read first; the others follow in the background.

Treat the names as a helper, not gospel.

## Set up on a Mac (from scratch)

Open **Terminal** (press ⌘ Space, type `Terminal`, press Return) and follow the steps.
Lines in grey boxes are commands: copy one, paste it into Terminal, press Return.

### 1. Install Apple's command line tools (gives you `python3` and `git`)

```sh
xcode-select --install
```

A window pops up: click **Install** and wait until it finishes. (If it says the tools
are already installed, that's fine.) Check it worked:

```sh
python3 --version
```

It should print something like `Python 3.9.6`.

### 2. Install Audiveris (the note reader)

Find out which kind of chip your Mac has:

```sh
uname -m
```

`arm64` means an Apple chip (M1, M2, M3, M4 …), `x86_64` means an Intel chip.

1. Go to <https://github.com/Audiveris/audiveris/releases> and, under the newest release,
   open **Assets** and download the **macOS `.dmg`** that matches your chip
   (the file name contains `arm64` for Apple chips or `x86_64` for Intel).
2. Open the downloaded `.dmg` and drag **Audiveris** into **Applications**.
3. macOS may block apps downloaded from the internet. Unblock it (it asks for your Mac
   login password; nothing shows while you type it, just press Return):

   ```sh
   sudo xattr -dr com.apple.quarantine /Applications/Audiveris*.app
   ```

   If it says "Operation not permitted", open System Settings → Privacy & Security →
   App Management, switch Terminal on, quit and reopen Terminal, and run it again.
   Alternatively, open Audiveris once from Applications and, if macOS blocks it, click
   **Open Anyway** under System Settings → Privacy & Security.

4. Check that Sheet Cheat will be able to find it:

   ```sh
   ls /Applications/Audiveris*.app/Contents/MacOS/
   ```

   This should list a program called `Audiveris`. Audiveris ships with its own Java,
   so nothing else is needed.

### 3. Get Sheet Cheat

The easiest way (works for a private repository too):

1. Open <https://github.com/mymanryman/sheet-cheat>, click the green **Code** button,
   then **Download ZIP**.
2. Unpack it into your home folder:

   ```sh
   cd ~/Downloads
   unzip -q sheet-cheat-main.zip
   mv sheet-cheat-main ~/sheet-cheat
   ```

(If you prefer git and have it signed in to GitHub:
`git clone https://github.com/mymanryman/sheet-cheat.git ~/sheet-cheat`.)

### 4. Start it

```sh
cd ~/sheet-cheat
python3 server.py
```

Your browser opens <http://localhost:8765>. Click **Open PDF…** (or drop a PDF on the page).
The PDF shows straight away; note names appear as each page is read.

Leave the Terminal window open while you use it. To stop, click in Terminal and press
**Ctrl + C**.

### Every time after that

```sh
cd ~/sheet-cheat
python3 server.py
```

### Updating to a newer version

Stop the server (Ctrl + C), delete the old zip, download the new ZIP from GitHub
(Code → Download ZIP), then:

```sh
cd ~/Downloads
unzip -q sheet-cheat-main.zip
mv ~/sheet-cheat/cache sheet-cheat-main/ 2>/dev/null
rm -rf ~/sheet-cheat
mv sheet-cheat-main ~/sheet-cheat
cd ~/sheet-cheat
python3 server.py
```

This keeps the pages that were already read (the `cache` folder).

## Using it

* **Turn pages**: the big ‹ › buttons on the left and right, or the arrow keys,
  Page Up/Down, or the space bar (Shift + space goes back). Works with most
  Bluetooth page-turn pedals too, since they send arrow or page keys.
* **Note names**: switch them on and off at the top.
* **As written / Sharps only / Flats only**: show accidentals as printed (C♯, D♭),
  or always as sharps, or always as flats.
* **Octave**: adds the octave number (middle C is C4).
* **Colors**: gives each note letter its own color.
* **Size**: makes the labels bigger or smaller.
* **Fit page / Fit width**: fit width makes everything larger; scroll down within the page.

## Troubleshooting

* **"Audiveris not installed"**: step 2 didn't find the app. If it's installed somewhere
  else, start the server with its path:
  `AUDIVERIS="/path/to/Audiveris" python3 server.py`
* **A page shows no names or an error**: Audiveris' log for that page is in
  `cache/<long id>/page-N.audiveris.log`, next to the MusicXML it produced
  (`page-N.mxl`, which you can open in MuseScore to see what it read).
* **Read a PDF again from scratch**: quit the server, delete the cache, start again:
  `rm -rf ~/sheet-cheat/cache`
* **Port already in use**: `python3 server.py --port 8800`, then open <http://localhost:8800>.

## Development

```sh
python3 -m unittest discover -s tests
```

`omr.py` can also be run on a MusicXML file to print the note positions:
`python3 omr.py some-file.mxl`.
