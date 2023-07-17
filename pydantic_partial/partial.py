"""
A partial model will set certain (or all) fields to be optional with a default value of
`None`. This means you can construct a model copy with a partial representation of the details
you would normally provide.

Partial models can be used to for example only send a reduced version of your internal
models as response data to the client when you combine partial models with actively
replacing certain fields with `None` values and usage of `exclude_none` (or
`response_model_exclude_none`).

Usage example:
```python
# Something can be used as a partial, too
class Something(PartialModelMixin, pydantic.BaseModel):
    name: str
    age: int


# Create a full partial model
FullSomethingPartial = Something.as_partial()
FullSomethingPartial(name=None, age=None)
# You could also create a "partial Partial":
#AgeSomethingPartial = Something.as_partial("age")
```
"""

import functools
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar, Union, get_args, get_origin

import pydantic

from ._compat import PydanticCompat

SelfT = TypeVar("SelfT", bound=pydantic.BaseModel)


@functools.lru_cache(maxsize=None, typed=True)
def create_partial_model(
    base_cls: Type[SelfT],
    *fields: str,
    recursive: bool = False,
) -> Type[SelfT]:
    # Convert one type to being partial - if possible
    def _partial_annotation_arg(field_name_: str, field_annotation: Type) -> Type:
        if (
                isinstance(field_annotation, type)
                and issubclass(field_annotation, PartialModelMixin)
        ):
            field_prefix = f"{field_name_}."
            children_fields = [
                field.removeprefix(field_prefix)
                for field
                in fields_
                if field.startswith(field_prefix)
            ]
            if children_fields == ["*"]:
                children_fields = []
            return field_annotation.as_partial(*children_fields, recursive=recursive)
        else:
            return field_annotation

    model_compat = PydanticCompat(base_cls)

    # By default make all fields optional, but use passed fields when possible
    if fields:
        fields_ = list(fields)
    else:
        fields_ = list(model_compat.model_fields.keys())

    # Construct list of optional new field overrides
    optional_fields: dict[str, Any] = {}
    for field_name, field_info in model_compat.model_fields.items():
        field_annotation = model_compat.get_model_field_info_annotation(field_info)
        if field_annotation is None:
            continue

        # Do we have any fields starting with $FIELD_NAME + "."?
        sub_fields_requested = any(
            field.startswith(f"{field_name}.")
            for field
            in fields_
        )

        # Continue if this field needs not to be handled
        if field_name not in fields_ and not sub_fields_requested:
            continue

        # Change type for sub models, if requested
        if recursive or sub_fields_requested:
            field_annotation_origin = get_origin(field_annotation)
            if field_annotation_origin in (Union, list, Tuple, tuple, List, dict, Dict):
                field_annotation = field_annotation_origin[
                    tuple(
                        _partial_annotation_arg(field_name, field_annotation_arg)
                        for field_annotation_arg
                        in get_args(field_annotation)
                    )
                ]
            else:
                field_annotation = _partial_annotation_arg(field_name, field_annotation)

        # Construct new field definition
        if field_name in fields_:
            if model_compat.is_model_field_info_required(field_info):
                optional_fields[field_name] = (
                    Optional[field_annotation],
                    model_compat.copy_model_field_info(
                        field_info,
                        default=None,  # Set default to None
                        defaul_factory=None,  # Remove default_factory if set
                        nullable=True,  # For API usage
                    ),
                )
        elif recursive or sub_fields_requested:
            optional_fields[field_name] = (
                field_annotation,
                model_compat.copy_model_field_info(field_info),
            )

    # Return original model class if nothing has changed
    if not optional_fields:
        return base_cls

    # Generate new subclass model with those optional fields
    return pydantic.create_model(
        f"{base_cls.__name__}Partial",
        __base__=base_cls,
        **optional_fields,
    )


class PartialModelMixin(pydantic.BaseModel):
    """
    Partial model mixin. Will allow usage of `as_partial()` on the model class
    to create a partial version of the model class.
    """

    @classmethod
    def as_partial(  # noqa: C901
        cls: Type[SelfT],
        *fields: str,
        recursive: bool = False,
    ) -> Type[SelfT]:
        return create_partial_model(cls, *fields, recursive=recursive)
