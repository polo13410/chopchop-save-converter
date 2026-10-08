# Example: a real conversion

These are real saves from the author's playthrough, so you can see what the converter does before running it on yours.

| File | What it is |
|---|---|
| [`demo-save.sav`](demo-save.sav) | A demo save after about 3 hours of play, at the end of the demo content |
| [`converted-save.sav`](converted-save.sav) | The same save after conversion, ready to be installed in the full game |
| [`../data/base-full-game.sav`](../data/base-full-game.sav) | The fresh full-game save the converter starts from |

## Side by side

| | Demo save | Fresh full game | Converted save |
|---|---|---|---|
| Money | 1747 | 0 | 1747 |
| Backpack (kinds of items / total) | 41 / 302 | 5 / 19 | 41 / 302 |
| Unlocked recipes | 146 | 328 | 385 |
| Unlocked shop items | 26 | 28 | 35 |
| Unlocked board missions | 25 | 0 | 25 |
| Running board missions | 3 | 0 | 3 |
| Active missions (incl. hidden) | 48 | 105 | 111 |
| Strength / stamina / move speed | 3.02 / 100 / 1.40 | 1.00 / 100 / 1.00 | 3.02 / 100 / 1.40 |
| World objects | 1160 | 1479 | 1552 |
| Trees standing | 325 | 358 | 357 |
| Player position | (265, 100, 252) | (265, 100, 251) | (265, 100, 252) |
| Tutorial finished marker | no | no | yes |

How to read it:

- **Money, backpack, board missions and skills** come straight from the demo.
- **Recipes and shop items** are the demo's plus the ones the full game gives from the start, plus 4 recipes the full game added to missions the demo completed.
- **Active missions** are the demo's, plus the full game's own background missions (achievements, recipe unlocks...), plus 18 missions the full game added on top of missions and zone triggers the demo already ran (city upgrades, new audiences, the lab door repair...).
- **World objects and trees**: the full game has a bigger map. The demo area takes its state from the demo save (cut trees stay cut), and the new areas come from the full game. The lab gets its full-game door battery holders.
- **Tutorial finished marker**: added because the demo finished the tutorial; some full-game missions wait for it.

## Try it yourself

From the repository root, with Python 3.10+:

```
python -m chopchop.converter examples/demo-save.sav my-converted.sav
python -m tools.compare_saves examples/demo-save.sav data/base-full-game.sav my-converted.sav --names "Demo save" "Fresh full game" "Converted save"
```

The first command prints everything it transfers. Your `my-converted.sav` is byte for byte identical to `converted-save.sav`, and the tests check exactly that on every build.

To dig deeper, turn any save into readable JSON:

```
python -m tools.savetool decode examples/demo-save.sav demo.json
```

If you change how the converter works on purpose, regenerate the reference with the first command (writing to `examples/converted-save.sav`), check the result in game, and commit both.
