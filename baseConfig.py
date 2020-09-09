import configparser
import logging


class BaseConfig(object):
    def __init__(self, configfile):
        self._config = configparser.SafeConfigParser()
        self._config.read(configfile)

    def _defaulting(self, section: str, variable: str, default: str, quiet=False):
        if quiet is False:
            logging.info('Config option %s not set in [%s] defaulting to: \'%s\'',
                         variable, section, default)

    def _read_config_var(self, section, variable, default, var_type='str', quiet=False):
        try:
            if var_type == 'str':
                return self._config.get(section, variable)
            elif var_type == 'bool':
                return self._config.getboolean(section, variable)
            elif var_type == 'int':
                return self._config.getint(section, variable)
        except (configparser.NoSectionError, configparser.NoOptionError):
            self._defaulting(section, variable, default, quiet)
            return default

    def get_str(self, section: str, variable: str, default: str, quiet: bool = False) -> str:
        try:
            return self._config.get(section, variable)
        except (configparser.NoSectionError, configparser.NoOptionError):
            self._defaulting(section, variable, default, quiet)
            return default

    def get_int(self, section: str, variable: str, default: int, quiet: bool = False) -> int:
        try:
            return self._config.getint(section, variable)
        except (configparser.NoSectionError, configparser.NoOptionError):
            self._defaulting(section, variable, str(default), quiet)
            return default
