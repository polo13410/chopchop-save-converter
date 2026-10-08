# Chop Chop Inc. demo save converter

Played the **Chop Chop Inc. demo** for hours and don't want to start over? This tool carries your demo progress over to the **full game**: money, backpack, recipes, missions, skills, and the world itself (trees you cut, things you built, machines and their contents).

Officially, demo saves are not compatible with the full game. This is an unofficial fan tool, not affiliated with NullRef Entertainment or the publisher. It always backs up your saves before touching anything.

## How to use it

1. **Close the game.**
2. **Turn off Steam Cloud for Chop Chop Inc.** In Steam, right-click the game, then *Properties* > *General* > untick *Keep game saves in the Steam Cloud*. Otherwise Steam may put your old save back. You can turn it back on once you have loaded the converted save and saved in game.
3. **Download `ChopChopSaveConverter.exe`** from the [latest release](../../releases/latest).
4. **Double-click it.** It finds your demo save, shows what it is about to do, and asks you to confirm.
5. **Launch Chop Chop Inc. and load your save.**

What the program does when you confirm:

- it copies your current full-game saves to a backup folder next to them, named `saves-backup-<date>-<time>`;
- it converts your demo save and installs it as the full-game save (`save0.sav`);
- it writes a `conversion-log.txt` in the backup folder, with everything it transferred.

