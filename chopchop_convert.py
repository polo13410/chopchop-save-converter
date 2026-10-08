"""Chop Chop Inc. save converter: one-click tool for players.

Finds the demo save, backs up the full-game saves, converts the demo save and
installs it as the full-game save. This is the entry point of the .exe release.

    ChopChopSaveConverter.exe                 interactive, does everything
    ChopChopSaveConverter.exe --demo FILE     convert this demo save instead
    ChopChopSaveConverter.exe --no-install    only write the converted save next to the program
    ChopChopSaveConverter.exe --progress-only keep the full-game world, transfer progress only
    ChopChopSaveConverter.exe --yes           do not ask for confirmation
"""

import argparse
import datetime
import glob
import os
import shutil
import subprocess
import sys
import traceback

from chopchop import __version__, data_dir, odin_binary
from chopchop.converter import ConversionError, convert

GAME_PROCESSES = ("ChopChopInc.exe", "ChopChopIncDemo.exe")
TARGET_NAME = "save0.sav"


def saves_root():
    profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(profile, "AppData", "LocalLow", "NullRef Entertainment")


def running_games():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.lower()
    except OSError:
        return []
    return [p for p in GAME_PROCESSES if f'"{p.lower()}"' in out]


def ask(question, default=True, assume_yes=False):
    if assume_yes:
        return True
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(question + suffix).strip().lower()
    except EOFError:
        return default
    return default if not answer else answer.startswith("y")


def choose_demo_save(demo_dir, assume_yes):
    saves = sorted(glob.glob(os.path.join(demo_dir, "*.sav")), key=os.path.getmtime, reverse=True)
    if not saves:
        return None
    if len(saves) == 1 or assume_yes:
        return saves[0]
    print("Several demo saves were found:")
    for i, path in enumerate(saves, 1):
        when = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        print(f"  {i}. {os.path.basename(path)}  (last saved {when})")
    while True:
        try:
            answer = input("Which one should be converted? [1] ").strip() or "1"
        except EOFError:
            return saves[0]
        if answer.isdigit() and 1 <= int(answer) <= len(saves):
            return saves[int(answer) - 1]
        print("Please type one of the numbers above.")


def self_test():
    """Quick check used by the release build: the bundled data reads back losslessly."""
    with open(os.path.join(data_dir(), "base-full-game.sav"), "rb") as f:
        data = f.read()
    assert odin_binary.encode(odin_binary.decode(data)) == data
    for name in ("catalog-demo.csv", "catalog-full.csv", "scene-demo.csv", "scene-full.csv",
                 "missions-demo.json", "missions-full.json"):
        assert os.path.getsize(os.path.join(data_dir(), name)) > 0, name
    print("Self-test OK")


def run(args):
    print(f"Chop Chop Inc. save converter {__version__}")
    print("Carries your demo progress over to the full game.\n")

    root = saves_root()
    demo_dir = os.path.join(root, "ChopChopIncDemo", "saves")
    full_dir = os.path.join(root, "ChopChopInc", "saves")

    demo_path = args.demo or choose_demo_save(demo_dir, args.yes)
    if not demo_path or not os.path.isfile(demo_path):
        print("No demo save was found in:")
        print(f"  {demo_dir}")
        print("Play the demo and save at least once, or pass the file with --demo.")
        return 1

    running = running_games()
    if running and not args.no_install:
        print(f"Please close the game first ({', '.join(running)} is running), then run this again.")
        return 1

    if args.no_install:
        output = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "converted-" + TARGET_NAME)
        print(f"Demo save:      {demo_path}")
        print(f"Converted save: {output}\n")
    else:
        output = os.path.join(full_dir, TARGET_NAME)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = os.path.join(root, "ChopChopInc", f"saves-backup-{stamp}")
        existing = sorted(glob.glob(os.path.join(full_dir, "*.sav")))
        print(f"Demo save to convert: {demo_path}")
        print(f"It will become:       {output}")
        if existing:
            print("Your current full-game saves will be moved to a backup folder:")
            print(f"  {backup_dir}")
            for path in existing:
                print(f"  - {os.path.basename(path)}")
        print()
        print("Tip: if Steam Cloud is on for Chop Chop Inc., Steam may put your old save back.")
        print("     Turn it off in Steam: right-click the game > Properties > General.\n")
        if not ask("Go ahead?", assume_yes=args.yes):
            print("Nothing was changed.")
            return 1

    with open(demo_path, "rb") as f:
        demo_bytes = f.read()
    lines = []

    def log(msg):
        lines.append(msg)
        if args.verbose:
            print("  " + msg)

    print("Converting...")
    result = convert(demo_bytes, with_world=not args.progress_only, log=log)

    if args.no_install:
        with open(output, "wb") as f:
            f.write(result)
        print(f"\nDone. Converted save written to:\n  {output}")
        print(f"Copy it to {full_dir} as {TARGET_NAME} (back up your saves first).")
        return 0

    # Backup first: the whole saves folder, plus a copy of the demo save for reference.
    os.makedirs(backup_dir, exist_ok=True)
    if os.path.isdir(full_dir):
        shutil.copytree(full_dir, os.path.join(backup_dir, "saves"), dirs_exist_ok=True)
    shutil.copy2(demo_path, os.path.join(backup_dir, "demo-" + os.path.basename(demo_path)))
    os.makedirs(full_dir, exist_ok=True)
    # Remove the other saves (they are in the backup) so the game loads the converted one.
    for path in existing:
        os.remove(path)
    with open(output, "wb") as f:
        f.write(result)
    with open(os.path.join(backup_dir, "conversion-log.txt"), "w", encoding="utf-8") as f:
        f.write(f"Chop Chop Inc. save converter {__version__}\n")
        f.write(f"Demo save: {demo_path}\nConverted save: {output}\n\n")
        f.write("\n".join(lines) + "\n")

    print("\nDone! Your demo progress is now your full-game save.")
    print(f"Backup of your previous saves and conversion log:\n  {backup_dir}")
    print("\nLaunch Chop Chop Inc. and load your save.")
    print("To undo: copy the files from the backup's 'saves' folder back into")
    print(f"  {full_dir}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--demo", help="demo save to convert (default: found automatically)")
    p.add_argument("--no-install", action="store_true", help="only write the converted save next to the program")
    p.add_argument("--progress-only", action="store_true", help="keep the full-game world, transfer progress only")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--verbose", action="store_true", help="show the conversion details")
    p.add_argument("--no-pause", action="store_true", help="do not wait for Enter before closing")
    p.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.self_test:
        self_test()
        return 0

    try:
        code = run(args)
    except ConversionError as e:
        print(f"\nThe conversion failed: {e}")
        code = 1
    except Exception:
        print("\nSomething went wrong. Nothing was installed. Details for a bug report:\n")
        traceback.print_exc()
        code = 1
    if not args.no_pause and not args.yes:
        try:
            input("\nPress Enter to close.")
        except EOFError:
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
