# interactor-voxhammer-image-mesh-editing

Model image for `voxhammer_image_mesh_editing`, per
[weftspun's RFD 0036](https://github.com/weftspun/request-for-discussion/tree/main/0036-packaging-convention)

- [RFD 0037](https://github.com/weftspun/request-for-discussion/tree/main/0037-composite-models-as-taskweft-domains)
  (composite models as taskweft domains). Facts from
  [RFD 0048](https://github.com/weftspun/request-for-discussion/tree/main/0048-voxhammer-image-mesh-editing).

## This shares RFD 0047's domain

RFD 0048's own folder holds `problem.ex` and `plan.ex` only — no `domain.ex` of its own. Per
RFD 0048: this is the same VoxHammer HTN domain as
[`voxhammer_text_mesh_editing`](https://github.com/weftspun/interactor-voxhammer-text-mesh-editing)
(RFD 0047); `domain.ex` here is copied verbatim from that repo. The only real difference is
`problem.ex`'s `mode`: `%{type: :ref, init: %{conditioning: "image"}}` instead of `"text"` — this
variant conditions the edit on a reference image instead of a text instruction. `plan.ex`'s 7
steps are the same shape with `a_edit_image` standing in for `a_edit_text`.

**The guard that matters** (same as RFD 0047): `a_splice` must run before `a_decode`. Inversion
(`a_invert`) is lossy — a decode of an unedited latent doesn't return the input mesh exactly, so
a naive implementation moves vertices the caller never selected. `a_splice` pastes the original
geometry back outside the mask first. The domain states this as a hard guard
(`a_decode requires /have/preserved_outside`); this dispatcher's fixed step order reproduces it.

## Model

| Property   | Value                                                                                                                                                          |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Upstream   | [Nelipot-Lee/VoxHammer](https://github.com/Nelipot-Lee/VoxHammer) (3DV 2026 Oral), on [microsoft/TRELLIS.2](https://github.com/microsoft/TRELLIS.2)'s backbone |
| License    | MIT — independently checked, matches RFD 0047/0048 (VoxHammer's own code; TRELLIS.2's code it depends on carries its own MIT license too)                      |
| Parameters | 0 — shares [`interactor-trellis2-image-to-textured-mesh`](https://github.com/weftspun/interactor-trellis2-image-to-textured-mesh)'s weights                    |
| bf16       | 8.0 GB, the RFD 0038 cost                                                                                                                                      |

## Interface

`POST /predict`:

| Input       | Type            | Default  | Note                                                                      |
| ----------- | --------------- | -------- | ------------------------------------------------------------------------- |
| `mesh`      | Path/URL/base64 | required |                                                                           |
| `reference` | Path/URL/base64 | required | An image — conditions the edit, replacing RFD 0047's `instruction` string |
| `region`    | Path/URL/base64 | required | A mask — see `decisions/api/api.md`'s supported mask list                 |
| `seed`      | int             | -1       |                                                                           |

Returns `{layer, plan, seed, stub}` — `layer` is the edit sublayer (RFD 0053: muting it returns
the original mesh unchanged), `plan` is the step list actually executed, included so a caller
can confirm the guard order held.

## Build

Builds `FROM` `weftspun/trellis2-base`'s worker stage — build that image first.

```sh
docker build --target contract -t interactor-voxhammer-image-mesh-editing:contract .
docker run --rm -p 8000:8000 interactor-voxhammer-image-mesh-editing:contract
curl -X POST localhost:8000/predict -d @test_input.json -H 'Content-Type: application/json'
```

## Status

**Scaffolded from the RFD, not yet built or run.** The domain/plan/problem `.ex` files are real
(`domain.ex` ported verbatim from RFD 0047, `problem.ex`/`plan.ex` fetched from RFD 0048's own
GitHub folder). `server.py`'s dispatcher runs the plan's step order correctly in stub mode
(proving the sequencing), but each individual step's call into VoxHammer's real Python API is
**not yet wired up** — `_run_plan` raises `NotImplementedError` outside stub mode. Confirm
VoxHammer's actual inversion/edit/splice/decode functions (and how it accepts an image reference
instead of a text instruction) against the upstream repo before trusting the worker stage.
