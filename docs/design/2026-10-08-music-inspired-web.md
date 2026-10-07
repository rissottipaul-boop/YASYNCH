# Music-inspired web appearance

Telegram Turntable keeps its own name, icon set, album artwork, and Telegram
workflows. The web UI takes general cues from modern desktop music players:
light and dark neutral surfaces, a compact source rail, spacious song rows,
prominent playback controls, and a restrained red accent.

The skin is implemented in the final section of `static/style.css`. It changes
presentation only; playback, queue, search, source management, sharing,
metadata, and settings continue to use their existing DOM IDs and handlers.
It uses original CSS and the project's existing assets. No Apple Design
Resources, Apple Music art, or Apple branding is included. Apple's published
[Design Resources License](https://developer.apple.com/apple-design-resources-license/)
does not allow embedding that kit in this web player.

## Visual rules

- The accent highlights primary playback, active selection, progress, and
  current track state. It does not replace destructive status colors.
- Use system UI fonts so the player feels native on each platform. Keep every
  control keyboard accessible with a visible focus ring.
- Use square album art throughout, including the Now Playing panel. It stays
  still while audio plays.
- Keep the existing responsive layout and all controls visible at their
  supported breakpoints. The mobile dock remains reachable above the safe area.
- Material blur stays on the header, Now Playing pane, player, and overlays.
  Ordinary song and source rows remain clear, opaque surfaces.

## Verification targets

- Light and dark library views at desktop and phone widths.
- Playlist playback, next, pause, seek, repeat, shuffle, volume, and likes.
- Source selection, search, sorting, queue tabs, and settings.
- No clipped player controls or blocked Now Playing transport on mobile.
