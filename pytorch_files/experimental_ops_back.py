# Copyright (c) Meta Platforms, Inc. and affiliates
from typing import List, Optional, Sequence, Tuple

import torch
from torch.distributed._tensor.op_schema import OpSchema, OutputSharding
from torch.distributed._tensor.ops.common_rules import pointwise_rule
from torch.distributed._tensor.ops.utils import register_prop_rule
import torch.distributed as dist

from torch.distributed._tensor.placement_types import (
    _Partial,
    DTensorSpec,
    Placement,
    Replicate,
    Shard,
)

aten = torch.ops.aten  # pyre-ignore


@register_prop_rule(  # pyre-ignore
    [
        aten._foreach_neg.default,
        aten._foreach_reciprocal.default,
        aten._foreach_sqrt.default,
    ]
)
def _prop__foreach_unaop(op_schema: OpSchema) -> OutputSharding:
    self = op_schema.args_schema[0]
    assert isinstance(self, list) and all([isinstance(s, DTensorSpec) for s in self])
    # FIXME(@mrshenli): for sqrt, this is only mathematically correct for
    # Replicate and Shard tensor.
    return OutputSharding(output_spec=self)


@register_prop_rule(
    [
        aten.nll_loss_forward.default,
    ]
)
def _nll_foward_rule(op_schema: OpSchema) -> OutputSharding:
    # global_device_mesh = get_global_device_mesh()
    _rank = dist.get_rank()
    args = op_schema.args_schema
    input_mesh = args[0].mesh
    in_placements = args[0].placements
    in_tensor_meta = args[0].tensor_meta
    target_dtensor = args[1]
    target_placements = target_dtensor.placements
    target_mesh = target_dtensor.mesh
    target_meta = target_dtensor.tensor_meta
    weights = args[2]
    reduction = args[3]
    ignore = args[4]

    """in_args=
    0 (DTensorSpec(mesh=DeviceMesh:([0, 1]), placements=[Replicate()], 
    tensor_meta=TensorMetadata(shape=torch.Size([32768, 65]), 
    dtype=torch.float32, requires_grad=False, stride=(65, 1), memory_format=torch.contiguous_format, 
    is_quantized=False, qparams={})), 
    1 DTensorSpec(mesh=DeviceMesh:([0, 1]), placements=[Shard(dim=0)], 
    tensor_meta=TensorMetadata(shape=torch.Size([32768]), dtype=torch.int64, requires_grad=False, stride=(1,), 
    memory_format=torch.contiguous_format, is_quantized=False, qparams={})), 
    None, 1, -100)
    """
    # in tensor = [32768, 65], stride = (65,1) placements = Replicate()
    # out tensor = 32768, stride = 1
    # None
    # 1
    # -100

    new_placements = [_Partial(0)]  # * global_device_mesh.ndim
    if _rank == 0:
        print(f"101 {input_mesh=}, {input_mesh.ndim=}")
        out_placements = op_schema.args_schema[1]
        print(f"103, {out_placements=}\n")
        in_args = op_schema.args_schema
        print(f"101 {in_args=}\n")
        print(f"102 global mesh dim {input_mesh.ndim=}\n")
        input = op_schema.args_schema[0]
        print(f"101 ops {input=}\n")

        print(f"103 ops, {new_placements=}")

    res = OutputSharding(
        output_spec=DTensorSpec(
            mesh=input_mesh,
            placements=new_placements,  # [Shard(0)] * global_device_mesh.ndim,
            # tensor_meta=input.tensor_meta,
        )
    )
    return res


"""def nll_forward_rule(op_schema: OpSchema) -> OutputSharding:
    def nll_loss_forward(
    self: Tensor,
    target: Tensor,
    weight: Optional[Tensor],
    reduction: int,
    ignore_index: int,
) -> Tuple[Tensor, Tensor]:
    assert self.dim() > 0 and self.dim() <= 2, "input tensor should be 1D or 2D"
    assert (
        target.dim() <= 1
    ), "0D or 1D target tensor expected, multi-target not supported"

    no_batch_dim = self.dim() == 1 and target.dim() == 0
    assert no_batch_dim or (
        self.shape[0] == target.shape[0]
    ), f"size mismatch (got input: {self.shape}, target: {target.shape})"

    n_classes = self.shape[-1]

    assert weight is None or (
        weight.dim() == 1 and weight.numel() == n_classes
    ), f"weight tensor should be defined either for all {n_classes} classes or no classes but got weight tensor of shape: {weight.shape}"  # noqa: B950

    # self can be [N, C] or [C]
    # target can be [N] or []

    n_dims = self.dim()
    channel_dim = 1
    if n_dims < 2:
        channel_dim = 0

    if weight is not None:
        w = weight.unsqueeze(0) if n_dims > 1 else weight
        self = self * w
    safe_target = torch.where(target != ignore_index, target, 0)
    safe_target_ = safe_target.unsqueeze(channel_dim)
    # target can be [N, 1] or [1]

    result = -torch.gather(self, channel_dim, safe_target_).squeeze(channel_dim)

    result = torch.where(target != ignore_index, result, 0)

    if reduction == Reduction.NONE.value and n_dims > 1:
        total_weight = self.new_full((), 0.0)
        return result, total_weight

    if weight is not None:
        w = weight.unsqueeze(0).expand(self.shape) if n_dims > 1 else weight
        wsum = torch.gather(w, channel_dim, safe_target_).squeeze(channel_dim)
        wsum = torch.where(target != ignore_index, wsum, 0)
        total_weight = wsum.sum()
    else:
        total_weight = (target != ignore_index).sum().to(self)

    if reduction == Reduction.SUM.value:
        result = result.sum()
    elif reduction == Reduction.MEAN.value:
        result = result.sum() / total_weight

    return result, total_weight
"""


