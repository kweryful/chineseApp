# Dialogue Workshop

A local web app for turning Chinese textbook dialogues into sentence-level listening clips.

## Run locally

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open <http://127.0.0.1:8000>. The app binds to the local machine by default. Audio is processed by the local Python server. FFmpeg is provided by the `imageio-ffmpeg` Python package.

## Workflow

1. Enter the dialogue text and choose its MP3. Speaker labels such as `大卫：` are removed. A leading unpunctuated chapter heading is checked against the audio but is not required as a separate name field. Export files use the MP3 filename.
2. Select **Prepare, sync & generate fields**. The app creates line candidates, transcribes Mandarin speech locally, and matches the dialogue in order, skipping spoken lesson numbers and other unmatched introductions. Within speaker-labelled dialogue, an unlabelled wrapped continuation is joined to the preceding speaker turn when the text ends mid-sentence. The same button moves into the editor as **Auto-sync & generate fields** so you can rerun matching and regenerate study fields after editing line text. Comma-separated text is initially split into candidate clauses. During auto-sync, clear clause cues such as `不过`, `可是`, `结果`, `实在`, `就`, `我没做完`, and `然后` start a new line; paired constructions such as `不但……还得……` stay together. Other comma-separated clauses are combined unless the recognized speech has a pause of at least 0.4 seconds. Sentence-ending punctuation always starts a new line. If a leading heading such as `马克介绍自己学习汉语的方法` is spoken, it is included as the first timed line; if it is not spoken, it remains only as a heading in the entered dialogue text. If a sentence is split too aggressively, select **Merge with next** under the line to combine it with the following one; run **Auto-sync & generate fields** again to refresh its timing and study fields. At boundaries between matched lines, auto-sync checks the decoded waveform and trims each clip to the nearest edge of a detected quiet section, removing the pause from both clips rather than placing a shared boundary in its middle. When a quiet section cannot be detected, the waveform-based timing uses only a short lead-in before recognized speech rather than a long silence cushion. The full-dialogue waveform is an overview; use the round play/pause button and seeker beneath it to play or seek across the whole recording. Set or adjust timings only on each line's padded waveform, which also has a round **▶/❚❚** playback control. Click a line entry's background to select it and focus its waveform; press **Space** to play or pause its clip. After dragging to set a timing, the waveform remains focused. In the study-field editors, **Tab** moves from English translation to reading, ruby, and dictionary gloss, skipping the **Edit HTML** controls. Lines the recognizer cannot match can be timed the same way. After auto-sync succeeds, the button generates editable English translations and Chinese Support 3-style readings, ruby, and dictionary glosses for each line.
3. Optionally enter new vocabulary in the right sidebar, one entry per line: the word, optional numbered pinyin, then its definition (for example, `血 xue4 blood` or `血 xie3 blood`). Matching vocabulary is highlighted in bold over a light background directly in each dialogue line's Hanzi editor, updating as the line text or vocabulary list changes. Select **Show formatted vocabulary** to submit the list and display tone-colored ruby with its definition; select **Edit vocabulary** to return to the text editor. When returning to edit mode, the displayed pinyin is converted to numbered pinyin so you can correct ambiguous pronunciations. Each line's English translation is inside the expandable study-fields section with the reading, ruby, and dictionary gloss. For each dialogue line, matching vocabulary is exported in the `Word`, `WordDef`, and `WordRuby` fields: words and ruby are comma-separated, while definitions are separated by `<hr>`. When vocabulary is provided, the **Export vocabulary lines** button exports only lines containing a listed word in the audio clips, dialogue text, JSON, and CSV; **Export line clips** exports every line. The vocabulary list is included in either export's vocabulary text file. You may optionally enter a source folder name; clip filenames then use `<folder>-<mp3-name>-line-001.mp3` (for example, `hsk4_SB_B_audio-11-2-line-001.mp3`). The browser does not expose the selected MP3's folder path, so enter the folder name in the optional field. Export a ZIP containing one MP3 per exported line, `<mp3-name>.txt` with the exported dialogue text, and, if vocabulary was provided, `<mp3-name>-vocab.txt` with tab-separated hanzi, pinyin, and definitions, plus `dialogue.json` and `dialogue.csv`. The text files use UTF-8; the vocabulary pinyin uses the entered numbered pronunciation when supplied, otherwise the generated reading. JSON and CSV omit clip start/end timestamps. The English translation remains in the `gloss` field for compatibility.

Automatic sync uses the `base` faster-whisper model on the CPU. The first sync downloads the model from Hugging Face (about 150 MB); later syncs use the cached local copy. English translations use Argos Translate on your computer; the first translation downloads the Chinese-to-English model, which is then cached locally. Dialogue text and audio are not sent to a transcription or translation service. Set `DIALOGUE_WHISPER_MODEL` before starting the app to select another faster-whisper model size, such as `small`.

Translations are generated by `glossing.py` through `/api/translations` as part of the combined field-generation action. The app installs the Argos Chinese-to-English model on first use; this one-time setup requires an internet connection. If the download fails, the app reports the issue and does not use an online translation service. Generated translations remain editable before export.

Study-field generation also uses the pinyin and dictionary features from [Chinese Support 3](https://github.com/kweryful/anki-chinese-support-3), adapted to run locally without Anki. The first use downloads and verifies its approximately 76 MB dictionary. The generated reading applies the common `一`/`不` tone changes; ruby and dictionary glosses use the add-on's local Chinese Support engine. Expand a line's study-fields section to edit each field in its tone-colored visual editor, or choose **Edit HTML** to edit its markup directly. Changes made in HTML mode are sanitized to preserve only tone spans, ruby annotations, and line/rule breaks when returning to the visual editor. All outputs are included in the export.

## Licensing

This application includes Chinese Support 3 code, licensed under GNU GPL version 3 or later; see [third_party/anki_chinese_support_3/LICENSE](./third_party/anki_chinese_support_3/LICENSE). Its dictionary data has additional source-specific attribution and license terms listed in [third_party/anki_chinese_support_3/chinese/data/db/COPYING.txt](./third_party/anki_chinese_support_3/chinese/data/db/COPYING.txt). The integrated source is pinned to upstream commit `306f3a32f453d33d949532c1325c1a689bbab7c2`; standalone adaptations are documented in [third_party/anki_chinese_support_3/README.md](./third_party/anki_chinese_support_3/README.md).

## Tests

```powershell
python -m unittest discover -s tests
```
