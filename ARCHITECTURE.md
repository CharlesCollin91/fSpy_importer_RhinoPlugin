# Architecture

This page explains how `Fspy_importer_CC.py` is built, so that someone else can take it over and improve it. Function names are given instead of line numbers, because line numbers change with every edit.

## Design decisions

- **One single file.** Everything (logging, theme, fSpy maths, window) lives in `Fspy_importer_CC.py`. No local imports, no external packages: install = copy one file.
- **`#! python 3` on line 1.** Without it Rhino's `_RunPythonScript` starts IronPython 2.7 instead of the Python 3 of Rhino 8.
- **Python 3.9 syntax only** (no `match`, no `X | Y` type hints), the safe level for Rhino 8.
- **The `.fspy` file is read directly**, like the official fSpy Blender importer: a 16-byte header, a JSON state, then the photo bytes. fSpy's world is right-handed and Z-up like Rhino, so the camera matrix is used as is.
- **Logic and window are kept apart.** The `CORE` code never touches the window, so the maths can be read, changed and logged on its own.
- **Refuse rather than succeed in the wrong place.** If the target viewport is missing, or the current origin cannot be kept, nothing is changed and the reason is reported.
- **Questions first, changes after.** Every Yes/No question of a Run or Sync is asked before the document or the viewports change, so "No" or "Cancel" changes nothing.

## File layout

| Section | What it holds |
|---|---|
| `HEADER / IMPORTS` | Imports (`Rhino`, `Rhino.Geometry as rg`, `scriptcontext`, `Eto` for the window). |
| `CONFIG` | Constants: named-view prefix, photo layer name, target viewport (`TARGET_VIEW`), user-string keys, unit tables, tolerances. Resolves the plugin folder and the `logs` folder. |
| `LOGGING` | One log file per window session in `logs/`, capped at 500 MB in total. `log(tag, msg)` and `log_exc(where)` never raise. |
| `THEME` | Colour and font tokens (`TOKENS`, `color()`, `font()`) used by the window. |
| `CORE` | `FspySettings`, the `.fspy` reader, the camera and photo-plane maths, the document and viewport operations, and the Run / Sync phases (below). |
| `UI` | Hand-drawn dark widgets (`FlatButton`, `Toggle`, ...), `BaseWindow` (log session, wrapped handlers, single undo record per Run) and `PluginUI` (the window, the file watch, Run and Sync). |
| `ENTRY POINT` | `main()`: checks Rhino 8+ / Python 3, keeps a single window instance (stored in `scriptcontext.sticky`), and shows it. |

## Data objects

- `FspySettings` (dataclass): what the user sets in the window (named view, viewport lock, photo layer lock, embed image, transparency, Flip X / Y / Z). `flips()` returns the axis signs.
- The context `dict` returned by `prepare_import`: everything a Run or Sync needs (camera position and basis, lens, image bytes, previous photo plane, origin choice, flips), filled further by the later phases.
- `FspyError`: raised with a user-facing message when a `.fspy` file cannot be read.

## The pipeline (what happens on Run or Sync)

```
PluginUI._import(mode)              mode = "run" or "sync"
   |
   v
prepare_import()            no change to the document; all questions asked here
   |   parse_fspy()            header, JSON state, photo bytes
   |   sensor_info()           Camera data (preset or custom sensor)
   |   scale_factor()          fSpy reference unit -> document units
   |   camera_basis()          position, right, up, forward from the camera matrix
   |   lens_from_fov()         Rhino 35 mm lens length
   |   objects_on_plane_layer()  previous photo plane(s) and the values recorded on them
   |   pixel_ray() + floor_point()  "keep the current origin": old origin pixel -> floor point -> shift
   |   apply_flips()           Flip X / Y / Z about 0,0,0
   v
set_three_view_layout()     Run only: 3View, then Perspective / Top / Front by screen position
   v
apply_camera_and_image()    unlock (get_lock / set_lock), apply_camera(), set_world_top_cplane(),
   |                        set_front_display(), remember_view(), save_image_next_to()
   v
build_scene()               inside one undo record: delete the old photo (delete_object),
   |                        save_named_view(), build_image_plane(), set_layer_lock()
   v
finish_lock()  ->  zoom_extents_except() (Run only)  ->  report_import()
```

Key ideas inside the steps:

- **Photo plane** (`build_image_plane`): a picture frame perpendicular to the camera, sized to fill the frustum at the depth of the world origin, and shifted by the fSpy principal point so the origin pixel lands exactly on 0,0,0.
- **Pixel to ray** (`pixel_ray`): image coordinates are normalised by half the longer image side, the camera looks down its local -Z, and the principal point is subtracted. The ray through fSpy's stored origin pixel passes through 0,0,0.
- **Keeping the origin** (`prepare_import`, `floor_point`): when the origin was moved in fSpy and the user keeps the current one, the old origin pixel is cast into the new calibration and cut by the floor plane z = 0; the camera is shifted so that point stays at 0,0,0.
- **State between runs**: values are stored as user strings on the photo plane (`NAMED_VIEW_KEY`, `ORIGIN_PX_KEY`, `ANCHOR_PX_KEY`, `REF_KEY`) and in the document strings (`doc_named_view`, `remember_view`), and read back by the next Run or Sync.
- **Sync turns green** (`PluginUI._on_watch`, `file_stamp`): a one-second UI timer compares the `.fspy` date and size with the last read.
- **Mirrors** (`apply_flips`): an odd number of flips is a reflection; Rhino's camera is right-handed, so the photo then shows reversed (reported).

## Logs

Every window session writes `logs/Fspy_importer_CC_<date>_<time>.log`. Lines look like `TAG | message` with tags such as `ITEM` (what is happening), `API` (result of a RhinoCommon call, as returned), `SKIP`, `ERROR`. When reporting a bug, attach the matching log.

## Where to start if you want to...

| Goal | Look at |
|---|---|
| Support another `.fspy` field or version | `parse_fspy`, `sensor_info` |
| Change how the photo is placed | `build_image_plane` |
| Change the viewport layout | `set_three_view_layout` |
| Change what the Front viewport shows | `set_front_display`, `set_world_top_cplane` |
| Change how the previous photo is found or replaced | `objects_on_plane_layer`, `delete_object`, `build_scene` |
| Add an option | `FspySettings`, `PluginUI.read_settings`, the toggles in `PluginUI._build` |
| Change the look of the window | `TOKENS` in the THEME section, then the widget classes in UI |
