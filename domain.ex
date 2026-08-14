# SPDX-License-Identifier: MIT
#
# VoxHammer mesh editing, as a RECTGTN HTN domain.
# RFD 0047 records why this is a domain and not a script.
#
# The model carries no weights of its own. It runs on the TRELLIS.2
# backbone from RFD 0038.
#
# The guard that matters is preserved_outside. Inversion is lossy,
# thus a decode of an unedited latent does not return the input mesh
# exactly. a_splice pastes the original geometry back outside the
# mask, and a_decode refuses to run before it. No plan can therefore
# move a vertex the caller never selected.
defmodule VoxhammerMeshEditing do
  use Taskweft.DSL

  @name "voxhammer_mesh_editing"

  @variables %{
    have: %{
      type: :bool,
      init: %{
        mesh: true,
        region: false,
        voxels: false,
        latents: false,
        edited_latents: false,
        preserved_outside: false,
        edited_mesh: false,
        layer: false
      }
    },
    handle: %{
      type: :ref,
      init: %{
        mesh: "/inputs/source.usdc",
        region: "",
        voxels: "",
        latents: "",
        edited_latents: "",
        edited_mesh: "",
        layer: ""
      }
    },
    # RFD 0047 is text, and RFD 0048 is image. One domain serves both.
    mode: %{
      type: :ref,
      init: %{conditioning: "text"}
    }
  }

  @actions %{
    a_mark_region: %{
      params: [],
      body: [
        %{eval: %{type: "math/eq", a: %{pointer_get: "/have/mesh"}, b: true}},
        %{pointer_set: "/have/region", value: true},
        %{pointer_set: "/handle/region", value: "/work/region.json"}
      ]
    },
    a_voxelize: %{
      params: [],
      body: [
        %{eval: %{type: "math/eq", a: %{pointer_get: "/have/region"}, b: true}},
        %{pointer_set: "/have/voxels", value: true},
        %{pointer_set: "/handle/voxels", value: "/work/voxels.npz"}
      ]
    },
    # This step is lossy, and preserved_outside exists because of it.
    a_invert: %{
      params: [],
      body: [
        %{eval: %{type: "math/eq", a: %{pointer_get: "/have/voxels"}, b: true}},
        %{pointer_set: "/have/latents", value: true},
        %{pointer_set: "/handle/latents", value: "/work/latents.safetensors"}
      ]
    },
    a_edit_text: %{
      params: [],
      body: [
        %{eval: %{type: "math/eq", a: %{pointer_get: "/have/latents"}, b: true}},
        %{eval: %{type: "math/eq", a: %{pointer_get: "/mode/conditioning"}, b: "text"}},
        %{pointer_set: "/have/edited_latents", value: true},
        %{pointer_set: "/handle/edited_latents", value: "/work/edited.safetensors"}
      ]
    },
    a_edit_image: %{
      params: [],
      body: [
        %{eval: %{type: "math/eq", a: %{pointer_get: "/have/latents"}, b: true}},
        %{eval: %{type: "math/eq", a: %{pointer_get: "/mode/conditioning"}, b: "image"}},
        %{pointer_set: "/have/edited_latents", value: true},
        %{pointer_set: "/handle/edited_latents", value: "/work/edited.safetensors"}
      ]
    },
    # The step that makes the edit local.
    a_splice: %{
      params: [],
      body: [
        %{eval: %{type: "math/eq", a: %{pointer_get: "/have/edited_latents"}, b: true}},
        %{eval: %{type: "math/eq", a: %{pointer_get: "/have/region"}, b: true}},
        %{pointer_set: "/have/preserved_outside", value: true}
      ]
    },
    a_decode: %{
      params: [],
      body: [
        %{eval: %{type: "math/eq", a: %{pointer_get: "/have/preserved_outside"}, b: true}},
        %{pointer_set: "/have/edited_mesh", value: true},
        %{pointer_set: "/handle/edited_mesh", value: "/work/edited.usdc"}
      ]
    },
    # RFD 0053 gives the rule. A muted layer returns the original.
    a_write_layer: %{
      params: [],
      body: [
        %{eval: %{type: "math/eq", a: %{pointer_get: "/have/edited_mesh"}, b: true}},
        %{pointer_set: "/have/layer", value: true},
        %{pointer_set: "/handle/layer", value: "/outputs/edit.usda"}
      ]
    }
  }

  @methods %{
    prepare: %{
      params: [],
      alternatives: [
        %{name: :standard, subtasks: [["a_mark_region"], ["a_voxelize"], ["a_invert"]]}
      ]
    },
    # One alternative per conditioning. The mode variable decides
    # which one the planner may take.
    apply_edit: %{
      params: [],
      alternatives: [
        %{
          name: :text,
          check: [%{eval: %{type: "math/eq", a: %{pointer_get: "/mode/conditioning"}, b: "text"}}],
          subtasks: [["a_edit_text"]]
        },
        %{
          name: :image,
          check: [
            %{eval: %{type: "math/eq", a: %{pointer_get: "/mode/conditioning"}, b: "image"}}
          ],
          subtasks: [["a_edit_image"]]
        }
      ]
    },
    edit: %{
      params: [],
      alternatives: [
        %{
          name: :standard,
          subtasks: [
            ["prepare"],
            ["apply_edit"],
            ["a_splice"],
            ["a_decode"],
            ["a_write_layer"]
          ]
        }
      ]
    },
    have: %{
      params: [:artifact, :desired],
      alternatives: [
        %{
          name: :produce_layer,
          check: [%{eval: %{type: "math/eq", a: "{artifact}", b: "layer"}}],
          subtasks: [["edit"]]
        }
      ]
    }
  }

  @todo_list [["edit"]]
end
