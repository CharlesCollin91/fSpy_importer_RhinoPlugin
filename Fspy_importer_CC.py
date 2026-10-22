#! python 3
# Fspy_importer_CC - match a Rhino viewport to an fSpy project (.fspy): camera, real-world scale,
# backdrop photo plane through the origin, named view, optional viewport lock.
# Requires: Rhino 8+ (Windows), Python 3 (built into Rhino 8). No extra packages.
# Run: ! _-RunPythonScript "C:\path\to\Fspy_importer_CC\Fspy_importer_CC.py"
# Copyright (C) 2026 Charles Collin. Licensed under GPL-3.0-or-later (see LICENSE).
#
# v2.4: rebuilt on the rhino-plugin-creation standard (window, log, theme) from CC_Import_Fspy_v2.3.
# v2.5: Sync button (re-applies the .fspy, updates the project's named view), 35 mm film sensor check,
#       fSpy/Rhino focal pair in Report, viewport lock read/set through RhinoViewport.LockedProjection.
# v2.6: Sync turns green when the .fspy is saved again on disk; Front is the default target viewport.
# v2.7: warns when no reference distance is set (Select: OK, Run/Sync: Yes/No); on Sync, asks what to do
#       when the origin was moved in fSpy (follow it, or keep the current Rhino origin by the floor plane);
#       Report shows a reference-distance change; one named view per project (Run replaces it too).
# v2.8: the fSpy_ImagePlane layer holds one photo only: everything on it is replaced, whatever its state
#       (the lookup by name missed planes and left duplicates). Principal point always applied (option and
#       Flip Y removed: they only shifted the photo off the fSpy origin). Named view also kept in the
#       document's strings, so it is found even without the previous plane.
# v2.9: always the Front viewport (no viewport choice); named views MatchPerspectiveFspy1, 2, ...
# v2.10: Flip X / Flip Y / Flip Z: reverse fSpy axes (about Rhino 0,0,0). An odd number of flips is a
#       mirror: the photo shows reversed (warned in Report).
# v2.11: the Front viewport's construction plane is set to World Top (XY) at each Run / Sync.
# v2.12: "Lock photo layer" option (fSpy_ImagePlane locked when done); labels "Create named view", "Lock viewport".
# v2.13: Run first sets the 3-viewport layout (Perspective large left, Top upper right, Front lower right),
#        logic from 3viewport_cc v1.0 (validated in Rhino 8.37), then works in that Front viewport.
# v2.14: Front shows Ghosted + grid + axes (Run and Sync); Run zooms extents in Perspective and Top
#        (never in Front: it would move the matched camera).
# The fSpy maths (camera, scale, principal point, image plane) are unchanged.
__version__ = "2.14"

# =============================================================================
# HEADER / IMPORTS
# =============================================================================
import os
import sys
import json
import math
import time
import struct
import uuid
import tempfile
import logging
import datetime
import textwrap
import traceback
import contextlib
from dataclasses import dataclass

import clr
import System
import System.Drawing
import Rhino
import Rhino.Geometry as rg
import Rhino.DocObjects as rdo
import Rhino.UI
from Rhino.Display import DefinedViewportProjection as Proj
import scriptcontext as sc
import rhinoscriptsyntax as rs      # only for rs.AddPictureFrame (kept as in v2.3, see CORE)
import Eto.Forms as forms
import Eto.Drawing as drawing

# =============================================================================
# CONFIG
# =============================================================================
PLUGIN_NAME = "Fspy_importer_CC"
STICKY_KEY = PLUGIN_NAME + ".ui"
DEFAULT_PLUGIN_DIR = os.path.join(os.path.expanduser("~"), "Fspy_importer_CC")
LOG_LIMIT_BYTES = 500 * 1024 * 1024
TOOLTIP_WIDTH = 60

NAMED_VIEW_PREFIX = "MatchPerspectiveFspy"   # named views: MatchPerspectiveFspy1, 2, ... (one per project)
IMAGE_SUFFIX = "_fspytex"            # extracted photo is written next to the .fspy as <name><suffix>.<ext>
IMAGE_PLANE_LAYER = "fSpy_ImagePlane"
IMAGE_PLANE_DISTANCE = None          # None = auto (through the world origin). A number overrides.

NAMED_VIEW_KEY = "fspy_named_view"   # user strings on the image plane, read back by the next Run / Sync:
ORIGIN_PX_KEY = "fspy_origin_px"     #   fSpy origin in the image (relative x,y) at the last import
ANCHOR_PX_KEY = "fspy_anchor_px"     #   image point that sits at Rhino 0,0,0 (differs when "keep" was chosen)
REF_KEY = "fspy_ref"                 #   reference distance at the last import: axis|value|unit
ORIGIN_TOL = 1e-5                    # relative image units: below this the origin did not move
TARGET_VIEW = "Front"                # the only viewport the plugin works in
VIEWPORT_ID_KEY = "__front_viewport_id"   # document string: id of that viewport, kept if its title changes
WATCH_INTERVAL_S = 1.0               # how often the .fspy date is checked for the green Sync button
FILM_35MM = (36.0, 24.0)             # "35 mm film" sensor, in mm
SENSOR_TOL_MM = 0.05
FOCAL_MISMATCH = 0.005               # 0.5 %: above this the focal pair line turns orange

FSPY_MAGIC = 2037412710
FSPY_UNIT_METERS = {
    "Millimeters": 1e-3, "Centimeters": 1e-2, "Meters": 1.0, "Kilometers": 1e3,
    "Inches": 0.0254, "Feet": 0.3048, "Miles": 1609.344,
}
RHINO_UNIT_METERS = {
    0: 1.0, 1: 1e-6, 2: 1e-3, 3: 1e-2, 4: 1.0, 5: 1e3,
    6: 2.54e-8, 7: 2.54e-5, 8: 0.0254, 9: 0.3048, 10: 1609.344,
}


def _plugin_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__)), "__file__"
    except Exception:
        return DEFAULT_PLUGIN_DIR, "default path (__file__ undefined)"


PLUGIN_DIR, PLUGIN_DIR_SOURCE = _plugin_dir()
LOG_DIR = os.path.join(PLUGIN_DIR, "logs")

# =============================================================================
# LOGGING
# =============================================================================
_logger = logging.getLogger(PLUGIN_NAME)
_logger.setLevel(logging.DEBUG)
_logger.propagate = False
_log_path = None


def _trim_log_dir(current_path):
    try:
        files = []
        for name in os.listdir(LOG_DIR):
            p = os.path.join(LOG_DIR, name)
            if os.path.isfile(p) and name.lower().endswith(".log"):
                files.append((os.path.getmtime(p), p, os.path.getsize(p)))
        total = sum(f[2] for f in files)
        files.sort()
        for _, p, size in files:
            if total <= LOG_LIMIT_BYTES:
                break
            if current_path and os.path.normcase(p) == os.path.normcase(current_path):
                continue
            try:
                os.remove(p)
                total -= size
            except Exception:
                pass
    except Exception:
        pass


def start_log_session():
    """One log file per window session. Never blocks startup."""
    global _log_path
    for h in list(_logger.handlers):
        try:
            h.close()
        except Exception:
            pass
        _logger.removeHandler(h)
    _log_path = None
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(LOG_DIR, f"{PLUGIN_NAME}_{stamp}.log")
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d | %(message)s", "%Y-%m-%d %H:%M:%S"))
        _logger.addHandler(handler)
        _log_path = path
        _trim_log_dir(path)
    except Exception:
        _log_path = None
    return _log_path


def stop_log_session():
    for h in list(_logger.handlers):
        try:
            h.flush()
            h.close()
        except Exception:
            pass
        _logger.removeHandler(h)


def log(tag, msg):
    try:
        _logger.info(f"{tag:<6} | {msg}")
    except Exception:
        pass


def log_exc(where):
    log("ERROR", f"{where}: exception\n{traceback.format_exc()}")


# =============================================================================
# THEME
# =============================================================================
TOKENS = {
    "bg_window": "#2B2D30",
    "bg_panel": "#1E1F22",
    "bg_hover": "#35373B",
    "border": "#393B40",
    "text": "#DFE1E5",
    "text_muted": "#9DA0A8",
    "text_disabled": "#5A5D63",
    "accent": "#7C5CD6",
    "accent_hover": "#8E71DE",
    "help_icon": "#3D8BFD",
    "success": "#4E9A51",
    "success_hover": "#5DAF60",
    "warning": "#C8912F",
    "error": "#D9534F",
    "bg_invalid": "#4A2528",
    "font": ("Segoe UI", 9.0),
    "font_mono": ("Consolas", 9.0),
    "space": 8,
    "control_height": 28,
}


def color(token):
    h = TOKENS[token].lstrip("#")
    return drawing.Color.FromArgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def font(token="font", bold=False):
    fam, size = TOKENS[token]
    if bold:
        return drawing.Font(fam, size, drawing.FontStyle.Bold)
    return drawing.Font(fam, size)


def wrap_tip(text):
    # wrap each line separately so explicit line breaks in a tooltip are kept
    return "\n".join(textwrap.fill(line, TOOLTIP_WIDTH) if line else "" for line in text.split("\n"))



# =============================================================================
# CORE  (pure logic, no window)
# =============================================================================
class FspyError(Exception):
    """User-facing reason why an import cannot go on."""


@dataclass
class FspySettings:
    view_name: str = TARGET_VIEW    # always the Front viewport
    named_view: bool = True         # save a named view match1, match2, ...
    lock_viewport: bool = True      # lock the viewport when done (off = leave it as it was before)
    lock_photo: bool = True         # lock the fSpy_ImagePlane layer when done (off = leave it as it was before)
    embed_image: bool = False       # False: the picture frame references the file next to the .fspy
    flip_x: bool = False            # reverse the fSpy X axis (about Rhino 0,0,0)
    flip_y: bool = False
    flip_z: bool = False
    transparency_pct: float = 60.0  # image plane transparency, 0 = leave the material alone

    def describe(self):
        return (f"view={self.view_name!r} named_view={self.named_view} lock={self.lock_viewport} lock_photo={self.lock_photo} "
                f"embed={self.embed_image} transparency={self.transparency_pct}% "
                f"flip=({self.flip_x}, {self.flip_y}, {self.flip_z})")

    def flips(self):
        return (-1.0 if self.flip_x else 1.0, -1.0 if self.flip_y else 1.0, -1.0 if self.flip_z else 1.0)


def _unit(x, y, z):
    """New unit vector (no in-place Unitize: structs are not mutated reliably under pythonnet)."""
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        return rg.Vector3d(x, y, z)
    return rg.Vector3d(x / n, y / n, z / n)


