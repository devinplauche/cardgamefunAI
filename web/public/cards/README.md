# Card artwork

These 59 unmodified JPEG card scans come from the official
[Hero Realms card gallery](https://www.herorealms.com/card-gallery/), retrieved
2026-09-14. Artwork and Hero Realms belong to Wise Wizard Games and their
respective artists; these assets are not represented as original or openly
licensed project artwork. `sources.json` records each original image URL.

The interface displays a CSS viewport over the illustration area of each scan,
leaving game names, rules, and action controls as accessible HTML. The original
files retain their printed credits. Assets are served locally, without runtime
requests to the publisher. The footer links to the source gallery.

The catalog covers all 55 data-file cards and the four starter cards. Card
names map to filenames in `src/cardArt.ts`, including the synthetic Fire Gem.
Unknown cards or failed image loads retain a decorative symbol and fully
usable rules and controls. Opponent hands never render face artwork.
