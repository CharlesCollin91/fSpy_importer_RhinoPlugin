# Fspy_importer_CC

[Français](README.fr.md) · **English**

A Rhino 8 Python script that imports an [fSpy](https://fspy.io) camera-match project (`.fspy`) into Rhino. It sets the camera of the Front viewport to the fSpy match at real-world scale, puts the photo on a textured plane whose origin lands exactly on the fSpy origin, and arranges a 3-viewport layout (Perspective, Top, Front). It opens a small floating window: select the `.fspy` file and press **Run**; after each change saved in fSpy, the **Sync** button turns green and re-applies it. One Ctrl+Z undoes the photo plane and the named view, and the `.fspy` file is never modified.

Version **2.14** · License: [GPL-3.0-or-later](LICENSE) · Code walkthrough: [ARCHITECTURE.md](ARCHITECTURE.md)

## Requirements
Windows, Rhino 8 or later (built-in Python 3). No extra packages.

## Install
1. Download `Fspy_importer_CC.py` and put it in any folder.
2. In Rhino, create a toolbar button with this macro (adjust the path):
   ```
   ! _-RunPythonScript "C:\Tools\Fspy_importer_CC\Fspy_importer_CC.py"
   ```

## Inputs
One fSpy project file (`.fspy`), which holds both the calibration and the photo. For a correct size in Rhino, set a reference distance in fSpy; for a direct match between fSpy's focal length and Rhino's lens length, set fSpy's Camera data to 35 mm film. The plugin warns about both. The photo is written next to the `.fspy` file.

## Contributing
Improvements are welcome. Start with [ARCHITECTURE.md](ARCHITECTURE.md), which explains how the single file is organized and where each step lives. To report a bug, open an issue and attach the matching file from the `logs` folder the plugin creates next to the script. Version history: [CHANGELOG.md](CHANGELOG.md).

## License
GNU General Public License v3.0 or later: you can use, study, modify and share this code, and any distributed modified version must stay under the same license. See [LICENSE](LICENSE).