def parse_fspy(path):
    """Read the .fspy binary. Returns (camera_parameters, reference_axis, reference_unit, image_bytes, state)."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 16 or struct.unpack('<I', data[0:4])[0] != FSPY_MAGIC:
        raise FspyError("Not an fSpy project file.")
    if struct.unpack('<I', data[4:8])[0] != 1:
        raise FspyError("Unsupported fSpy project version.")
    state_size = struct.unpack('<I', data[8:12])[0]
    image_size = struct.unpack('<I', data[12:16])[0]
    state = json.loads(data[16:16 + state_size].decode('utf-8'))
    image_bytes = data[16 + state_size:16 + state_size + image_size]
    if "cameraParameters" not in state or not state["cameraParameters"]:
        raise FspyError("No cameraParameters in this fSpy project (was the calibration finished in fSpy?).")
    cp = state["cameraParameters"]
    cs = state.get("calibrationSettingsBase", {})
    return cp, cs.get("referenceDistanceAxis"), cs.get("referenceDistanceUnit"), image_bytes, state


def sensor_info(state):
    """Camera data of the project. Returns (label, width_mm, height_mm, is_35mm_film).
    A preset (presetId + presetData) wins over the custom sensor, as in fSpy."""
    cd = (state.get("calibrationSettingsBase") or {}).get("cameraData") or {}
    log("API", f"cameraData raw: {json.dumps(cd)}")
    pd = cd.get("presetData") or {}
    if cd.get("presetId") and pd:
        label = str(pd.get("displayName") or cd.get("presetId"))
        w, h = pd.get("sensorWidth"), pd.get("sensorHeight")
    else:
        label = "Custom"
        w, h = cd.get("customSensorWidth"), cd.get("customSensorHeight")
    try:
        w, h = float(w), float(h)
    except (TypeError, ValueError):
        return label, None, None, False
    ok = abs(w - FILM_35MM[0]) <= SENSOR_TOL_MM and abs(h - FILM_35MM[1]) <= SENSOR_TOL_MM
    return label, w, h, ok


def origin_px(state):
    """fSpy origin control point in the image, relative coords (x right, y down, 0..1), or None."""
    o = (state.get("controlPointsStateBase") or {}).get("origin")
    try:
        return (float(o["x"]), float(o["y"]))
    except Exception:
        return None


def px_str(px):
    return f"{px[0]:.10g},{px[1]:.10g}" if px else ""


def parse_px(text):
    try:
        a, b = str(text).split(",")
        return (float(a), float(b))
    except Exception:
        return None


def same_px(a, b):
    return a is not None and b is not None and abs(a[0] - b[0]) <= ORIGIN_TOL and abs(a[1] - b[1]) <= ORIGIN_TOL


def ref_text(state):
    """Reference distance as 'axis|value|unit', or 'none' when no axis is set."""
    cs = state.get("calibrationSettingsBase") or {}
    axis = cs.get("referenceDistanceAxis")
    if axis is None:
        return "none"
    return f"{axis}|{cs.get('referenceDistance')}|{cs.get('referenceDistanceUnit')}"


def pixel_ray(cp, px, right, up, forward):
    """World direction of the camera ray through image point px (relative coords), fSpy convention:
    image-plane coords are normalised by half the longer side; the camera looks down its local -Z.
    Checked: the ray through the stored origin pixel passes through 0,0,0 (both test projects, 1e-15)."""
    w, h = float(cp["imageWidth"]), float(cp["imageHeight"])
    a = w / h
    if a >= 1.0:
        x, y = 2.0 * px[0] - 1.0, (1.0 - 2.0 * px[1]) / a
    else:
        x, y = (2.0 * px[0] - 1.0) * a, 1.0 - 2.0 * px[1]
    pp = cp.get("principalPoint") or {"x": 0.0, "y": 0.0}
    f = cp.get("relativeFocalLength")
    if f is None:
        fov = float(cp["horizontalFieldOfView"] if a >= 1.0 else cp["verticalFieldOfView"])
        f = 1.0 / math.tan(fov * 0.5)
    cx, cy, cz = x - float(pp.get("x", 0.0)), y - float(pp.get("y", 0.0)), -float(f)
    # camera basis: right, up, back = -forward
    return (right.X * cx + up.X * cy - forward.X * cz,
            right.Y * cx + up.Y * cy - forward.Y * cz,
            right.Z * cx + up.Z * cy - forward.Z * cz)


def apply_flips(f, pos, right, up, forward):
    """Reverse world axes: every point and direction is multiplied by f = (fx, fy, fz), about 0,0,0.
    The photo plane is built from these same vectors, so photo and geometry stay aligned. With an odd
    number of -1 this is a mirror: Rhino's camera is right-handed, so the photo shows reversed."""
    fx, fy, fz = f
    return (rg.Point3d(pos.X * fx, pos.Y * fy, pos.Z * fz),
            rg.Vector3d(right.X * fx, right.Y * fy, right.Z * fz),
            rg.Vector3d(up.X * fx, up.Y * fy, up.Z * fz),
            rg.Vector3d(forward.X * fx, forward.Y * fy, forward.Z * fz))


def floor_point(pos, d):
    """Where the ray pos + t*d (t > 0) meets the floor plane z = 0, or None."""
    if abs(d[2]) < 1e-12:
        return None
    t = -pos.Z / d[2]
    if t <= 0:
        return None
    return rg.Point3d(pos.X + t * d[0], pos.Y + t * d[1], pos.Z + t * d[2])


def calibration_mode(state):
    return str((state.get("globalSettings") or {}).get("calibrationMode") or "unknown")


def fspy_focal(cp, sensor_width_mm):
    """Focal length as fSpy shows it for a given sensor width (relativeFocalLength * width / 2).
    Falls back on the field of view of the longer image side if relativeFocalLength is missing."""
    rel = cp.get("relativeFocalLength")
    if rel is None:
        w, h = float(cp["imageWidth"]), float(cp["imageHeight"])
        fov = float(cp["horizontalFieldOfView"] if w >= h else cp["verticalFieldOfView"])
        rel = 1.0 / math.tan(fov * 0.5)
    return float(rel) * sensor_width_mm / 2.0


def doc_unit_meters():
    """Meters per document unit. The table is used first (as in v2.3); UnitScale only if the table fails."""
    us = sc.doc.ModelUnitSystem
    table, api = None, None
    try:
        table = RHINO_UNIT_METERS.get(int(us))
    except Exception:
        table = None
    try:
        api = float(Rhino.RhinoMath.UnitScale(us, Rhino.UnitSystem.Meters))
    except Exception:
        api = None
    log("API", f"document units {us}: table={table} UnitScale(doc->m)={api}")
    if table is not None:
        if api is not None and abs(api - table) > 1e-9 * max(abs(table), 1e-12):
            log("API", "units MISMATCH between table and UnitScale: table used (as in v2.3)")
        return table
    if api:
        return api
    return 1.0


def scale_factor(ref_axis, ref_unit):
    """fSpy units -> document units. Returns (factor, warning or None)."""
    if ref_axis is None:
        return 1.0, ("No reference distance set in fSpy (referenceDistanceAxis is null), "
                     "so the scene scale is arbitrary. Set the reference distance axis + "
                     "real length in fSpy for correct measurements.")
    fspy_m = FSPY_UNIT_METERS.get(ref_unit, 1.0)
    rhino_m = doc_unit_meters()
    return fspy_m / rhino_m, None


def image_extension(b):
    if b[:3] == b'\xff\xd8\xff':
        return ".jpg"
    if b[:8] == b'\x89PNG\r\n\x1a\n':
        return ".png"
    return ".img"


def save_image_next_to(fspy_path, image_bytes):
    """Write the embedded image beside the .fspy and return its path.
    Falls back to the temp folder only if the .fspy folder is not writable."""
    ext = image_extension(image_bytes)
    target = os.path.splitext(fspy_path)[0] + IMAGE_SUFFIX + ext
    try:
        if os.path.isfile(target) and os.path.getsize(target) == len(image_bytes):
            with open(target, "rb") as f:
                if f.read() == image_bytes:
                    log("ITEM", f"image unchanged, not rewritten: {target}")
                    return target
        with open(target, "wb") as f:
            f.write(image_bytes)
        return target
    except Exception:
        log_exc(f"write image next to .fspy ({target})")
        target = os.path.join(tempfile.gettempdir(), "fspy_" + uuid.uuid4().hex + ext)
        with open(target, "wb") as f:
            f.write(image_bytes)
        return target


def file_stamp(path):
    """(modification time, size) of a file, or None if it cannot be read."""
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except Exception:
        return None


def view_names():
    """Names of the standard viewports that are open (no page views)."""
    return [v.MainViewport.Name for v in sc.doc.Views.GetViewList(True, False)]


def find_view(name):
    """The target viewport: the one used last time (id kept in the document strings, so it is found even if
    its title changed), else the viewport titled `name`."""
    try:
        vid = sc.doc.Strings.GetValue("Fspy_importer_CC", VIEWPORT_ID_KEY)
        if vid:
            v = sc.doc.Views.Find(System.Guid(vid))
            log("API", f"Views.Find(id {vid}) -> {v.ActiveViewport.Name if v is not None else None}")
            if v is not None:
                return v
    except Exception:
        log_exc("find viewport by stored id")
    return sc.doc.Views.Find(name, False)


def set_world_top_cplane(view):
    """Construction plane of the target viewport = World Top (XY plane, Z up). Returns True if read back."""
    vp = view.ActiveViewport
    try:
        vp.SetConstructionPlane(rg.Plane.WorldXY)
        cp = vp.ConstructionPlane()
        ok = (cp.Origin.DistanceTo(rg.Point3d(0, 0, 0)) < 1e-9 and abs(cp.ZAxis.Z - 1.0) < 1e-9
              and abs(cp.XAxis.X - 1.0) < 1e-9)
        log("API", f"SetConstructionPlane(WorldXY) -> read back origin ({cp.Origin.X:.6g}, {cp.Origin.Y:.6g}, "
                   f"{cp.Origin.Z:.6g}) x ({cp.XAxis.X:.3f}, {cp.XAxis.Y:.3f}, {cp.XAxis.Z:.3f}) "
                   f"z ({cp.ZAxis.X:.3f}, {cp.ZAxis.Y:.3f}, {cp.ZAxis.Z:.3f}) -> World Top={ok}")
        view.Redraw()
        return ok
    except Exception:
        log_exc("set World Top construction plane")
        return False


# ---- 3-viewport layout (logic of 3viewport_cc v1.0, validated in Rhino 8.37) ----
LAYOUT_TOL = 8           # pixel tolerance when comparing viewport edges
LAYOUT_BIG_RATIO = 1.3   # the large viewport must be at least this many times bigger in area


def model_views():
    """Model views only (no layout pages)."""
    return list(sc.doc.Views.GetViewList(True, False))


def _vid(view):
    return view.RuntimeSerialNumber


def _rect(view):
    return view.ScreenRectangle


def _area(view):
    r = _rect(view)
    return r.Width * r.Height


def describe_views(label, views):
    log("API", f"{label}: {len(views)} model view(s)")
    for v in views:
        try:
            r = _rect(v)
            log("API", f"  {_vid(v)} '{v.ActiveViewport.Name}' L={r.Left} T={r.Top} R={r.Right} B={r.Bottom} "
                       f"(w={r.Width} h={r.Height})")
        except Exception:
            log_exc("describe views")


def _run_command(cmd):
    res = Rhino.RhinoApp.RunScript(cmd, False)
    log("API", f"RunScript('{cmd}') -> {res}")
    return res


def _set_projection(view, projection, name):
    vp = view.ActiveViewport
    res = vp.SetProjection(projection, name, False)
    vp.Name = name
    log("API", f"SetProjection({name}) -> {res}")
    view.Redraw()


def _find_slots(views):
    """(big, top_right, bottom_right) if the layout is one large view on the left and two stacked on the
    right, else None."""
    if len(views) != 3:
        log("SKIP", f"layout check: {len(views)} views, expected 3")
        return None
    big = max(views, key=_area)
    others = sorted([v for v in views if _vid(v) != _vid(big)], key=lambda v: _rect(v).Top)
    rb, r1, r2 = _rect(big), _rect(others[0]), _rect(others[1])
    on_the_right = r1.Left >= rb.Right - LAYOUT_TOL and r2.Left >= rb.Right - LAYOUT_TOL
    aligned = abs(r1.Left - r2.Left) <= LAYOUT_TOL
    stacked = r1.Bottom <= r2.Top + LAYOUT_TOL and r1.Top < r2.Top
    bigger = _area(big) >= LAYOUT_BIG_RATIO * max(_area(others[0]), _area(others[1]))
    log("API", f"layout check: on_the_right={on_the_right} aligned={aligned} stacked={stacked} bigger={bigger}")
    if on_the_right and aligned and stacked and bigger:
        return big, others[0], others[1]
    return None


