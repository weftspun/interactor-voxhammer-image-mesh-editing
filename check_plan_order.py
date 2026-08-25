"""Gate: the dispatcher's step list satisfies the domain's own guards, and the
payload it returns opens.

WHY THIS EXISTS. `server.py`'s docstring states the thing that matters: "a_splice must
run before a_decode. Inversion is lossy, so a naive decode moves vertices outside the
edited region." It then says the dispatcher's fixed step list reproduces that ordering.
Nothing checked it. `PLAN` is a Python list a hand can reorder, and the consequence of
reordering it is not a crash -- it is a mesh with vertices moved where the caller never
selected, which looks like a model that is slightly worse rather than like a bug.

The ordering is not restated here. `domain.ex` already carries it as preconditions:
`a_decode` evaluates `/have/preserved_outside`, and only `a_splice` sets that pointer.
So this gate reads the domain, executes `PLAN` against it, and requires every guard to
hold when its step runs. Restating "splice before decode" in Python would have been a
third place for one rule to live, and the third place is the one that goes stale.

WHAT IT CHECKS, and why each is separate.

1. THE TWO PLANS AGREE. `server.py`'s `PLAN` equals `plan.ex`'s `@plan`. The header says
   "the same 7 steps plan.ex records", and a generated file and a hand-written one drift.

2. EVERY STEP EXISTS. Each step is an action `domain.ex` declares. A typo composes as a
   step that does nothing and reports success.

3. THE GUARDS HOLD. Executing `PLAN` from the problem's initial state, every `eval` in
   an action's body is true when that action runs. This is where a swapped splice and
   decode fails, and it fails naming the pointer rather than the rule.

4. THE GOAL IS REACHED. `/have/layer` is true at the end. A plan can satisfy every guard
   it happens to run and still not finish the job.

5. THE HANDLES ARE THE FILES. The paths the domain sets -- `/work/edited.usdc`,
   `/outputs/edit.usda` -- name files `server.py` actually writes. The domain saying
   `edited.usdc` while the server writes `edited.usd` is drift no test of either alone
   can see.

6. THE PAYLOAD OPENS. The stub's returned layer parses, its `weftspun:sourceAsset`
   resolves next to it, and the file it resolves to is a USD layer USD will open.

   THIS ONE IS WHY THE GATE WAS WRITTEN. The stub wrote `b"PSDC" + b"stub"` as
   `edited.usdc`. A crate begins `PXR-USDC`, so USD rejected the file with "File too
   small to contain bootstrap structure", and every consumer received a layer pointing
   at something it could not open. The response was a 200 with a plausible-looking
   `layer` field, which is the shape of defect this repository keeps meeting: the check
   that would have caught it did not exist, and the thing it produced looked fine.

   The layer was also unresolvable for a second reason, fixed with the first: only the
   layer came back, and its `sourceAsset` is a relative path into a server-side temp
   directory. `predict` now returns the mesh beside the layer.

WHAT IT DOES NOT CHECK. Whether VoxHammer's real steps do what their names say -- none
of them are wired, and `_run_plan` raises `NotImplementedError` outside stub mode. This
gate is about the order they run in and the payload that comes back, both of which are
real today.

    python check_plan_order.py [--self-test]

Exit code is non-zero on any failure, and on any negative control that fails to fail.
"""

import base64
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent

ACTION_RE = re.compile(r"^    (a_\w+): %\{(.*?)^    \},?$", re.S | re.M)
EVAL_RE = re.compile(
    r'eval: %\{type: "math/eq", a: %\{pointer_get: "([^"]+)"\}, b: ([^}]+)\}'
)
SET_RE = re.compile(r'pointer_set: "([^"]+)", value: ("[^"]*"|true|false)')
INIT_BLOCK_RE = re.compile(r"(\w+): %\{\s*type: :(\w+),\s*init: %\{(.*?)\}", re.S)
INIT_PAIR_RE = re.compile(r"(\w+): (\"[^\"]*\"|true|false)")
PLAN_PY_RE = re.compile(r"^PLAN = \[(.*?)^\]", re.S | re.M)
PLAN_EX_RE = re.compile(r"@plan \[(.*?)\n  \]", re.S)
QUOTED_RE = re.compile(r'"([^"]+)"')


def literal(text):
    text = text.strip()
    if text == "true":
        return True
    if text == "false":
        return False
    return text.strip('"')


def actions(domain_text):
    """{action name: (preconditions, effects)} straight out of domain.ex."""
    out = {}
    for name, body in ACTION_RE.findall(domain_text):
        pre = [(p, literal(b)) for p, b in EVAL_RE.findall(body)]
        post = [(p, literal(v)) for p, v in SET_RE.findall(body)]
        out[name] = (pre, post)
    return out


