# Changelog

All notable changes to Fspy_importer_CC. Format inspired by [Keep a Changelog](https://keepachangelog.com/); versions follow the plugin's own numbering (1.0, 1.1, ... 2.14).

## [2.14] - 2026-10-22
First public release on GitHub.
- Reads the `.fspy` project directly (calibration, reference distance and embedded photo).
- Front viewport camera set to the fSpy match at real-world scale; photo on a textured plane through the origin, with the fSpy principal point applied so Rhino 0,0,0 lands on the fSpy origin.
- 3-viewport layout on Run (Perspective, Top, Front), zoom extents in Perspective and Top, Ghosted display with grid and axes and a World Top construction plane in Front.
- Sync button: turns green when the `.fspy` is saved again and re-applies it; asks whether to follow a moved fSpy origin or keep the current Rhino origin.
- Warnings for a missing reference distance and for Camera data other than 35 mm film; fSpy and Rhino focal lengths shown side by side.
- Flip X / Y / Z, one named view per project, viewport and photo layer lock, one photo only on its layer, single-step undo, per-session log files.

## [1.0] to [2.13] - 2026-07-10 to 2026-10-22
Private development versions, not published individually.