def _split(view, want):
    """Split a view: want = 'side' (left/right) or 'stack' (top/bottom). Returns the new view or None."""
    for cmd in ("_SplitViewportVertical", "_SplitViewportHorizontal"):
        before = set(_vid(v) for v in model_views())
        sc.doc.Views.ActiveView = view
        _run_command(cmd)
        new = [v for v in model_views() if _vid(v) not in before]
        if not new:
            log("SKIP", f"{cmd}: no new view created")
            continue
        a, b = _rect(view), _rect(new[0])
        is_side = abs(a.Top - b.Top) <= LAYOUT_TOL and abs(a.Bottom - b.Bottom) <= LAYOUT_TOL
        is_stack = abs(a.Left - b.Left) <= LAYOUT_TOL and abs(a.Right - b.Right) <= LAYOUT_TOL
        log("API", f"{cmd}: is_side={is_side} is_stack={is_stack}")
        if (want == "side" and is_side) or (want == "stack" and is_stack):
            return new[0]
        log("SKIP", f"{cmd}: wrong orientation, closing the new view")
        sc.doc.Views.ActiveView = new[0]
        _run_command("_CloseViewport")
    return None


def _rebuild_layout():
    views = model_views()
    if not views:
        return None
    keep = sc.doc.Views.ActiveView or views[0]
    for v in views:
        if _vid(v) != _vid(keep):
            sc.doc.Views.ActiveView = v
            _run_command("_CloseViewport")
    describe_views("after closing extra views", model_views())
    second = _split(keep, "side")
    if second is None:
        return None
    right = keep if _rect(keep).Left > _rect(second).Left else second
    third = _split(right, "stack")
    if third is None:
        return None
    views = model_views()
    describe_views("after splits", views)
    return _find_slots(views)


def set_three_view_layout():
    """Perspective large on the left, Top upper right, Front lower right. Returns the Front view, or None."""
    log("RUN", "layout: left Perspective (large) / right-top Top / right-bottom Front")
    try:
        _run_command("_3View")
        views = model_views()
        describe_views("after 3View", views)
        slots = _find_slots(views)
        if slots is None:
            log("RUN", "3View layout does not match the target, rebuilding with split commands")
            slots = _rebuild_layout()
        if slots is None:
            log("ERROR", "could not build the 3-viewport layout (unexpected viewport geometry)")
            return None
        big, top_right, bottom_right = slots
        _set_projection(big, Proj.Perspective, "Perspective")
        _set_projection(top_right, Proj.Top, "Top")
        _set_projection(bottom_right, Proj.Front, TARGET_VIEW)
        describe_views("final layout", model_views())
        return bottom_right
    except Exception:
        log_exc("3-viewport layout")
        return None


FRONT_DISPLAY_MODE = "Ghosted"   # English name, independent of the Rhino language


def find_display_mode(english_name):
    """Display mode by its English name (works with a French Rhino)."""
    try:
        modes = list(Rhino.Display.DisplayModeDescription.GetDisplayModes())
    except Exception:
        log_exc("GetDisplayModes")
        modes = []
    for m in modes:
        if str(m.EnglishName).lower() == english_name.lower():
            return m
    log("API", f"display mode '{english_name}' not in {[str(m.EnglishName) for m in modes]}")
    try:
        return Rhino.Display.DisplayModeDescription.FindByName(english_name)
    except Exception:
        log_exc("FindByName display mode")
        return None


def set_front_display(view):
    """Ghosted display, construction grid, grid axes and world axes icon in the target viewport.
    Returns True when everything reads back as asked."""
    vp = view.ActiveViewport
    ok = True
    mode = find_display_mode(FRONT_DISPLAY_MODE)
    if mode is None:
        log("SKIP", f"display mode '{FRONT_DISPLAY_MODE}' not found, left unchanged")
        ok = False
    else:
        try:
            vp.DisplayMode = mode
            now = vp.DisplayMode
            same = now is not None and now.Id == mode.Id
            log("API", f"DisplayMode -> '{getattr(now, 'EnglishName', now)}' (ok={same})")
            ok = ok and same
        except Exception:
            log_exc("set display mode")
            ok = False
    for prop in ("ConstructionGridVisible", "ConstructionAxesVisible", "WorldAxesVisible"):
        try:
            setattr(vp, prop, True)
            back = bool(getattr(vp, prop))
            log("API", f"{prop} = True -> read back {back}")
            ok = ok and back
        except Exception:
            log_exc(f"set {prop}")
            ok = False
    view.Redraw()
    return ok


def zoom_extents_except(target):
    """Zoom extents in every model view except the target (its camera is the fSpy match)."""
    done = []
    for v in model_views():
        if _vid(v) == _vid(target):
            continue
        try:
            r = v.ActiveViewport.ZoomExtents()
            log("API", f"ZoomExtents('{v.ActiveViewport.Name}') -> {r}")
            v.Redraw()
            done.append(v.ActiveViewport.Name)
        except Exception:
            log_exc(f"zoom extents {v.ActiveViewport.Name}")
    return done


def remember_view(view):
    try:
        r = sc.doc.Strings.SetString("Fspy_importer_CC", VIEWPORT_ID_KEY, str(view.MainViewport.Id))
        log("API", f"Strings.SetString(viewport id {view.MainViewport.Id}) -> {r!r}")
    except Exception:
        log_exc("remember viewport id")


def camera_basis(cp, s):
    m = cp["cameraTransform"]["rows"]
    pos = rg.Point3d(m[0][3] * s, m[1][3] * s, m[2][3] * s)
    right = _unit(m[0][0], m[1][0], m[2][0])
    up = _unit(m[0][1], m[1][1], m[2][1])
    forward = _unit(-m[0][2], -m[1][2], -m[2][2])
    return pos, right, up, forward


def lens_from_fov(cp):
    w = float(cp["imageWidth"])
    h = float(cp["imageHeight"])
    hfov = float(cp["horizontalFieldOfView"])
    vfov = float(cp["verticalFieldOfView"])
    if w >= h:
        return 12.0 / math.tan(vfov * 0.5)
    return 12.0 / math.tan(hfov * 0.5)


def get_lock(view):
    """Viewport lock state (RhinoViewport.LockedProjection), or None if it cannot be read."""
    try:
        v = bool(view.ActiveViewport.LockedProjection)
        log("API", f"LockedProjection read -> {v}")
        return v
    except Exception:
        log_exc("read LockedProjection")
        return None


def set_lock(view, flag):
    """Set the viewport lock. Returns the state read back (None if unreadable)."""
    try:
        view.ActiveViewport.LockedProjection = bool(flag)
        back = bool(view.ActiveViewport.LockedProjection)
        log("API", f"LockedProjection = {bool(flag)} -> read back {back}")
        view.Redraw()
        return back
    except Exception:
        log_exc(f"set LockedProjection {flag}")
        return None


def apply_camera(view, pos, right, up, forward, lens):
    vp = view.ActiveViewport
    if not vp.IsPerspectiveProjection:
        vp.ChangeToPerspectiveProjection(True, lens)
        log("API", "ChangeToPerspectiveProjection done")
    vpi = rdo.ViewportInfo(vp)
    log("API", f"SetCameraLocation -> {vpi.SetCameraLocation(pos)}")
    log("API", f"SetCameraDirection -> {vpi.SetCameraDirection(forward)}")
    log("API", f"SetCameraUp -> {vpi.SetCameraUp(up)}")
    vpi.Camera35mmLensLength = lens
    log("API", f"SetViewProjection -> {vp.SetViewProjection(vpi, True)}")
    view.Redraw()
    gap = vp.CameraLocation.DistanceTo(pos)
    tol = 1e-4 * (1.0 + pos.DistanceTo(rg.Point3d(0, 0, 0)))
    log("API", f"camera landed {gap:.6g} from target (tolerance {tol:.6g})")
    return gap <= tol


def ensure_layer(name):
    idx = sc.doc.Layers.FindByFullPath(name, -1)
    if idx < 0:
        lay = rdo.Layer()
        lay.Name = name
        idx = sc.doc.Layers.Add(lay)
        log("API", f"Layers.Add({name}) -> {idx}")
    return idx


def _enum_settings():
    st = rdo.ObjectEnumeratorSettings()
    st.HiddenObjects = True
    st.DeletedObjects = False
    st.IncludeGrips = False
    st.NormalObjects = True
    st.LockedObjects = True
    st.IncludeLights = False
    st.ReferenceObjects = False
    try:
        st.VisibleFilter = False          # do not drop objects on hidden layers
    except Exception:
        pass
    return st


def objects_on_plane_layer(project_name):
    """Every object on IMAGE_PLANE_LAYER (any state: hidden, locked, layer off or locked), plus any object
    still named after the project elsewhere. Three lookups are merged and logged, so a lookup that misses
    an object shows in the log."""
    found = {}
    counts = {}
    idx = sc.doc.Layers.FindByFullPath(IMAGE_PLANE_LAYER, -1)
    if idx >= 0:
        lay = sc.doc.Layers[idx]
        log("ITEM", f"layer {IMAGE_PLANE_LAYER}: index {idx} visible={lay.IsVisible} locked={lay.IsLocked}")
        try:
            st = _enum_settings()
            st.LayerIndexFilter = idx
            objs = list(sc.doc.Objects.GetObjectList(st))
            counts["enum layer"] = len(objs)
            for o in objs:
                found[o.Id] = o
        except Exception:
            log_exc("enumerate layer")
        try:
            objs = list(sc.doc.Objects.FindByLayer(lay) or [])
            counts["FindByLayer"] = len(objs)
            for o in objs:
                found[o.Id] = o
        except Exception:
            log_exc("FindByLayer")
    else:
        log("ITEM", f"layer {IMAGE_PLANE_LAYER} does not exist yet")
    try:
        st = _enum_settings()
        st.NameFilter = project_name
        objs = list(sc.doc.Objects.GetObjectList(st))
        counts["by name"] = len(objs)
        for o in objs:
            found[o.Id] = o
    except Exception:
        log_exc("enumerate by name")
    result = list(found.values())
    log("ITEM", f"previous photo plane lookup {counts} -> {len(result)} object(s): "
                f"{[(str(o.Id), o.Attributes.Name) for o in result]}")
    return result


def delete_object(obj):
    """Delete even when the object or its layer is locked or hidden. Returns the API answer."""
    try:
        return sc.doc.Objects.Delete(obj, True, True)       # quiet, ignore modes (locked / hidden)
    except Exception:
        log_exc("Objects.Delete(obj, quiet, ignoreModes)")
        return sc.doc.Objects.Delete(obj.Id, True)


DOC_STRINGS_SECTION = "Fspy_importer_CC"


def doc_named_view(project_name, value=None):
    """Named view of a project kept in the document's strings (survives the plane being deleted)."""
    try:
        if value is None:
            v = sc.doc.Strings.GetValue(DOC_STRINGS_SECTION, project_name)
            log("API", f"Strings.GetValue({project_name}) -> {v!r}")
            return v or None
        r = sc.doc.Strings.SetString(DOC_STRINGS_SECTION, project_name, value)
        log("API", f"Strings.SetString({project_name}, {value}) -> {r!r}")
        return value
    except Exception:
        log_exc("document strings")
        return None


