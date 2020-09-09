#!/usr/bin/python3
# Alarm Server
# Supporting Envisalink 2DS/3/4
# Original version for DSC Written by donnyk+envisalink@gmail.com,
# lightly improved by leaberry@gmail.com
# Honeywell version adapted by matt.weinecke@gmail.com
# Significant rewrite by michaelj@gmail.com
#
# This code is under the terms of the GPL v3 license.

import getopt
import logging
import re
import sys
from datetime import datetime
from datetime import timedelta
from typing import Dict, Any

from twisted.internet import reactor
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.internet.task import LoopingCall
from twisted.protocols.basic import LineOnlyReceiver
from twisted.python import log
from twisted.web.resource import Resource

from baseConfig import BaseConfig
from envisalinkdefs import *
from smartthings import SmartThings

AlarmState = Dict[str, Dict[int, Dict[str, Any]]]
ALARMSTATE: AlarmState = {}
MAXPARTITIONS: int = 16
MAXZONES: int = 128
MAXALARMUSERS: int = 47
SHUTTINGDOWN: bool = False


class AlarmServerConfig(BaseConfig):
    def __init__(self, configfile: str):
        # call ancestor for common setup
        super(self.__class__, self).__init__(configfile)

        self.ENVISALINKHOST = self.get_str('envisalink', 'host', 'envisalink')
        self.ENVISALINKPORT = self.get_int('envisalink', 'port', 4025)
        self.ENVISALINKPASS = self.get_str('envisalink', 'pass', 'user')
        self.ENVISAPOLLINTERVAL = self.get_int('envisalink', 'pollinterval', 0)
        self.ENVISAZONEDUMPINTERVAL = self.get_int('envisalink', 'zonedumpinterval', 60)
        self.ENVISAKEYPADUPDATEINTERVAL = self.get_int('envisalink', 'keypadupdateinterval', 60)
        self.ENVISACOMMANDTIMEOUT = self.get_int('envisalink', 'commandtimeout', 30)
        self.ENVISAKPEVENTTIMEOUT = self.get_int('envisalink', 'kpeventtimeout', 45)
        self.ALARMCODE = self.get_int('envisalink', 'alarmcode', 1111)
        self.LOGFILE = self.get_str('alarmserver', 'logfile', '')
        self.LOGLEVEL = self.get_str('alarmserver', 'loglevel', 'DEBUG')

        self.PARTITIONNAMES: Dict[int, str] = {}
        for i in range(1, MAXPARTITIONS + 1):
            self.PARTITIONNAMES[i] = self.get_str('alarmserver', 'partition' + str(i), 'False', True)

        self.ZONENAMES: Dict[int, str] = {}
        for i in range(1, MAXZONES + 1):
            self.ZONENAMES[i] = self.get_str('alarmserver', 'zone' + str(i), 'False', True)

        self.ALARMUSERNAMES: Dict[int, str] = {}
        for i in range(1, MAXALARMUSERS + 1):
            self.ALARMUSERNAMES[i] = self.get_str('alarmserver', 'user' + str(i), 'False', True)

    def initialize_alarmstate(self):
        ALARMSTATE['zone'] = {}
        for zone_num in list(self.ZONENAMES.keys()):
            zone_name = self.ZONENAMES[zone_num]
            if not zone_name:
                continue
            ALARMSTATE['zone'][zone_num] = {
                'name': zone_name,
                'message': 'uninitialized',
                'status': 'uninitialized',
                'closedSeconds': -1,
                'lastChanged': 'never'
            }

        ALARMSTATE['partition'] = {}
        for partition_num in list(self.PARTITIONNAMES.keys()):
            partition_name = self.PARTITIONNAMES[partition_num]
            if not partition_name:
                continue
            ALARMSTATE['partition'][partition_num] = {
                'name': partition_name,
                'message': 'uninitialized',
                'status': 'uninitialized',
                'beep': 'uninitialized',
                'alarm': False,
                'alarm_in_memory': False,
                'armed_away': False,
                'ac_present': False,
                'bypass': False,
                'chime': False,
                'armed_max': False,
                'alarm_fire': False,
                'system_trouble': False,
                'ready': False,
                'fire': False,
                'low_battery': False,
                'armed_stay': False
            }


