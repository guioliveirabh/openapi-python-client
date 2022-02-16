""" TODO """
from dataclasses import dataclass
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


@dataclass
class PropertyWithHierarchy:
    prop: Property
    name_prefix: str = ''
    level: int = 0
    required: bool = False

    @property
    def name(self) -> str:
        if self.level == 0 and not self.name_prefix:
            return ''
        if self.name_prefix:
            return f"{self.name_prefix}{Node.NAME_SEPARATOR}{self.prop.python_name.strip(Node.NAME_SEPARATOR)}"
        return self.prop.python_name.strip(Node.NAME_SEPARATOR)

    @property
    def name_var(self) -> str:
        if not self.name_prefix:
            return self.prop.python_name
        return f"{self.name_prefix}{Node.NAME_SEPARATOR}{self.prop.python_name.strip(Node.NAME_SEPARATOR)}"

    def name_arg(self, sub_property: Property) -> str:
        name = self.name
        if name:
            return f"{name}{Node.NAME_SEPARATOR}{sub_property.python_name.strip(Node.NAME_SEPARATOR)}"
        return sub_property.python_name


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
        def _get_imports_for_property(prop: Property) -> Generator[str, None, None]:
            if isinstance(prop, ListProperty):
                prop = prop.inner_property
            if isinstance(prop, ModelProperty):
                for _relative in prop.relative_imports:
                    yield _relative.replace("..", f"{self.PACKAGE_NAME}.")

                properties = prop.required_properties + prop.optional_properties
                if isinstance(prop.additional_properties, Property):
                    properties.append(prop.additional_properties)
                for sub_property in properties:
                    yield from _get_imports_for_property(sub_property)

        if self.is_root():
            yield f"from {self.PACKAGE_NAME}.cli_main import cli"
        else:
            yield 'from typing import Any, Dict, List, Optional, Union, cast'
            yield 'import json'
            yield 'import click'
            yield f"from {self.PACKAGE_NAME}.api_request import APIRequest, pass_api"
            yield f"from {self.PACKAGE_NAME}.models import *"
            yield f"from {self.PACKAGE_NAME}.types import UNSET"
        for name in self.keys():
            yield f"from .{name} import {name}"
        for method, endpoint in self.get_endpoints():
            yield f"from {self.PACKAGE_NAME}.api.{endpoint.tag}.{endpoint.file_name}" \
                  f" import sync_detailed as {self.name}_{method}"
            for relative in endpoint.relative_imports:
                yield relative.replace("...", f"{self.PACKAGE_NAME}.")
            if endpoint.json_body:
                yield from _get_imports_for_property(endpoint.json_body)
            if endpoint.multipart_body:
                yield from _get_imports_for_property(endpoint.multipart_body)
            for iterator in [endpoint.query_parameters.values(),
                             endpoint.header_parameters.values(),
                             endpoint.cookie_parameters.values()]:
                for _sub_property in iterator:
                    yield from _get_imports_for_property(prop=_sub_property)

    @classmethod
    def _get_all_properties_args(cls, endpoint: Endpoint) -> Generator[Property, None, None]:
        # TODO: move to Endpoint?
        for prop in endpoint.path_parameters.values():
            yield prop

    @classmethod
    def get_fw_arguments(cls, endpoint: Endpoint) -> Generator[str, None, None]:
        # TODO: move to Endpoint?
        for prop in cls._get_all_properties_args(endpoint):
            type_str = get_click_type(prop.get_base_type_string())
            yield f"'{prop.python_name}'" + f", type={type_str}" if type_str else ''

    @classmethod
    def get_fw_options(cls, endpoint: Endpoint) -> Generator[str, None, None]:
        # TODO: move to Endpoint?
        for prop_h in cls.get_all_props_for_endpoint(endpoint):
            name = prop_h.name
            required = prop_h.required
            prop = prop_h.prop

            content = f"'--{name.replace(cls.NAME_SEPARATOR, '-')}'"
            if required:
                content += ', required=True'
            # if prop.default:
            #     content += f", default={repr(prop.default)}"
            if isinstance(prop, EnumProperty):
                content += f", type=click.Choice({get_click_choices_list(prop)})"
            elif prop.get_base_type_string() == 'bool':
                content += ', is_flag=True'
            else:
                type_str = get_click_type(prop.get_base_type_string())
                if type_str:
                    content += f", type={type_str}"
            # if is_list:
            #     content += ', multiple=True'
            yield content

    @classmethod
    def get_function_arguments(cls, endpoint: Endpoint) -> Generator[str, None, None]:
        # TODO: move to Endpoint?
        for prop in cls._get_all_properties_args(endpoint):
            yield prop.python_name

        for prop_h in cls.get_all_props_for_endpoint(endpoint):
            yield prop_h.name

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
    def get_property_queue(
            cls,
            endpoint: Endpoint
    ) -> "Queue[PropertyWithHierarchy]":
        queue: "Queue[PropertyWithHierarchy]" = Queue()
        if endpoint.json_body:
            queue.put(PropertyWithHierarchy(endpoint.json_body, required=endpoint.json_body.required))
        if endpoint.multipart_body:
            queue.put(PropertyWithHierarchy(endpoint.multipart_body, required=endpoint.multipart_body.required))
        for iterator in [endpoint.query_parameters.values(),
                         endpoint.header_parameters.values(),
                         endpoint.cookie_parameters.values()]:
            for _sub_property in iterator:
                queue.put(PropertyWithHierarchy(_sub_property, level=1, required=_sub_property.required))
        return queue

    @classmethod
    def get_all_props_for_endpoint(
            cls,
            endpoint: Endpoint
    ) -> Generator[PropertyWithHierarchy, None, None]:
        queue = cls.get_property_queue(endpoint)
        while not queue.empty():
            prop_h = queue.get()
            prop = prop_h.prop

            if isinstance(prop, ListProperty):
                prop = prop.inner_property
                prop_h.prop = prop
                prop_h.level += 1
            if isinstance(prop, ModelProperty):
                if isinstance(prop.additional_properties, Property):
                    queue.put(PropertyWithHierarchy(
                        prop=prop.additional_properties,
                        level=prop_h.level + 1,
                        name_prefix=prop_h.name,
                        required=prop_h.required and prop.additional_properties.required,
                    ))
                elif prop.additional_properties \
                        and prop_h.level > 0 \
                        and len(prop.required_properties) == 0 \
                        and len(prop.optional_properties) == 0:
                    yield prop_h

                for sub_property in prop.required_properties + prop.optional_properties:
                    queue.put(PropertyWithHierarchy(
                        prop=sub_property,
                        level=prop_h.level + 1,
                        name_prefix=prop_h.name,
                        required=prop_h.required and sub_property.required
                    ))
            elif prop_h.name:
                yield prop_h

    @classmethod
    def get_fw_cls_creation(
            cls,
            endpoint: Endpoint
    ) -> Generator[str, None, None]:
        # TODO: move to Endpoint?

        queue = cls.get_property_queue(endpoint)
        calls: List[str] = []

        while not queue.empty():
            prop_h = queue.get()
            prop = prop_h.prop
            # queue.task_done()
            if isinstance(prop, ListProperty):
                name = prop_h.name_var
                prop = prop.inner_property
                prop_h.prop = prop
                prop_h.level += 1
                content = f"{name} = []\n" \
                          f"if {prop_h.name} is not None:\n" \
                          f"    {name}.append({prop_h.name})\n"
                calls.append(content)

            if isinstance(prop, EnumProperty):
                calls.append(f"{prop_h.name} = {prop.class_info.name}({prop_h.name})\n")
            elif isinstance(prop, ModelProperty):
                if isinstance(prop.additional_properties, Property):
                    content = f"{prop_h.name_var} = {prop.class_info.name}()\n" \
                              f"{prop_h.name_var}.additional_properties = " \
                              f"{{'{prop.python_name}': {prop_h.name_arg(prop.additional_properties)}}}\n"
                    calls.append(content)
                    queue.put(PropertyWithHierarchy(
                        prop=prop.additional_properties,
                        level=prop_h.level + 1,
                        name_prefix=prop_h.name,
                        required=prop_h.required and prop.additional_properties.required
                    ))
                elif prop.additional_properties \
                        and prop_h.level > 0 \
                        and len(prop.required_properties) == 0 \
                        and len(prop.optional_properties) == 0:
                    content = f"if {prop_h.name_var} is None:\n" \
                              f"    {prop_h.name_var} = UNSET\n" \
                              f"else:\n" \
                              f"    _tmp = {prop.class_info.name}()\n" \
                              f"    _tmp.additional_properties = " \
                              f"json.loads({prop_h.name_var}) # TODO: check if dict\n" \
                              f"    {prop_h.name_var} = _tmp\n"
                    calls.append(content)

                for sub_property in prop.required_properties + prop.optional_properties:
                    queue.put(PropertyWithHierarchy(
                        prop=sub_property,
                        level=prop_h.level + 1,
                        name_prefix=prop_h.name,
                        required=prop_h.required and sub_property.required
                    ))

                if len(prop.required_properties) > 0 or len(prop.optional_properties) > 0:
                    content = f"{prop_h.name_var} = {prop.class_info.name}(\n"
                    for sub_property in prop.required_properties + prop.optional_properties:
                        content += f"{sub_property.python_name} = {prop_h.name_arg(sub_property)},\n"
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