@register_prop_rule(  # pyre-ignore
    [
        aten._foreach_add.List,
        aten._foreach_div.List,
        aten._foreach_mul.List,
    ]
)
def _prop__foreach_binop_list(op_schema: OpSchema) -> OutputSharding:
    self, other = op_schema.args_schema[:2]
    scalar = None if len(op_schema.args_schema) < 3 else op_schema.args_schema[2]
    assert isinstance(self, list) and all(
        [isinstance(s, DTensorSpec) for s in self]
    ), f"Expect a List[DTensorSpec] but got {self}"
    assert isinstance(other, list) and all(
        [isinstance(o, DTensorSpec) for o in other]
    ), f"Expect a List[DTensorSpec] but got {other}"
    assert len(self) == len(other), (
        "Two tensor lists must match in length, "
        f"but got {len(self)} and {len(other)}"
    )

    if any([s != o for s, o in zip(self, other)]):
        # If DTensorSpec for the two operand do not match, suggest using
        # self's DTensorSpec. This will trigger allreduce if other is partial
        # and self is replicated.
        return OutputSharding(
            output_spec=None,
            schema_suggestions=[
                OpSchema(
                    func_schema=op_schema.func_schema,
                    args_schema=(self, self, scalar) if scalar else (self, self),
                    kwargs_schema=op_schema.kwargs_schema,
                    is_inplace=op_schema.is_inplace,
                    is_out_variant=op_schema.is_out_variant,
                )
            ],
        )
    else:
        return OutputSharding(output_spec=self)


@register_prop_rule(  # pyre-ignore
    [
        aten._foreach_add.Scalar,
        aten._foreach_div.Scalar,
        aten._foreach_mul.Scalar,
        aten._foreach_sub.Scalar,
    ]
)
def _prop__foreach_binop_scalar(op_schema: OpSchema) -> OutputSharding:
    self, scalar = op_schema.args_schema
    assert isinstance(self, list) and all([isinstance(s, DTensorSpec) for s in self])
    assert not isinstance(scalar, list)
    return OutputSharding(output_spec=self)


@register_prop_rule(  # pyre-ignore
    [
        aten._foreach_addcdiv.Scalar,
        aten._foreach_addcmul.Scalar,
    ]
)
def _prop__foreach_addcop_scalar(op_schema: OpSchema):
    self, tensor1, tensor2 = op_schema.args_schema[:3]
    scalar = None if len(op_schema.args_schema) < 4 else op_schema.args_schema[3]
    assert isinstance(self, list) and all([isinstance(s, DTensorSpec) for s in self])
    assert isinstance(tensor1, list) and all([isinstance(s, DTensorSpec) for s in self])
    assert isinstance(tensor2, list) and all([isinstance(s, DTensorSpec) for s in self])
    if any([s != t1 or s != t2 for s, t1, t2 in zip(self, tensor1, tensor2)]):
        # If DTensorSpec for the two operand do not match, suggest using
        # self's DTensorSpec. This will trigger allreduce if other is partial
        # and self is replicated.
        return OutputSharding(
            output_spec=None,
            schema_suggestions=[
                OpSchema(
                    func_schema=op_schema.func_schema,
                    args_schema=(self, self, self, scalar)
                    if scalar
                    else (self, self, self),
                    kwargs_schema=op_schema.kwargs_schema,
                    is_inplace=op_schema.is_inplace,
                    is_out_variant=op_schema.is_out_variant,
                )
            ],
        )
    else:
        return OutputSharding(output_spec=self)


