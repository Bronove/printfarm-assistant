# Third-Party Notices

## Gmsh

The standalone `step_converter.exe` uses Gmsh 4.15.2 to convert STEP/STP files
to STL.

- Copyright: Christophe Geuzaine and Jean-Francois Remacle
- License: GNU General Public License, version 2 or later
- License text: [third_party/GPL-2.0.txt](third_party/GPL-2.0.txt)
- Project: https://gmsh.info/
- Source: https://gitlab.onelab.info/gmsh/gmsh
- Version source:
  https://gitlab.onelab.info/gmsh/gmsh/-/tree/gmsh_4_15_2

Gmsh runs in a separate process and is not linked into the PrintFarm Assistant
desktop process. The converter wrapper is also GPL-2.0-or-later.

## Protected multicolor component

`protected_core.exe` is compiled with Nuitka and includes CPython plus
open-source numerical and geometry libraries:

- Python, PSF-2.0
- Nuitka, Apache-2.0
- NumPy, BSD-3-Clause
- SciPy, BSD-3-Clause
- trimesh, MIT
- Pillow, HPND

The multicolor planning implementation itself is proprietary and is not
covered by those upstream licenses.

## Other components

The application and installer include open-source Python, JavaScript, font,
and Windows runtime components. Upstream license files are retained in the
installed application where supplied. Each public release includes an SBOM and
checksum inventory.

Bambu Studio is not distributed by this project.