def build_image_plane(cp, image_path, pos, right, up, forward, settings, obj_name, user_strings=None):
    """Textured plane through the world origin (or IMAGE_PLANE_DISTANCE). Returns (guid, depth, height)."""
    w_img = float(cp["imageWidth"])
    h_img = float(cp["imageHeight"])
    vfov = float(cp["verticalFieldOfView"])
    if IMAGE_PLANE_DISTANCE is not None:
        d = float(IMAGE_PLANE_DISTANCE)
    else:
        d = -(pos.X * forward.X + pos.Y * forward.Y + pos.Z * forward.Z)
        if d < 1e-9:
            d = pos.DistanceTo(rg.Point3d(0, 0, 0)) or 1.0
    half_h = d * math.tan(vfov * 0.5)
    half_w = half_h * (w_img / h_img)

    # Principal point (optical centre) offset. fSpy normalizes the principal
    # point by half the LARGER image dimension. Shift the image so the principal
    # point lands on the optical axis -> photo content lies on its true rays.
    # Always applied: without it the photo is off the fSpy origin (57 / 33 px on the test project).
    pp = cp.get("principalPoint") or {"x": 0.0, "y": 0.0}
    ppx = float(pp.get("x", 0.0))
    ppy = float(pp.get("y", 0.0))
    s = half_w if half_w >= half_h else half_h
    off_r = -ppx * s
    off_u = -ppy * s
    log("API", f"principal point x={ppx} y={ppy} -> offset right={off_r:.6g} up={off_u:.6g}")

    # image centre = axis point at depth d, shifted by the principal-point offset
    ax = pos.X + forward.X * d + off_r * right.X + off_u * up.X
    ay = pos.Y + forward.Y * d + off_r * right.Y + off_u * up.Y
    az = pos.Z + forward.Z * d + off_r * right.Z + off_u * up.Z
    bl = rg.Point3d(ax - right.X * half_w - up.X * half_h,
                    ay - right.Y * half_w - up.Y * half_h,
                    az - right.Z * half_w - up.Z * half_h)
    plane = rg.Plane(bl, right, up)
    # rhinoscriptsyntax kept for this one call: same arguments as v2.3 (RhinoCommon argument order not verified).
    guid = rs.AddPictureFrame(plane, image_path, half_w * 2.0, half_h * 2.0,
                              True, settings.embed_image, False, False)
    log("API", f"rs.AddPictureFrame -> {guid}")
    if not guid or guid == System.Guid.Empty:
        return None, d, half_h * 2.0

    obj = sc.doc.Objects.FindId(guid)
    if obj is not None:
        attr = obj.Attributes.Duplicate()
        attr.LayerIndex = ensure_layer(IMAGE_PLANE_LAYER)
        attr.Name = obj_name
        for key, value in (user_strings or {}).items():
            if value:
                attr.SetUserString(key, str(value))
        log("API", f"Objects.ModifyAttributes(layer, name) -> {sc.doc.Objects.ModifyAttributes(obj, attr, True)}")
    if 0.0 < settings.transparency_pct <= 100.0:
        try:
            obj2 = sc.doc.Objects.FindId(guid)
            mi = obj2.Attributes.MaterialIndex       # picture frame already has its textured material
            log("API", f"picture frame material index -> {mi}")
            if mi is not None and mi >= 0:
                mat = sc.doc.Materials[mi]
                mat.Transparency = settings.transparency_pct / 100.0
                mat.CommitChanges()
                log("API", f"material transparency set to {settings.transparency_pct / 100.0}")
        except Exception:
            log_exc("set image plane transparency (plane kept opaque)")
    return guid, d, half_h * 2.0


def named_view_index(name):
    nv = sc.doc.NamedViews
    for i in range(nv.Count):
        if nv[i].Name == name:
            return i
    return -1


def save_named_view(name, view, replace):
    """Add a named view. replace=True: an existing view with this name is deleted first (Sync).
    Returns the index, or -1."""
    if replace:
        i = named_view_index(name)
        if i >= 0:
            log("API", f"NamedViews.Delete({i} '{name}') -> {sc.doc.NamedViews.Delete(i)}")
    idx = sc.doc.NamedViews.Add(name, view.MainViewport.Id)
    log("API", f"NamedViews.Add({name}) -> {idx}")
    return idx if idx is not None else -1


def next_match_name():
    nv = sc.doc.NamedViews
    existing = set(nv[i].Name for i in range(nv.Count))
    i = 1
    while (NAMED_VIEW_PREFIX + str(i)) in existing:
        i += 1
    return NAMED_VIEW_PREFIX + str(i)


def prepare_import(path, settings, asks, say, mode="run"):
    """Phase A: everything that does not change the document. Returns a context dict, or None
    (the reason was already said). asks = callbacks, all asked before anything changes:
      replace(count, name) -> bool   (Run only: Sync replaces without asking)
      arbitrary_scale() -> bool      (no reference distance in the project)
      origin() -> "follow" | "keep" | None   (Sync only, when the origin was moved in fSpy)"""
    if not path or not os.path.exists(path):
        say("No valid .fspy file selected. Use Select.", "warning")
        return None
    try:
        cp, ref_axis, ref_unit, image_bytes, state = parse_fspy(path)
    except Exception as ex:
        log_exc("parse_fspy")
        say(f"Could not read this .fspy file: {ex}", "error")
        return None
    sensor = sensor_info(state)
    mode_cal = calibration_mode(state)
    cur_origin = origin_px(state)
    cur_ref = ref_text(state)
    log("ITEM", f"parsed {path}: image {cp.get('imageWidth')}x{cp.get('imageHeight')}, "
                f"{len(image_bytes)} bytes, ref axis={ref_axis} unit={ref_unit}, "
                f"calibration={mode_cal}, sensor={sensor}")
    if mode == "run":
        view = None             # Run sets the 3-viewport layout after the questions and takes its Front view
    else:
        view = find_view(settings.view_name)
        log("API", f"target viewport -> {view.ActiveViewport.Name if view is not None else None}")
    if view is None and mode != "run":
        say(f"No '{settings.view_name}' viewport is open. Open the standard 4-viewport layout "
            f"(or a viewport titled '{settings.view_name}') and try again. Nothing was changed.", "error")
        return None
    if ref_axis is None:
        ok = asks["arbitrary_scale"]()
        log("API", f"no reference distance: continue with arbitrary scale -> {ok}")
        if not ok:
            say("Cancelled: no reference distance in this project. Set it in fSpy, save, then Sync.", "warning")
            return None
    s, warn = scale_factor(ref_axis, ref_unit)
    if warn:
        say(warn, "warning")
    pos, right, up, forward = camera_basis(cp, s)
    lens = lens_from_fov(cp)
    log("ITEM", f"scale={s:.6g} camera=({pos.X:.4f}, {pos.Y:.4f}, {pos.Z:.4f}) lens={lens:.4f} mm")

    obj_name = "fSpy_ref_" + os.path.splitext(os.path.basename(path))[0]
    old = objects_on_plane_layer(obj_name)
    prev = {}
    # this project's plane wins; another project's plane on the layer is only replaced
    for o in sorted(old, key=lambda ob: ob.Attributes.Name == obj_name):
        if o.Attributes.Name != obj_name:
            continue
        for key in (NAMED_VIEW_KEY, ORIGIN_PX_KEY, ANCHOR_PX_KEY, REF_KEY):
            v = o.Attributes.GetUserString(key)
            if v:
                prev[key] = v
    log("ITEM", f"recorded on previous plane: {prev}")
    prev_named = prev.get(NAMED_VIEW_KEY) or doc_named_view(obj_name)
    prev_origin = parse_px(prev.get(ORIGIN_PX_KEY))
    prev_anchor = parse_px(prev.get(ANCHOR_PX_KEY)) or prev_origin
    log("ITEM", f"origin pixel: file={cur_origin} previous={prev_origin} anchor={prev_anchor}")

    # Which image point sits at Rhino 0,0,0. Run always follows fSpy; Sync keeps the previous choice
    # and asks when the origin was moved in fSpy since the last import.
    anchor, origin_note = cur_origin, None
    if mode == "sync" and prev_origin is not None and cur_origin is not None:
        if same_px(cur_origin, prev_origin):
            anchor = prev_anchor
            if not same_px(anchor, cur_origin):
                origin_note = "kept"
        else:
            choice = asks["origin"]()
            log("API", f"origin moved in fSpy: choice -> {choice}")
            if choice is None:
                say("Cancelled: nothing was changed.", "warning")
                return None
            if choice == "keep":
                anchor, origin_note = prev_anchor, "kept"
            else:
                origin_note = "followed"
    if mode != "sync" and prev_anchor is not None and not same_px(prev_anchor, cur_origin):
        origin_note = "followed"            # Run always follows the fSpy origin
    shift = None
    if anchor is not None and not same_px(anchor, cur_origin):
        d = pixel_ray(cp, anchor, right, up, forward)
        shift = floor_point(pos, d)
        log("ITEM", f"keep origin: ray {d} from camera -> floor point {shift}")
        if shift is None:
            say("Cannot keep the current origin: in the new calibration, the previous origin point does not "
                "fall on the floor plane (z = 0). Nothing was changed. Choose 'follow' or check fSpy.", "error")
            return None
        pos = rg.Point3d(pos.X - shift.X, pos.Y - shift.Y, pos.Z - shift.Z)
        log("ITEM", f"camera shifted by {-shift.X:.6g}, {-shift.Y:.6g}, {-shift.Z:.6g} -> "
                    f"({pos.X:.4f}, {pos.Y:.4f}, {pos.Z:.4f})")
    prev_ref = prev.get(REF_KEY)
    ref_changed = (prev_ref, cur_ref) if (prev_ref and prev_ref != cur_ref) else None
    flips = settings.flips()
    if flips != (1.0, 1.0, 1.0):
        pos, right, up, forward = apply_flips(flips, pos, right, up, forward)
        log("ITEM", f"flips {flips} -> camera ({pos.X:.4f}, {pos.Y:.4f}, {pos.Z:.4f}) "
                    f"forward ({forward.X:.4f}, {forward.Y:.4f}, {forward.Z:.4f}) up ({up.X:.4f}, {up.Y:.4f}, {up.Z:.4f})")

    if old and mode != "sync" and not asks["replace"](len(old), obj_name):
        log("CANCEL", "replace previous plane refused: nothing changed")
        say("Cancelled: the previous image plane was kept and nothing was changed.", "warning")
        return None

    return {"path": path, "cp": cp, "ref_axis": ref_axis, "ref_unit": ref_unit, "image_bytes": image_bytes,
            "view": view, "view_title": view.ActiveViewport.Name if view is not None else settings.view_name,
            "scale": s,
            "pos": pos, "right": right, "up": up, "forward": forward, "lens": lens,
            "obj_name": obj_name, "old_ids": [o.Id for o in old], "prev_named": prev_named,
            "sensor": sensor, "calibration": mode_cal, "mode": mode,
            "origin_px": cur_origin, "anchor_px": anchor, "origin_note": origin_note, "shift": shift,
            "ref_text": cur_ref, "ref_changed": ref_changed, "flips": flips}


