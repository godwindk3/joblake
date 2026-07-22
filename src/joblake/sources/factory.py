from importlib import import_module

from joblake.sources.base import JobSource


DEFAULT_ADAPTERS = {
    "itviec": "joblake.sources.itviec.ITviecSource",
    "topcv": "joblake.sources.topcv.TopCVSource",
}


def create_source(config: dict) -> JobSource:
    source_name = config["source"]
    adapter_path = config.get(
        "source_adapter",
        DEFAULT_ADAPTERS.get(source_name),
    )

    if not adapter_path:
        raise ValueError(
            f"No source_adapter configured for {source_name}"
        )

    try:
        module_name, class_name = adapter_path.rsplit(
            ".",
            maxsplit=1,
        )
    except ValueError as exc:
        raise ValueError(
            "source_adapter must be a dotted class path, "
            f"got: {adapter_path}"
        ) from exc

    try:
        module = import_module(module_name)
        adapter_class = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            f"Cannot load source_adapter {adapter_path}"
        ) from exc

    if (
        not isinstance(adapter_class, type)
        or not issubclass(adapter_class, JobSource)
    ):
        raise TypeError(
            f"{adapter_path} must inherit JobSource"
        )

    return adapter_class(config)
