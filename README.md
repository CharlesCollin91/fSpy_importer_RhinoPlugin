# Fspy_importer_CC

[Français](README.fr.md) · **English**

**The plugin** : A Rhino 8 Python script that imports an [fSpy](https://fspy.io) camera-match project (`.fspy`) into Rhino. 

 <p>
  <img
    width="300"
    align="top"
    alt="Image 1"
    src="https://github.com/user-attachments/assets/38273ad4-e2b6-4ecd-81bd-5438ed248f01"
  />
  <img
    width="705"
    align="top"
    alt="Rhino fSpy Import"
    src="https://github.com/user-attachments/assets/7d3010c5-468c-427a-85da-690fcf669d90"
  />
</p>


- It sets the camera of the Front viewport to the fSpy match at real-world scale, 
- puts the photo on a textured plane whose origin lands exactly on the fSpy origin. 

Version **2.14** · License: [GPL-3.0-or-later](LICENSE) · Code walkthrough: [ARCHITECTURE.md](ARCHITECTURE.md)

## Requirements
Windows, Rhino 8 or later (built-in Python 3). No extra packages.

## Install
1. Download `Fspy_importer_CC.py` and put it in any folder.
2. In Rhino, create a toolbar button with this macro (adjust the path):
   ```
   ! _-RunPythonScript "C:\...\Fspy_importer_CC\Fspy_importer_CC.py"
   ```

## Inputs
fSpy project file (`.fspy`), which holds both the calibration and the photo. 

## Contributing
Improvements are welcome. Start with [ARCHITECTURE.md](ARCHITECTURE.md), which explains how the single file is organized and where each step lives.  Version history: [CHANGELOG.md](CHANGELOG.md).

## License
GNU General Public License v3.0 or later: you can use, study, modify and share this code, and any distributed modified version must stay under the same license. See [LICENSE](LICENSE).