class EnvisalinkClientFactory(ReconnectingClientFactory):
    def __init__(self, in_config: AlarmServerConfig):
        self._config: AlarmServerConfig = in_config
        self._smartthings: SmartThings = SmartThings(in_config)
        self._envisalinkClient = None
        self._currentLoopingCall = None

    def buildProtocol(self, addr):
        logging.debug("%s connection established to %s:%s", addr.type, addr.host, addr.port)
        logging.debug("resetting connection delay")
        self.resetDelay()
        self._envisalinkClient = EnvisalinkClient(self._config, self._smartthings)

        # check on the state of the envisalink connection repeatedly
        self._currentLoopingCall = LoopingCall(self._envisalinkClient.check_alive)
        self._currentLoopingCall.start(1)
        return self._envisalinkClient

    def startedConnecting(self, connector):
        logging.debug("Started to connect to Envisalink...")

    def clientConnectionLost(self, connector, reason):
        if not SHUTTINGDOWN:
            logging.debug('Lost connection to Envisalink.  Reason: %s', str(reason))
            if hasattr(self, "_currentLoopingCall"):
                try:
                    self._currentLoopingCall.stop()
                except:
                    logging.error("Error trying to stop looping call, ignoring...")
            ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        logging.debug('Connection failed to Envisalink. Reason: %s', str(reason))
        if hasattr(self, "_currentLoopingCall"):
            try:
                self._currentLoopingCall.stop()
            except:
                logging.error("Error trying to stop looping call, ignoring...")
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)


