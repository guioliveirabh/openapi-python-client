""" TODO """
from queue import Queue
from typing import Dict, Generator, Tuple, List

from .openapi import Endpoint
from .properties import Property, EnumProperty, ListProperty, ModelProperty

CLICK_TYPE_MAP = {
    # 'str': 'click.STRING',
    # 'int': 'click.INT',
    # 'float': 'click.FLOAT',
    # 'bool': 'click.BOOL',
    'str': 'str',
    'int': 'int',
    'float': 'float',
    'bool': 'bool',
    'Any': '',
    'datetime.datetime': 'click.DateTime()',
}


def get_click_type(type_str: str) -> str:
    try:
        return CLICK_TYPE_MAP[type_str]
    except KeyError:
        print('TODO: Implement', type_str)
        return ''


def get_click_choices_list(prop: EnumProperty) -> str:
    return '[' + ', '.join(repr(value) for value in prop.values.values()) + ']'


class Node(dict):
    # TODO: improve this class
    ROOT_NODE = 'cli_auto_gen'
    PACKAGE_NAME = None  # TODO: find better solution
    NAME_SEPARATOR = '_'

    def __init__(self, name: str = '', parent: "Node" = None):
        super().__init__()
        self.name = name
        self.parent = parent
        self.endpoints: Dict[str, Endpoint] = {}

    @classmethod
    def get_root(cls) -> "Node":
        return cls(name=cls.ROOT_NODE)

    def add_endpoint(self, endpoint: Endpoint):
        print(endpoint.tag, endpoint.path, endpoint.method)
        # if endpoint.path.startswith('/policies'):
        #     print(endpoint)
        #     print()

        parent = self
        split_path = [part for part in endpoint.path.strip('/').split('/')
                      if not part.startswith('{')]  # TODO: think of a better filter
        for part in split_path:
            parent = parent.setdefault(part, Node(part, parent))

        name = parent.get_method_name(endpoint)
        if name in parent.endpoints:
            raise RuntimeError(f"Duplicated: {name}, {endpoint.name}")
        parent.endpoints[name] = endpoint

    def is_root(self) -> bool:
        return self.parent is None and self.name == self.ROOT_NODE

    def get_methods(self) -> Generator[str, None, None]:
        for method in self.endpoints.keys():
            yield method

    def get_endpoints(self) -> Generator[Tuple[str, Endpoint], None, None]:
        for method, endpoint in self.endpoints.items():
            yield method, endpoint

    def get_all_imports(self) -> Generator[str, None, None]:
        if self.is_root():
            yield f"from {self.PACKAGE_NAME}.cli_main import cli"
        else:
            yield 'from typing import Any, Dict, List, Optional, Union, cast'
            yield 'import click'
            yield f"from {self.PACKAGE_NAME}.api_request import APIRequest, pass_api"
            yield f"from {self.PACKAGE_NAME}.models import *"  # TODO: improve
        for name in self.keys():
            yield f"from .{name} import {name}"
        for method, endpoint in self.get_endpoints():
            yield f"from {self.PACKAGE_NAME}.api.{endpoint.tag}.{endpoint.file_name}" \
                  f" import sync_detailed as {self.name}_{method}"
            for relative in endpoint.relative_imports:
                yield relative.replace("...", f"{self.PACKAGE_NAME}.")

    @classmethod
    def _get_all_properties_args(cls, endpoint: Endpoint) -> Generator[Property, None, None]:
        # TODO: move to Endpoint?
        for prop in endpoint.path_parameters.values():
            yield prop

    @classmethod
    def _get_all_properties_with_context_name(
            cls,
            endpoint: Endpoint
    ) -> Generator[Tuple[Property, str, bool, bool], None, None]:
        # TODO: move to Endpoint?
        def _rec_fn(
                prop: Property,
                name_prefix: str = '',
                level: int = 0,
                required: bool = False,
        ) -> Generator[Tuple[Property, str, bool, bool], None, None]:
            is_list = False
            if isinstance(prop, ListProperty):
                prop = prop.inner_property
                is_list = True
            if isinstance(prop, ModelProperty):
                # if level == 0:
                for sub_property in prop.required_properties + prop.optional_properties:
                    yield from _rec_fn(
                        sub_property,
                        f"{name_prefix}{sub_property.python_name}{cls.NAME_SEPARATOR}",
                        level + 1,
                        required and sub_property.required
                    )
            else:
                if level > 0:
                    yield prop, f"{name_prefix.rstrip(cls.NAME_SEPARATOR)}", is_list, required and prop.required

        if endpoint.json_body:
            yield from _rec_fn(endpoint.json_body, required=endpoint.json_body.required)
        if endpoint.multipart_body:
            yield from _rec_fn(endpoint.multipart_body, required=endpoint.multipart_body.required)
        for iterator in [endpoint.query_parameters.values(),
                         endpoint.header_parameters.values(),
                         endpoint.cookie_parameters.values()]:
            for _sub_property in iterator:
                yield from _rec_fn(
                    prop=_sub_property,
                    name_prefix=f"{_sub_property.python_name.rstrip(cls.NAME_SEPARATOR)}{cls.NAME_SEPARATOR}",
                    level=1,
                    required=_sub_property.required,
                )

    @classmethod
    def get_fw_arguments(cls, endpoint: Endpoint) -> Generator[str, None, None]:
        # TODO: move to Endpoint?
        for prop in cls._get_all_properties_args(endpoint):
            type_str = get_click_type(prop.get_base_type_string())
            yield f"'{prop.python_name}'" + f", type={type_str}" if type_str else ''

    @classmethod
    def get_fw_options(cls, endpoint: Endpoint) -> Generator[str, None, None]:
        # TODO: move to Endpoint?
        for prop, name, is_list, required in cls._get_all_properties_with_context_name(endpoint):
            content = f"'--{name.replace(cls.NAME_SEPARATOR, '-')}'"
            if required:
                content += ', required=True'
            if isinstance(prop, EnumProperty):
                content += f", type=click.Choice({get_click_choices_list(prop)})"
            elif prop.get_base_type_string() == 'bool':
                content += ', is_flag=True'
            else:
                type_str = get_click_type(prop.get_base_type_string())
                if type_str:
                    content += f", type={type_str}"
            if is_list:
                content += ', multiple=True'
            yield content

    @classmethod
    def get_function_arguments(cls, endpoint: Endpoint) -> Generator[str, None, None]:
        # TODO: move to Endpoint?
        for prop in cls._get_all_properties_args(endpoint):
            yield prop.python_name

        for _, name, _, _ in cls._get_all_properties_with_context_name(endpoint):
            yield name

    @classmethod
    def get_api_call_arguments(cls, endpoint: Endpoint) -> Generator[str, None, None]:
        # TODO: move to Endpoint?
        for prop in cls._get_all_properties_args(endpoint):
            yield prop.python_name

        if endpoint.json_body:
            yield endpoint.json_body.python_name

        if endpoint.multipart_body:
            yield endpoint.multipart_body.python_name

        for iterator in [endpoint.query_parameters.values(),
                         endpoint.header_parameters.values(),
                         endpoint.cookie_parameters.values()]:
            for _sub_property in iterator:
                yield _sub_property.python_name

    @classmethod
    def get_fw_cls_creation(
            cls,
            endpoint: Endpoint
    ) -> Generator[str, None, None]:
        # TODO: move to Endpoint?

        queue = Queue()
        calls: List[str] = []

        if endpoint.json_body:
            queue.put(('', 0, endpoint.json_body))
        if endpoint.multipart_body:
            queue.put(('', 0, endpoint.multipart_body))
        for iterator in [endpoint.query_parameters.values(),
                         endpoint.header_parameters.values(),
                         endpoint.cookie_parameters.values()]:
            for _sub_property in iterator:
                queue.put((f"{_sub_property.python_name.rstrip(cls.NAME_SEPARATOR)}{cls.NAME_SEPARATOR}",
                           0,
                           _sub_property))

        while not queue.empty():
            name_prefix, level, prop = queue.get()
            # queue.task_done()
            if isinstance(prop, ListProperty):
                prop = prop.inner_property
            variable_name = f"{name_prefix.rstrip(cls.NAME_SEPARATOR) if level > 0 else prop.python_name}"
            if isinstance(prop, EnumProperty):
                calls.append(f"{variable_name} = {prop.class_info.name}({variable_name})\n")
            if isinstance(prop, ModelProperty):
                content = f"{variable_name} = {prop.class_info.name}(\n"
                for sub_property in prop.required_properties + prop.optional_properties:
                    include_ok = True
                    if isinstance(sub_property, ModelProperty):
                        if sub_property.required_properties + sub_property.optional_properties:
                            queue.put((f"{name_prefix}{sub_property.python_name}{cls.NAME_SEPARATOR}",
                                       level + 1,
                                       sub_property))
                        else:
                            include_ok = False
                    if include_ok:
                        content += f"{sub_property.python_name} = {name_prefix}{sub_property.python_name},\n"
                content += ')\n'
                calls.append(content)

        for call in reversed(calls):
            yield call

    @classmethod
    def get_method_name(cls, endpoint: Endpoint) -> str:
        if 'list' in endpoint.name.split('.')[-1]:
            return 'get_list'

        return {
            'delete': 'remove',
            'get': 'get',
            'patch': 'update',
            'post': 'create',
        }[endpoint.method]