def apply_camera_and_image(ctx):
    """Phase A2: unlock if needed, move the camera, write the photo next to the .fspy (no document object yet)."""
    ctx["was_locked"] = get_lock(ctx["view"])
    if ctx["was_locked"]:
        set_lock(ctx["view"], False)
    ctx["camera_ok"] = apply_camera(ctx["view"], ctx["pos"], ctx["right"], ctx["up"], ctx["forward"], ctx["lens"])
    sc.doc.Views.ActiveView = ctx["view"]
    ctx["cplane_ok"] = set_world_top_cplane(ctx["view"])
    ctx["display_ok"] = set_front_display(ctx["view"])
    remember_view(ctx["view"])
    ctx["img_path"] = save_image_next_to(ctx["path"], ctx["image_bytes"])
    log("ITEM", f"image file used by the plane: {ctx['img_path']}")


def set_layer_lock(flag):
    """Lock / unlock IMAGE_PLANE_LAYER. Returns the state read back, or None (layer missing / error)."""
    try:
        idx = sc.doc.Layers.FindByFullPath(IMAGE_PLANE_LAYER, -1)
        if idx < 0:
            return None
        lay = sc.doc.Layers[idx]
        if bool(lay.IsLocked) != bool(flag):
            lay.IsLocked = bool(flag)
            try:
                ok = lay.CommitChanges()
            except Exception:
                ok = sc.doc.Layers.Modify(lay, idx, True)
            log("API", f"layer {IMAGE_PLANE_LAYER} IsLocked = {bool(flag)} -> commit {ok}")
        back = bool(sc.doc.Layers[idx].IsLocked)
        log("API", f"layer {IMAGE_PLANE_LAYER} locked read back -> {back}")
        return back
    except Exception:
        log_exc(f"set layer lock {flag}")
        return None


def layer_locked():
    idx = sc.doc.Layers.FindByFullPath(IMAGE_PLANE_LAYER, -1)
    return bool(sc.doc.Layers[idx].IsLocked) if idx >= 0 else False


def build_scene(ctx, settings, say):
    """Phase B (inside the undo record): replace the previous plane, add the new one, named view.
    The photo layer is unlocked while it changes, then locked (option on) or put back as it was."""
    ctx["layer_was_locked"] = layer_locked()
    if ctx["layer_was_locked"]:
        set_layer_lock(False)
    ctx["deleted"] = 0
    ctx["delete_failed"] = 0
    for oid in ctx["old_ids"]:
        obj = sc.doc.Objects.FindId(oid)
        ok = delete_object(obj) if obj is not None else False
        log("API", f"Objects.Delete({oid}) -> {ok}")
        if ok:
            ctx["deleted"] += 1
        else:
            ctx["delete_failed"] += 1
    ctx["named"] = None
    ctx["named_updated"] = False
    if settings.named_view:
        # One named view per project (Run and Sync): the one recorded on the previous plane is replaced.
        if ctx.get("prev_named"):
            name, replace = ctx["prev_named"], True
        else:
            name, replace = next_match_name(), False
        idx = save_named_view(name, ctx["view"], replace)
        if idx >= 0:
            ctx["named"] = name
            ctx["named_updated"] = replace
            doc_named_view(ctx["obj_name"], name)
        else:
            say(f"Named view '{name}' could not be saved.", "error")
    strings = {NAMED_VIEW_KEY: ctx["named"] or ctx.get("prev_named"),
               ORIGIN_PX_KEY: px_str(ctx.get("origin_px")),
               ANCHOR_PX_KEY: px_str(ctx.get("anchor_px")),
               REF_KEY: ctx.get("ref_text")}
    log("ITEM", f"recorded on new plane: {strings}")
    guid, depth, height = build_image_plane(ctx["cp"], ctx["img_path"], ctx["pos"], ctx["right"],
                                            ctx["up"], ctx["forward"], settings, ctx["obj_name"], strings)
    ctx["guid"], ctx["depth"], ctx["plane_h"] = guid, depth, height
    if guid is None:
        say("The image plane could not be created (see log). Camera and scale were applied.", "error")
    want = True if settings.lock_photo else ctx["layer_was_locked"]
    ctx["photo_locked"] = set_layer_lock(want) if want else layer_locked()
    ctx["view"].Redraw()


def finish_lock(ctx, settings):
    """Phase C: lock when the option is on; otherwise put back the state found before the Run.
    Returns the final state (None if it cannot be read)."""
    want = True if settings.lock_viewport else bool(ctx.get("was_locked"))
    if want:
        return set_lock(ctx["view"], True)
    return get_lock(ctx["view"])


def report_import(ctx, settings, say):
    ref = ctx
    verb = "synced" if ref.get("mode") == "sync" else "applied"
    if ref.get("layout_ok"):
        say("Layout: Perspective (left) / Top (upper right) / Front (lower right).", "text_muted")
    say(f"fSpy project {verb} to '{ref['view_title']}'.", "success")
    if not ref.get("camera_ok", True):
        say("  camera did not land where expected (see log)", "warning")
    label, sw, sh, film = ref["sensor"]
    f35 = fspy_focal(ref["cp"], FILM_35MM[0])
    gap = abs(f35 - ref["lens"]) / max(ref["lens"], 1e-9)
    say(f"  fSpy focal (35 mm film): {f35:.2f} mm | Rhino lens: {ref['lens']:.2f} mm",
        "warning" if gap > FOCAL_MISMATCH else "text_muted")
    if gap > FOCAL_MISMATCH:
        say("  the two differ: the photo is not 3:2, so they cannot match exactly", "warning")
    if not film:
        size = f"{sw:g} x {sh:g} mm" if sw else "unknown size"
        shown = f", fSpy shows {fspy_focal(ref['cp'], sw):.2f} mm" if sw else ""
        say(f"  camera data is {label} ({size}){shown}: set it to 35 mm film in fSpy", "warning")
    if ref.get("origin_note") == "kept":
        sh = ref.get("shift")
        say(f"  origin: KEPT at Rhino 0,0,0 (fSpy origin is at {sh.X:.3f}, {sh.Y:.3f}, {sh.Z:.3f})"
            if sh is not None else "  origin: KEPT at Rhino 0,0,0", "warning")
    elif ref.get("origin_note") == "followed":
        say("  origin: moved to the new fSpy origin (the photo moved in Rhino)", "warning")
    fl = ref.get("flips") or (1.0, 1.0, 1.0)
    names = [a for a, v in zip("XYZ", fl) if v < 0]
    if names:
        mirrored = len(names) % 2 == 1
        say(f"  flipped axes: {', '.join(names)}" + (" -> MIRROR: the photo shows reversed" if mirrored else
                                                     " (a half-turn: the photo reads normally)"),
            "warning" if mirrored else "text_muted")
    if ref.get("ref_changed"):
        old_r, new_r = ref["ref_changed"]
        say(f"  reference distance changed: {old_r} -> {new_r} (the photo was rescaled)", "warning")
    if ref.get("calibration") == "OneVanishingPoint":
        say("  1 vanishing point: fSpy does not compute the focal, you set it by hand", "text_muted")
    say(f"  reference axis : {ref['ref_axis']}   unit: {ref['ref_unit']}", "text_muted")
    say(f"  scale factor   : {ref['scale']:g}  (fSpy units -> document units)", "text_muted")
    say(f"  camera distance from origin: {ref['pos'].DistanceTo(rg.Point3d(0, 0, 0)):.3f}", "text_muted")
    say(f"  image saved    : {ref['img_path']}", "text_muted")
    if ref.get("deleted"):
        say(f"  previous plane replaced ({ref['deleted']})", "text_muted")
    if ref.get("delete_failed"):
        say(f"  {ref['delete_failed']} old object(s) on '{IMAGE_PLANE_LAYER}' could not be deleted (see log)", "error")
    if ref.get("guid"):
        say(f"  image plane    : through origin, depth {ref['depth']:.3f}, height {ref['plane_h']:.1f} units", "text_muted")
        say(f"                   layer '{IMAGE_PLANE_LAYER}' -> hide it to see your model", "text_muted")
        if 0.0 < settings.transparency_pct <= 100.0:
            say(f"                   transparency: {int(settings.transparency_pct)}%", "text_muted")
    if ref.get("named"):
        state = "updated" if ref.get("named_updated") else "saved"
        say(f"  named view {state}: {ref['named']}", "text_muted")
    if ref.get("display_ok"):
        say(f"  display: {FRONT_DISPLAY_MODE}, grid and axes shown", "text_muted")
    else:
        say(f"  display: {FRONT_DISPLAY_MODE} / grid / axes not all applied (see log)", "warning")
    if ref.get("zoomed"):
        say(f"  zoom extents: {', '.join(ref['zoomed'])} (not Front: its camera is the match)", "text_muted")
    if ref.get("cplane_ok"):
        say("  construction plane: World Top", "text_muted")
    else:
        say("  construction plane could not be set to World Top (see log)", "warning")
    pl = ref.get("photo_locked")
    if pl is None:
        say(f"  photo layer lock state could not be read (see log)", "warning")
    else:
        say(f"  photo layer '{IMAGE_PLANE_LAYER}' is {'LOCKED' if pl else 'unlocked'}", "text_muted")
    lk = ref.get("locked")
    if lk is None:
        say("  viewport lock state could not be read (see log)", "warning")
    elif lk:
        say(f"  viewport '{ref['view_title']}' is LOCKED", "text_muted")
    else:
        say(f"  viewport '{ref['view_title']}' is unlocked", "text_muted")


# =============================================================================
# UI  (shared widgets - hand-drawn dark controls, see skill note ui-eto.md)
# =============================================================================
class _Report:
    """Report panel: short coloured lines. Colour is optional (falls back to plain)."""

    def __init__(self):
        self.area = forms.RichTextArea()
        self.area.ReadOnly = True
        self.area.Font = font("font_mono")
        self.area.BackgroundColor = color("bg_panel")
        self.area.TextColor = color("text")
        self.lines = []
        self._color_ok = True

    def clear(self):
        self.lines = []
        self._render()

    def add(self, text, kind="text"):
        self.lines.append((text, kind))
        self.lines = self.lines[-200:]
        self._render()

    def _render(self):
        full = "\n".join(t for t, _ in self.lines)
        self.area.Text = full
        if not self._color_ok:
            return
        try:
            pos = 0
            for text, kind in self.lines:
                if kind in ("success", "warning", "error", "text_muted") and text:
                    rng = forms.Range[int](pos, pos + len(text) - 1)
                    self.area.Buffer.SetForeground(rng, color(kind))
                pos += len(text) + 1
        except Exception:
            self._color_ok = False
            log("ERROR", "report colouring unavailable, plain text used\n" + traceback.format_exc())


def _help_icon(tip):
    d = forms.Drawable()
    d.Size = drawing.Size(16, 16)
    d.ToolTip = wrap_tip(tip)

    def paint(sender, e):
        try:
            g = e.Graphics
            g.AntiAlias = True
            c = color("help_icon")
            rect = drawing.RectangleF(1.5, 1.5, 13.0, 13.0)
            g.DrawEllipse(drawing.Pen(c, 1.2), rect)
            f = drawing.Font("Segoe UI", 7.5, drawing.FontStyle.Bold)
            try:
                size = g.MeasureString(f, "?")
                w, h = size.Width, size.Height
            except Exception:
                w, h = 5.0, 11.0
            cx, cy = rect.X + rect.Width / 2.0, rect.Y + rect.Height / 2.0
            g.DrawText(f, c, cx - w / 2.0, cy - h / 2.0, "?")
        except Exception:
            log_exc("help icon paint")

    d.Paint += paint
    return d