@register_prop_rule([aten._foreach_pow.ScalarAndTensor])  # pyre-ignore
def _prop__foreach_pow_scalar_and_tensor(op_schema: OpSchema):
    scala, exponent = op_schema.args_schema
    assert isinstance(exponent, list) and all(
        [isinstance(s, DTensorSpec) for s in exponent]
    )
    return OutputSharding(output_spec=exponent)


@register_prop_rule([aten._fused_adam.default])  # pyre-ignore
def _prop__fused_adam(op_schema: OpSchema):
    NT = 5
    tesnor_list_args: Tuple[List[DTensorSpec]] = op_schema.args_schema[:NT]  # type: ignore[assignment]

    assert all([isinstance(schema, list) for schema in tesnor_list_args])
    assert all(
        [isinstance(s, DTensorSpec) for schema in tesnor_list_args for s in schema]
    )

    tensor_schemas: Tuple[List[DTensorSpec]] = [  # type: ignore[assignment]
        schema for schema in tesnor_list_args if len(schema)
    ]

    assert all([len(s) == len(tensor_schemas[0]) for s in tensor_schemas]), (
        "expect the same number of gradients and states, but got "
        f"{[len(s) for s in tensor_schemas]}."
    )

    if any([any([t != ts[0] for t in ts]) for ts in zip(*tensor_schemas)]):
        new_schemas: Tuple[List[DTensorSpec]] = tuple(  # type: ignore[assignment]
            op_schema.args_schema[0] if len(s) else s for s in tesnor_list_args
        )
        return OutputSharding(
            output_spec=None,
            schema_suggestions=[
                OpSchema(
                    func_schema=op_schema.func_schema,
                    args_schema=new_schemas + op_schema.args_schema[NT:],
                    kwargs_schema=op_schema.kwargs_schema,
                    is_inplace=op_schema.is_inplace,
                    is_out_variant=op_schema.is_out_variant,
                )
            ],
        )
    else:
        return OutputSharding(output_spec=(op_schema.args_schema[0],) * NT)  # type: ignore[arg-type]


@register_prop_rule(aten.native_layer_norm.default)  # pyre-ignore
def _prop_native_layer_norm(op_schema: OpSchema) -> OutputSharding:
    input, normalized_shape, weight, bias, eps = op_schema.args_schema
    assert isinstance(input, DTensorSpec)
    assert isinstance(weight, DTensorSpec)
    if bias:
        assert isinstance(bias, DTensorSpec)
    assert isinstance(normalized_shape, (tuple, list))
    assert all(isinstance(p, Replicate) for p in weight.placements)
    if bias:
        assert all(isinstance(p, Replicate) for p in bias.placements)
    # only the left-most (non-normalized) dimensions of the input can be sharded
    batch_ndim = len(input.shape) - len(normalized_shape)
    assert all(
        isinstance(p, Replicate) or (isinstance(p, Shard) and p.dim < batch_ndim,)
        for p in input.placements
    )
    stats_spec = DTensorSpec(
        mesh=weight.mesh,
        placements=input.placements,
    )
    return OutputSharding(output_spec=(input, stats_spec, stats_spec))


@register_prop_rule(aten.native_layer_norm_backward.default)  # pyre-ignore
def _prop_native_layer_norm_backward(op_schema: OpSchema) -> OutputSharding:
    (
        grad,
        input,
        normalized_shape,
        result1,
        result2,
        weight,
        bias,
        grad_input_mask,
    ) = op_schema.args_schema
    assert isinstance(grad, DTensorSpec)
    assert isinstance(weight, DTensorSpec)
    if bias:
        assert isinstance(bias, DTensorSpec)
    assert isinstance(grad_input_mask, (list, tuple))
    assert all(isinstance(s, Replicate) for s in weight.placements)
    if bias:
        assert all(isinstance(s, Replicate) for s in bias.placements)
    # ensure sharding on dim 0, which will trigger the "Partial" output on weight and bias grads
    assert any(
        isinstance(s, Shard) and s.dim == 0 for s in grad.placements
    ), f"Got {grad.placements}"
    weight_grad = DTensorSpec(
        mesh=weight.mesh,
        placements=[_Partial()] * weight.mesh.ndim,
    )
    bias_grad = DTensorSpec(
        mesh=bias.mesh,
        placements=[_Partial()] * bias.mesh.ndim,
    )
    return OutputSharding(
        # NOTE: type errors below are legit. This is because DTensor currently
        # doesn't support Optional return values. Need to be fixed in DTensor repo.
        output_spec=(
            grad if grad_input_mask[0] else None,
            weight_grad if grad_input_mask[1] else None,
            bias_grad if grad_input_mask[2] else None,
        ),
    )


