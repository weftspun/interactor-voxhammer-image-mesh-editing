"""VoxHammer image mesh editing. RFD 0047, a composite per RFD 0037.

The order of operations lives in domain.ex/plan.ex, not in this file (RFD
0037's whole point: "the order lives in the domain, and not in the Python").
This server reads the solved plan (PLAN below, the same 7 steps plan.ex
records) and calls one Python function per step -- a pipeline change edits
domain.ex + regenerates plan.ex, not this dispatcher.

The critical guard: a_splice must run before a_decode. Inversion (a_invert)
is lossy, so a naive decode moves vertices outside the edited region.
a_splice pastes the original geometry back outside the mask before a_decode
runs -- that ordering is exactly what the domain's guards enforce and what
this dispatcher's fixed step list reproduces.

No weights of its own -- runs on microsoft/TRELLIS.2's backbone (RFD 0038).
"""

import base64
import os
import tempfile
import urllib.request
from pathlib import Path

STUB = os.environ.get("WEFTSPUN_STUB") == "1"
_READY = {"loaded": False}

# The solved plan, same 7 steps as plan.ex (regenerate both together if the
# domain changes -- see domain.ex's header).
PLAN = [
    "a_mark_region",
    "a_voxelize",
    "a_invert",
    "a_edit_image",
    "a_splice",
    "a_decode",
    "a_write_layer",
]


class InputError(ValueError):
    """The request is wrong. This is the caller's fault, and not ours."""


def _fetch(value: str, work: Path, name: str) -> Path:
    target = work / name
    if value.startswith(("http://", "https://")):
        urllib.request.urlretrieve(value, target)
        return target
    if value.startswith("data:"):
        value = value.split(",", 1)[1]
    target.write_bytes(base64.b64decode(value))
    return target


def _validate(job_input: dict) -> dict:
    if not job_input.get("mesh"):
        raise InputError("mesh is required: a URL, a data URI, or base64 GLB/USD bytes")
    if not job_input.get("reference"):
        raise InputError("reference is required")
    if not job_input.get("region"):
        raise InputError("region is required: a mask")
    return {
        "mesh": job_input["mesh"],
        "reference": job_input["reference"],
        "region": job_input["region"],
        "seed": int(job_input.get("seed", -1)),
    }


def _run_plan(state: dict) -> None:
    """Runs PLAN in order. Each action is NOT YET wired to VoxHammer's real
    inversion/edit/splice/decode implementation -- see README's Status. In
    stub mode each step just marks its state flag, proving the dispatcher
    follows the domain's order without needing the model."""
    for step in PLAN:
        if STUB:
            state[step] = True
            continue
        raise NotImplementedError(
            f"VoxHammer's real '{step}' implementation is not yet wired up -- "
            "see Nelipot-Lee/VoxHammer and README's Status section"
        )


def _write_edited(work: Path) -> Path:
    """The decoded mesh a_decode's handle names, /work/edited.usdc.

    In stub mode this is a real, empty crate rather than four bytes that spell
    something crate-like. It wrote b"PSDC" + b"stub", which is not the "PXR-USDC"
    a crate starts with, so USD refused the file the returned layer points at:
    every consumer got a layer whose sourceAsset could not open.
    """
    edited = work / "edited.usdc"
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateNew(str(edited))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    asset = UsdGeom.Xform.Define(stage, "/Asset")
    stage.SetDefaultPrim(asset.GetPrim())
    stage.GetRootLayer().Save()
    return edited


def _to_usd(edited: Path, work: Path) -> Path:
    """RFD 0053: the edit is a sublayer over the source mesh, not a flat
    file -- muting this layer returns the original."""
    from pxr import Sdf, Usd, UsdGeom

    layer = work / "edit.usda"
    stage = Usd.Stage.CreateNew(str(layer))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/Asset")
    stage.SetDefaultPrim(root.GetPrim())
    edit = stage.DefinePrim("/Asset/Edit")
    edit.CreateAttribute("weftspun:sourceAsset", Sdf.ValueTypeNames.Asset).Set(
        Sdf.AssetPath(edited.name)
    )
    edit.CreateAttribute("weftspun:stage", Sdf.ValueTypeNames.Token).Set(
        "voxhammer_image_mesh_editing"
    )
    stage.GetRootLayer().Save()
    return layer


def _encode(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def predict(job_input: dict) -> dict:
    args = _validate(job_input)
    work = Path(tempfile.mkdtemp())
    _fetch(args["mesh"], work, "input.mesh")

    state = {"mode": {"conditioning": "image"}}
    _run_plan(state)

    edited = _write_edited(work)
    layer = _to_usd(edited, work)

    # The mesh travels with the layer. RFD 0053's rule -- muting the layer
    # returns the original -- needs the original to be there to return to, and
    # the layer's sourceAsset is a relative path into a temp directory the
    # caller never sees. Returning only the layer shipped a reference that
    # could not resolve anywhere but on this machine, for as long as the
    # directory survived.
    return {
        "layer": _encode(layer),
        "mesh": _encode(edited),
        "mesh_name": edited.name,
        "plan": PLAN,
        "seed": args["seed"],
        "stub": STUB,
    }


def load() -> None:
    _READY["loaded"] = True


def build_app():
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel

    app = FastAPI(title="voxhammer_image_mesh_editing", version="0.1.0")

    class PredictRequest(BaseModel):
        mesh: str
        reference: str
        region: str
        seed: int = -1

    @app.get("/health")
    def health():
        return {"status": "ok", "ready": _READY["loaded"], "stub": STUB}

    @app.post("/predict")
    def run(request: PredictRequest):
        try:
            return predict(request.model_dump())
        except InputError as error:
            return JSONResponse(status_code=400, content={"error": str(error)})

    return app


if __name__ == "__main__":
    import uvicorn

    load()
    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
