""" TODO """
from queue import Queue
from typing import Dict, Generator, Tuple, List

from .openapi import Endpoint
from .properties import Property, ListProperty, ModelProperty

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
    ) -> Generator[Tuple[Property, str, bool], None, None]:
        # TODO: move to Endpoint?
        def _rec_fn(
                prop: Property,
                name_prefix: str = '',
                level: int = 0,
        ) -> Generator[Tuple[Property, str, bool], None, None]:
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
                    )
            else:
                if level > 0:
                    yield prop, f"{name_prefix.rstrip(cls.NAME_SEPARATOR)}", is_list

        if endpoint.json_body:  # TODO: other parameters/body
            yield from _rec_fn(endpoint.json_body)

    @classmethod
    def get_fw_arguments(cls, endpoint: Endpoint) -> Generator[str, None, None]:
        # TODO: move to Endpoint?
        for prop in cls._get_all_properties_args(endpoint):
            type_str = get_click_type(prop.get_base_type_string())
            yield f"'{prop.python_name}'" + f", type={type_str}" if type_str else ''

    @classmethod
    def get_fw_options(cls, endpoint: Endpoint) -> Generator[str, None, None]:
        # TODO: move to Endpoint?
        for prop, name, is_list in cls._get_all_properties_with_context_name(endpoint):
            content = f"'--{name.replace(cls.NAME_SEPARATOR, '-')}'"
            # if prop.required:
            #     content += ', required=True'  # TODO: depends on parent
            if prop.get_base_type_string() == 'bool':
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

        for _, name, _ in cls._get_all_properties_with_context_name(endpoint):
            yield name

    @classmethod
    def get_api_call_arguments(cls, endpoint: Endpoint) -> Generator[str, None, None]:
        # TODO: move to Endpoint?
        for prop in cls._get_all_properties_args(endpoint):
            yield prop.python_name

        if endpoint.json_body:
            yield endpoint.json_body.python_name

    @classmethod
    def get_fw_cls_creation(
            cls,
            endpoint: Endpoint
    ) -> Generator[str, None, None]:
        # TODO: move to Endpoint?

        queue = Queue()
        calls: List[str] = []

        if endpoint.json_body:  # TODO: other parameters/body
            queue.put(('', endpoint.json_body))

        while not queue.empty():
            name_prefix, prop = queue.get()
            # queue.task_done()
            if isinstance(prop, ListProperty):
                prop = prop.inner_property
            if isinstance(prop, ModelProperty):
                content = f"{name_prefix.rstrip(cls.NAME_SEPARATOR) if name_prefix else prop.python_name}" \
                          f" = {prop.class_info.name}(\n"
                for sub_property in prop.required_properties + prop.optional_properties:
                    include_ok = True
                    if isinstance(sub_property, ModelProperty):
                        if sub_property.required_properties + sub_property.optional_properties:
                            queue.put((f"{name_prefix}{sub_property.python_name}{cls.NAME_SEPARATOR}", sub_property))
                        else:
                            include_ok = False
                    if include_ok:
                        content += f"{sub_property.python_name} = {name_prefix}{sub_property.python_name},\n"
                content += ')\n'
                calls.append(content)
            else:
                raise RuntimeError("debug this")

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