class EnvisalinkClient(LineOnlyReceiver):
    def __init__(self, in_config: AlarmServerConfig, smartthings: SmartThings):
        # Are we logged in?
        self._loggedin = False

        self._has_partition_state_changed = False

        # Set config and smartthings
        self._config = in_config
        self._smartthings = smartthings

        self._commandinprogress = False
        now = datetime.now()
        self._lastkeypadupdate = now
        self._lastpoll = datetime.min
        self._lastpollresponse = datetime.min
        self._lastzonedump = datetime.min
        self._lastpartitionupdate = datetime.min
        self._lastcommand = now
        self._lastcommandresponse = now

    def logout(self):
        logging.debug("Ending Envisalink client connection...")
        self._loggedin = False
        if hasattr(self, 'transport'):
            self.transport.loseConnection()

    def send_data(self, data):
        logging.debug('TX > ' + data)
        self.sendLine(data.encode('ascii'))

    def check_alive(self):
        if self._loggedin:
            now = datetime.now()

            # if too much time has passed since command was sent without a
            # response, something is wrong
            delta = now - self._lastcommand
            if (self._lastcommandresponse < self._lastcommand and
                    delta > timedelta(seconds=self._config.ENVISACOMMANDTIMEOUT)):
                message = "Timed out waiting for command response, resetting connection..."
                logging.error(message)
                self._smartthings.send_error(message)
                self.logout()
                return

            # is it time to poll again?
            if self._config.ENVISAPOLLINTERVAL != 0:
                delta = now - self._lastpoll
                if (delta > timedelta(seconds=self._config.ENVISAPOLLINTERVAL) and
                        not self._commandinprogress):
                    self._lastpoll = now
                    self.send_command('00', '')

            # is it time to dump zone states again?
            delta = now - self._lastzonedump
            if (delta > timedelta(seconds=self._config.ENVISAZONEDUMPINTERVAL) and
                    not self._commandinprogress):
                self._lastzonedump = now
                self.dump_zone_timers()

            # if 10 seconds have passed and we haven't received a keypad update,
            # something is wrong
            delta = now - self._lastkeypadupdate
            if delta > timedelta(seconds=self._config.ENVISAKPEVENTTIMEOUT):
                # reset connection
                message = "No recent keypad updates from envisalink, resetting connection..."
                logging.error(message)
                self._smartthings.send_error(message)
                self.logout()
                return

    # application commands to the envisalink

    def send_command(self, code, data):
        if not self._loggedin:
            logging.error("Not connected to Envisalink - ignoring command %s",
                          code)
            return
        if self._commandinprogress:
            logging.error("Command already in progress - ignoring command %s",
                          code)
            return
        self._commandinprogress = True
        self._lastcommand = datetime.now()
        to_send = '^' + code + ',' + data + '$'
        self.send_data(to_send)

    def change_partition(self, partition_num):
        if partition_num < 1 or partition_num > 8:
            logging.error("Invalid Partition Number %d specified when trying "
                          "to change partition, ignoring.", partition_num)
            return
        self.send_command('01', str(partition_num))

    def dump_zone_timers(self):
        self.send_command('02', '')

    def keypresses_to_default_partition(self, keypresses):
        self.send_data(keypresses)

    def keypresses_to_partition(self, partition_num, keypresses):
        for char in keypresses:
            to_send = '^03,' + str(partition_num) + ',' + char + '$'
            self.send_data(to_send)

    # network communication callbacks

    def connectionMade(self):
        logging.info("Connected to %s:%d" %
                     (self._config.ENVISALINKHOST,
                      self._config.ENVISALINKPORT))

    def connectionLost(self, reason):
        if not SHUTTINGDOWN:
            logging.info("Disconnected from %s:%d, reason was %s" %
                         (self._config.ENVISALINKHOST,
                          self._config.ENVISALINKPORT,
                          reason.getErrorMessage()))
            if self._loggedin:
                self.logout()

    def lineReceived(self, input_bytes):
        input_line = input_bytes.decode('ascii')
        if input_line != '':
            logging.debug('----------------------------------------')
            logging.debug('RX < ' + input_line)
            if input_line[0] in ("%", "^"):
                # keep first sentinel char to tell difference between tpi and
                # Envisalink command responses.  Drop the trailing $ sentinel.
                input_list = input_line[0:-1].split(',')
                code = input_list[0]
                data = ','.join(input_list[1:])
            else:
                # assume it is login info
                code = input_line
                data = ''

            try:
                handler = "handle_%s" % evl_ResponseTypes[code]['handler']
            except KeyError:
                logging.warning('No handler defined for ' + code + ', skipping...')
                return

            try:
                handler_func = getattr(self, handler)
            except AttributeError:
                raise RuntimeError("Handler function doesn't exist")

            handler_func(data)
            logging.debug('----------------------------------------')

    # Envisalink Response Handlers

    def handle_login(self, data):
        self.send_data(self._config.ENVISALINKPASS)

    def handle_login_success(self, data):
        self._loggedin = True
        logging.info('Password accepted, session created')

    def handle_login_failure(self, data):
        logging.error('Password is incorrect. Server is closing socket connection.')

    def handle_login_timeout(self, data):
        logging.error('Envisalink timed out waiting for password, whoops that '
                      'should never happen.  Server is closing socket connection')

    def handle_poll_response(self, code):
        self._lastpollresponse = datetime.now()
        self.handle_command_response(code)

    def handle_command_response(self, code):
        self._commandinprogress = False
        self._lastcommandresponse = datetime.now()
        response_str = evl_TPI_Response_Codes[code]
        logging.debug("Envisalink response: " + response_str)
        if code != '00':
            logging.error("error sending command to envisalink.  Response was: "
                          + response_str)

    def handle_keypad_update(self, data):
        self._lastkeypadupdate = datetime.now()
        data_list = data.split(',')
        # make sure data is in format we expect, current TPI seems to
        # send bad data every so ofen
        if len(data_list) != 5 or "%" in data:
            logging.error("Data format invalid from Envisalink, ignoring...")
            return

        partition_num = int(data_list[0])
        flags = IconLED_Flags()
        flags.asShort = int(data_list[1], 16)
        user_or_zone = data_list[2]
        beep = evl_Virtual_Keypad_How_To_Beep.get(data_list[3], 'unknown')
        alpha = data_list[4]

        if partition_num not in ALARMSTATE['partition']:
            logging.debug("Skipping partition %d", partition_num)
            return

            # TODO: update status text based on bitfield
        # if (newStatus['alarm']):
        #     statusText == 'IN_ALARM'
        # elif (newStatus[
        #         'alarm_in_memory': statusText == 'ALARM_IN_MEMORY',
        #         'armed_away': statusText == 'ARMED_AWAY',
        #         # 'ac_present'
        #         'bypass': statusText == 'READY_BYPASS',
        #         # 'chime': statusText == '',
        #         'armed_max': statusText == 'ARMED_MAX',
        #         'alarm_fire': statusText == 'ALARM_FIRE',
        #         # 'system_trouble': statusText == '',
        #         'ready': statusText == 'READY',  # in ('READY', 'READY_BYPASS'),
        #         'fire': statusText == 'ALARM_FIRE',
        #         # 'low_battery': statusText == '',
        #         'armed_stay': statusText == 'ARMED_STAY',
        #         'status': statusText

        new_status = {
            'alarm': bool(flags.alarm),
            'alarm_in_memory': bool(flags.alarm_in_memory),
            'armed_away': bool(flags.armed_away),
            'ac_present': bool(flags.ac_present),
            'bypass': bool(flags.bypass),
            'chime': bool(flags.chime),
            'armed_max': bool(flags.armed_zero_entry_delay),
            'alarm_fire': bool(flags.alarm_fire_zone),
            'system_trouble': bool(flags.system_trouble),
            'ready': bool(flags.ready),
            'fire': bool(flags.fire),
            'low_battery': bool(flags.low_battery),
            'armed_stay': bool(flags.armed_stay),
            'beep': beep,
            'message': alpha
        }

        now = datetime.now()
        delta = now - self._lastpartitionupdate
        if delta < timedelta(seconds=self._config.ENVISAKEYPADUPDATEINTERVAL):
            logging.debug('Skipping keypad update within update interval')
        else:
            # We shouldn't have to skip keypad update during command in
            # progress because we don't initiate another command.
            if self._commandinprogress:
                logging.warning('Keypad update while command in progress')
            self._lastpartitionupdate = now
            logging.debug("keypad_update: zone %s status %s", user_or_zone, new_status)
            # Update zone status if the keypad is reporting a fault.
            if alpha.startswith("FAULT") and not flags.ready:
                zone_number = int(user_or_zone)
                self.update_zone_status(zone_number, "open")
            self.set_partition_status(partition_num, new_status)

            # Send update to SmartThings
            self._smartthings.send_update(ALARMSTATE)

    def update_zone_status(self, zone_num: int, zone_status: str):
        zone_name = self._config.ZONENAMES[zone_num]
        # only bother to update if zone name is defined in config
        if not zone_name:
            return False

        logmessage = ("%s (zone %i) is %s" % (zone_name, zone_num, zone_status))
        logging.debug(logmessage)
        status_changed = (ALARMSTATE['zone'][zone_num]['status'] != zone_status)
        if status_changed:
            logging.info("zone state change: " + logmessage)
            time_str = self.get_time_text()
            ALARMSTATE['zone'][zone_num].update({
                'message': ("%s at %s" % (zone_status, time_str)),
                'status': zone_status, 'closedSeconds': 0,
                'lastChanged': time_str
            })
        return status_changed

    def handle_zone_state_change(self, data):
        # Envisalink TPI is inconsistent at generating these
        logging.debug("handle_zone_state_change: data='%s'" % data)

        # Data is an 64-bit number in hex, little endian: 8 2-char bytes.
        le_hex = data
        # Convert from little-endian to big-endian by reversing the order of the bytes
        be_hex = "".join([le_hex[2 * i] + le_hex[2 * i + 1] for i in range(7, -1, -1)])
        # Convert from hex to binary
        be_bin = bin(int(be_hex, 16))[2:].zfill(64)

        for zone_num in range(1, 65):
            # zone numbers are 1-indexed.  big-endian means zone 1 is
            # the last bit, so zone i is the (64-i)th bit.
            zone_bit = be_bin[64 - zone_num]
            zone_status = 'open' if zone_bit == '1' else 'closed'

            # zone_state_change will often continue reporting zones as
            # open when they have already closed, so we ignore open
            # zones here and instead rely on keypad update to tell us
            # when zones are open.
            if zone_status == 'closed':
                self.update_zone_status(zone_num, zone_status)

    def handle_partition_state_change(self, data):
        self._has_partition_state_changed = True
        for currentIndex in range(0, 8):
            partition_num = currentIndex + 1
            status_code = data[currentIndex * 2:(currentIndex * 2) + 2]
            status_text = evl_Partition_Status_Codes[str(status_code)]['name']

            # skip partitions we don't care about
            if (status_text == 'NOT_USED' or
                    not self._config.PARTITIONNAMES[partition_num]):
                continue

            new_status = {
                'alarm': status_text == 'IN_ALARM',
                'alarm_in_memory': status_text == 'ALARM_IN_MEMORY',
                'armed_away': status_text == 'ARMED_AWAY',
                # 'ac_present'
                'bypass': status_text == 'READY_BYPASS',
                # 'chime': statusText == '',
                'armed_max': status_text == 'ARMED_MAX',
                'alarm_fire': status_text == 'ALARM_FIRE',
                # 'system_trouble': statusText == '',
                'ready': status_text == 'READY',  # in ('READY', 'READY_BYPASS'),
                'fire': status_text == 'ALARM_FIRE',
                # 'low_battery': statusText == '',
                'armed_stay': status_text == 'ARMED_STAY',
                'status': status_text
            }
            logging.debug('partition %d status update: %s',
                          partition_num, new_status)
            self.set_partition_status(partition_num, new_status)

    def set_partition_status(self, partition_num, new_status):
        status_map = ALARMSTATE['partition'][partition_num]
        # compute list of all keys that are different between old and new status.
        # message change doesn't count as a state change.
        key_diff = [key for key in new_status
                    if (new_status[key] != status_map[key] and
                        key not in ('message', 'status'))]
        if len(key_diff) > 0:
            logging.debug('Partition old status: ' + str(status_map))
            status_map['lastChanged'] = self.get_time_text()
            logging.debug('Partition state change: ' + str(status_map))
            logging.debug('Partition key diff: ' + str(key_diff))

        status_map.update(new_status)
        logging.debug('Partition %d status: %s', partition_num, str(new_status))
        if status_map['ready']:
            # close all zones and send a zone status update if necessary
            for zoneNumber, zoneInfo in list(ALARMSTATE['zone'].items()):
                self.update_zone_status(zoneNumber, 'closed')

    def handle_realtime_cid_event(self, data):
        event_type_int = int(data[0])
        event_type = evl_CID_Qualifiers[event_type_int]
        cid_event_int = int(data[1:4])
        cid_event = evl_CID_Events[cid_event_int]
        partition = data[4:6]
        zone_or_user = int(data[6:9])

        logging.debug('Event Type is ' + event_type)
        logging.debug('CID Type is ' + cid_event['type'])
        logging.debug('CID Description is ' + cid_event['label'])
        logging.debug('Partition is ' + partition)
        logging.debug(cid_event['type'] + ' value is ' + str(zone_or_user))

    # returns the current time in a human-readable format, optionally
    # offset by a number of seconds.
    def get_time_text(self, seconds_ago=0):
        t = datetime.now() - timedelta(seconds=seconds_ago)
        return t.strftime("%Y-%m-%d %H:%M:%S")

    # note that a request to dump zone timers generates both a standard command
    # response (handled elsewhere) as well as this event
    def handle_zone_timer_dump(self, zone_dump):
        zone_info_array = self.convert_zone_dump(zone_dump)
        for zone_number, zone_info in enumerate(zone_info_array, start=1):
            zone_name = self._config.ZONENAMES[zone_number]

            # skip zones we don't care about or that haven't changed state
            if (not zone_name or
                    ALARMSTATE['zone'][zone_number]['status'] == zone_info['status']):
                continue

            log_message = ("%s (zone %i) %s" % (zone_name, zone_number, zone_info))

            # Set lastChanged time to closedSeconds, which is 0 if open.
            zone_info['lastChanged'] = self.get_time_text(
                seconds_ago=zone_info['closedSeconds'])

            # zone dumps seem to be buggy and falsely report zone
            # closed; leave an error margin of 60 seconds before
            # closing a zone.
            if (zone_info['status'] == 'closed' and
                    zone_info['closedSeconds'] < 60):
                logging.debug("ignoring zone status dump state "
                              "change under 60 seconds: " + log_message)
            else:
                # update zone state
                logging.info("zone state change: " + log_message)
                ALARMSTATE['zone'][zone_number].update(zone_info)

    # convert a zone dump into something humans can make sense of
    def convert_zone_dump(self, raw_string):
        logging.debug("converting zone dump, raw string='%s'" % raw_string)
        return_items = []

        # every four characters
        input_items = re.findall('....', raw_string)
        for inputItem in input_items:
            # Swap the couples of every four bytes
            # (little endian to big endian)
            swapped_bytes = []
            swapped_bytes.insert(0, inputItem[0:2])
            swapped_bytes.insert(0, inputItem[2:4])

            # add swapped set of four bytes to our return items
            item_hex_string = ''.join(swapped_bytes)
            # convert from hex to int
            item_int = int(item_hex_string, 16)

            # each value is a timer for a zone that ticks down every
            # five seconds from maxint
            max_ticks = 65536
            item_ticks = max_ticks - item_int
            item_seconds = item_ticks * 5

            item_last_closed = self.human_time_ago(timedelta(seconds=item_seconds))
            # status = ''

            if item_hex_string == "FFFF":
                item_last_closed = "Currently Open"
                item_seconds = 0
                status = 'open'
            elif item_hex_string == "0000":
                item_last_closed = "Last Closed longer ago than I can remember"
                status = 'closed'
            else:
                item_last_closed = "Last Closed " + item_last_closed
                status = 'closed'

            logging.debug("zone dump: index=%d raw='%s' swapped='%s' int=%d" %
                          (len(return_items), inputItem, item_hex_string, item_int))

            return_items.append({'message': item_last_closed, 'status': status,
                                 'closedSeconds': item_seconds})
        return return_items

    # public domain from https://pypi.python.org/pypi/ago/0.0.6
    def delta2dict(self, delta):
        delta = abs(delta)
        return {
            'year': int(delta.days / 365),
            'day': int(delta.days % 365),
            'hour': int(delta.seconds / 3600),
            'minute': int(delta.seconds / 60) % 60,
            'second': delta.seconds % 60,
            'microsecond': delta.microseconds
        }

    def human_time_ago(self, dt, precision=3, past_tense='{} ago', future_tense='in {}'):
        """Accept a datetime or timedelta, return a human readable delta string"""
        delta = dt
        if type(dt) is not type(timedelta()):
            delta = datetime.now() - dt

        the_tense = past_tense
        if delta < timedelta(0):
            the_tense = future_tense

        d = self.delta2dict(delta)
        hlist = []
        count = 0
        units = ('year', 'day', 'hour', 'minute', 'second', 'microsecond')
        for unit in units:
            if count >= precision:
                break  # met precision
            if d[unit] == 0:
                continue  # skip 0's
            s = '' if d[unit] == 1 else 's'  # handle plurals
            hlist.append('%s %s%s' % (d[unit], unit, s))
            count += 1
        human_delta = ', '.join(hlist)
        return the_tense.format(human_delta)


