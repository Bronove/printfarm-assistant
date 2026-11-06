# Third-Party Notices

## Gmsh 4.15.2

The standalone `step_converter.exe` component uses
[Gmsh](https://gmsh.info/), a three-dimensional finite element mesh generator.

- Copyright: Christophe Geuzaine and Jean-Francois Remacle
- License: GNU General Public License, version 2 or later
- License text: `third_party/GPL-2.0.txt`
- Source: https://gitlab.onelab.info/gmsh/gmsh
- Version-specific source:
  https://gitlab.onelab.info/gmsh/gmsh/-/tree/gmsh_4_15_2

Gmsh is distributed in a separate executable and is not linked into the
PrintFarm Assistant desktop process. The corresponding Gmsh source is available
from the links above. `step_converter.py` is licensed under GPL-2.0-or-later.

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

## Other dependencies

The installer also contains third-party Python, JavaScript, font, and runtime
components. Their license files are retained in the packaged application where
provided by the upstream projects. A complete dependency inventory is generated
as an SBOM for each public release.
