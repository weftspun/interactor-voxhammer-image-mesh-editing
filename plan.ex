# SPDX-License-Identifier: MIT
#
# GENERATED. Do not edit by hand.
#
# Solved from the RFD 0047 domain, with problem.ex here supplying
# mode.conditioning of "image".
#
#   mcp__taskweft__plan(
#     domain_dsl: File.read!("../0047-voxhammer-text-mesh-editing/domain.ex"),
#     format: "dsl"
#   )
defmodule VoxhammerImageMeshEditingPlan do
  @source "voxhammer_mesh_editing"
  @solved_by "taskweft v0.5.3"
  @temporally_consistent true

  # 7 steps, and one differs from RFD 0047. apply_edit took its :image
  # alternative here. That is the evidence for the RFD 0048 claim that
  # one domain serves both variants.
  @plan [
    ["a_mark_region"],
    ["a_voxelize"],
    ["a_invert"],
    ["a_edit_image"],
    ["a_splice"],
    ["a_decode"],
    ["a_write_layer"]
  ]

  def plan, do: @plan
  def source, do: @source
end