def _refine_sharding(
    op_schema: OpSchema, active_dim: Optional[int]
) -> Sequence[Placement]:
    """
    Considers 2 first inputs of op_schema as having same shape,
    and returns suggested placement for a pointwise operation.
    """
    # consider the operating dimension as a singleton to prevent sharding on it
    # however, if active_dim is None, this means the input and output shapes are equal and
    # we'll apply exactly the pointwise rule.
    from torch.fx.passes.shape_prop import TensorMetadata

    args_schema = []
    for s in op_schema.args_schema[:2]:
        assert isinstance(s, DTensorSpec) and s.tensor_meta is not None
        args_schema.append(
            DTensorSpec(
                mesh=s.mesh,  # type: ignore[attr-defined]
                placements=s.placements,  # type: ignore[attr-defined]
                tensor_meta=TensorMetadata(
                    shape=torch.Size(
                        s.shape[0:active_dim] + (1,) + s.shape[active_dim + 1 :]
                    )
                    if active_dim is not None
                    else s.shape,
                    dtype=s.tensor_meta.dtype,
                    requires_grad=s.tensor_meta.requires_grad,
                    stride=s.tensor_meta.stride,
                    memory_format=s.tensor_meta.memory_format,
                    is_quantized=s.tensor_meta.is_quantized,
                    qparams=s.tensor_meta.qparams,
                ),
            )
        )

    op_schema = OpSchema(
        func_schema=op_schema.func_schema,
        args_schema=args_schema,  # type: ignore[arg-type]
        kwargs_schema={},
        is_inplace=op_schema.is_inplace,
        is_out_variant=op_schema.is_out_variant,
    )
    output_sharding = pointwise_rule(op_schema, linearity=False)
    if output_sharding.output_spec:
        assert isinstance(output_sharding.output_spec, DTensorSpec)
        return output_sharding.output_spec.placements
    else:
        assert output_sharding.schema_suggestions is not None
        out_schema = output_sharding.schema_suggestions[0].args_schema[0]
        assert isinstance(out_schema, DTensorSpec)
        return tuple(out_schema.placements)


@register_prop_rule(aten.slice_scatter.default)  # pyre-ignore
def prop_slice_scatter(op_schema: OpSchema) -> OutputSharding:
    # 1. number of dimensions in input and src need to match.
    # 2. number of elements on all non-dim need to match between input and src.
    # 3. numer of elements in src in dim need to match the slice size.
    # Given the above:
    # - We suggest for src to follow the sharding of input, except on the scatter dimension,
    #   where our best bet for now is to make them replicated as a fall-back.
    #   TODO: Ideally we'd like to make sure the output is re-sharded afterwards to keep input sharding.

    defaults = (None, None, 0, None, None, 1)
    input, src, dim, start, end, step = (
        op_schema.args_schema + defaults[len(op_schema.args_schema) :]
    )
    assert isinstance(input, DTensorSpec)
    assert isinstance(src, DTensorSpec)
    assert isinstance(dim, int)

    if dim < 0:
        dim += input.ndim

    # if the input shape and the output shape are the same on the operating dimension,
    # this is effectively a no-op, so we just propagate sharding as we would do for
    # pointwise, no exceptions.
    if input.shape[dim] == src.shape[dim]:
        assert start == 0
        assert end >= src.shape[dim]  # type: ignore[operator]
        dim = None

    # apply sharding refinement as implemented in pointwise_rule
    input_suggestion = list(_refine_sharding(op_schema, dim))
    # apply the exception -- disallow sharding on the operating dimension.
    for i, p in enumerate(input_suggestion):
        if isinstance(p, Shard) and p.dim == dim:
            input_suggestion[i] = Replicate()
    input_suggestion = tuple(input_suggestion)  # type: ignore[assignment]

    if input_suggestion == tuple(input.placements) and src.placements == tuple(
        input.placements
    ):
        # if our sharding is correct, the output sharding will be the same as the input.
        return OutputSharding(
            output_spec=DTensorSpec(
                mesh=input.mesh,
                placements=input.placements,
            )
        )
    else:
        # otherwise, return the suggestion.
        return OutputSharding(
            output_spec=None,
            schema_suggestions=[
                OpSchema(
                    func_schema=op_schema.func_schema,
                    args_schema=(
                        DTensorSpec(
                            mesh=input.mesh,
                            placements=input_suggestion,
                            tensor_meta=input.tensor_meta,
                        ),
                        DTensorSpec(
                            mesh=src.mesh,
                            placements=input_suggestion,
                            tensor_meta=src.tensor_meta,
                        ),
                    )
                    + op_schema.args_schema[2:],
                    kwargs_schema=op_schema.kwargs_schema,
                )
            ],
        )