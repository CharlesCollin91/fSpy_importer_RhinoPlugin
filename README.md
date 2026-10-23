<img width="1761" height="1166" alt="ImgRef" src="https://github.com/user-attachments/assets/1faa25b5-383d-47cd-8f29-513dab1feeaf" />
# Fspy_importer_CC

[Français](README.fr.md) · **English**

**The plugin** : A Rhino 8 Python script that imports an [fSpy](https://fspy.io) camera-match project (`.fspy`) into Rhino. 

<p><img src="https://github.com/user-attachments/assets/38273ad4-e2b6-4ecd-81bd-5438ed248f01" alt="Fspy importer UI" width="28.6%"> <img src="https://github.com/user-attachments/assets/7d3010c5-468c-427a-85da-690fcf669d90" alt="Rhino fSpy Import" width="70.1%"></p>

- It sets the camera of the Front viewport to the fSpy match at real-world scale, 
- puts the photo on a textured plane whose origin lands exactly on the fSpy origin. 

Version **2.14** · License: [GPL-3.0-or-later](LICENSE) · Code walkthrough: [ARCHITECTURE.md](ARCHITECTURE.md)

## Requirements
Windows, Rhino 8 or later (built-in Python 3). No extra packages.

## Install
1. Download `Fspy_importer_CC.py` and put it in any folder.
3. In Rhino, create a toolbar button with this macro (adjust the path):
   ```
   ! _-RunPythonScript "C:\...\Fspy_importer_CC\Fspy_importer_CC.py"
   ```
## How to
1. Highly recommanded to understand the basics of fSpy. Everything you need to know for the basics here in this excellent youtube video by Bartochsz Pampush https://www.youtube.com/watch?v=daiMOYR8GS8&t=1343s
2. Analyse your image
<p align="center"><img width="600" alt="AnalysedImg" src="https://github.com/user-attachments/assets/d487f03e-1311-40a6-a090-aacff44ecccf" /></p>
3. Do your first adjustments in fSpy
<p align="center"><img width="600" alt="fspy_image_adjustments" src="https://github.com/user-attachments/assets/26c8ed21-5538-41f9-a790-e6bcef178128" /></p>
4. Import to Rhino via the plugin
<p align="center"><img width="600" alt="Rhino_fspy_import" src="https://github.com/user-attachments/assets/66520091-792b-43c9-87b2-e54402288ff4" /></p>
5. Iterate to adjust the lens lenght (back and forth between Rhino and Fspy. Made easy with the "sync" option)
6. Modelize
<p align="center"><img width="600" alt="Modelisation" src="https://github.com/user-attachments/assets/6560c1ce-9bff-428a-ad86-226d6c115960" />
7. Get your skillz out
<p><img width="46.4%" alt="ModelisationAdvanced" src="https://github.com/user-attachments/assets/4be28361-bf7e-4ec9-850d-a6c3701d8bac"> <img width="52.3%" alt="ImgRef" src="https://github.com/user-attachments/assets/751db2a8-8dd5-46d9-b9e4-d5a3a6e1df2b"></p>
8. Enjoy ;)






## Inputs
fSpy project file (`.fspy`), which holds both the calibration and the photo. 

## Contributing
Improvements are welcome. Start with [ARCHITECTURE.md](ARCHITECTURE.md), which explains how the single file is organized and where each step lives.  Version history: [CHANGELOG.md](CHANGELOG.md).

## License
GNU General Public License v3.0 or later: you can use, study, modify and share this code, and any distributed modified version must stay under the same license. See [LICENSE](LICENSE).
