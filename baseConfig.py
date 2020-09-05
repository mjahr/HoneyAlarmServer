import configparser


class BaseConfig(object):
    def __init__(self, configfile):
        self._config = configparser.SafeConfigParser()
        self._config.read(configfile)

    def defaulting(self, section, variable, default, quiet=False):
        if quiet is False:
            print('Config option ' + str(variable) + ' not set in [' +
                  str(section) + '] defaulting to: \'' + str(default) + '\'')

    def read_config_var(self, section, variable, default, var_type='str', quiet=False):
        try:
            if var_type == 'str':
                return self._config.get(section, variable)
            elif var_type == 'bool':
                return self._config.getboolean(section, variable)
            elif var_type == 'int':
                return self._config.getint(section, variable)
        except (configparser.NoSectionError, configparser.NoOptionError):
            self.defaulting(section, variable, default, quiet)
            return default
