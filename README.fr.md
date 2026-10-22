# Fspy_importer_CC

**Français** · [English](README.md)

Un script Python pour Rhino 8 qui importe un projet de calage de caméra [fSpy](https://fspy.io) (`.fspy`) dans Rhino. Il règle la caméra de la vue Front sur le calage de fSpy, à l'échelle réelle, pose la photo sur un plan texturé dont l'origine tombe exactement sur celle de fSpy, et met en place une disposition à 3 vues (Perspective, Top, Front). Il ouvre une petite fenêtre flottante : choisis le fichier `.fspy` et appuie sur **Run** ; après chaque modification enregistrée dans fSpy, le bouton **Sync** devient vert et la réapplique. Un seul Ctrl+Z annule le plan de la photo et la vue nommée, et le fichier `.fspy` n'est jamais modifié.

Version **2.14** · Licence : [GPL-3.0 ou ultérieure](LICENSE) · Visite du code : [ARCHITECTURE.md](ARCHITECTURE.md) (en anglais)

## Prérequis
Windows, Rhino 8 ou plus récent (Python 3 intégré). Aucun paquet supplémentaire.

## Installation
1. Télécharge `Fspy_importer_CC.py` et place-le dans le dossier de ton choix.
2. Dans Rhino, crée un bouton de barre d'outils avec cette macro (adapte le chemin) :
   ```
   ! _-RunPythonScript "C:\Outils\Fspy_importer_CC\Fspy_importer_CC.py"
   ```

## Entrées
Un fichier de projet fSpy (`.fspy`), qui contient à la fois le calage et la photo. Pour une taille juste dans Rhino, définis une distance de référence dans fSpy ; pour que la focale de fSpy corresponde directement à la lens length de Rhino, règle la Camera data de fSpy sur 35 mm film. Le plugin avertit dans les deux cas. La photo est écrite à côté du fichier `.fspy`.

## Contribuer
Les améliorations sont bienvenues. Commence par [ARCHITECTURE.md](ARCHITECTURE.md), qui explique comment le fichier unique est organisé et où se trouve chaque étape. Pour signaler un bogue, ouvre une « issue » et joins le fichier correspondant du dossier `logs` que le plugin crée à côté du script. Historique des versions : [CHANGELOG.md](CHANGELOG.md).

## Licence
GNU General Public License v3.0 ou ultérieure : tu peux utiliser, étudier, modifier et partager ce code, et toute version modifiée et distribuée doit rester sous la même licence. Voir [LICENSE](LICENSE).