Your saves live in `%USERPROFILE%\AppData\LocalLow\NullRef Entertainment\`. To undo, copy the files from the backup's `saves` folder back into `ChopChopInc\saves`.

> **Tip: easier save management.** The [Better Save Slots](https://www.nexusmods.com/chopchopinc/mods/6) mod (Nexus Mods, needs BepInEx) adds more save slots to the game. Handy to keep your converted save next to a fresh full-game run. It is a separate community mod, not made by this project. The converter installs the converted save in the first slot (`save0.sav`).

> **Windows says "Windows protected your PC"?** The program is not signed with a paid certificate, so SmartScreen warns about it. Click *More info* > *Run anyway*. See [Is it safe?](#is-it-safe) to check the file first.

### Is it safe?

You should not run an .exe from the internet blindly. Here is how to check this one.

- **It is built in the open.** Nobody uploads the .exe by hand. GitHub's own servers build it from the source code in this repository, every time the code changes. Each release links to the exact commit and to the build log.
- **Check the hash.** Each release page shows the SHA-256 of the .exe (also in the `.sha256` file next to it). In PowerShell, in your download folder:

  ```
  (Get-FileHash .\ChopChopSaveConverter.exe -Algorithm SHA256).Hash
  ```

  The value must match the release page. This proves your file is the one on the release page and was not altered.
- **Check where it was built (strongest).** Every build gets a signed [build provenance attestation](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations). It is a certificate, signed by GitHub, saying "this exact file was built by this repository's workflow from this commit". A hash posted somewhere can be faked along with the file; this cannot. With the [GitHub CLI](https://cli.github.com/):

  ```
  gh attestation verify .\ChopChopSaveConverter.exe --repo polo13410/chopchop-save-converter
  ```

- **Scan it.** You can drop the file on [VirusTotal](https://www.virustotal.com/). Some antivirus engines flag every program made with PyInstaller, the standard tool that turns Python into an .exe. That is a known false positive.
- **Or skip the .exe entirely** and run the source code with Python (see [Run from source](#run-from-source)). The converter only uses the Python standard library.

What the program touches: it reads your demo save, and writes only inside `%USERPROFILE%\AppData\LocalLow\NullRef Entertainment\ChopChopInc\`, after backing up the existing saves. It does not connect to the internet.

### Options

Run it from a terminal to use these:

| Option | What it does |
|---|---|
| `--demo PATH` | Convert this demo save instead of the one found automatically |
| `--no-install` | Only write `converted-save0.sav` next to the program, change nothing else |
| `--progress-only` | Keep the full-game world untouched, transfer progress only |
| `--verbose` | Show the conversion details |
| `--yes` | Do not ask for confirmation |

### What carries over

| Carried over | Not carried over |
|---|---|
| Money and backpack | The item in your hand |
| Unlocked recipes and shop items | Drones and trucks in the middle of a delivery |
| Target audience levels | Achievements |
| Mission board and active missions, with their progress | |
| Strength, stamina and move speed | |
| Trees and rocks you removed | |
| Buildings, machines, their contents, items on the ground | |
| Your position and where you look | |

### Things to know

- **The Area 2 teleporter has to be rebuilt.** The full game moved it: it now leads to the mountains, from another spot. The converter follows the full game, so the old doors near the lake are not transferred.
- **A few trees and bushes may come back.** The developers rearranged some vegetation. Where a tree moved, the full game's layout wins.
- **New full-game content starts fresh**: new areas, new audiences to unlock, city upgrades, the turtle. The converter starts the missions the full game added on top of the demo, so they show up as if you had played the full game.
- **One full-game tutorial step** ("walk to Chester") may appear. Just follow it.
- Tested with the full game Steam build `25187442` and the demo build `24361147`. A game update may need new data (see [Updating after a game patch](#updating-after-a-game-patch)).

Curious what it does before running it? The [examples folder](examples) has a real demo save, its conversion, and a side-by-side comparison.

If something looks wrong in game, open an issue with what you see, your `conversion-log.txt`, and the game log `ChopChopInc\Player.log` from the saves folder above.

---

## How it works (for curious nerds)

Getting a demo save to load in the full game took a bit more than copying a file. Here is the whole story.

### 1. The save format: Odin Serializer

Chop Chop Inc. is a Unity game. Its saves (`save0.sav`) are written with [Odin Serializer](https://github.com/TeamSirenix/odin-serializer) in its binary format. It is a self-describing tree of entries: nodes carry their C# type name (`Service.Inventory.ServiceData, Assembly-CSharp`...), then named fields, arrays and primitive arrays.

[`chopchop/odin_binary.py`](chopchop/odin_binary.py) reads and writes that format from scratch, following Odin's `BinaryDataReader.cs` / `BinaryDataWriter.cs`. The tree it produces is lossless: decoding then re-encoding gives back the exact same bytes. Two quirks of this game: every string is UTF-16, and there is no end-of-stream marker.

Odin keeps reference ids on reference nodes, numbered in file order, and later entries can point back to them (`intref`), for example to share a dictionary comparer. Any edit that adds, removes or moves nodes must renumber them and repair those links. That is [`chopchop/odin_tree.py`](chopchop/odin_tree.py).

The root of a save is a `Service.SessionData.ServiceData` holding a dictionary from a service type to its data: recipes, shop, inventories, mission board, and one dictionary per kind of per-object data (`WorldObject+SaveData`, `Health+SaveData`, `Crafter+SaveData`...), keyed by world object number.

### 2. Two kinds of identifiers

- **assetIDs** name a *kind* of thing: a recipe, an item, a mission, a prefab. They are hashes, and they are identical in the demo and the full game. Recipes, shop items, audiences and inventory contents only use these, so they copy over directly.
- **worldObjectIDs** number the objects that exist in the world. They are assigned at runtime, so the same number means different objects in the two versions.

To give names to assetIDs, [`tools/extract_catalog.py`](tools/extract_catalog.py) reads the game's Unity files with [UnityPy](https://github.com/K0lb3/UnityPy). Every id used in a 3-hour demo save exists in the full game, except an end-of-demo sign.

### 3. The map

The full game reuses the demo map, so objects can be matched by **type and position**. [`tools/extract_scene.py`](tools/extract_scene.py) extracts the initial state of both maps from the scene files (positions computed through the Transform hierarchy). With three sources (demo map, full map, and the two saves), each object falls into one case ([`chopchop/world.py`](chopchop/world.py)):

| Demo map | Full map | Demo save | Result |
|---|---|---|---|
| yes | yes | present | the full-game object keeps its number and takes the demo state |
| yes | yes | missing | destroyed in the demo (a cut tree): removed |
| yes | moved by up to 3 m | | the full-game version stays at its new spot, unless destroyed in the demo |
| yes | no | | the full game changed that spot: the full game wins |
| no | no | present | spawned during the demo (a building, a dropped item): added with a new number |
| no | yes | | new full-game content: kept |

Two lessons learned the hard way, from the game log and the decompiled game code (read with [dnfile](https://github.com/malwarefrank/dnfile) and [dncil](https://github.com/mandiant/dncil)):

- **Scene objects must keep their number.** Within one version, objects placed in the scenes always get the same worldObjectID, and the game finds them by that number when loading. The first version renumbered them and the game hung on the loading screen.
- **Some scene objects are inactive at the start of the full game** (the cabin, the workbench) and are not in a fresh full-game save. They are recreated from their prefab.

Links between objects are renumbered too: inventories, machines pointing at the object that holds their inventory, child objects, and objects owned by missions.

### 4. Machines that changed

The beaver carving workshop is a simple crafter in the demo and an automated crafter in the full game. When an `AutomatedCrafter` has no saved data, its `OnInitialComponentSaveDataSet` runs before `Awake` has set its link to the crafter, and throws a `NullReferenceException` that blocks loading. The converter gives every automated machine an empty crafting queue, so the game takes its normal "loaded from save" path.

### 5. Missions

An active mission is an invisible world object with the state of its checks. A finished mission simply disappears. The mission board keeps unlocked missions by assetID and running missions by worldObjectID. The demo missions replace the ones the demo knows about, and missions only the full game knows are kept ([`chopchop/missions.py`](chopchop/missions.py)).

The tricky part: **the full game added actions to missions that already existed in the demo.** `Mission_Board_InitialSetup` starts 16 missions in the full game instead of 7 (city upgrades, new audiences). If the demo already ran it, those 9 would never start. So:

1. [`tools/extract_missions.py`](tools/extract_missions.py) extracts every mission of both versions from the game files: its checks (class and id, which match the saves exactly), its actions (start a mission, unlock a recipe, spawn an object...), and the spawn points.
2. The converter infers which demo missions ran. A finished mission leaves no trace of its own, so this is a fixed point over its *visible effects*: unlocked recipes, board missions and shop items, spawned objects, missions started next. An effect only counts if a single mission can produce it, and missions without checks complete as soon as they start. Recipes are weak evidence, since the game can also unlock them from elsewhere: a completion resting only on a recipe is rejected if the mission's lasting reward objects are nowhere in the demo world. That rule stopped two workhall storage boxes from showing up, which the demo had never unlocked.
3. For every mission that ran, the actions added by the full game are applied: missions to start (with their own start actions, which the game does not run for a mission loaded from a save), recipes, and reward objects at their spawn point. Actions are compared by assetID, because some missions were only renamed.
4. **Zone triggers** work the same way. They are world objects that act when the player walks into them, then destroy themselves. In the full game, the trigger that marks the Genovatech lab as discovered also spawns the two lab door battery holders and starts the door repair mission; in the demo it only spawned the dome. [`tools/extract_triggers.py`](tools/extract_triggers.py) extracts every trigger of both maps with its actions and spawn points. For each trigger the demo already fired, the actions added by the full game are applied, and a demo object spawned at the same spot as a full-game one (the old dome) is replaced.
5. The full game spawns a `p_tutorialPlayed` marker at the end of its tutorial, and some missions wait for it (the turtle!). The demo finished the tutorial, so the marker is added.

### 6. Building the full-game save

The converter starts from a fresh full-game save shipped in [`data/base-full-game.sav`](data/base-full-game.sav), then applies all of the above. Player stats are copied within the full game's limits (the strength cap went from 4 to 6). The result is checked to read back, and the tests compare it byte for byte with a known-good conversion.

## Project layout

| Path | What it is |
|---|---|
| [`chopchop_convert.py`](chopchop_convert.py) | The program players run: finds the saves, backs up, converts, installs |
| [`chopchop/`](chopchop) | The converter: save format, tree editing, progress, world, missions |
| [`data/`](data) | Catalogs, initial maps and mission definitions extracted from the games, and the base save |
| [`tools/`](tools) | Analysis and extraction tools (need UnityPy) |
| [`examples/`](examples) | A real demo save, its conversion and a side-by-side comparison |
| [`tests/`](tests) | Tests |

## Run from source

Python 3.10 or newer, no dependency needed to convert:

```
python chopchop_convert.py
```

Or the converter alone, which never touches your game folder:

```
python -m chopchop.converter path\to\demo\save0.sav converted.sav
```

## Development

Inspect saves:

```
python -m tools.savetool check save0.sav                    # lossless round trip?
python -m tools.savetool decode save0.sav save0.json         # save -> editable JSON
python -m tools.savetool encode save0.json save0.sav         # JSON -> save
python -m tools.savetool summary save0.sav --depth 3         # tree overview
python -m tools.savetool services demo.sav full.sav          # services side by side
python -m tools.savetool schema --a demo.sav --b full.sav    # fields written per type
```

Tests: `python -m unittest discover tests`. They convert [`examples/demo-save.sav`](examples/demo-save.sav) and compare the result byte for byte with [`examples/converted-save.sav`](examples/converted-save.sav), the expected output. They also run on every push, before the release is built.

Summarize and compare saves: `python -m tools.compare_saves a.sav b.sav c.sav`.

Build the .exe locally: run `build.bat`. A local build will not have the same hash as the official one, because PyInstaller builds are not byte-for-byte reproducible. Only the release files are the reference.

Releases are automatic: every push to `main` runs the tests, builds the .exe on GitHub, signs its build attestation, and publishes a release named `v<version>-build.<number>` with the .exe, its `.sha256` file and the hash in the notes. The version comes from `chopchop/__init__.py`.

### Updating after a game patch

With both games installed:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-tools.txt
.venv\Scripts\python -m tools.extract_all
```

This regenerates every file in `data/`. If the full game changed a lot, a new fresh full-game save may also be needed in `data/base-full-game.sav`: start a new game, save right away, and copy `save0.sav`.

## Credits

Built by polo13410 with Claude. Thanks to the Odin Serializer and UnityPy projects, whose open source code made this possible.