def _warn_icon(tip):
    """Triangle with '!' in the warning colour. Hidden by default (set .Visible)."""
    d = forms.Drawable()
    d.Size = drawing.Size(18, 18)
    d.ToolTip = wrap_tip(tip)
    d.Visible = False

    def paint(sender, e):
        try:
            g = e.Graphics
            g.AntiAlias = True
            c = color("warning")
            path = drawing.GraphicsPath()
            path.AddLines(drawing.PointF(9.0, 1.5), drawing.PointF(16.5, 15.5), drawing.PointF(1.5, 15.5))
            path.CloseFigure()
            g.DrawPath(drawing.Pen(c, 1.4), path)
            f = drawing.Font("Segoe UI", 8.0, drawing.FontStyle.Bold)
            try:
                size = g.MeasureString(f, "!")
                w, h = size.Width, size.Height
            except Exception:
                w, h = 4.0, 11.0
            g.DrawText(f, c, 9.0 - w / 2.0, 10.5 - h / 2.0, "!")
        except Exception:
            log_exc("warn icon paint")

    d.Paint += paint
    return d


def _label(text, muted=False, bold=False, tip=None, width=None):
    lb = forms.Label()
    lb.Text = text
    lb.Font = font(bold=bold)
    lb.TextColor = color("text_muted" if muted else "text")
    lb.VerticalAlignment = forms.VerticalAlignment.Center
    if width:
        lb.Width = width
    if tip:
        lb.ToolTip = wrap_tip(tip)
    return lb


def _stepper(value, minv=0.1, maxv=100000.0, places=1, inc=5.0, width=80):
    s = forms.NumericStepper()
    s.DecimalPlaces = places
    s.MinValue = minv
    s.MaxValue = maxv
    s.Increment = inc
    s.Value = value
    s.Width = width
    s.TextColor = color("text")
    s.BackgroundColor = color("bg_panel")
    return s


# ---- custom-drawn controls -----------------------------------------------------
# Native Eto buttons / radios / checkboxes ignore dark-theme colours in some states
# (black text, black radio dot). These are drawn by hand so every colour is ours.
class _Event:
    """Minimal event: supports `obj.Evt += handler`; handlers get (sender, e)."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self, sender):
        for fn in list(self.handlers):
            fn(sender, None)


def _text_size(fnt, text):
    try:
        sz = fnt.MeasureString(text)
        return float(sz.Width), float(sz.Height)
    except Exception:
        return len(text) * 6.5, 14.0


def _hook_mouse(widget, d):
    def enter(sender, e):
        widget.hover = True
        d.Invalidate()

    def leave(sender, e):
        widget.hover = False
        d.Invalidate()

    def up(sender, e):
        try:
            if widget.enabled:
                widget.clicked()
        except Exception:
            log_exc(f"{type(widget).__name__} click")

    d.MouseEnter += enter
    d.MouseLeave += leave
    d.MouseUp += up
    try:
        d.Cursor = forms.Cursors.Pointer
    except Exception:
        pass


class FlatButton:
    def __init__(self, text, tip=None, bg="bg_panel", bg_hover="bg_hover", min_width=0):
        self.text, self.bg, self.bg_hover = text, bg, bg_hover
        self.hover, self.enabled = False, True
        self.Click = _Event()
        self.font = font()
        w, _ = _text_size(self.font, text)
        d = forms.Drawable()
        d.Size = drawing.Size(max(int(w) + 28, int(min_width)), TOKENS["control_height"])
        if tip:
            d.ToolTip = wrap_tip(tip)
        d.Paint += self._paint
        _hook_mouse(self, d)
        self.control = d

    @property
    def Enabled(self):
        return self.enabled

    @Enabled.setter
    def Enabled(self, value):
        self.enabled = bool(value)
        self.control.Invalidate()

    def clicked(self):
        self.Click.fire(self)

    def set_colors(self, bg, bg_hover):
        if (bg, bg_hover) != (self.bg, self.bg_hover):
            self.bg, self.bg_hover = bg, bg_hover
            self.control.Invalidate()

    def _paint(self, sender, e):
        try:
            g = e.Graphics
            w, h = float(self.control.Width), float(self.control.Height)
            bg = self.bg_hover if (self.hover and self.enabled) else self.bg
            if not self.enabled:
                bg = "bg_panel"
            g.FillRectangle(color(bg), 0.0, 0.0, w, h)
            g.DrawRectangle(color("border"), 0.0, 0.0, w - 1.0, h - 1.0)
            tw, th = _text_size(self.font, self.text)
            g.DrawText(self.font, color("text" if self.enabled else "text_disabled"),
                       (w - tw) / 2.0, (h - th) / 2.0, self.text)
        except Exception:
            log_exc("FlatButton paint")


class _Option:
    """One radio option or a checkbox, drawn by hand."""

    def __init__(self, owner, index, text, kind):
        self.owner, self.index, self.text, self.kind = owner, index, text, kind
        self.hover, self.enabled = False, True
        self.font = font()
        w, _ = _text_size(self.font, text)
        d = forms.Drawable()
        d.Size = drawing.Size(int(w) + 26, TOKENS["control_height"] - 4)
        d.Paint += self._paint
        _hook_mouse(self, d)
        self.control = d

    def clicked(self):
        self.owner._clicked(self.index)

    def _paint(self, sender, e):
        try:
            g = e.Graphics
            g.AntiAlias = True
            h = float(self.control.Height)
            g.FillRectangle(color("bg_window"), 0.0, 0.0, float(self.control.Width), h)
            on = self.owner._is_on(self.index)
            if self.enabled:
                edge = color("accent" if on else ("text" if self.hover else "text_muted"))
                txt = color("text")
            else:
                edge = color("text_disabled")
                txt = color("text_disabled")
            box = drawing.RectangleF(2.0, h / 2.0 - 6.5, 13.0, 13.0)
            fill = color("accent" if self.enabled else "text_disabled")
            if self.kind == "radio":
                g.DrawEllipse(drawing.Pen(edge, 1.2), box)
                if on:
                    g.FillEllipse(fill, drawing.RectangleF(5.5, h / 2.0 - 3.0, 6.0, 6.0))
            else:
                if on:
                    g.FillRectangle(fill, box)
                    pen = drawing.Pen(color("text"), 1.6)
                    g.DrawLine(pen, 5.0, h / 2.0, 7.5, h / 2.0 + 2.5)
                    g.DrawLine(pen, 7.5, h / 2.0 + 2.5, 12.0, h / 2.0 - 3.0)
                else:
                    g.DrawRectangle(drawing.Pen(edge, 1.2), box)
            tw, th = _text_size(self.font, self.text)
            g.DrawText(self.font, txt, 21.0, (h - th) / 2.0, self.text)
        except Exception:
            log_exc("option paint")


class OptionGroup:
    """Radio group (horizontal or vertical); selected dot in accent colour.
    SelectedIndex -1 = nothing selected. Items can be replaced with set_items()."""

    def __init__(self, items, selected=0, vertical=False):
        self._enabled = True
        self._index = selected
        self.SelectedIndexChanged = _Event()
        lay = forms.StackLayout()
        lay.Orientation = forms.Orientation.Vertical if vertical else forms.Orientation.Horizontal
        lay.Spacing = 2 if vertical else TOKENS["space"]
        self.control = lay
        self.items, self.options = [], []
        self.set_items(items, selected)

    def set_items(self, items, selected=-1):
        self.items = list(items)
        self._index = selected if 0 <= selected < len(self.items) else -1
        self.control.Items.Clear()
        self.options = [_Option(self, i, t, "radio") for i, t in enumerate(self.items)]
        for op in self.options:
            op.enabled = self._enabled
            self.control.Items.Add(forms.StackLayoutItem(op.control, False))

    @property
    def SelectedIndex(self):
        return self._index

    @SelectedIndex.setter
    def SelectedIndex(self, value):
        self._index = value
        for op in self.options:
            op.control.Invalidate()

    @property
    def SelectedItem(self):
        return self.items[self._index] if 0 <= self._index < len(self.items) else None

    @property
    def Enabled(self):
        return self._enabled

    @Enabled.setter
    def Enabled(self, value):
        self._enabled = bool(value)
        for op in self.options:
            op.enabled = self._enabled
            op.control.Invalidate()

    def _is_on(self, i):
        return i == self._index

    def _clicked(self, i):
        if i != self._index:
            self._index = i
            for op in self.options:
                op.control.Invalidate()
            self.SelectedIndexChanged.fire(self)


class Toggle:
    """Checkbox drawn by hand; checked box filled with the accent colour."""

    def __init__(self, text, checked=True):
        self._checked = checked
        self.CheckedChanged = _Event()
        self.option = _Option(self, 0, text, "check")
        self.control = self.option.control

    @property
    def Checked(self):
        return self._checked

    @Checked.setter
    def Checked(self, value):
        self._checked = bool(value)
        self.control.Invalidate()

    @property
    def Enabled(self):
        return self.option.enabled

    @Enabled.setter
    def Enabled(self, value):
        self.option.enabled = bool(value)
        self.control.Invalidate()

    def _is_on(self, i):
        return self._checked

    def _clicked(self, i):
        self._checked = not self._checked
        self.control.Invalidate()
        self.CheckedChanged.fire(self)


class TextField:
    """Dark text box. `.control` is the Eto TextBox. Invalid state tints the background.
    TextChanged handlers get (sender, e); they must be wrapped by the window's _safe()."""

    def __init__(self, text="", width=95, placeholder=None, readonly=False):
        tb = forms.TextBox()
        tb.Text = text
        tb.Width = width
        tb.Font = font()
        tb.TextColor = color("text")
        tb.BackgroundColor = color("bg_panel")
        if placeholder:
            try:
                tb.PlaceholderText = placeholder
            except Exception:
                pass
        if readonly:
            tb.ReadOnly = True
        self.control = tb
        self.valid = True
        self.TextChanged = _Event()
        tb.TextChanged += self._changed

    def _changed(self, sender, e):
        try:
            self.TextChanged.fire(self)
        except Exception:
            log_exc("TextField changed")

    @property
    def Text(self):
        return self.control.Text or ""

    @Text.setter
    def Text(self, value):
        self.control.Text = value

    @property
    def Enabled(self):
        return self.control.Enabled

    @Enabled.setter
    def Enabled(self, value):
        self.control.Enabled = bool(value)

    def set_valid(self, ok):
        self.valid = bool(ok)
        try:
            self.control.BackgroundColor = color("bg_panel" if ok else "bg_invalid")
        except Exception:
            pass


def _table_row(*items):
    """TableRow from controls or (control, expand); None = empty cell."""
    row = forms.TableRow()
    for it in items:
        ctrl, expand = it if isinstance(it, tuple) else (it, False)
        ctrl = getattr(ctrl, "control", ctrl)
        row.Cells.Add(forms.TableCell(ctrl, expand))
    return row


def _hrow(*items):
    """Single-row table; items are controls or (control, expand)."""
    t = forms.TableLayout()
    t.Spacing = drawing.Size(TOKENS["space"], 0)
    t.Rows.Add(_table_row(*items))
    return t


