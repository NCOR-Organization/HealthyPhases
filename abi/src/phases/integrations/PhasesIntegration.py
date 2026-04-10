import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import requests
from naas_abi_core import logger
from naas_abi_core.integration import Integration, IntegrationConfiguration
from naas_abi_core.integration.integration import IntegrationConnectionError
from naas_abi_core.services.cache.CacheFactory import CacheFactory
from naas_abi_core.services.cache.CachePort import DataType
from naas_abi_core.services.cache.CacheService import CacheService


@dataclass
class PhasesIntegrationConfiguration(IntegrationConfiguration):
    """Configuration for the Phases integration."""
    pass


class PhasesIntegration(Integration):
    """Phases integration."""

    __configuration: PhasesIntegrationConfiguration

    def __init__(self, configuration: PhasesIntegrationConfiguration):
        super().__init__(configuration)
        self.__configuration = configuration
