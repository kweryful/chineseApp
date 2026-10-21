# Chinese Support 3 integration

The Python modules in `chinese/` are from [kweryful/anki-chinese-support-3](https://github.com/kweryful/anki-chinese-support-3), pinned at commit `306f3a32f453d33d949532c1325c1a689bbab7c2`. They are distributed under the GNU General Public License version 3 or later; see `LICENSE`.

The app adapts this code to work without an Anki process:

- `chinese/main.py` provides the dictionary and the minimal field configuration expected by the add-on modules.
- `chinese/database.py` accepts the app's cached dictionary path and permits its shared read connection to be used by the local web server.
- `chinese/util.py` imports Anki only inside the Anki-specific note-saving helper.
- `chinese/sound.py` imports the add-on's Anki audio downloader only when sound generation is requested.
- Dictionary glosses use Jieba's full mode to include shorter terms inside compound segments. Pinyin and ruby keep Jieba's default non-overlapping segmentation so a vocabulary word such as `来得及` is read once.

The dictionary database is downloaded from that same pinned commit and checked against its Git blob hash before use. Its third-party data sources and their separate terms are listed in `chinese/data/db/COPYING.txt`.