def initial_state(domain_text, problem_text):
    """The domain's initial pointers, with the problem's overrides on top.

    The problem sets `mode.conditioning` to "image" and the domain's own init says
    "text", so reading only the domain would fail `a_edit_image`'s second guard and
    report the shipped plan as broken.
    """
    state = {}
    for text in (domain_text, problem_text):
        for group, _type, block in INIT_BLOCK_RE.findall(text):
            for key, value in INIT_PAIR_RE.findall(block):
                state[f"/{group}/{key}"] = literal(value)
    return state


def server_plan(server_text):
    match = PLAN_PY_RE.search(server_text)
    return QUOTED_RE.findall(match.group(1)) if match else []


def plan_ex_plan(plan_text):
    match = PLAN_EX_RE.search(plan_text)
    return QUOTED_RE.findall(match.group(1)) if match else []


def check_plans_agree(plan, generated, problems):
    if not plan:
        problems.append("server.py declares no PLAN, so there is nothing to check")
    if not generated:
        problems.append("plan.ex declares no @plan, so there is nothing to check against")
    if plan and generated and plan != generated:
        problems.append(
            f"server.py's PLAN is {plan} and plan.ex's @plan is {generated}"
        )


def check_guards(plan, domain, state, problems):
    """Execute the plan, and require each action's own preconditions to hold.

    Returns the final state and the pointers the plan itself set. The second is not the
    first: `/handle/mesh` is `/inputs/source.usdc` before any step runs, and reading the
    final state as output made this gate demand that `server.py` write the file it reads.
    """
    state = dict(state)
    written = set()
    for index, step in enumerate(plan):
        if step not in domain:
            problems.append(f"step {index + 1} is {step!r}, which domain.ex does not declare")
            continue
        pre, post = domain[step]
        for pointer, expected in pre:
            actual = state.get(pointer)
            if actual != expected:
                problems.append(
                    f"step {index + 1} {step} needs {pointer} == {expected!r} "
                    f"and it is {actual!r}"
                )
        for pointer, value in post:
            state[pointer] = value
            written.add(pointer)
    return state, written


def check_goal(final, problems, goal="/have/layer"):
    if final.get(goal) is not True:
        problems.append(f"the plan ends with {goal} == {final.get(goal)!r}, and the goal is True")


def check_handles(final, written, server_text, problems):
    """Every file the plan's own steps name in a handle is a file server.py writes."""
    for pointer in sorted(written):
        value = final.get(pointer)
        if not pointer.startswith("/handle/") or not isinstance(value, str) or not value:
            continue
        name = value.rsplit("/", 1)[-1]
        # USD extensions only. The domain's other handles -- region.json, voxels.npz,
        # latents.safetensors -- belong to steps VoxHammer has not wired, so requiring
        # server.py to write them would gate work nobody has done. `.usdz` is in the list
        # because leaving it out let a control through: the negative control renamed the
        # handle to `edited.usdz`, the filter skipped it, and the gate reported a pass.
        if not name.endswith((".usd", ".usda", ".usdc", ".usdz")):
            continue
        if name not in server_text:
            problems.append(f"the domain sets {pointer} to {value} and server.py never writes {name}")


def check_payload(payload, problems):
    """The returned layer opens, and its sourceAsset resolves to a layer that opens."""
    from pxr import Usd

    if "layer" not in payload:
        problems.append("the payload carries no layer")
        return
    work = pathlib.Path(tempfile.mkdtemp())
    layer_path = work / "edit.usda"
    layer_path.write_bytes(base64.b64decode(payload["layer"]))
    if "mesh" in payload:
        (work / payload.get("mesh_name", "edited.usdc")).write_bytes(
            base64.b64decode(payload["mesh"])
        )
    stage = Usd.Stage.Open(str(layer_path))
    if stage is None:
        problems.append("the returned layer does not open")
        return
    prim = stage.GetPrimAtPath("/Asset/Edit")
    if not prim:
        problems.append("the returned layer has no /Asset/Edit prim")
        return
    asset = prim.GetAttribute("weftspun:sourceAsset").Get()
    if asset is None:
        problems.append("the returned layer names no sourceAsset")
        return
    resolved = asset.resolvedPath
    if not resolved:
        problems.append(
            f"the layer's sourceAsset {asset.path} resolves to nothing beside the layer"
        )
        return
    # Opened rather than sniffed for magic bytes: "does USD take it" is the question,
    # and a byte comparison is the convenient proxy for it.
    try:
        opened = Usd.Stage.Open(resolved)
    except Exception as error:  # noqa: BLE001 -- USD raises its own exception type
        problems.append(f"the sourceAsset {asset.path} does not open: {str(error).strip()[:80]}")
        return
    if opened is None:
        problems.append(f"the sourceAsset {asset.path} does not open")


