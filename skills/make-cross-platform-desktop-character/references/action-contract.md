# Action Contract

## Identity and Canvas

- Use one approved standard character as the identity source for every sheet.
- Keep face shape, eye shape, hair, skin tone, main outfit details, and body proportions consistent.
- Generate RGBA artwork with a genuinely transparent background.
- Normalize runtime frames to 560x500 with nearest-neighbor scaling and safe padding.
- Keep standing poses near the same visual height and align feet to a shared baseline.

## Required 3x2 Sheets

Place cells left-to-right, top-to-bottom.

| File | Six cells |
|---|---|
| `expressions-sheet-alpha.png` | pout, laugh, eyes-closed enjoyment, friendly gesture, surprised, sad |
| `life-states-sheet-alpha.png` | bored, hungry, angry, thinking, sleepy, sleeping pose |
| `prop-actions-sheet-alpha.png` | cake, phone, seated pose, waking, dragged pose, selfie pose |
| `extra-interactions-sheet-alpha.png` | wink, computer work, corgi touch, corgi play, wave, neutral idle |
| `front-facing-specials-sheet-alpha.png` | starry eyes, burger, camera, emperor pose, stretch, bashful front pose |

Create optional outfit sheets with six genuinely different clothing designs per sheet. Vary silhouette, fabric, styling, props, and pose; do not submit recolors as separate outfits.

## Walk

- Produce 12 RGBA frames at 560x500.
- Use a repeating six-frame left/right step rhythm.
- Include contact, compression, passing, lift, opposite contact, and recovery.
- Alternate legs clearly and add restrained arm swing plus small hair lag.
- Preview at 150 ms per frame before approval.

## Rejection Conditions

Reject any frame with identity drift, extra or missing limbs, merged hands, cropped hair, opaque corners, halo residue, wrong canvas size, sudden scale change, or a walking cycle that only shakes in place.
