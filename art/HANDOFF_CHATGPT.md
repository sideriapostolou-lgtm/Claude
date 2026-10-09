# Night Shift: Skyport — art handoff for ChatGPT

**For:** ChatGPT (the artist). **From:** Claude Code (the builder). **Owner:** Sideri.
**Repository:** https://github.com/sideriapostolou-lgtm/claude, branch `claude/nightcrawler-memecoin-bot-Gwnb1S`.

You made the Night Shift: Skyport reference pack (ten images and `CLAUDE_START_HERE.txt`). This
document asks you for the **production art** that goes into the live 3D world: the six characters
as cut-out sprite sheets, a few props, and (second priority) the sky and material textures.

Claude builds the 3D world in code (three.js) and places your characters in it. The characters
walk, work, talk and react **only when the bot does something real** (see "How the art connects to
the business" below). So you draw poses and surfaces, never scenes, screens with data, or text.

---

## 1. What to deliver, in priority order

Send the **character sheets first**, as soon as they are done. Everything else can follow later.

| # | File | Size (px) | What |
|---|---|---|---|
| 1 | `characters/<id>_turnaround.png` × 6 | 1536 × 1024 | Each character from 5 angles plus one blink frame |
| 2 | `characters/<id>_actions.png` × 6 | 1536 × 1024 | Each character in 6 action poses |
| 3 | `props/props.png` | 1536 × 1024 | 6 small props the cast carries or uses |
| 4 | `world/sky_panorama.png` | 1536 × 1024 or wider | The blue-hour sky around the island (optional) |
| 5 | `world/tex_*.png` × 6 | 1024 × 1024 | Seamless material textures (optional) |
| 6 | `world/foliage.png` | 1536 × 1024 | Plant and lantern cut-outs (optional) |

`<id>` is one of: `voss`, `pip`, `nyx`, `rook`, `mote`, `jet` (lower case, exactly these).
That is **12 character images** for priority 1 and 2.

---

## 2. Rules for every image (please read twice)

1. **Real transparent background.** PNG with a true alpha channel around the figures.
   If you cannot produce real transparency, use a **perfectly flat, single-colour background**:
   pure green `#00FF00` for every character **except Mote**, who gets pure magenta `#FF00FF`
   (Mote is mint green). No gradient, no vignette, no floor, no cast shadow on the background,
   and **never a drawn grey-and-white checkerboard** (that is not transparency).
2. **Same style as the reference pack.** Premium stylized 3D animated-film look, identical
   character designs to `08_crew_lineup.png` (details in section 3). Same materials: aged brass,
   leather, fabric, glossy eyes.
3. **Layout of a sheet:** 6 figures in reading order, **3 per row, 2 rows**. Each figure fully
   visible (nothing cut off at the image edge), with **clear empty space around it** (figures never
   touch or overlap). Claude cuts the sheet apart automatically, so spacing matters more than a
   perfect grid.
4. **Same scale everywhere.** Within one character's two sheets, the character is the same size in
   every pose, standing on the same invisible floor line near the bottom of its cell. Fill about
   80 % of the cell height with the tallest pose.
5. **Camera:** slightly above eye level, about 15 degrees looking down, like a drone hovering just
   above the crew (this matches the live world's camera). Gentle perspective, no fisheye.
6. **Light:** the pack's look. Warm amber key light from the upper left, soft lilac rim light from
   the right. No coloured light spill from a background (there is none).
7. **No words or numbers anywhere.** No text, letters, digits, prices, charts, logos, UI,
   signatures or watermarks. Tablets, screens and holograms show **only abstract glow**. The app
   writes the real numbers itself; nothing in the art may look like a trade, a price or a profit.
8. **PNG only, sRGB.** File names exactly as in section 1 and section 7.

---

## 3. The cast (match `08_crew_lineup.png` exactly)

| id | Character | Must-have details | Height in the world |
|---|---|---|---|
| `voss` | Cobalt owl, the director | Cobalt-blue feathers with a lighter blue face disc, big golden eyes, small orange beak, ear tufts; teal waistcoat with brass buttons; violet cape with a round brass clasp; brown belt with pouches; cyan glowing tablet | 0.9 m |
| `pip` | Orange fox, the builder | White muzzle, chest and tail tip; big dark eyes; brass goggles with blue lenses on the forehead; ivory shirt with rolled sleeves; brown leather harness with brass buckles and tool pouches; dark brown gloves | 0.95 m (with ears) |
| `nyx` | Lavender octopus, the analyst | Lavender skin with faint sparkle speckles, large dark glossy eyes with highlights, brass monocle on one eye, curled tentacles with pink suckers, holds a brass fountain pen | 0.6 m |
| `rook` | Slate golem, risk keeper | Chunky body of rounded slate-brown rocks, glowing amber eyes and a few amber cracks, brass collar with star medallions, brown leather straps and pouches | 2.0 m |
| `mote` | Mint archivist in a glass bell | Small translucent mint creature with a cute face, always inside a clear glass bell with a brass top knob, on a brass base with four spoked wheels | 0.75 m (bell and cart) |
| `jet` | Yellow courier robot | Yellow capsule body and round head, black visor with two cyan glowing eyes, brass ear discs, dark grey jointed arms and legs, yellow boots, brown leather messenger satchel | 0.75 m |

Keep each design identical in every pose: same colours, same costume pieces, same proportions.

---

## 4. Sheet A — `<id>_turnaround.png` (one per character)

Reading order, 3 per row:

1. **Front**, standing relaxed, looking at the viewer.
2. **Three-quarter front, facing the viewer's left.**
3. **Side profile, facing left.**
4. **Three-quarter back, facing left** (we see the back and a bit of the side).
5. **Back**, facing away.
6. **Front, eyes closed** (identical to pose 1 except the eyes; used for blinking).

Claude mirrors poses 2–4 to get the right-facing versions, so draw them facing **left** only.

---

## 5. Sheet B — `<id>_actions.png` (one per character)

All six poses in **three-quarter front view, facing the viewer's left** (like turnaround pose 2):

1. **Walk A** — mid-stride, right foot (or right side) forward.
2. **Walk B** — mid-stride, left foot (or left side) forward. Walk A and B alternate to make the walk.
3. **Working** — the character's job pose (table below).
4. **Talking** — explaining something, mouth open, one hand or wing gesturing.
5. **Happy** — a small celebration (used only after a real win).
6. **Worried** — concerned, a hand to the face or shoulders down (used only after a real loss or a blocked trade).

| id | Walk A and B (their own way of moving) | Working (pose 3) |
|---|---|---|
| `voss` | Small owl steps; in B the wings open slightly as in a short glide; cape sways | Reviewing the cyan tablet (abstract glow only), one wing tip pointing at it |
| `pip` | Springy fox walk, tail up for balance | Goggles pulled down over the eyes, holding a small glowing cube up to inspect it, a wrench in the other paw |
| `nyx` | Tentacle crawl: front tentacles reaching forward in A, pulling in B | Three tentacles raised at three heights as if typing on floating keys (no screens drawn), pen in a fourth |
| `rook` | Heavy steps, body leaning into each step | Pressing a big brass approval stamp down at desk height |
| `mote` | The cart rolls: wheels in two rotation positions, Mote leaning forward inside the bell | Writing in a tiny glowing blank ledger inside the bell |
| `jet` | Quick little steps, satchel bouncing | Holding a glowing data cube in both hands (cube in neutral white-violet; the app tints it gold or red) |

---

## 6. Props — `props/props.png`

Six objects, reading order, same rules (transparent or flat `#00FF00`, separated, no text or symbols):

1. Glowing data cube, white core with a soft violet edge (the app tints it gold for a win, red for a loss).
2. Plain gold coin, no symbol or engraving.
3. Brass approval stamp with a walnut handle (stamp face blank).
4. Small open ledger book with blank pages.
5. Coffee mug with a wisp of steam.
6. Parcel box with brass corners and a leather strap.

---

## 7. World textures (optional, after the characters)

| File | Size | What |
|---|---|---|
| `world/sky_panorama.png` | 1536 × 1024 or wider | Blue-hour sky: cobalt to lilac at the top, peach glow at the horizon, a sea of soft peach and lilac clouds in the lower third, a few small distant floating islands with tiny warm lights. **No main island, no characters, no buildings up close.** The left and right edges must join seamlessly when wrapped. |
| `world/tex_stone_pavers.png` | 1024 × 1024 | Worn cream stone pavers, top-down, **seamless tile** |
| `world/tex_stone_wall.png` | 1024 × 1024 | Carved cream stone blocks, front-on, seamless tile |
| `world/tex_brass.png` | 1024 × 1024 | Aged brass with soft patina, seamless tile |
| `world/tex_walnut.png` | 1024 × 1024 | Walnut wood planks, seamless tile |
| `world/tex_cliff_rock.png` | 1024 × 1024 | Underside of the floating island: warm grey-brown rock with moss, seamless tile |
| `world/tex_roof_tiles.png` | 1024 × 1024 | Roof tiles in the reference pack's colours, seamless tile |
| `world/foliage.png` | 1536 × 1024 | Six cut-outs, transparent or flat `#00FF00`: hanging vine with purple flowers, potted fern, small cypress tree, purple flower cluster, brass lantern glowing warm, short brass railing segment |

"Seamless tile" means the image repeats edge to edge with no visible seam, flat even lighting,
no perspective, no shadows from a single direction.

---

## 8. How to send it

Put everything in one zip named **`skyport_art.zip`**:

```
skyport_art/
  characters/  voss_turnaround.png  voss_actions.png  pip_turnaround.png  pip_actions.png
               nyx_turnaround.png   nyx_actions.png   rook_turnaround.png rook_actions.png
               mote_turnaround.png  mote_actions.png  jet_turnaround.png  jet_actions.png
  props/       props.png
  world/       sky_panorama.png  tex_stone_pavers.png  tex_stone_wall.png  tex_brass.png
               tex_walnut.png  tex_cliff_rock.png  tex_roof_tiles.png  foliage.png
```

Sideri sends the zip to Claude in the Claude chat. A partial zip (only the 12 character images)
is welcome; send the rest later.

If you have write access to the GitHub repository, you may instead commit the files under
`art/incoming/` on a **new branch named `art/skyport-assets`**. Do not commit to
`claude/nightcrawler-memecoin-bot-Gwnb1S`, and do not change any other file.

---

## 9. How the art connects to the business

Nothing moves for show. Each pose plays when the bot's ledger records the matching event, and every
word and number on screen is written by the app from that ledger.

| When this really happens | Who | What you will see |
|---|---|---|
| The crawler finds brand-new coins | Pip | Working at the workshop, then walks (A/B) to Nyx's den to hand over |
| The scam filter, danger check or setup check runs | Nyx | Working, then talking; hands the coin on to Voss |
| The AI judge decides; the Polymarket desk buys or settles | Voss | Working or talking at the mission table; the holographic board shows the desk's real positions, real money and pretend money labelled apart |
| An order is placed or closed | Jet | Carries the data cube from the dock to the vault; gold glow for a win, red for a loss |
| Risk approves or blocks | Rook | Stamping (working) for an approval, worried for a block |
| A receipt is recorded; the coach learns something | Mote | Writing in the ledger (working) |
| A trade settles as a win | whoever handled it | Happy |
| A trade settles as a loss | whoever handled it | Worried |

Idle moments (looking around, blinking, a coffee) are decoration and never show words or numbers.

---

## 10. What happens after you send it

Claude runs an automatic check on every file: size, real transparency or a clean key colour, the
number of figures per sheet (6), figures not touching, and a consistent scale across a character's
two sheets. Anything off comes back to Sideri as a short, exact redo note for you (for example:
"pip_actions.png: figures 3 and 4 touch; please separate"). Then the characters go into the 3D
world, and Sideri gets screenshots before it goes live.

---

## 11. Checklist before sending

- [ ] 12 character images named exactly `<id>_turnaround.png` and `<id>_actions.png`
- [ ] 1536 × 1024 PNG, real transparency, or flat `#00FF00` (Mote: `#FF00FF`), no checkerboard
- [ ] 6 figures per sheet, 3 per row, none touching, none cut off
- [ ] Same scale and floor line in every pose of a character
- [ ] Turnaround and action poses face the viewer's **left**
- [ ] Designs identical to `08_crew_lineup.png`
- [ ] No text, numbers, logos, charts or watermarks anywhere; screens show only glow
- [ ] Zip named `skyport_art.zip` with `characters/`, `props/`, `world/` folders
