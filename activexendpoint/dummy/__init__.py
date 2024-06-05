import os
import string
from nanoid import generate as nanoid
from mictlanx.logger.log import Log
import types
import sys

# AXO_ENDPOINT_ID = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-{}".format(nanoid(alphabet=string.ascii_lowercase+string.digits, size=8 )))
AXO_LOGGER_PATH = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_LOGGER_WHEN = os.environ.get("AXO_LOGGER_WHEN","h")
AXO_LOGGER_INTERVAL = int(os.environ.get("AXO_LOGGER_INTERVAL","24"))
AXO_DEBUG = bool(int(os.environ.get("AXO_DEBUG","1")))
logger = Log(
    console_handler_filter=lambda x: AXO_DEBUG,
    create_folder=True,
    error_log=True,
    name="activex.dummy.class",
    path=AXO_LOGGER_PATH,
    when=AXO_LOGGER_WHEN,
    interval=AXO_LOGGER_INTERVAL,
)

class Dummy:
    def __init__(self, *args, **kwargs):
        self.__dict__['attributes'] = {}
        self.__dict__['methods'] = {}

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, state):
        self.__dict__.update(state)

    def __getattr__(self, name):
        # Provide access to methods
        if name in self.__dict__['methods']:
            return self.__dict__['methods'][name]
        # Provide access to attributes
        if name in self.__dict__['attributes']:
            return self.__dict__['attributes'][name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        if callable(value):
            self.__dict__['methods'][name] = value
        else:
            self.__dict__['attributes'][name] = value
    # def __init__(self, *args, **kwargs):
    #     pass

    # def __getstate__(self):
    #     return {}

    # def __setstate__(self, state):
    #     self.__dict__.update(state)
    

def add_dummy_module(module_path, class_name, dummy_class):
    logger.debug({
        "event":"ADD.MODULE.BEFORE",
        "module":module_path,
        "name":class_name,
        "class":str(dummy_class),
        "modules":len(sys.modules)
    })
    parts = module_path.split('.')
    # Create and insert parent modules if they don't exist
    for i in range(1, len(parts)):
        parent_module_name = '.'.join(parts[:i])
        previous_index = i -1
        if parent_module_name not in sys.modules:
            parent_module = types.ModuleType(parent_module_name)
            sys.modules[parent_module_name] = parent_module
            # Add the parent module to its own parent if necessary
            if i > 1:
                # part_i_1 = par
                grandparent_module_name = '.'.join(parts[:previous_index ])
                setattr(sys.modules[grandparent_module_name], parts[i-1], parent_module)
    
    # Create the final module and add the dummy class
    module_name = parts[-1]
    final_module = types.ModuleType(module_path)
    setattr(final_module, class_name, dummy_class)
    sys.modules[module_path] = final_module

    # Add the final module to its parent module
    parent_module_path = '.'.join(parts[:-1])
    if parent_module_path:
        setattr(sys.modules[parent_module_path], module_name, final_module)
    logger.debug({
        "event":"ADD.MODULE.AFTER",
        "module":module_path,
        "name":class_name,
        "class":str(dummy_class),
        "modules":len(sys.modules)
    })