def stub_payload():
    """Run the server's own predict in stub mode."""
    import os

    os.environ["WEFTSPUN_STUB"] = "1"
    sys.path.insert(0, str(HERE))
    for stale in ("server",):
        sys.modules.pop(stale, None)
    import server

    blob = base64.b64encode(b"a mesh stands in for a mesh").decode()
    return server.predict({"mesh": blob, "reference": blob, "region": blob, "seed": 7})


def check(plan=None, domain_text=None, problem_text=None, plan_text=None,
          server_text=None, payload=None):
    problems = []
    domain_text = domain_text if domain_text is not None else (HERE / "domain.ex").read_text(encoding="utf-8")
    problem_text = problem_text if problem_text is not None else (HERE / "problem.ex").read_text(encoding="utf-8")
    plan_text = plan_text if plan_text is not None else (HERE / "plan.ex").read_text(encoding="utf-8")
    server_text = server_text if server_text is not None else (HERE / "server.py").read_text(encoding="utf-8")
    plan = plan if plan is not None else server_plan(server_text)

    check_plans_agree(plan, plan_ex_plan(plan_text), problems)
    domain = actions(domain_text)
    if not domain:
        problems.append("domain.ex declares no actions, so no guard can be checked")
        return problems
    final, written = check_guards(
        plan, domain, initial_state(domain_text, problem_text), problems
    )
    check_goal(final, problems)
    check_handles(final, written, server_text, problems)
    if payload is not None:
        check_payload(payload, problems)
    return problems


PSDC_LAYER = """#usda 1.0
(
    defaultPrim = "Asset"
    upAxis = "Y"
)

def Xform "Asset"
{
    def "Edit"
    {
        custom asset weftspun:sourceAsset = @edited.usdc@
    }
}
"""


def fabricated_payload(mesh_bytes=b"PSDC" + b"stub", include_mesh=True):
    """The payload as it was before this gate: four bytes that spell nothing USD reads."""
    payload = {"layer": base64.b64encode(PSDC_LAYER.encode()).decode()}
    if include_mesh:
        payload["mesh"] = base64.b64encode(mesh_bytes).decode()
        payload["mesh_name"] = "edited.usdc"
    return payload


def as_plan_ex(plan):
    """A plan.ex whose @plan is this list, so a control isolates one failure.

    Mutating `PLAN` alone fails check 1 first, and a control that is rejected by a check
    other than the one it names proves nothing about that check. The first version of this
    self-test did exactly that: every plan mutation was reported as "server.py's PLAN is
    ... and plan.ex's @plan is ...", so the guard simulation had no control at all.
    """
    steps = ",\n    ".join(f'["{step}"]' for step in plan)
    return "defmodule X do\n  @plan [\n    " + steps + "\n  ]\nend\n"


def self_test():
    domain_text = (HERE / "domain.ex").read_text(encoding="utf-8")
    server_text = (HERE / "server.py").read_text(encoding="utf-8")
    shipped = server_plan(server_text)

    swapped = list(shipped)
    i, j = swapped.index("a_splice"), swapped.index("a_decode")
    swapped[i], swapped[j] = swapped[j], swapped[i]

    dropped = [step for step in shipped if step != "a_splice"]
    renamed = ["a_mark_regionn" if s == "a_mark_region" else s for s in shipped]
    truncated = shipped[:-1]

    def mutate(plan):
        return {"plan": plan, "plan_text": as_plan_ex(plan)}

    cases = [
        ("the shipped plan passes", {}, None),
        ("splice and decode swapped", mutate(swapped),
         "a_decode needs /have/preserved_outside == True"),
        ("splice dropped altogether", mutate(dropped),
         "a_decode needs /have/preserved_outside == True"),
        ("a step the domain does not declare", mutate(renamed),
         "which domain.ex does not declare"),
        ("a plan that never reaches the goal", mutate(truncated),
         "the plan ends with /have/layer"),
        ("server.py and plan.ex disagreeing", {"plan": shipped[:-1]},
         "and plan.ex's @plan is"),
        ("a handle naming a file the server never writes",
         {"domain_text": domain_text.replace("/work/edited.usdc", "/work/edited.usdz")},
         "server.py never writes edited.usdz"),
        ("the payload the stub used to return", {"payload": fabricated_payload()},
         "does not open"),
        ("a payload with no mesh beside the layer",
         {"payload": fabricated_payload(include_mesh=False)},
         "resolves to nothing beside the layer"),
    ]

    ok = True
    print("self-test: each known-bad input must be rejected, and for its own reason")
    for label, kw, expected in cases:
        found = check(**kw)
        if expected is None:
            good = not found
            why = found[0][:66] if found else ""
        else:
            good = any(expected in problem for problem in found)
            why = (found[0][:66] if found else "accepted")
        ok = ok and good
        print(f"  {'ok ' if good else 'BAD'} {label}: {why}")
    return 0 if ok else 1


def main(argv):
    if "--self-test" in argv:
        return self_test()
    found = check(payload=stub_payload())
    for line in found:
        print(line)
    print(f"{len(found)} problems")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