class BaseWindow:
    """Shared window behaviour (from the skill template): one log file per session, wrapped event
    handlers, single instance, Escape caught only during a Run, one Ctrl+Z per Run, progress meter.
    A plugin subclasses it as PluginUI and implements _build()."""

    WINDOW_SIZE = (440, 520)

    def __init__(self):
        self.version = __version__
        self.running = False
        self.cancel_requested = False
        self.is_open = False
        self.form = None
        self.report = None
        self.btn_run = None
        self.btn_cancel = None
        self.btn_log = None
        self._locked_buttons = []          # buttons disabled while a Run is going (besides Run)
        self._esc_handler = self._safe("Escape", self._on_escape)
        start_log_session()
        self._log_header()
        self._build()

    # ---- hooks for the plugin ----
    def extra_header(self):
        pass

    def on_window_closed(self):
        pass

    def can_run(self):
        return True

    def _build(self):
        raise NotImplementedError

    # ---- logging ----
    def _log_header(self):
        doc = sc.doc
        try:
            nsel = len(list(doc.Objects.GetSelectedObjects(False, False)))
        except Exception:
            nsel = -1
        log("START", f"{PLUGIN_NAME} v{__version__}")
        log("START", f"Rhino {Rhino.RhinoApp.Version} | Python {sys.version.split()[0]}")
        log("START", f"plugin dir {PLUGIN_DIR} (from {PLUGIN_DIR_SOURCE})")
        log("START", f"file {doc.Path or '(unsaved)'} | units {doc.ModelUnitSystem} | "
                     f"abs tol {doc.ModelAbsoluteTolerance} | ang tol {doc.ModelAngleToleranceDegrees} deg")
        log("START", f"selected objects at open: {nsel}")
        try:
            self.extra_header()
        except Exception:
            log_exc("extra_header")

    def _safe(self, name, fn):
        """Every event handler goes through this: Eto swallows exceptions silently otherwise."""
        def handler(sender, e):
            try:
                fn(sender, e)
            except Exception as ex:
                log_exc(name)
                try:
                    self.report.add(f"Error in {name}: {ex} (see log)", "error")
                except Exception:
                    pass
        return handler

    # ---- window ----
    def _make_form(self):
        f = forms.Form()
        self.form = f
        f.Title = PLUGIN_NAME
        f.Resizable = True
        f.Minimizable = False
        f.Maximizable = False
        f.ClientSize = drawing.Size(self.WINDOW_SIZE[0], self.WINDOW_SIZE[1])
        f.BackgroundColor = color("bg_window")
        f.Padding = drawing.Padding(TOKENS["space"])
        try:
            f.Owner = Rhino.UI.RhinoEtoApp.MainWindow
        except Exception:
            log_exc("set owner")
        f.Closed += self._safe("Closed", self.on_closed)
        return f

    def _make_common(self, run_text="Run", run_tip="Run.", cancel_tip="Stop the run. What is already done is kept.",
                     with_cancel=True):
        self.badge = _label(f"v{__version__}", muted=True)
        self.btn_log = FlatButton("Open log folder",
                                  "Open the logs folder of this plugin (one file per window session).")
        self.btn_log.Click += self._safe("Log", self.on_log)
        self.btn_run = FlatButton(run_text, run_tip, bg="accent", bg_hover="accent_hover")
        self.btn_run.Click += self._safe("Run", self.on_run)
        if with_cancel:
            self.btn_cancel = FlatButton("Cancel", cancel_tip)
            self.btn_cancel.Enabled = False
            self.btn_cancel.Click += self._safe("Cancel", self.on_cancel)
        self.report = _Report()

    def show(self):
        self.form.Show()
        self.is_open = True
        log("START", "window shown")

    def bring_to_front(self):
        try:
            self.form.BringToFront()
            self.form.Focus()
        except Exception:
            log_exc("bring_to_front")

    def close(self):
        try:
            self.form.Close()
        except Exception:
            log_exc("close")

    def on_closed(self, sender, e):
        self.is_open = False
        log("CLOSE", "window closed")
        try:
            self.on_window_closed()
        except Exception:
            log_exc("on_window_closed")
        if sc.sticky.get(STICKY_KEY) is self:
            sc.sticky.pop(STICKY_KEY, None)
        stop_log_session()

    def on_log(self, sender, e):
        log("SELECT", "Log clicked")
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            os.startfile(LOG_DIR)
        except Exception:
            log_exc("open log folder")
            self.report.add(f"Cannot open {LOG_DIR}", "error")

    def on_cancel(self, sender, e):
        if self.running:
            self.cancel_requested = True
            log("CANCEL", "Cancel clicked")

    def on_run(self, sender, e):
        raise NotImplementedError

    # ---- run helpers ----
    def _progress(self, action, *args):
        try:
            sn = sc.doc.RuntimeSerialNumber
            if action == "show":
                try:
                    Rhino.UI.StatusBar.ShowProgressMeter(sn, 0, args[0], PLUGIN_NAME, True, True)
                except Exception:
                    Rhino.UI.StatusBar.ShowProgressMeter(0, args[0], PLUGIN_NAME, True, True)
            elif action == "update":
                try:
                    Rhino.UI.StatusBar.UpdateProgressMeter(sn, args[0], True)
                except Exception:
                    Rhino.UI.StatusBar.UpdateProgressMeter(args[0], True)
            else:
                try:
                    Rhino.UI.StatusBar.HideProgressMeter(sn)
                except Exception:
                    Rhino.UI.StatusBar.HideProgressMeter()
        except Exception:
            pass

    def _on_escape(self, sender, e):
        # Only an Escape pressed while this run is going counts (sc.escape_test kept stale presses).
        if self.running and not self.cancel_requested:
            self.cancel_requested = True
            log("CANCEL", "Escape pressed during run")

    def _cancelled(self):
        try:
            Rhino.RhinoApp.Wait()
        except Exception:
            pass
        return self.cancel_requested

    def _set_running(self, flag):
        self.running = flag
        if flag:
            self.cancel_requested = False
        if self.btn_run is not None:
            self.btn_run.Enabled = (not flag) and self.can_run()
        if self.btn_cancel is not None:
            self.btn_cancel.Enabled = flag
        for b in self._locked_buttons:
            b.Enabled = not flag

    @contextlib.contextmanager
    def run_scope(self, label, total=0, undo=True, redraw_off=True, progress=True):
        """Everything a Run must set up and always tear down: buttons, Escape hook, one undo record,
        redraw suspended, progress meter. Yields a dict (key 'undo_sn')."""
        scope = {"undo_sn": 0}
        self._set_running(True)
        if redraw_off:
            sc.doc.Views.RedrawEnabled = False
        if progress:
            self._progress("show", total)
        esc_hooked = False
        try:
            Rhino.RhinoApp.EscapeKeyPressed += self._esc_handler
            esc_hooked = True
        except Exception:
            log_exc("hook Escape (Cancel button still works)")
        try:
            if undo:
                scope["undo_sn"] = sc.doc.BeginUndoRecord(f"{PLUGIN_NAME} {label}")
                log("UNDO", f"begin sn={scope['undo_sn']}")
            yield scope
        finally:
            if esc_hooked:
                try:
                    Rhino.RhinoApp.EscapeKeyPressed -= self._esc_handler
                except Exception:
                    log_exc("unhook Escape")
            if scope["undo_sn"]:
                sc.doc.EndUndoRecord(scope["undo_sn"])
                log("UNDO", f"end sn={scope['undo_sn']}")
            if progress:
                self._progress("hide")
            if redraw_off:
                sc.doc.Views.RedrawEnabled = True
            self._set_running(False)