class AlarmServer(Resource):
    def __init__(self, in_config):
        Resource.__init__(self)

        self._triggerid = reactor.addSystemEventTrigger('before', 'shutdown',
                                                        self.shutdown_event)

        # Create Envisalink client connection
        self._envisalinkClientFactory = EnvisalinkClientFactory(in_config)
        self._envisaconnect = reactor.connectTCP(in_config.ENVISALINKHOST,
                                                 in_config.ENVISALINKPORT,
                                                 self._envisalinkClientFactory)

        # Store config
        self._config = in_config

    def shutdown_event(self):
        global SHUTTINGDOWN
        SHUTTINGDOWN = True
        logging.debug("Disconnecting from Envisalink...")
        self._envisaconnect.disconnect()

    def getChild(self, name, request):
        return self


def usage():
    print('Usage: ' + sys.argv[0] + ' -c <configfile>')


def main(argv):
    try:
        opts, args = getopt.getopt(argv, "hc:", ["help", "config="])
    except getopt.GetoptError:
        usage()
        sys.exit(2)
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            usage()
            sys.exit()
        elif opt in ("-c", "--config"):
            global conffile
            conffile = arg


if __name__ == "__main__":
    conffile = 'alarmserver.cfg'
    main(sys.argv[1:])

    print('Using configuration file %s' % conffile)
    alarm_config = AlarmServerConfig(conffile)
    loggingconfig: Dict[str, Any] = {
        'level': alarm_config.LOGLEVEL,
        'format': '%(asctime)s %(levelname)s <%(name)s %(module)s %(funcName)s> %(message)s',
        'datefmt': '%Y-%m-%d %H:%M:%S',
        # force re-init because AlarmServerConfig may have already initialized default logging
        'force': True}
    if alarm_config.LOGFILE != '':
        loggingconfig['filename'] = alarm_config.LOGFILE
    logging.basicConfig(**loggingconfig)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    # re-parse config for logging
    alarm_config = AlarmServerConfig(conffile)

    logging.info('AlarmServer Starting')
    logging.info('Tested on a Honeywell Vista 20p + EVL-4')

    # allow Twisted to hook into our logging
    observer = log.PythonLoggingObserver()
    observer.start()

    alarm_config.initialize_alarmstate()
    AlarmServer(alarm_config)

    try:
        reactor.run()
    except KeyboardInterrupt:
        print("Crtl+C pressed. Shutting down.")
        logging.info('Shutting down from Ctrl+C')
        sys.exit()
