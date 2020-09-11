import configparser


class BaseConfig(object):
    def __init__(self, configfile):
        self._config = configparser.SafeConfigParser()
        self._config.read(configfile)

    def _defaulting(self, section: str, variable: str, default: str, quiet=False):
        if quiet is False:
            # can't use logging because we parse config before initializing logging
            print('Config option %s not set in [%s] defaulting to: \'%s\'' %
                  (variable, section, default))

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

    def get_bool(self, section: str, variable: str, default: bool, quiet: bool = False) -> bool:
        try:
            return self._config.getboolean(section, variable)
        except (configparser.NoSectionError, configparser.NoOptionError):
            self._defaulting(section, variable, str(default), quiet)
            return default
