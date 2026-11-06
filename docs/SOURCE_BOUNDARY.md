# Source Boundary

PrintFarm Assistant uses an open-core distribution model.

## Public source

The MIT-licensed `app/` tree includes:

- the React desktop workspace;
- the local HTTP bridge and task manager;
- model import, OCR, parameter parsing and log handling;
- Bambu Studio CLI slicing and ordinary packing/orientation orchestration;
- the standalone GPL STEP converter wrapper.

The public backend core is generated from the reviewed headless subset of the
legacy desktop module. The public UI exposes workbench, multicolor and batch
workspaces. Multi-color planning/validation, figurine mode, floating assistant,
closed optimizer implementations and Bambu desktop automation source are not
part of this tree.

## Closed components

The official installer may contain separately compiled components for:

- multi-color planning and Bambu support-validation;
- minimum-support direction optimization;
- tight-packing optimization;
- Bambu desktop automation.

The public application invokes `protected_core.exe` through a versioned JSON
protocol. It verifies the component's SHA-256 before planning and refuses a
missing, modified or incompatible component. Those components are not covered
by the MIT License. The official free installer remains usable by individuals
and print farms under the terms in `NOTICE.md`.

## Distribution rule

Do not copy ignored directories, local models, logs, user data, API keys,
tokens, `dist/`, `dist_v2/`, `node_modules/`, build work directories or local
installer outputs into a public commit.
