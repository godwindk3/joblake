import importlib

from joblake.parsing.base import JobParser


_DEFAULT_PARSERS = {
    "itviec": "joblake.parsing.parsers.itviec.ITviecParser",
    "topcv": "joblake.parsing.parsers.topcv.TopCVParser",
    "topdev": "joblake.parsing.parsers.topdev.TopDevParser",
    "vietnamworks": (
        "joblake.parsing.parsers.vietnamworks.VietnamWorksParser"
    ),
}


def _load_class(dotted_path: str):
    module_name, separator, class_name = dotted_path.rpartition(".")
    if not separator:
        raise ValueError(
            "parser_adapter must be a dotted class path"
        )
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def create_parser(config: dict) -> JobParser:
    source = config["source"]
    parse_config = config.get("parse", {})
    adapter_path = parse_config.get("parser_adapter")

    if adapter_path is None:
        try:
            adapter_path = _DEFAULT_PARSERS[source]
        except KeyError as exc:
            raise ValueError(
                f"No parser registered for source: {source}"
            ) from exc

    parser_class = _load_class(adapter_path)
    parser = parser_class()

    if not isinstance(parser, JobParser):
        raise TypeError(
            f"Parser adapter must extend JobParser: {adapter_path}"
        )
    if parser.source != source:
        raise ValueError(
            "Parser source does not match config source: "
            f"{parser.source} != {source}"
        )

    return parser