class PluginUI(BaseWindow):
    WINDOW_SIZE = (460, 640)

    def __init__(self):
        self.fspy_path = None
        self._stamp = None          # (mtime, size) of the .fspy last read by Select / Run / Sync
        self._stale = False         # True = file saved again since: Sync is green
        self._watch_failed = False
        self._timer = None
        super().__init__()

    # ---- layout ----
    def _build(self):
        f = self._make_form()
        self._make_common(run_tip="Set the 3-viewport layout (Perspective left, Top upper right, Front lower "
                                  "right; zoom extents in Perspective and Top), then apply the .fspy camera to the Front viewport, add the photo plane and the "
                                  "project's named view (replaced if it exists). Follows the fSpy origin. "
                                  "One Ctrl+Z undoes the plane and the named view (not the camera).",
                          with_cancel=False)
        self.btn_sync = FlatButton("Sync", "Re-read the .fspy from disk and re-apply it to the Front viewport. "
                                           "Replaces this project's photo plane without asking and updates its "
                                           "named view. Turns green when the .fspy was saved again in fSpy. "
                                           "If the origin was moved in fSpy, asks whether to follow it.")
        self.btn_sync.Click += self._safe("Sync", self.on_sync)
        self.btn_sync.Enabled = False
        self._locked_buttons.append(self.btn_sync)

        self.btn_select = FlatButton("Select", "Pick the .fspy project file.")
        self.btn_select.Click += self._safe("Select", self.on_select)
        self.lbl_file = _label("No file selected", muted=True)


        self.chk_named = Toggle("Create named view", True)
        self.chk_lock = Toggle("Lock viewport", True)
        self.chk_lock_photo = Toggle("Lock photo layer", True)
        self.chk_embed = Toggle("Embed image", False)
        self.chk_fx = Toggle("Flip X", False)
        self.chk_fy = Toggle("Flip Y", False)
        self.chk_fz = Toggle("Flip Z", False)
        for name, tg in (("Flip X", self.chk_fx), ("Flip Y", self.chk_fy), ("Flip Z", self.chk_fz)):
            tg.CheckedChanged += self._safe(name, self.on_flip(name, tg))
        self.st_transp = _stepper(60.0, 0.0, 100.0, 0, 5.0, 70)
        for name, tg in (("Create named view", self.chk_named), ("Lock viewport", self.chk_lock),
                         ("Lock photo layer", self.chk_lock_photo),
                         ("Embed image", self.chk_embed)):
            tg.CheckedChanged += self._safe(name, self.on_setting(name, lambda t=tg: t.Checked))
        self.st_transp.ValueChanged += self._safe("Transparency",
                                                  self.on_setting("Transparency", lambda: self.st_transp.Value))

        main = forms.TableLayout()
        main.Spacing = drawing.Size(TOKENS["space"], TOKENS["space"])

        def add(ctrl, scale_height=False):
            row = _table_row((ctrl, True))
            row.ScaleHeight = scale_height
            main.Rows.Add(row)

        add(_hrow((None, True), self.badge))                      # version: top right
        add(_label("Inputs", bold=True, tip="The fSpy project to import."))
        add(_hrow(self.btn_select, (self.lbl_file, True)))
        add(_hrow(_label("Target viewport", bold=True), _label(TARGET_VIEW, muted=True),
                  _help_icon("The camera of the Front viewport is always the one overwritten, and its "
                             "construction plane is set to World Top. If its title changes later, the plugin "
                             "still finds it (its id is kept in the document)."),
                  (None, True)))
        add(_label("Settings", bold=True))
        add(_hrow(self.chk_named,
                  _help_icon("Create named view: one per project (MatchPerspectiveFspy1 for the first project, "
                             "MatchPerspectiveFspy2 for the next...); Run and Sync replace it."),
                  (None, True)))
        add(_hrow(self.chk_lock, self.chk_lock_photo,
                  _help_icon("Lock viewport: a stray drag cannot move the matched camera. "
                             "Lock photo layer: the layer fSpy_ImagePlane is locked, so the photo cannot be "
                             "picked or moved. Off = left as it was before the Run."),
                  (None, True)))
        add(_hrow(self.chk_embed,
                  _help_icon("Embed image: also stores the pixels in the .3dm (heavier; off = the plane "
                             "references the file written next to the .fspy)."),
                  (None, True)))
        add(_hrow(self.chk_fx, self.chk_fy, self.chk_fz,
                  _help_icon("Reverse an fSpy axis that points the wrong way (about Rhino 0,0,0). Changing a box "
                             "turns Sync green. Two boxes = a half-turn, the photo reads normally. One or three "
                             "boxes = a mirror: the photo shows reversed (texts read backwards)."),
                  (None, True)))
        add(_hrow(_label("Transparency"), self.st_transp, _label("%", muted=True),
                  _help_icon("Transparency of the photo plane (0 = leave the material as it is, "
                             "60 = you see your model through the photo)."),
                  (None, True)))
        add(_hrow(self.btn_run, self.btn_sync, (None, True)))
        add(_label("Report", bold=True, tip="Short result of the last action. Full detail is in the log."))
        add(self.report.area, scale_height=True)
        add(_hrow(self.btn_log, (None, True)))                    # log folder: bottom left

        f.Content = main
        log("SELECT", f"target viewport: {TARGET_VIEW} (fixed)")
        self._start_watch()

    # ---- settings ----
    def read_settings(self):
        return FspySettings(view_name=TARGET_VIEW,
                            named_view=bool(self.chk_named.Checked),
                            lock_viewport=bool(self.chk_lock.Checked),
                            lock_photo=bool(self.chk_lock_photo.Checked),
                            embed_image=bool(self.chk_embed.Checked),
                            flip_x=bool(self.chk_fx.Checked),
                            flip_y=bool(self.chk_fy.Checked),
                            flip_z=bool(self.chk_fz.Checked),
                            transparency_pct=float(self.st_transp.Value))

    def on_setting(self, name, getter):
        def h(sender, e):
            log("SETTING", f"{name} = {getter()}")
        return h

    # ---- .fspy watch (green Sync) ----
    def _start_watch(self):
        try:
            self._timer = forms.UITimer()
            self._timer.Interval = WATCH_INTERVAL_S
            self._timer.Elapsed += self._on_watch
            self._timer.Start()
            log("START", f"file watch every {WATCH_INTERVAL_S} s")
        except Exception:
            self._timer = None
            log_exc("start file watch (Sync will not turn green)")

    def on_window_closed(self):
        if self._timer is not None:
            try:
                self._timer.Stop()
            except Exception:
                log_exc("stop file watch")

    def on_flip(self, name, tg):
        def h(sender, e):
            log("SETTING", f"{name} = {tg.Checked}")
            if self.fspy_path and self._stamp is not None:
                self._set_stale(True)           # the scene no longer matches: Sync turns green
        return h

    def _set_stale(self, flag):
        self._stale = bool(flag)
        if self._stale:
            self.btn_sync.set_colors("success", "success_hover")
        else:
            self.btn_sync.set_colors("bg_panel", "bg_hover")

    def _on_watch(self, sender, e):
        # Runs every second on the UI thread: never raises, logs only on a change.
        if self._watch_failed:
            return
        try:
            if not self.fspy_path or self._stamp is None or self._stale or self.running:
                return
            now = file_stamp(self.fspy_path)
            if now is None or now == self._stamp:
                return
            log("SELECT", f"file saved again on disk: {self.fspy_path} {self._stamp} -> {now}: Sync is green")
            self._set_stale(True)
            self.report.add("The .fspy was saved again: click Sync.", "success")
        except Exception:
            self._watch_failed = True
            log_exc("file watch (stopped)")

    def _mark_read(self, stamp):
        self._stamp = stamp
        self._set_stale(False)

    # ---- inputs ----
    def on_select(self, sender, e):
        log("SELECT", "Select clicked")
        fd = Rhino.UI.OpenFileDialog()
        fd.Title = "Select fSpy project"
        fd.Filter = "fSpy project (*.fspy)|*.fspy||"
        ok = fd.ShowOpenDialog()
        log("API", f"OpenFileDialog.ShowOpenDialog -> {ok}")
        if not ok:
            self.report.add("Selection cancelled: previous file kept.", "text_muted")
            return
        path = fd.FileName
        stamp = file_stamp(path)
        try:
            cp, ref_axis, ref_unit, image_bytes, state = parse_fspy(path)
        except Exception as ex:
            log_exc("parse_fspy on select")
            self.report.add(f"Could not read this .fspy file: {ex}", "error")
            return
        self.fspy_path = path
        self._mark_read(stamp)
        self.lbl_file.Text = os.path.basename(path)
        self.btn_sync.Enabled = not self.running
        log("SELECT", f"file {path}")
        label, sw, sh, film = sensor_info(state)
        log("ITEM", f"sensor {label} {sw} x {sh} mm, 35 mm film={film} | reference {ref_text(state)}")
        self._warn_select(None if film else (label, sw, sh), ref_axis is None)
        self.report.add(f"Selected: {os.path.basename(path)} "
                        f"(photo {cp.get('imageWidth')}x{cp.get('imageHeight')}, "
                        f"reference distance: {ref_unit if ref_axis is not None else 'not set'})", "text")

    def _warn_select(self, sensor, no_ref):
        """One OK window at Select for everything worth fixing in fSpy before importing."""
        parts = []
        if no_ref:
            parts.append("No reference distance is set.\n"
                         "It gives the photo its real size in Rhino. Setting it later moves and resizes "
                         "the photo, and what you modelled will no longer line up.\n"
                         "In fSpy: Reference distance > axis + real length.")
            self.report.add("No reference distance in this project: the scale will be arbitrary.", "warning")
        if sensor:
            label, sw, sh = sensor
            size = f"{sw:g} x {sh:g} mm" if sw else "unknown size"
            parts.append(f"Camera data is not set to 35 mm film (36 x 24 mm).\n"
                         f"This project uses: {label} ({size}).\n"
                         f"With 35 mm film, the focal length in fSpy equals the lens length in Rhino "
                         f"(for a 3:2 photo), so iterating between the two is direct.\n"
                         f"In fSpy: Camera data > 35 mm film.")
            self.report.add(f"Camera data: {label} ({size}), not 35 mm film.", "warning")
        if not parts:
            return
        msg = "\n\n".join(parts) + "\n\nFix it in fSpy, save, then click Sync."
        r = Rhino.UI.Dialogs.ShowMessage(msg, PLUGIN_NAME, Rhino.UI.ShowMessageButton.OK,
                                         Rhino.UI.ShowMessageIcon.Warning)
        log("API", f"select warning shown (no_ref={no_ref}, sensor={sensor}) -> {r}")

    def _ask_arbitrary_scale(self):
        r = Rhino.UI.Dialogs.ShowMessage(
            "No reference distance is set in this fSpy project.\n\n"
            "The size of the photo in Rhino comes from it. Without it the scale is arbitrary, and setting it "
            "later moves and resizes the photo (what you modelled will no longer line up).\n\n"
            "Continue with an arbitrary scale?",
            PLUGIN_NAME, Rhino.UI.ShowMessageButton.YesNo, Rhino.UI.ShowMessageIcon.Warning)
        return r == Rhino.UI.ShowMessageResult.Yes

    def _ask_origin(self):
        r = Rhino.UI.Dialogs.ShowMessage(
            "The origin was moved in fSpy since the last import.\n\n"
            "Yes = follow the new fSpy origin: Rhino 0,0,0 goes to the new point. The photo and the camera "
            "move; what you modelled stays where it is.\n\n"
            "No = keep the current Rhino origin: the previous point stays at 0,0,0. Both points must be on "
            "the same floor plane.\n\n"
            "Cancel = change nothing.",
            PLUGIN_NAME, Rhino.UI.ShowMessageButton.YesNoCancel, Rhino.UI.ShowMessageIcon.Question)
        if r == Rhino.UI.ShowMessageResult.Yes:
            return "follow"
        if r == Rhino.UI.ShowMessageResult.No:
            return "keep"
        return None

    # ---- run ----
    def _confirm_replace(self, count, name):
        r = Rhino.UI.Dialogs.ShowMessage(
            f"{count} object(s) on layer '{IMAGE_PLANE_LAYER}' (the previous photo plane) will be deleted "
            f"and replaced by the new plane. This layer holds one photo only.\n\nContinue?",
            PLUGIN_NAME, Rhino.UI.ShowMessageButton.YesNo, Rhino.UI.ShowMessageIcon.Question)
        log("API", f"confirm replace previous plane({count}) -> {r}")
        return r == Rhino.UI.ShowMessageResult.Yes

    def on_run(self, sender, e):
        self._import("run")

    def on_sync(self, sender, e):
        if not self.fspy_path:
            self.report.add("Select a .fspy file first.", "warning")
            return
        self._import("sync")

    def _import(self, mode):
        if self.running:
            return
        settings = self.read_settings()
        log("RUN", f"mode={mode} file={self.fspy_path} | {settings.describe()}")
        self.report.clear()

        def say(text, kind="text"):
            self.report.add(text, kind)
            log("RUN", f"[{kind}] {text}")

        t_start = time.time()
        stamp = file_stamp(self.fspy_path) if self.fspy_path else None
        asks = {"replace": self._confirm_replace, "arbitrary_scale": self._ask_arbitrary_scale,
                "origin": self._ask_origin}
        ctx = prepare_import(self.fspy_path, settings, asks, say, mode)
        if ctx is None:
            log("DONE", "nothing changed")
            return
        if mode == "run":
            front = set_three_view_layout()
            ctx["layout_ok"] = front is not None
            if front is None:
                say("The 3-viewport layout could not be set (see log): using the current Front viewport.",
                    "warning")
                front = find_view(settings.view_name)
            if front is None:
                say(f"No '{settings.view_name}' viewport is open. Nothing was imported.", "error")
                log("DONE", "no target viewport")
                return
            ctx["view"], ctx["view_title"] = front, front.ActiveViewport.Name
        try:
            apply_camera_and_image(ctx)
            with self.run_scope("Sync" if mode == "sync" else "Run", redraw_off=False, progress=False):
                build_scene(ctx, settings, say)
            ctx["locked"] = finish_lock(ctx, settings)
            if mode == "run":
                ctx["zoomed"] = zoom_extents_except(ctx["view"])
        except Exception as ex:
            log_exc("run")
            say(f"Unexpected error: {ex} (see log)", "error")
            return
        sc.doc.Views.Redraw()
        self._mark_read(stamp)
        report_import(ctx, settings, say)
        log("DONE", f"mode={mode} view={ctx['view_title']} plane={ctx.get('guid')} named={ctx.get('named')} "
                    f"updated={ctx.get('named_updated')} origin={ctx.get('origin_note')} "
                    f"was_locked={ctx.get('was_locked')} "
                    f"locked={ctx.get('locked')} in {time.time() - t_start:.2f} s")


# =============================================================================
# ENTRY POINT
# =============================================================================
def main():
    if Rhino.RhinoApp.ExeVersion < 8 or sys.version_info[0] < 3:
        msg = f"{PLUGIN_NAME} needs Rhino 8+ with Python 3. Install Rhino 8+."
        Rhino.RhinoApp.WriteLine(msg)
        try:
            Rhino.UI.Dialogs.ShowMessage(msg, PLUGIN_NAME)
        except Exception:
            pass
        return
    existing = sc.sticky.get(STICKY_KEY)
    if existing is not None and getattr(existing, "is_open", False):
        if getattr(existing, "version", None) == __version__:
            existing.bring_to_front()
            return
        existing.close()
    ui = PluginUI()
    sc.sticky[STICKY_KEY] = ui
    ui.show()


try:
    main()
except Exception:
    log_exc("main")
    Rhino.RhinoApp.WriteLine(f"{PLUGIN_NAME}: startup error, see {LOG_DIR}")
