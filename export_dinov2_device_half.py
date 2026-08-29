"""Export VoxHammer's DINOv2 stage at a fixed shape and census its operators.

RFD 1167 rung 1 for this model, and rung 2 if the census is clean. The cut is at
the patch tokens: everything after them is `grid_sample` and a scatter, which
RFD 1131 refuses. `DEVICE_OPS` is read through the manifest link rather than
copied, so the allowlist has one home.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import os
import sys
import tempfile

RESOLUTION = 518
PATCH = 14
EMBED = 1024
#: Relative: `x_prenorm` reaches 124, so an absolute bound measures the wrong thing.
REL_TOL = 1e-4

#: Upstream's constants, recorded here but not exported: `compile_hef.py` folds
#: normalization into the input layer, and a second copy would double-apply it.
MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]

_HERE = os.path.dirname(os.path.abspath(__file__))
LINKED_GATE = os.path.join(_HERE, "..", "..", "hailo_device_ops.py")
SIBLING_GATE = os.path.join(_HERE, "..", "rf-detr-cpp", "scripts", "gate_onnx_device.py")


def default_gate():
    """The manifest link if `repo sync` wrote it, else the sibling checkout."""
    return LINKED_GATE if os.path.exists(LINKED_GATE) else SIBLING_GATE


def load_device_ops(path):
    if not os.path.exists(path):
        sys.exit("FAIL  no allowlist at %s; `repo sync` writes the link, or pass --gate" % path)
    spec = importlib.util.spec_from_file_location("rfdetr_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return set(mod.DEVICE_OPS), dict(mod.KNOWN_BLOCKERS)


class DeviceHalf:
    """Wraps the hub model so the export is a tensor in and a tensor out."""

    def __new__(cls, dinov2):
        import torch

        n_patch = RESOLUTION // PATCH
        skip = dinov2.num_register_tokens + 1

        class _M(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.dinov2 = dinov2

            def forward(self, x):
                f = self.dinov2(x, is_training=True)
                t = f["x_prenorm"][:, skip:]
                return t.permute(0, 2, 1).reshape(x.shape[0], EMBED, n_patch, n_patch)

        return _M()


def census(model_path):
    import onnx

    g = onnx.load(model_path).graph
    counts = collections.Counter(n.op_type for n in g.node)
    return len(g.node), counts


def self_test(gate):
    """A census that has never refused an operator has not shown it can refuse one."""
    device_ops, blockers = load_device_ops(gate)
    planted = "GridSample"
    if planted in device_ops:
        sys.exit("FAIL  %s is inside the allowlist; the control cannot plant it" % planted)
    if planted not in blockers:
        sys.exit("FAIL  %s is not a named blocker, so the reason line would be empty" % planted)
    counts = collections.Counter({"Conv": 2, planted: 1})
    outside = {op: c for op, c in counts.items() if op not in device_ops}
    if outside != {planted: 1}:
        sys.exit("FAIL  the census passed a graph carrying %s" % planted)
    print("self-test: a %s in the census is refused, and named -- %s"
          % (planted, blockers[planted]))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(),
                                              "dinov2_vitl14_reg_518.onnx"))
    ap.add_argument("--gate", default=default_gate())
    ap.add_argument("--model", default="dinov2_vitl14_reg")
    ap.add_argument("--opset", type=int, default=17)
    ap.add_argument("--self-test", action="store_true",
                    help="assert the census rejects a graph carrying a refused operator")
    a = ap.parse_args()

    if a.self_test:
        return self_test(a.gate)

    import numpy as np
    import torch

    device_ops, blockers = load_device_ops(a.gate)

    print("loading %s from torch.hub..." % a.model)
    # `is_training=True` is upstream's own call: it returns the prenorm tokens.
    hub = torch.hub.load("facebookresearch/dinov2", a.model, pretrained=True)
    hub.eval()
    net = DeviceHalf(hub).eval()

    x = torch.randn(1, 3, RESOLUTION, RESOLUTION)
    with torch.no_grad():
        want = net(x)
    n_patch = RESOLUTION // PATCH
    if tuple(want.shape) != (1, EMBED, n_patch, n_patch):
        sys.exit("FAIL  device half emits %s, expected %s" % (
            tuple(want.shape), (1, EMBED, n_patch, n_patch)))

    torch.onnx.export(net, (x,), a.out, opset_version=a.opset,
                      input_names=["image"], output_names=["patch_tokens"],
                      dynamo=False)

    import onnxruntime as ort
    sess = ort.InferenceSession(a.out, providers=["CPUExecutionProvider"])
    got = sess.run(None, {"image": x.numpy()})[0]
    ref = want.numpy()
    diff = float(np.abs(got - ref).max())
    scale = float(np.abs(ref).max())
    rel = diff / scale

    n, counts = census(a.out)
    outside = {op: c for op, c in counts.items() if op not in device_ops}

    print("  %s: %d nodes, %d operators" % (a.model, n, len(counts)))
    print("  max|diff| %.3e over max|ref| %.3f = %.3e relative" % (diff, scale, rel))
    for op, c in sorted(outside.items()):
        print("  outside DEVICE_OPS: %s x%d -- %s"
              % (op, c, blockers.get(op, "not measured; the DFC decides")))

    problems = []
    if rel > REL_TOL:
        problems.append("onnxruntime disagrees with torch by %.3e relative, over %.0e"
                        % (rel, REL_TOL))
    if outside:
        problems.append("%d operator(s) outside the allowlist" % len(outside))

    if problems:
        print("\nFAIL (%d):" % len(problems))
        for p in problems:
            print("  %s" % p)
        return 1
    print("\nPASS: exports at a fixed shape, runs, and every operator is inside DEVICE_OPS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
