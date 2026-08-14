# SPDX-License-Identifier: MIT
#
# Edit one region of one mesh from a reference image.
#
# The domain is shared with RFD 0047. Only the conditioning changes,
# thus this file sets mode and nothing else. RFD 0048 records why one
# domain serves both variants.
defmodule VoxhammerImageEditOne do
  use Taskweft.DSL

  @name "voxhammer_image_edit_one"
  @source "voxhammer_mesh_editing"

  @variables %{
    handle: %{
      type: :ref,
      init: %{
        mesh: "/inputs/source.usdc",
        layer: ""
      }
    },
    # The one line that differs from RFD 0047. apply_edit checks this
    # and takes the image alternative.
    mode: %{
      type: :ref,
      init: %{conditioning: "image"}
    }
  }

  @todo_list [%{goal: [%{pointer: "/have/layer", eq: true}]}]
end
