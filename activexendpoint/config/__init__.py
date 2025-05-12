import os
from mictlanx.utils.index import Utils as MictlanXUtils

class Config:
    def __init__(self):
        self.AXO_CLASSES_REPOSITORY = os.environ.get("AXO_CLASSES_REPOSITORY", "/home/nacho/Programming/Python/activex-endpoint/classes")
        self.AXO_ENDPOINT_ID = os.environ.get("AXO_ENDPOINT_ID", "activex-endpoint-0")
        self.AXO_LOGGER_PATH = os.environ.get("AXO_LOGGER_PATH", "/log")
        self.AXO_LOGGER_WHEN = os.environ.get("AXO_LOGGER_WHEN", "h")
        self.AXO_SYNC_MAX_IDLE_TIME = os.environ.get("AXO_SYNC_MAX_IDLE_TIME","24h")
        self.AXO_HEATER_TICK_TIME = os.environ.get("AXO_HEATER_TICK_TIME","30s")
        self.AXO_LOGGER_INTERVAL = int(os.environ.get("AXO_LOGGER_INTERVAL", "24"))
        self.AXO_DEBUG = bool(int(os.environ.get("AXO_DEBUG", "1")))
        self.AXO_SINK_PATH = os.environ.get("AXO_SINK_PATH", "/sink")
        self.AXO_SOURCE_PATH = os.environ.get("AXO_SOURCE_PATH", "/source")
        self.AXO_DATA_PATH = os.environ.get("AXO_DATA_PATH", "/data")
        self.AXO_ENDPOINT_IMAGE = os.environ.get("AXO_ENDPOINT_IMAGE", "nachocode/activex:endpoint-0.0.22-alpha")
        self.AXO_ENDPOINT_DEPENDENCIES_STR = os.environ.get("AXO_ENDPOINT_DEPENDENCIES", "")
        self.AXO_ENDPOINT_DEPENDENCIES = list(filter(lambda x: len(x) > 0, self.AXO_ENDPOINT_DEPENDENCIES_STR.split(";")))
        self.AXO_PROTOCOL = os.environ.get("AXO_PROTOCOL", "tcp")
        self.AXO_PUB_SUB_PORT = int(os.environ.get("AXO_PUB_SUB_PORT", 16666))
        self.AXO_REQ_RES_PORT = int(os.environ.get("AXO_REQ_RES_PORT", 16667))
        self.AXO_HOSTNAME = os.environ.get("AXO_HOSTNAME", "127.0.0.1")
        self.AXO_SUBSCRIBER_HOSTNAME = os.environ.get("AXO_SUBSCRIBER_HOSTNAME", "*")
        self.AXO_ENDPOINTS_STR = os.environ.get("AXO_ENDPOINTS", "").split(" ")
        self.AXO_ENDPOINTS = list(filter(lambda x: len(x) > 0, self.AXO_ENDPOINTS_STR))
        self.AXO_HEATER_MAX_IDLE_TIME = os.environ.get("AXO_HEATER_MAX_IDLE_TIME", "1h")
        
        self.MICTLANX_XOLO_IP_ADDR = os.environ.get("MICTLANX_XOLO_IP_ADDR", "localhost")
        self.MICTLANX_XOLO_API_VERSION = os.environ.get("MICTLANX_XOLO_API_VERSION", "3")
        self.MICTLANX_XOLO_NETWORK = os.environ.get("MICTLANX_XOLO_NETWORK", "10.0.0.0/25")
        self.MICTLANX_XOLO_PORT = os.environ.get("MICTLANX_XOLO_PORT", "15000")
        self.MICTLANX_XOLO_PROTOCOL = os.environ.get("MICTLANX_XOLO_PROTOCOL", "http")
        self.MICTLANX_XOLO_MODE = os.environ.get("MICTLANX_XOLO_MODE", "docker")
        
        self.MICTLANX_BUCKET_ID = os.environ.get("MICTLANX_BUCKET_ID", "activex")
        self.MICTLANX_ROUTERS = os.environ.get("MICTLANX_ROUTERS", "mictlanx-router-0:localhost:60666")
        
        self.MICTLANX_CLIENT_ID = os.environ.get("MICTLANX_CLIENT_ID", "activex-mictlanx-0")
        self.MICTLANX_DEBUG = bool(int(os.environ.get("MICTLANX_DEBUG", "0")))
        self.MICTLANX_LOG_INTERVAL = int(os.environ.get("MICTLANX_LOG_INTERVAL", "24"))
        self.MICTLANX_LOG_WHEN = os.environ.get("MICTLANX_LOG_WHEN", "h")
        self.MICTLANX_LOG_OUTPUT_PATH = os.environ.get("MICTLANX_LOG_OUTPUT_PATH", "/log")
        self.MICTLANX_MAX_WORKERS = int(os.environ.get("MICTLANX_MAX_WORKERS", "4"))

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
